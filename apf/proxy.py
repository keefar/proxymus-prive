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
carries the full conversation history. Token IDs (`<EMAIL_3>`) must stay
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

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse

from .detokenizer import detokenize_text
from .resolver import resolve_tool_call_args
from .tokenizer import Span, tokenize_text
from .vault import Vault

ANTHROPIC_UPSTREAM = os.environ.get(
    "APF_UPSTREAM_BASE", "https://api.anthropic.com"
)
PROXY_PORT = int(os.environ.get("APF_PORT", "8765"))

# Per-session vaults. In production: bounded LRU with eviction; for PoC, dict.
_VAULTS: dict[str, Vault] = {}
_DETECTOR: Any = None


def _get_or_create_vault(session_id: str | None) -> tuple[str, Vault]:
    if session_id is None:
        session_id = f"anon-{uuid.uuid4().hex[:12]}"
    if session_id not in _VAULTS:
        _VAULTS[session_id] = Vault()
    return session_id, _VAULTS[session_id]


def _tokenise_text(text: str, vault: Vault) -> str:
    if not text or not _DETECTOR:
        return text
    detected = _DETECTOR.detect(text)
    spans = [Span(start=s.start, end=s.end, label=s.label, tier=s.tier,
                  confidence=getattr(s, "confidence", 1.0))
             for s in detected]
    return tokenize_text(text, spans, vault)


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


def _stub_secret_resolver() -> str | None:
    """Placeholder. Real implementation reads env var or keychain based on
    tool_use context. For PoC: return a marker so it's obvious in logs."""
    return "[FROM_LOCAL_SECRET_STORE]"


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
                    secret_resolver=_stub_secret_resolver,
                ),
            })
        else:
            new_content.append(part)
    return {**body, "content": new_content}


def _tokenise_request_body(body: dict, vault: Vault) -> dict:
    """Walk an Anthropic Messages API request and tokenise user/system text
    + tool_result content. Leave the rest untouched."""
    out = dict(body)
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
                "ref": f"SECRET#{secret_idx}",
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

    # Tokenise outbound.
    tokenised = _tokenise_request_body(inbound, vault)

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
    # Flag low-confidence entries so the client UI can offer confirmation
    # for paraphrased / implicit PII the detector wasn't sure about.
    uncertain = vault.low_confidence_entries(threshold=0.85)
    response_headers = {"x-apf-session": session_id}
    if uncertain:
        # Compact comma-separated list of token IDs in this session that
        # the user might want to confirm.
        response_headers["x-apf-uncertain"] = ",".join(
            e.token if e.tier != "C" else f"SECRET#{i}"
            for i, e in enumerate(uncertain))
        # And a structured count summary.
        response_headers["x-apf-uncertain-count"] = str(len(uncertain))
    return JSONResponse(
        content=rewritten,
        status_code=upstream.status_code,
        headers=response_headers,
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
