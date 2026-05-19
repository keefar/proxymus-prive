"""FastAPI proxy intercepting the Anthropic Messages API.

Flow (non-streaming PoC):

    client (Claude Code) ──POST /v1/messages──▶ proxy
                                                   │
                                                   ├── tokenise outbound text via detector
                                                   ├── vault stores originals
                                                   │
                                                   └─POST /v1/messages──▶ api.anthropic.com
                                                                            │
    client ◀──── detokenised body ────── proxy ◀────── response ──────────┘
       │                                    │
       │                                    └── resolve tool_use args at boundary
       │                                        (Tier C via secret_resolver hook)
       │
       └── client executes tool_use with REAL values, returns tool_result
                  ▼
            (next turn — proxy re-tokenises the tool_result)

Session model
-------------
The proxy is stateless across turns *within* a process — every request
carries the full conversation history. Token IDs (`<REF_3>`) must stay
stable within a conversation. We key the vault by the `x-apf-session`
header (client-supplied UUID); fall back to per-request session when the
header is absent.

Limitations of this PoC
-----------------------
- Non-streaming only. SSE streaming requires chunk-aware rewriting and
  is a follow-up.
- The secret resolver is a stub — returns a placeholder. A real wiring
  would read from env / Keychain based on the surrounding context.
- No multi-API support (just /v1/messages); OpenAI / OAI-compatible
  routing is a follow-up.
- No auth check on inbound — assumes localhost binding (127.0.0.1).
"""
from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .audit_log import LOG as _AUDIT_LOG, enabled as _audit_enabled
from .detokenizer import detokenize_text
from .endpoint_policy import POLICY_OFF, policy_for_url
from .local_only import categories_in, refusal_body
from .openai_shape import (
    OpenAISSERewriter,
    detokenise_response as oai_detokenise_response,
    scan_request_for_locked as oai_scan_for_locked,
    tokenise_request as oai_tokenise_request,
)
from .resolver import resolve_tool_call_args
from .secrets import make_default_store, resolver_for_vault
from .sse import SSERewriter, format_sse_event, parse_sse_event
from .tokenizer import Span, tokenize_text
from .vault import Vault

ANTHROPIC_UPSTREAM = os.environ.get(
    "APF_UPSTREAM_BASE", "https://api.anthropic.com"
)
# Per apf-fwt user clarification 2026-05-17: the OpenAI path is OpenAI-
# *compatible* (not OpenAI-specific). The user configures whichever
# OAI-compatible upstream they want (api.openai.com, localhost:11434
# for Ollama, api.groq.com, api.together.ai, LM Studio, oMLX, etc.).
# Default empty — operator must opt in by setting it.
OPENAI_UPSTREAM = os.environ.get("APF_OPENAI_UPSTREAM", "")

# Cached at module load so policy decisions don't hit disk per request.
_UPSTREAM_POLICY = policy_for_url(ANTHROPIC_UPSTREAM)
_OPENAI_UPSTREAM_POLICY = (
    policy_for_url(OPENAI_UPSTREAM) if OPENAI_UPSTREAM else POLICY_OFF
)
PROXY_PORT = int(os.environ.get("APF_PORT", "8765"))

# apf-lnr: control-plane system prompts (filter explainer, agent personality,
# tool-use schemas) add steady-baseline false-positives to every vault when
# tokenised, and confuse models that expect their system prompt verbatim.
# Default: skip role=system. Opt-in via APF_TOKENISE_SYSTEM=1 for setups
# whose system prompts legitimately contain user PII the proxy should mask.
# Note: the locked-category scan ALWAYS runs on system messages regardless
# of this flag — the safety net for never-forward categories does not depend
# on whether we tokenise.
TOKENISE_SYSTEM = os.environ.get("APF_TOKENISE_SYSTEM", "0") != "0"

# apf-1f6: labels detected but NOT tokenised — the value passes through raw.
# ORG is opt-out by default: for the coding-agent use case the overwhelming
# majority of ORG mentions are public software / services (GitHub, Stripe,
# OpenAI) where masking yields ~zero privacy gain and breaks the prompt
# ('write a Stripe client' with <REF_N> is nonsense). Genuinely sensitive
# org-ish content (employer, asylum/abuse-related orgs) is covered by other
# labels / the locked-category set. Override with APF_SKIP_LABELS (comma-
# separated); set APF_SKIP_LABELS= (empty) to mask everything including ORG.
def _load_skip_labels() -> frozenset[str]:
    raw = os.environ.get("APF_SKIP_LABELS")
    if raw is None:
        return frozenset({"ORG"})
    return frozenset(t.strip() for t in raw.split(",") if t.strip())


SKIP_LABELS = _load_skip_labels()

# Per-session vaults. In production: bounded LRU with eviction; for PoC, dict.
_VAULTS: dict[str, Vault] = {}
_DETECTOR: Any = None


def _get_or_create_vault(session_id: str | None) -> tuple[str, Vault]:
    if session_id is None:
        session_id = f"anon-{uuid.uuid4().hex[:12]}"
    if session_id not in _VAULTS:
        _VAULTS[session_id] = Vault()
    return session_id, _VAULTS[session_id]


_INLINE_BYPASS_RE = re.compile(r'!raw\s+(?:"([^"]+)"|(\S+))')


def _extract_inline_bypass(text: str, vault: Vault) -> str:
    """Strip `!raw VALUE` markers from the user's text and add VALUE to the
    session whitelist (apf-qzc). Two forms accepted:

    - `!raw foo@example.com`       — single whitespace-delimited token
    - `!raw "John Smith"`          — quoted multi-word value (for names,
                                     addresses with spaces, etc.)

    Once whitelisted, the value passes through detection+tokenisation
    unmodified for the rest of the session. Use the
    /v1/sessions/{id}/whitelist endpoint for bulk additions.
    """
    if "!raw" not in text:
        return text
    def _consume(m: re.Match[str]) -> str:
        # Quoted form group 1 wins if present, else bare token group 2.
        value = m.group(1) if m.group(1) is not None else m.group(2)
        vault.add_whitelist(value)
        return value
    return _INLINE_BYPASS_RE.sub(_consume, text)


def _tokenise_text(text: str, vault: Vault) -> str:
    if not text or not _DETECTOR:
        return text
    cleaned = _extract_inline_bypass(text, vault)
    detected = _DETECTOR.detect(cleaned)
    # apf-1f6: drop spans whose label is in SKIP_LABELS (default: ORG) —
    # detected but not masked, the value passes through raw.
    spans = [Span(start=s.start, end=s.end, label=s.label, tier=s.tier,
                  confidence=getattr(s, "confidence", 1.0))
             for s in detected if s.label not in SKIP_LABELS]
    return tokenize_text(cleaned, spans, vault)


def _scan_text_for_locked(text: str) -> list[str]:
    """Read-only locked-label scan. Detects spans on `text`, returns the
    set of locked-label names encountered. Does NOT tokenise, does NOT
    write to the vault.

    This is run before tokenisation (apf-enr) so locked values are never
    vaulted at all — the proxy refuses to forward and the values stay in
    the original request body, which is discarded along with the 422
    response.
    """
    if not text or not _DETECTOR:
        return []
    detected = _DETECTOR.detect(text)
    return categories_in(detected)


def _scan_body_for_locked(body: dict) -> list[str]:
    """Walk the same shape as _tokenise_request_body but only collect
    locked-category labels. Returns deduplicated list (ordered by first
    sight)."""
    seen: list[str] = []
    def _add(labels: list[str]) -> None:
        for l in labels:
            if l not in seen:
                seen.append(l)
    if isinstance(body.get("system"), str):
        _add(_scan_text_for_locked(body["system"]))
    elif isinstance(body.get("system"), list):
        # apf-47e: the Anthropic API accepts `system` as either a string or
        # a list of typed parts. The locked-cat safety net has to scan both
        # shapes regardless of TOKENISE_SYSTEM — otherwise a list-form
        # system prompt with locked content could silently forward.
        for part in body["system"]:
            if isinstance(part, dict) and part.get("type") == "text":
                _add(_scan_text_for_locked(part.get("text", "")))
    for msg in body.get("messages", []) or []:
        content = msg.get("content")
        if isinstance(content, str):
            _add(_scan_text_for_locked(content))
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    _add(_scan_text_for_locked(part.get("text", "")))
                elif part.get("type") == "tool_result":
                    tc = part.get("content")
                    if isinstance(tc, str):
                        _add(_scan_text_for_locked(tc))
                    elif isinstance(tc, list):
                        for tp in tc:
                            if isinstance(tp, dict) and tp.get("type") == "text":
                                _add(_scan_text_for_locked(tp.get("text", "")))
    return seen


def _tokenise_block(block: Any, vault: Vault) -> Any:
    """Walk a content block (str or list of part-dicts) and tokenise text parts."""
    if isinstance(block, str):
        return _tokenise_text(block, vault)
    if isinstance(block, list):
        return [_tokenise_part(part, vault) for part in block]
    return block


def _tokenise_part(part: dict, vault: Vault) -> dict:
    if part.get("type") == "text":
        return {**part, "text": _tokenise_text(part.get("text", ""), vault)}
    if part.get("type") == "tool_result":
        # Tool results coming back FROM the client TO the LLM also need
        # to be tokenised — they may contain PII (grep output, db rows, etc).
        content = part.get("content")
        if isinstance(content, str):
            return {**part, "content": _tokenise_text(content, vault)}
        if isinstance(content, list):
            return {**part, "content": [_tokenise_part(p, vault) for p in content]}
    return part


_SECRET_STORE = make_default_store(
    allow_vault_fallback=os.environ.get("APF_VAULT_FALLBACK", "1") != "0",
)


def _make_secret_resolver(vault: Vault):
    """Build a vault-bound secret resolver for one tool_use payload.
    Uses env var lookup first (via the captured KEY name when KEY=VALUE
    was detected), then falls back to vault.original unless the operator
    disables vault fallback via APF_VAULT_FALLBACK=0."""
    return resolver_for_vault(vault, _SECRET_STORE)


def _detokenise_response_body(body: dict, vault: Vault) -> dict:
    """For Anthropic Messages API response shape:
        {role, content: [{type: text|tool_use, ...}]}

    - text parts: detokenise for the client (it's about to be shown to
      the user, who should see the originals).
    - tool_use parts: resolve `input` JSON via the boundary resolver
      (the client executor needs real values to run the tool).
    """
    content = body.get("content")
    if not isinstance(content, list):
        return body
    new_content = []
    for part in content:
        ptype = part.get("type")
        if ptype == "text":
            new_content.append({
                **part,
                "text": detokenize_text(part.get("text", ""), vault),
            })
        elif ptype == "tool_use":
            new_content.append({
                **part,
                "input": resolve_tool_call_args(
                    part.get("input", {}), vault,
                    secret_resolver=_make_secret_resolver(vault),
                ),
            })
        else:
            new_content.append(part)
    return {**body, "content": new_content}


def _tokenise_request_body(body: dict, vault: Vault) -> dict:
    """Walk an Anthropic Messages API request and tokenise text + tool_result
    content. The top-level `system` field is skipped unless TOKENISE_SYSTEM
    is enabled (apf-lnr). Leave the rest untouched."""
    out = dict(body)
    if TOKENISE_SYSTEM:
        if isinstance(out.get("system"), str):
            out["system"] = _tokenise_text(out["system"], vault)
        elif isinstance(out.get("system"), list):
            out["system"] = [_tokenise_part(p, vault) for p in out["system"]]
    if isinstance(out.get("messages"), list):
        new_messages = []
        for msg in out["messages"]:
            new_messages.append({
                **msg,
                "content": _tokenise_block(msg.get("content"), vault),
            })
        out["messages"] = new_messages
    return out


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm up the detector once at startup."""
    global _DETECTOR
    from benchmarks.adapters_mlx import EnsembleMaxAdapter
    _DETECTOR = EnsembleMaxAdapter()
    _DETECTOR.warmup()
    yield


app = FastAPI(title="apf — agent privacy filter", lifespan=lifespan)


@app.get("/healthz")
async def health() -> dict:
    return {
        "status": "ok",
        "detector": _DETECTOR.name if _DETECTOR else None,
        "active_sessions": len(_VAULTS),
        "upstream": ANTHROPIC_UPSTREAM,
    }


@app.get("/v1/sessions/{session_id}/audit")
async def session_audit(session_id: str) -> dict:
    """Return audit entries for a session. Empty unless APF_AUDIT_LOG=1
    was set when the entries were recorded. See apf/audit_log.py for
    the deliberately limited shape (counts only, never values)."""
    if not _audit_enabled():
        return {"session_id": session_id, "enabled": False, "entries": []}
    return {"session_id": session_id, "enabled": True,
            "entries": _AUDIT_LOG.entries_for(session_id)}


@app.post("/v1/sessions/{session_id}/whitelist")
async def add_whitelist(session_id: str, request: Request) -> dict:
    """Add user-declared bypass values to the session whitelist (apf-qzc).

    Body: {"values": ["alice@example.com", "MyPseudonym", ...]}

    Values added here pass through detection+tokenisation untouched for
    the rest of the session. Use for values the user knows are safe to
    forward raw (their own pseudonyms, already-public addresses, test
    fixture values). Inline `!raw VALUE` in the message text does the same
    thing for one-off cases.
    """
    body = await request.json()
    values = body.get("values") or []
    if not isinstance(values, list):
        return Response(  # type: ignore[return-value]
            content=json.dumps({"error": "values must be a list"}),
            status_code=400, media_type="application/json",
        )
    _, vault = _get_or_create_vault(session_id)
    added = 0
    for v in values:
        if isinstance(v, str) and v.strip():
            vault.add_whitelist(v)
            added += 1
    return {"session_id": session_id, "added": added,
            "total_whitelist": vault.whitelist_size()}


@app.get("/v1/sessions/{session_id}/status")
async def session_status(session_id: str) -> dict:
    """On-demand vault summary. Counts only — no original values, no surface
    tokens. Lets a user (or their wrapper UI) answer 'what has the proxy done
    in this session?' without trawling logs.

    Per docs/THREAT-MODEL-PRIVATE.md §5.4, this is the data source for
    cumulative-profile warnings: orthogonal categories per_label['…'] and
    third-party counts let a client compute a profile-diversity score.
    """
    vault = _VAULTS.get(session_id)
    if vault is None:
        return {"session_id": session_id, "exists": False, "summary": None}
    return {"session_id": session_id, "exists": True,
            "summary": vault.summary()}


@app.get("/v1/sessions/{session_id}/uncertain")
async def list_uncertain(session_id: str, threshold: float = 0.85) -> dict:
    """List vault entries with confidence below the threshold — candidates
    for a user-confirmation UX. Surface tokens for Tier-A/B; for Tier-C
    return only a per-session sequence number (real secret values must not
    leak via this endpoint)."""
    vault = _VAULTS.get(session_id)
    if vault is None:
        return {"session_id": session_id, "uncertain": [], "exists": False}
    entries = vault.low_confidence_entries(threshold=threshold)
    out = []
    secret_idx = 0
    for e in entries:
        if e.tier == "C":
            secret_idx += 1
            out.append({
                "kind": "secret",
                "ref": f"REF#{secret_idx}",
                "label": e.label,
                "tier": e.tier,
                "confidence": e.confidence,
            })
        else:
            out.append({
                "kind": "regular",
                "token": e.token,
                "original": e.original,
                "label": e.label,
                "tier": e.tier,
                "confidence": e.confidence,
            })
    return {"session_id": session_id, "uncertain": out, "exists": True,
            "threshold": threshold}


@app.post("/v1/messages")
async def messages(
    request: Request,
    x_api_key: str | None = Header(default=None),
    anthropic_version: str | None = Header(default=None),
    x_apf_session: str | None = Header(default=None),
) -> Response:
    inbound = await request.json()
    session_id, vault = _get_or_create_vault(x_apf_session)

    # Per apf-enr: refuse to forward content in locked categories
    # (asylum, abuse, whistleblower intent, undocumented immigration).
    # Tokenisation is not safe enough for these — the fact of processing
    # them is itself a leak. Scan is read-only; values never enter the
    # vault. Skipped when policy=off because the values aren't going to
    # a cloud upstream anyway.
    if _UPSTREAM_POLICY != POLICY_OFF:
        locked = _scan_body_for_locked(inbound)
        if locked:
            return JSONResponse(
                content=refusal_body(locked),
                status_code=422,
                headers={"x-apf-session": session_id,
                         "x-apf-locked-categories": ",".join(locked)},
            )

    # Per apf-ycu: if the upstream is a trusted endpoint (local engines,
    # user-configured exceptions), bypass tokenisation entirely. The proxy
    # then acts as a transparent passthrough — useful for routing all
    # traffic through one tool but only filtering cloud destinations.
    if _UPSTREAM_POLICY == POLICY_OFF:
        tokenised = inbound
    else:
        tokenised = _tokenise_request_body(inbound, vault)
        # Per apf-ive: record category counts to the audit log (off unless
        # APF_AUDIT_LOG=1). Counts only, never values; safe to surface.
        if _audit_enabled():
            _AUDIT_LOG.record(session_id, vault.summary())

    # Forward to Anthropic. We pass through Authorization/x-api-key from the
    # caller. The proxy itself doesn't hold an API key.
    upstream_headers = {
        "content-type": "application/json",
        "anthropic-version": anthropic_version or "2023-06-01",
    }
    if x_api_key:
        upstream_headers["x-api-key"] = x_api_key
    auth = request.headers.get("authorization")
    if auth:
        upstream_headers["authorization"] = auth
    # apf-3mb: beta-gated body fields (context_management, …) that clients
    # like Claude Code send are only accepted by the API when the matching
    # `anthropic-beta` header is present. Dropping it makes the API 400 the
    # unknown body field ("Extra inputs are not permitted"). Forward verbatim
    # — the header is a comma-separated list of beta flags.
    beta = request.headers.get("anthropic-beta")
    if beta:
        upstream_headers["anthropic-beta"] = beta

    # Streaming path: tokenised request is forwarded with `stream: true`,
    # response is rewritten on the fly via SSERewriter.
    if tokenised.get("stream") is True:
        return await _stream_messages(
            session_id, vault, tokenised, upstream_headers
        )

    async with httpx.AsyncClient(timeout=120.0) as client:
        upstream = await client.post(
            f"{ANTHROPIC_UPSTREAM}/v1/messages",
            json=tokenised,
            headers=upstream_headers,
        )
        upstream_body = upstream.json() if upstream.headers.get(
            "content-type", "").startswith("application/json") else None

    if upstream_body is None:
        # Non-JSON response — pass through unmodified.
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers={"x-apf-session": session_id, **{
                k: v for k, v in upstream.headers.items()
                if k.lower() not in ("content-length", "content-encoding")
            }},
        )

    # Detokenise the response for the client.
    rewritten = _detokenise_response_body(upstream_body, vault)
    response_headers = _build_response_headers(session_id, vault)
    return JSONResponse(
        content=rewritten,
        status_code=upstream.status_code,
        headers=response_headers,
    )


def _build_response_headers(session_id: str, vault: Vault) -> dict[str, str]:
    """Compose the apf-* response headers from session vault state.

    Per docs/THREAT-MODEL-PRIVATE.md §5.4 / apf-80c, the UX-feedback channel
    is response headers (machine-readable, default-invisible) plus the
    /v1/sessions/{id}/status endpoint for on-demand inspection. Headers
    carry counts only — never originals, never surface tokens for sensitive
    entries (only uncertain ones are token-listed, because the user
    explicitly wants to inspect them).
    """
    headers = {"x-apf-session": session_id}
    summary = vault.summary()
    if summary["total"]:
        headers["x-apf-replaced-count"] = str(summary["total"])
        # Per-tier breakdown: 'A=3,B=1,C=2' compact form.
        headers["x-apf-replaced-tiers"] = ",".join(
            f"{tier}={cnt}" for tier, cnt in sorted(summary["per_tier"].items())
        )
        # Per-label distribution: same compact form. Categories not values.
        headers["x-apf-replaced-categories"] = ",".join(
            f"{label}={cnt}"
            for label, cnt in sorted(summary["per_label"].items())
        )
        if summary["third_party"]:
            headers["x-apf-third-party-count"] = str(summary["third_party"])
    # Uncertain channel (apf-2yn pre-existing): list of token IDs the user
    # may want to inspect via the uncertain endpoint.
    uncertain = vault.low_confidence_entries(threshold=0.85)
    if uncertain:
        headers["x-apf-uncertain"] = ",".join(
            e.token if e.tier != "C" else f"REF#{i}"
            for i, e in enumerate(uncertain))
        headers["x-apf-uncertain-count"] = str(len(uncertain))
    return headers


async def _stream_messages(
    session_id: str, vault: Vault, tokenised_body: dict, upstream_headers: dict,
) -> StreamingResponse:
    """SSE relay: forward tokenised stream request, rewrite each event on
    the fly via SSERewriter. Token-spanning boundaries are buffered per
    content block; tool_use input JSON is accumulated and resolved at
    content_block_stop."""
    rewriter = SSERewriter(vault, secret_resolver=_make_secret_resolver(vault))

    async def generate():
        buffer = ""
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{ANTHROPIC_UPSTREAM}/v1/messages",
                json=tokenised_body,
                headers=upstream_headers,
            ) as upstream:
                async for chunk in upstream.aiter_text():
                    buffer += chunk
                    while True:
                        ev_type, ev_data, buffer = parse_sse_event(buffer)
                        if ev_type is None:
                            break
                        if ev_data is None:
                            # Forward malformed/empty events as-is.
                            yield (f"event: {ev_type}\ndata: \n\n").encode("utf-8")
                            continue
                        for out_type, out_data in rewriter.feed(ev_type, ev_data):
                            yield format_sse_event(out_type, out_data)
        # End of upstream — flush any held text.
        for out_type, out_data in rewriter.flush():
            yield format_sse_event(out_type, out_data)

    # Request-side tokenisation is complete; summary headers are stable from
    # here on (LLM output doesn't add new vault entries, only references them).
    headers = _build_response_headers(session_id, vault)
    headers["cache-control"] = "no-cache"
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers=headers,
    )


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    x_apf_session: str | None = Header(default=None),
) -> Response:
    """OpenAI-compatible Chat Completions endpoint (apf-fwt).

    Forwards to whatever upstream URL the operator has configured via
    APF_OPENAI_UPSTREAM — that covers api.openai.com, Ollama on
    localhost, LM Studio, vLLM, Groq, Together, Mistral, OpenRouter,
    Cerebras, SambaNova, oMLX, mlx-lm and anything else that speaks
    OAI-compatible. Same per-session vault, same locked-category
    refusal, same audit and feedback headers as /v1/messages.

    Auth headers (Authorization, OpenAI-Organization, etc.) are passed
    through from the client request unchanged — the proxy itself never
    holds credentials.
    """
    if not OPENAI_UPSTREAM:
        return JSONResponse(
            content={
                "error": {
                    "type": "apf_upstream_not_configured",
                    "message": (
                        "Set APF_OPENAI_UPSTREAM to the base URL of any "
                        "OpenAI-compatible endpoint (e.g. http://localhost:11434 "
                        "for Ollama, https://api.openai.com, https://api.groq.com)."
                    ),
                }
            },
            status_code=503,
        )
    inbound = await request.json()
    session_id, vault = _get_or_create_vault(x_apf_session)

    # Locked-category refusal (apf-enr) on the OpenAI shape — same logic,
    # different walker. Skipped when policy=off (trusted local upstream).
    if _OPENAI_UPSTREAM_POLICY != POLICY_OFF:
        locked = oai_scan_for_locked(inbound, _scan_text_for_locked)
        if locked:
            return JSONResponse(
                content=refusal_body(locked),
                status_code=422,
                headers={"x-apf-session": session_id,
                         "x-apf-locked-categories": ",".join(locked)},
            )

    if _OPENAI_UPSTREAM_POLICY == POLICY_OFF:
        tokenised = inbound
    else:
        tokenised = oai_tokenise_request(
            inbound, vault, _tokenise_text, tokenise_system=TOKENISE_SYSTEM,
        )
        if _audit_enabled():
            _AUDIT_LOG.record(session_id, vault.summary())

    # Forward auth + organisation headers as the client sent them.
    upstream_headers = {"content-type": "application/json"}
    for h in ("authorization", "openai-organization", "openai-project"):
        v = request.headers.get(h)
        if v:
            upstream_headers[h] = v

    if tokenised.get("stream") is True:
        return await _stream_chat_completions(
            session_id, vault, tokenised, upstream_headers
        )

    async with httpx.AsyncClient(timeout=120.0) as client:
        upstream = await client.post(
            f"{OPENAI_UPSTREAM}/v1/chat/completions",
            json=tokenised,
            headers=upstream_headers,
        )
        upstream_body = upstream.json() if upstream.headers.get(
            "content-type", "").startswith("application/json") else None

    if upstream_body is None:
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers={"x-apf-session": session_id, **{
                k: v for k, v in upstream.headers.items()
                if k.lower() not in ("content-length", "content-encoding")
            }},
        )
    rewritten = oai_detokenise_response(
        upstream_body, vault, _make_secret_resolver(vault)
    )
    response_headers = _build_response_headers(session_id, vault)
    return JSONResponse(
        content=rewritten,
        status_code=upstream.status_code,
        headers=response_headers,
    )


async def _stream_chat_completions(
    session_id: str, vault: Vault, tokenised_body: dict, upstream_headers: dict,
) -> StreamingResponse:
    """OpenAI streaming relay. Reads data-only SSE chunks from upstream
    and runs them through OpenAISSERewriter."""
    rewriter = OpenAISSERewriter(
        vault, secret_resolver=_make_secret_resolver(vault),
    )

    async def generate():
        buffer = ""
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{OPENAI_UPSTREAM}/v1/chat/completions",
                json=tokenised_body,
                headers=upstream_headers,
            ) as upstream:
                async for chunk in upstream.aiter_text():
                    buffer += chunk
                    while True:
                        # OpenAI SSE is data-only chunks separated by \n\n.
                        # Each chunk starts with "data: " then a JSON
                        # payload (or [DONE]).
                        delim = buffer.find("\n\n")
                        if delim < 0:
                            break
                        chunk_text, buffer = buffer[:delim], buffer[delim+2:]
                        for line in chunk_text.split("\n"):
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            payload = line[len("data:"):].strip()
                            for out_chunk in rewriter.feed(payload):
                                yield out_chunk.encode("utf-8")
        for out_chunk in rewriter.flush():
            yield out_chunk.encode("utf-8")

    headers = _build_response_headers(session_id, vault)
    headers["cache-control"] = "no-cache"
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers=headers,
    )


def main() -> int:
    """Run the proxy. Standard entry: `python -m apf.proxy`."""
    import uvicorn
    uvicorn.run(
        "apf.proxy:app",
        host="127.0.0.1",
        port=PROXY_PORT,
        reload=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    main()
