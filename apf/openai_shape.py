"""OpenAI Chat Completions shape handler (apf-fwt).

OpenAI-COMPATIBLE — that's the API standard everyone implements:
Cursor, Aider, Codex on the cloud side, plus Ollama / llama.cpp / LM
Studio / vLLM / mlx-lm / oMLX / Groq / Together / OpenRouter / Mistral
on the local + alternative-provider side. Supporting this shape covers
the entire non-Anthropic ecosystem in one go.

Differences from Anthropic Messages API:
- System message is messages[0] with role="system", not a top-level
  `system` field.
- messages[*].content is either a string OR an array of parts. Part
  shape: {"type": "text", "text": "..."} or
  {"type": "image_url", "image_url": {"url": "..."}}.
- Assistant messages may carry tool_calls. Each tool_call has
  {id, type, function: {name, arguments}}. arguments is a JSON-encoded
  STRING, not a dict.
- Tool result messages have role="tool" and tool_call_id pointing back
  to the tool_call.id that triggered them.
- Response: choices[0].message.content + choices[0].message.tool_calls.
- Streaming: data-only SSE chunks (no event lines), final "data: [DONE]".
  Text streams as choices[0].delta.content (raw text fragments).
  Tool calls stream as choices[0].delta.tool_calls — name and id come
  in early chunks, function.arguments streams as JSON-string fragments.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .detokenizer import detokenize_text
from .resolver import resolve_tool_call_args
from .tokenizer import Span, tokenize_text
from .vault import Vault


# ── Request walker (client → upstream) ────────────────────────────────────

def tokenise_request(
    body: dict, vault: Vault, tokeniser_fn, tokenise_system: bool = False,
) -> dict:
    """Walk an OpenAI Chat Completions request body and tokenise text
    surfaces. tokeniser_fn is the callback used by the proxy
    (apf.proxy._tokenise_text) so all the inline-bypass and detector
    plumbing applies uniformly.

    tokenise_system controls whether role=system messages are tokenised
    (apf-lnr). Default False: control-plane system prompts (filter explainer,
    agent personality) leak no false-positive vault entries. Pass True for
    setups whose system prompts legitimately carry user PII.
    """
    out = dict(body)
    msgs = out.get("messages")
    if not isinstance(msgs, list):
        return out
    new_msgs: list[dict] = []
    for msg in msgs:
        if not tokenise_system and msg.get("role") == "system":
            new_msgs.append(msg)
            continue
        new_msgs.append(_tokenise_message(msg, vault, tokeniser_fn))
    out["messages"] = new_msgs
    return out


def _tokenise_message(msg: dict, vault: Vault, tokeniser_fn) -> dict:
    out = dict(msg)
    content = msg.get("content")
    if isinstance(content, str):
        out["content"] = tokeniser_fn(content, vault)
    elif isinstance(content, list):
        new_parts: list = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                new_parts.append({
                    **part, "text": tokeniser_fn(part.get("text", ""), vault),
                })
            else:
                # image_url and other unknown part types pass through —
                # apf doesn't claim to filter image content.
                new_parts.append(part)
        out["content"] = new_parts
    # Assistant tool_calls (in conversation history): tokenise the JSON
    # arguments. They were originally the LLM's output and have been
    # resolved already once on the way back, but if the conversation has
    # been replayed through this turn they need tokenisation again.
    if isinstance(msg.get("tool_calls"), list):
        out["tool_calls"] = [
            _tokenise_tool_call(tc, vault, tokeniser_fn)
            for tc in msg["tool_calls"]
        ]
    return out


def _tokenise_tool_call(tc: dict, vault: Vault, tokeniser_fn) -> dict:
    out = dict(tc)
    fn = tc.get("function")
    if not isinstance(fn, dict):
        return out
    args_raw = fn.get("arguments")
    if not isinstance(args_raw, str):
        return out
    try:
        args = json.loads(args_raw)
    except json.JSONDecodeError:
        return out
    walked = _walk_json_tokenise(args, vault, tokeniser_fn)
    out["function"] = {**fn, "arguments": json.dumps(walked, ensure_ascii=False)}
    return out


def _walk_json_tokenise(value, vault: Vault, tokeniser_fn):
    if isinstance(value, str):
        return tokeniser_fn(value, vault)
    if isinstance(value, list):
        return [_walk_json_tokenise(v, vault, tokeniser_fn) for v in value]
    if isinstance(value, dict):
        return {k: _walk_json_tokenise(v, vault, tokeniser_fn) for k, v in value.items()}
    return value


# ── Request-side locked-category scan ─────────────────────────────────────

def scan_request_for_locked(body: dict, scan_fn) -> list[str]:
    """Mirror of apf.proxy._scan_body_for_locked but for OpenAI shape.
    scan_fn is the read-only detector-only scanner that returns locked
    label names without writing to vault."""
    seen: list[str] = []
    def _add(labels: list[str]) -> None:
        for l in labels:
            if l not in seen:
                seen.append(l)
    for msg in body.get("messages", []) or []:
        content = msg.get("content")
        if isinstance(content, str):
            _add(scan_fn(content))
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    _add(scan_fn(part.get("text", "")))
        # We don't scan tool_calls.arguments here because if locked
        # content showed up there it came from a prior round-trip the
        # proxy already vetted; the scan is for fresh user input.
    return seen


# ── Response walker (upstream → client) ───────────────────────────────────

def detokenise_response(body: dict, vault: Vault, secret_resolver) -> dict:
    """Walk an OpenAI Chat Completions response, detokenise text content
    and resolve tool_call.function.arguments at the boundary."""
    out = dict(body)
    choices = body.get("choices")
    if not isinstance(choices, list):
        return out
    new_choices: list[dict] = []
    for choice in choices:
        new_choices.append(_detokenise_choice(choice, vault, secret_resolver))
    out["choices"] = new_choices
    return out


def _detokenise_choice(choice: dict, vault: Vault, secret_resolver) -> dict:
    out = dict(choice)
    msg = choice.get("message")
    if isinstance(msg, dict):
        new_msg = dict(msg)
        if isinstance(msg.get("content"), str):
            new_msg["content"] = detokenize_text(msg["content"], vault)
        if isinstance(msg.get("tool_calls"), list):
            new_msg["tool_calls"] = [
                _resolve_tool_call(tc, vault, secret_resolver)
                for tc in msg["tool_calls"]
            ]
        out["message"] = new_msg
    return out


def _resolve_tool_call(tc: dict, vault: Vault, secret_resolver) -> dict:
    out = dict(tc)
    fn = tc.get("function")
    if not isinstance(fn, dict):
        return out
    args_raw = fn.get("arguments")
    if not isinstance(args_raw, str):
        return out
    try:
        args = json.loads(args_raw)
    except json.JSONDecodeError:
        return out
    resolved = resolve_tool_call_args(args, vault, secret_resolver=secret_resolver)
    out["function"] = {**fn, "arguments": json.dumps(resolved, ensure_ascii=False)}
    return out


# ── SSE rewriter for OpenAI streaming format ──────────────────────────────
# OpenAI streams data-only SSE chunks:
#   data: {"id":"...","choices":[{"delta":{"content":"Hello"},"index":0}]}
#   data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\""}}]}}]}
#   data: [DONE]
#
# Strategy:
# - text content: same partial-token-tail buffering as the Anthropic
#   text path, but the chunk shape is different so we extract+replace
#   the .content string per chunk.
# - tool_calls.function.arguments: accumulate across deltas (same
#   approach as Anthropic input_json_delta), parse + resolve when the
#   stream signals completion (finish_reason in a later chunk).


_PARTIAL_TOKEN_RE = re.compile(
    r"<[A-Z_][A-Z0-9_]*$|<S$|<SE$|<SEC$|<SECR$|<SECRE$|<SECRET$|<SECRET#\d*$"
)


def _split_safe(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    last_open = text.rfind("<")
    if last_open == -1:
        return text, ""
    if ">" in text[last_open:]:
        return text, ""
    tail = text[last_open:]
    if len(tail) > 48:
        return text, ""
    return text[:last_open], tail


@dataclass
class _ToolCallAccum:
    id: str = ""
    name: str = ""
    arguments_buf: str = ""
    emitted: bool = False


class OpenAISSERewriter:
    """Rewrite an OpenAI Chat Completions SSE stream on the fly.

    feed(raw_event_text) yields rewritten SSE chunk strings (or empties
    that should be held). flush() yields any final held content.
    """

    def __init__(self, vault: Vault, secret_resolver=None) -> None:
        self.vault = vault
        self.secret_resolver = secret_resolver
        # Per-choice text-buffer + per-(choice,tool_index) tool-call accumulator
        self.text_held: dict[int, str] = {}
        self.tool_calls: dict[tuple[int, int], _ToolCallAccum] = {}

    def feed(self, payload: str) -> list[str]:
        """Process one SSE 'data: ...' payload. Returns a list of output
        SSE chunks (formatted ready to send) — usually one rewritten or
        held; can be empty if waiting for more."""
        payload = payload.strip()
        if not payload:
            return []
        if payload == "[DONE]":
            # Flush any final held text per choice; then emit [DONE].
            out: list[str] = []
            for idx, held in self.text_held.items():
                if held:
                    obj = {"choices": [{"index": idx,
                                        "delta": {"content": held}}]}
                    out.append(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n")
                    self.text_held[idx] = ""
            # Emit accumulated tool_calls if any
            out.extend(self._emit_pending_tool_calls())
            out.append("data: [DONE]\n\n")
            return out
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            # Malformed chunk — pass through verbatim
            return [f"data: {payload}\n\n"]
        choices = data.get("choices")
        if not isinstance(choices, list):
            return [f"data: {json.dumps(data, ensure_ascii=False)}\n\n"]
        new_choices = []
        for choice in choices:
            new_choices.append(self._process_choice(choice))
        data["choices"] = new_choices
        out = [f"data: {json.dumps(data, ensure_ascii=False)}\n\n"]
        # If any choice's finish_reason is non-null, flush its tool calls.
        for choice in choices:
            if choice.get("finish_reason"):
                out.extend(self._emit_pending_tool_calls())
                break
        return out

    def _process_choice(self, choice: dict) -> dict:
        idx = choice.get("index", 0)
        out = dict(choice)
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            return out
        new_delta = dict(delta)
        # Text content
        if isinstance(delta.get("content"), str):
            combined = self.text_held.get(idx, "") + delta["content"]
            safe, held = _split_safe(combined)
            self.text_held[idx] = held
            if safe:
                new_delta["content"] = detokenize_text(safe, self.vault)
            else:
                # Nothing to emit yet — but we still emit an empty chunk
                # to preserve the chunk count semantics? Skip the
                # content field, leave other delta keys intact.
                new_delta.pop("content", None)
        # Tool calls
        if isinstance(delta.get("tool_calls"), list):
            # Tool calls stream incrementally; accumulate, don't emit
            # arguments live. The chunks that ONLY carry argument
            # fragments get their tool_calls stripped here — we emit
            # the resolved tool_call when finish_reason arrives.
            for tc_delta in delta["tool_calls"]:
                self._accumulate_tool_call(idx, tc_delta)
            new_delta.pop("tool_calls", None)
        out["delta"] = new_delta
        return out

    def _accumulate_tool_call(self, choice_idx: int, tc_delta: dict) -> None:
        ti = tc_delta.get("index", 0)
        key = (choice_idx, ti)
        accum = self.tool_calls.setdefault(key, _ToolCallAccum())
        if "id" in tc_delta and tc_delta["id"]:
            accum.id = tc_delta["id"]
        fn = tc_delta.get("function") or {}
        if "name" in fn and fn["name"]:
            accum.name = fn["name"]
        if "arguments" in fn:
            accum.arguments_buf += fn["arguments"]

    def _emit_pending_tool_calls(self) -> list[str]:
        out: list[str] = []
        for (choice_idx, ti), accum in list(self.tool_calls.items()):
            if accum.emitted or not accum.arguments_buf:
                continue
            try:
                args = json.loads(accum.arguments_buf)
            except json.JSONDecodeError:
                # Incomplete — leave it pending. Will be flushed at [DONE].
                continue
            resolved = resolve_tool_call_args(
                args, self.vault, secret_resolver=self.secret_resolver,
            )
            chunk = {
                "choices": [{
                    "index": choice_idx,
                    "delta": {
                        "tool_calls": [{
                            "index": ti,
                            "id": accum.id,
                            "type": "function",
                            "function": {
                                "name": accum.name,
                                "arguments": json.dumps(resolved, ensure_ascii=False),
                            },
                        }],
                    },
                }],
            }
            out.append(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n")
            accum.emitted = True
        return out

    def flush(self) -> list[str]:
        # Last-resort: anything still held when the stream ends without
        # a clean [DONE] (e.g. upstream truncation).
        out: list[str] = []
        for idx, held in self.text_held.items():
            if held:
                obj = {"choices": [{"index": idx, "delta": {"content": held}}]}
                out.append(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n")
                self.text_held[idx] = ""
        out.extend(self._emit_pending_tool_calls())
        return out
