"""apf-6dt: wire the resolver's on_unresolved fail-loud hook into the proxy.

apf-tu9 gave the tolerant token resolver an optional on_unresolved callback:
when a mangled REF token (the `REF`+digit shape a weak upstream model
produces) cannot be confidently resolved, the resolver leaves it literal
(fail-loud) and reports it via the callback. The proxy called
resolve_tool_call_args but passed NO callback, so an unresolved-mangled-token
event — a sign the upstream model is mangling tokens and the round-trip is
degrading — was invisible at the proxy level.

This wires on_unresolved on every resolve_tool_call_args call site in the
proxy, accumulating a per-session counter on the Vault and surfacing it
counts-only via /v1/sessions/{id}/status, /v1/sessions and /healthz. The
hard rule: COUNTS ONLY — the unresolved token text (near-PII) is never
stored or surfaced; the count is the signal.

TestClient is used without its context manager so the FastAPI lifespan
(MLX detector load) is skipped — these endpoints never touch the detector.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("APF_UPSTREAM_BASE", "http://mock-upstream.invalid")
os.environ.setdefault("APF_OPENAI_UPSTREAM",
                      "http://mock-openai-upstream.invalid")

from fastapi.testclient import TestClient  # noqa: E402

import apf.openai_shape as openai_shape  # noqa: E402
import apf.proxy as proxy  # noqa: E402
from apf.sse import SSERewriter  # noqa: E402
from apf.vault import Vault  # noqa: E402


# ── Vault counter mechanics ───────────────────────────────────────────────

def test_vault_unresolved_count_starts_at_zero() -> None:
    assert Vault().unresolved_count() == 0


def test_vault_note_unresolved_increments_count() -> None:
    v = Vault()
    v.note_unresolved()
    v.note_unresolved()
    assert v.unresolved_count() == 3 - 1  # two notes → count of 2


def test_vault_note_unresolved_discards_token_text() -> None:
    """note_unresolved satisfies the resolver's Callable[[str], None]
    contract but is counts-only — the near-PII mangled-token variant it
    is handed is discarded, never stored."""
    v = Vault()
    v.note_unresolved()                       # zero-arg call works
    v.note_unresolved("REF_99@secret.example")  # variant-arg call works
    assert v.unresolved_count() == 2
    # The variant text must not be retained anywhere on the vault.
    assert "REF_99@secret.example" not in repr(vars(v))


def test_vault_summary_carries_unresolved_count() -> None:
    v = Vault()
    v.note_unresolved()
    summary = v.summary()
    assert summary["unresolved"] == 1
    # still counts-only — no value/token fields leaked in
    assert all(isinstance(val, (int, dict)) for val in summary.values())


# ── on_unresolved wiring: Anthropic non-streaming path ────────────────────

def _mangled_tool_use_response() -> dict:
    """An Anthropic Messages response whose tool_use input carries a
    mangled REF token (`REF_99` — bracket-stripped) for an ID that was
    never minted in the vault. The tolerant resolver leaves it literal
    and must fire on_unresolved."""
    return {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "tu_1", "name": "send_email",
             "input": {"to": "REF_99", "body": "hello"}},
        ],
    }


def test_anthropic_unmask_bumps_session_counter_on_mangled_token() -> None:
    vault = Vault()
    rewritten = proxy._unmask_response_body(_mangled_tool_use_response(), vault)
    # The mangled token resolves to nothing — it stays literal (fail-loud)…
    assert rewritten["content"][0]["input"]["to"] == "REF_99"
    # …and the proxy-level counter records the event.
    assert vault.unresolved_count() == 1


def test_anthropic_unmask_no_bump_when_all_tokens_resolve() -> None:
    vault = Vault()
    entry = vault.get_or_mint("alice@example.com", "EMAIL", "A")
    body = {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "tu_1", "name": "send_email",
             "input": {"to": entry.token}},
        ],
    }
    rewritten = proxy._unmask_response_body(body, vault)
    assert rewritten["content"][0]["input"]["to"] == "alice@example.com"
    assert vault.unresolved_count() == 0


# ── on_unresolved wiring: OpenAI non-streaming path ───────────────────────

def test_openai_unmask_bumps_session_counter_on_mangled_token() -> None:
    vault = Vault()
    body = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "tc_1", "type": "function",
                    "function": {"name": "send_email",
                                 "arguments": json.dumps({"to": "REF_99"})},
                }],
            },
        }],
    }
    rewritten = openai_shape.unmask_response(
        body, vault, proxy._make_secret_resolver(vault),
        on_unresolved=vault.note_unresolved,
    )
    args = json.loads(
        rewritten["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    assert args["to"] == "REF_99"
    assert vault.unresolved_count() == 1


# ── on_unresolved wiring: OpenAI streaming path ───────────────────────────

def test_openai_sse_bumps_session_counter_on_mangled_token() -> None:
    vault = Vault()
    rewriter = openai_shape.OpenAISSERewriter(
        vault, secret_resolver=proxy._make_secret_resolver(vault),
        on_unresolved=vault.note_unresolved,
    )
    # tool_call streamed in one delta, then finish_reason, then [DONE].
    rewriter.feed(json.dumps({
        "choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 0, "id": "tc_1", "type": "function",
            "function": {"name": "send_email",
                         "arguments": json.dumps({"to": "REF_99"})},
        }]}}],
    }))
    rewriter.feed(json.dumps({
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
    }))
    list(rewriter.flush())
    assert vault.unresolved_count() == 1


# ── on_unresolved wiring: Anthropic streaming path ────────────────────────

def test_anthropic_sse_bumps_session_counter_on_mangled_token() -> None:
    vault = Vault()
    rewriter = SSERewriter(
        vault, secret_resolver=proxy._make_secret_resolver(vault),
        on_unresolved=vault.note_unresolved,
    )
    rewriter.feed("content_block_start", {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "tool_use", "id": "tu_1",
                          "name": "send_email"},
    })
    rewriter.feed("content_block_delta", {
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "input_json_delta",
                  "partial_json": json.dumps({"to": "REF_99"})},
    })
    rewriter.feed("content_block_stop", {
        "type": "content_block_stop", "index": 0})
    list(rewriter.flush())
    assert vault.unresolved_count() == 1


# ── Endpoint surfacing ────────────────────────────────────────────────────

def test_status_endpoint_surfaces_unresolved_count(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "_VAULTS", {})
    _, vault = proxy._get_or_create_vault("sess-mangled")
    vault.note_unresolved()
    vault.note_unresolved()
    resp = TestClient(proxy.app).get("/v1/sessions/sess-mangled/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["unresolved"] == 2


def test_sessions_list_surfaces_unresolved_count(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "_VAULTS", {})
    _, vault = proxy._get_or_create_vault("sess-a")
    vault.note_unresolved()
    resp = TestClient(proxy.app).get("/v1/sessions")
    assert resp.status_code == 200
    sess = next(s for s in resp.json()["sessions"]
                if s["session_id"] == "sess-a")
    assert sess["summary"]["unresolved"] == 1


def test_healthz_surfaces_process_total_unresolved(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "_VAULTS", {})
    _, va = proxy._get_or_create_vault("sess-a")
    _, vb = proxy._get_or_create_vault("sess-b")
    va.note_unresolved()
    va.note_unresolved()
    vb.note_unresolved()
    resp = TestClient(proxy.app).get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["unresolved_tokens"] == 3


# ── Counts-only invariant: no token text anywhere ─────────────────────────

def test_no_mangled_token_text_leaks_into_status_endpoint(monkeypatch) -> None:
    """The unresolved mangled token 'REF_99' is near-PII. After a full
    round-trip that triggers it, the status endpoint payload must contain
    a count — never the token text itself."""
    monkeypatch.setattr(proxy, "_VAULTS", {})
    _, vault = proxy._get_or_create_vault("sess-leak-check")
    proxy._unmask_response_body(_mangled_tool_use_response(), vault)
    resp = TestClient(proxy.app).get("/v1/sessions/sess-leak-check/status")
    raw = resp.text
    assert "REF_99" not in raw, "mangled token text must not leak via status"
    assert resp.json()["summary"]["unresolved"] == 1


def test_no_mangled_token_text_leaks_into_sessions_list(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "_VAULTS", {})
    _, vault = proxy._get_or_create_vault("sess-leak-check")
    proxy._unmask_response_body(_mangled_tool_use_response(), vault)
    raw = TestClient(proxy.app).get("/v1/sessions").text
    assert "REF_99" not in raw


def test_no_mangled_token_text_leaks_into_healthz(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "_VAULTS", {})
    _, vault = proxy._get_or_create_vault("sess-leak-check")
    proxy._unmask_response_body(_mangled_tool_use_response(), vault)
    raw = TestClient(proxy.app).get("/healthz").text
    assert "REF_99" not in raw
