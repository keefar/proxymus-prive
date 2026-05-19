"""SSE rewriter for Anthropic Messages API streaming responses.

The challenge: tokens like `<REF_1>` may straddle SSE chunk boundaries
(`<R` in one chunk, `EF_1>` in the next). Unmasking each chunk
independently would corrupt them. Solution: a small per-content-block
text buffer that holds back any partial-token tail.

Tool-use blocks are handled differently: their `input_json_delta` events
build up a JSON value incrementally. Rather than rewrite the partial JSON
stream (fragile), we accumulate the whole JSON for each tool_use block,
parse it at `content_block_stop`, run the boundary resolver, and emit a
single synthetic delta carrying the resolved JSON. The user sees no
intermediate streaming for tool args — acceptable, since args are short.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .unmasker import unmask_text
from .resolver import resolve_tool_call_args
from .vault import Vault


# A `<` not yet closed by `>` could be the start of a token; hold it back.
# All possible token shapes (<REF>, <REF_N>) start with `<` followed by
# uppercase letters / digits / underscores — the alternative below matches
# every legal prefix of such a token.
_PARTIAL_TOKEN_RE = re.compile(r"<[A-Z_][A-Z0-9_]*$")


def _split_safe(text: str) -> tuple[str, str]:
    """Return (safe_prefix, held_tail). The tail is text that might be
    the beginning of a token — wait for more before emitting."""
    if not text:
        return "", ""
    # Find the last unclosed `<`. If there's no `<` at all, everything is safe.
    last_open = text.rfind("<")
    if last_open == -1:
        return text, ""
    # If the last `<` is followed by a `>`, the token is closed.
    if ">" in text[last_open:]:
        return text, ""
    # Cap held tail at 48 chars — beyond that it's not a real token start.
    tail = text[last_open:]
    if len(tail) > 48:
        return text, ""
    return text[:last_open], tail


@dataclass
class _BlockState:
    """Per-content-block buffering state."""
    kind: str = ""  # "text" | "tool_use"
    pending_text: str = ""  # for text blocks: held partial-token tail
    tool_use_id: str = ""
    tool_use_name: str = ""
    tool_input_json: str = ""  # accumulated input_json_delta payload


class SSERewriter:
    """Stateful rewriter for one upstream streaming response.

    Usage:
        rewriter = SSERewriter(vault)
        for raw_event in iter_upstream_sse(...):
            for outbound_event in rewriter.feed(raw_event):
                yield outbound_event
        for outbound_event in rewriter.flush():
            yield outbound_event
    """

    def __init__(self, vault: Vault, secret_resolver=None) -> None:
        self.vault = vault
        self.secret_resolver = secret_resolver
        self.blocks: dict[int, _BlockState] = {}

    def _unmask(self, text: str) -> str:
        return unmask_text(text, self.vault)

    def feed(self, event_type: str, data: dict) -> list[tuple[str, dict]]:
        """Consume one SSE event, emit zero or more rewritten events."""
        out: list[tuple[str, dict]] = []

        if event_type == "content_block_start":
            idx = data.get("index", 0)
            block = data.get("content_block", {})
            kind = block.get("type", "text")
            self.blocks[idx] = _BlockState(
                kind=kind,
                tool_use_id=block.get("id", ""),
                tool_use_name=block.get("name", ""),
            )
            # text content blocks may start with empty text; pass through
            # as-is. For tool_use we forward the metadata but the input is
            # built up by deltas and emitted at content_block_stop.
            if kind == "text":
                out.append((event_type, data))
            else:
                # tool_use — emit the metadata immediately so the client
                # can prepare; the input will be filled in at stop.
                out.append((event_type, data))

        elif event_type == "content_block_delta":
            idx = data.get("index", 0)
            block = self.blocks.get(idx)
            if block is None:
                # Unknown index — pass through.
                out.append((event_type, data))
                return out

            delta = data.get("delta", {})
            delta_type = delta.get("type")

            if delta_type == "text_delta":
                # Append to pending, split into safe + held.
                combined = block.pending_text + delta.get("text", "")
                safe, held = _split_safe(combined)
                block.pending_text = held
                if safe:
                    new_data = {**data, "delta": {"type": "text_delta",
                                                   "text": self._unmask(safe)}}
                    out.append((event_type, new_data))
                # If nothing safe yet, emit nothing — wait for more.

            elif delta_type == "input_json_delta":
                # Accumulate; don't forward yet. Resolved JSON goes out
                # at content_block_stop.
                block.tool_input_json += delta.get("partial_json", "")

            else:
                out.append((event_type, data))

        elif event_type == "content_block_stop":
            idx = data.get("index", 0)
            block = self.blocks.get(idx)

            if block is None:
                out.append((event_type, data))
                return out

            if block.kind == "text":
                # Flush any pending text (it's not the start of a token after all).
                if block.pending_text:
                    flush_text = self._unmask(block.pending_text)
                    if flush_text:
                        out.append(("content_block_delta", {
                            "type": "content_block_delta", "index": idx,
                            "delta": {"type": "text_delta", "text": flush_text},
                        }))
                    block.pending_text = ""
                out.append((event_type, data))

            elif block.kind == "tool_use":
                # Parse, resolve, emit as a single input_json_delta with
                # the resolved JSON, then close.
                resolved_json = ""
                if block.tool_input_json.strip():
                    try:
                        parsed = json.loads(block.tool_input_json)
                        resolved = resolve_tool_call_args(
                            parsed, self.vault,
                            secret_resolver=self.secret_resolver,
                        )
                        resolved_json = json.dumps(resolved, ensure_ascii=False)
                    except json.JSONDecodeError:
                        # Couldn't parse — best we can do is unmask the
                        # raw JSON string.
                        resolved_json = self._unmask(block.tool_input_json)
                if resolved_json:
                    out.append(("content_block_delta", {
                        "type": "content_block_delta", "index": idx,
                        "delta": {"type": "input_json_delta",
                                  "partial_json": resolved_json},
                    }))
                out.append((event_type, data))

            else:
                out.append((event_type, data))

        elif event_type in ("message_start", "message_delta", "message_stop", "ping"):
            out.append((event_type, data))

        else:
            # Unknown event — forward unchanged.
            out.append((event_type, data))

        return out

    def flush(self) -> list[tuple[str, dict]]:
        """Flush any held buffers at end of stream. Should be called once
        the upstream is exhausted."""
        out: list[tuple[str, dict]] = []
        for idx, block in self.blocks.items():
            if block.kind == "text" and block.pending_text:
                flush_text = self._unmask(block.pending_text)
                if flush_text:
                    out.append(("content_block_delta", {
                        "type": "content_block_delta", "index": idx,
                        "delta": {"type": "text_delta", "text": flush_text},
                    }))
                block.pending_text = ""
        return out


def parse_sse_event(buffer: str) -> tuple[str | None, dict | None, str]:
    """Parse one SSE event from the head of `buffer`.

    Returns (event_type, data_dict, remaining_buffer). If no complete event
    is present, returns (None, None, buffer).
    """
    sep = buffer.find("\n\n")
    if sep == -1:
        return None, None, buffer
    raw = buffer[:sep]
    remaining = buffer[sep + 2:]
    event_type: str | None = None
    data_lines: list[str] = []
    for line in raw.split("\n"):
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
    data_str = "".join(data_lines)
    if not data_str:
        return event_type, None, remaining
    try:
        return event_type, json.loads(data_str), remaining
    except json.JSONDecodeError:
        return event_type, None, remaining


def format_sse_event(event_type: str, data: dict) -> bytes:
    """Format an event for emission to the client."""
    return (f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            ).encode("utf-8")
