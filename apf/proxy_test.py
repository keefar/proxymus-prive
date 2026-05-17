"""End-to-end test of the proxy without hitting the real Anthropic API.

Uses FastAPI TestClient + a monkey-patched httpx upstream. Verifies:

1. Outbound tokenisation: the upstream-mock receives the tokenised body,
   not the raw user PII.
2. Inbound detokenisation: the response body returned to the test client
   has tokens swapped for their originals.
3. Tool-use resolution: tool_use.input is resolved at the boundary,
   so the client receives the real values to execute.
4. Session continuity: a second request with the same x-apf-session
   reuses the vault, so the same original value gets the same token.

Run:
    .venv/bin/python -m apf.proxy_test
"""
from __future__ import annotations

import json
import os
import sys

# Pre-flight: set a dummy upstream so the lifespan handler still imports cleanly.
os.environ.setdefault("APF_UPSTREAM_BASE", "http://mock-upstream.invalid")

from fastapi.testclient import TestClient  # noqa: E402

import apf.proxy as proxy  # noqa: E402


class FakeUpstream:
    """Captures the outbound request and returns a canned response."""

    def __init__(self) -> None:
        self.last_request_body: dict | None = None
        self.next_response: dict | None = None

    async def post(self, url, json=None, headers=None):  # noqa: A002
        self.last_request_body = json
        body = self.next_response or {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "(stub)"}],
            "model": "claude-test",
            "stop_reason": "end_turn",
        }

        class _Resp:
            status_code = 200
            content = json_dumps_bytes(body)
            headers = {"content-type": "application/json"}

            def json(self_inner):
                return body

        return _Resp()


def json_dumps_bytes(d: dict) -> bytes:
    return json.dumps(d).encode("utf-8")


def install_fake_upstream(fake: FakeUpstream) -> None:
    """Replace httpx.AsyncClient with a context manager that yields the fake."""
    class _AsyncCtx:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self):
            return fake
        async def __aexit__(self, *a):
            return False
    proxy.httpx.AsyncClient = _AsyncCtx  # type: ignore[attr-defined]


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        print(f"FAIL  {label}")
        print(f"  expected: {expected!r}")
        print(f"  actual:   {actual!r}")
        sys.exit(1)
    print(f"  ok    {label}")


def main() -> int:
    fake = FakeUpstream()
    install_fake_upstream(fake)

    with TestClient(proxy.app) as client:
        # Test 1: round-trip. Two-phase, because under the opaque-default
        # scheme (THREAT-MODEL-PRIVATE.md §5.1) the fake upstream cannot
        # know which <SENSITIVE_N> indices will be minted without having
        # seen the request first. Phase A populates the vault; phase B
        # crafts a response referencing the real vault tokens and verifies
        # full detokenisation.
        print("\n=== Test 1: round-trip ===")

        # Phase A: stub fake, run a request to populate session-A vault.
        fake.next_response = {
            "id": "msg_warmup", "type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "(warm)"}],
            "model": "claude-test", "stop_reason": "end_turn",
        }
        warmup = client.post(
            "/v1/messages",
            json={
                "model": "claude-opus-4-7",
                "max_tokens": 256,
                "messages": [
                    {"role": "user", "content": [
                        {"type": "text", "text":
                         "Hallo Anna, schick die Akte an thomas.weber@example.de bis Freitag."},
                    ]},
                ],
            },
            headers={"x-api-key": "test-key", "x-apf-session": "session-A"},
        )
        assert_eq(warmup.status_code, 200, "warmup status 200")

        # The upstream should have seen tokens, not the raw PII.
        out_body = fake.last_request_body
        out_text = out_body["messages"][0]["content"][0]["text"]
        if "thomas.weber@example.de" in out_text:
            print("FAIL  upstream still saw the raw email")
            print(f"  body: {out_text!r}")
            sys.exit(1)
        if "<SENSITIVE_" not in out_text:
            print("FAIL  upstream body has no opaque tokens — detection or tokenisation broken")
            print(f"  body: {out_text!r}")
            sys.exit(1)
        print(f"  ok    upstream saw tokenised text:")
        print(f"        {out_text!r}")

        # Phase B: build a fake response referencing the actual vault tokens
        # and verify that text + tool_use both detokenise back to originals.
        vault = proxy._VAULTS["session-A"]
        by_orig = {e.original: e for e in vault.all_entries()}
        anna = by_orig["Anna"].token
        email = by_orig["thomas.weber@example.de"].token
        freitag = by_orig["Freitag"].token

        fake.next_response = {
            "id": "msg_1", "type": "message", "role": "assistant",
            "content": [
                {"type": "text", "text": f"Hi {anna}, see you on {freitag}."},
                {"type": "tool_use", "id": "tu_1", "name": "send_email",
                 "input": {"to": email, "subject": "Hello"}},
            ],
            "model": "claude-test", "stop_reason": "tool_use",
        }
        resp = client.post(
            "/v1/messages",
            json={
                "model": "claude-opus-4-7", "max_tokens": 256,
                "messages": [
                    {"role": "user", "content": [
                        {"type": "text", "text":
                         "Erinnere Anna an die Akte für thomas.weber@example.de zum Freitag."},
                    ]},
                ],
            },
            headers={"x-api-key": "test-key", "x-apf-session": "session-A"},
        )
        assert_eq(resp.status_code, 200, "round-trip status 200")

        client_body = resp.json()
        assistant_text = client_body["content"][0]["text"]
        if "<SENSITIVE_" in assistant_text:
            print("FAIL  client response still contained opaque tokens")
            print(f"  text: {assistant_text!r}")
            sys.exit(1)
        if "Anna" not in assistant_text or "Freitag" not in assistant_text:
            print(f"FAIL  client response did not restore originals: {assistant_text!r}")
            sys.exit(1)
        print(f"  ok    client saw detokenised response:")
        print(f"        {assistant_text!r}")

        tool_input = client_body["content"][1]["input"]
        if "<SENSITIVE_" in tool_input.get("to", ""):
            print("FAIL  tool_use.input still contained opaque tokens")
            sys.exit(1)
        if tool_input.get("to") != "thomas.weber@example.de":
            print(f"FAIL  tool_use.input.to mismatch: {tool_input!r}")
            sys.exit(1)
        print(f"  ok    tool_use boundary resolved to real values:")
        print(f"        {tool_input!r}")

        # Test 2: session continuity — same email in second request gets the
        # same token as before (within the same session).
        print("\n=== Test 2: session continuity ===")
        fake.next_response = {
            "id": "msg_2",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-test", "stop_reason": "end_turn",
        }
        resp2 = client.post(
            "/v1/messages",
            json={
                "model": "claude-opus-4-7", "max_tokens": 256,
                "messages": [
                    {"role": "user", "content": [
                        {"type": "text", "text":
                         "Erinnere mich nochmal an thomas.weber@example.de."}
                    ]},
                ],
            },
            headers={"x-api-key": "test-key", "x-apf-session": "session-A"},
        )
        assert_eq(resp2.status_code, 200, "status 200")
        out_text_2 = fake.last_request_body["messages"][0]["content"][0]["text"]
        # The email should have been tokenised, and crucially: the token
        # should match what was used in Test 1 (same session).
        # We can verify by checking session-A vault has one EMAIL entry.
        vault = proxy._VAULTS["session-A"]
        emails = [e for e in vault.all_entries() if e.label == "EMAIL"
                  and e.original == "thomas.weber@example.de"]
        if len(emails) != 1:
            print(f"FAIL  expected 1 EMAIL entry for the address, got {len(emails)}")
            sys.exit(1)
        token = emails[0].token
        if token not in out_text_2:
            print(f"FAIL  second call did not reuse the EMAIL token {token}")
            print(f"  body: {out_text_2!r}")
            sys.exit(1)
        print(f"  ok    second call reused token {token}")

        # Test 3: distinct session gets a fresh vault
        print("\n=== Test 3: session isolation ===")
        fake.next_response = {
            "id": "msg_3", "type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-test", "stop_reason": "end_turn",
        }
        client.post(
            "/v1/messages",
            json={
                "model": "claude-opus-4-7", "max_tokens": 256,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text":
                     "ping thomas.weber@example.com"}]}]
            },
            headers={"x-api-key": "test-key", "x-apf-session": "session-B"},
        )
        if "session-B" not in proxy._VAULTS:
            print("FAIL  session-B vault was not created")
            sys.exit(1)
        if proxy._VAULTS["session-B"] is proxy._VAULTS["session-A"]:
            print("FAIL  sessions A and B share vault state")
            sys.exit(1)
        print("  ok    sessions are isolated")

        # Test 4b: low-confidence flag
        print("\n=== Test 4b: low-confidence header for uncertain spans ===")
        fake.next_response = {
            "id": "msg_lc", "type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-test", "stop_reason": "end_turn",
        }
        # An implicit-PII style text that GLiNER will tag with a low score.
        resp_lc = client.post(
            "/v1/messages",
            json={
                "model": "claude-opus-4-7", "max_tokens": 256,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text":
                     "Der Kollege aus dem Controlling, der nächste Woche heiratet, "
                     "hat einen Termin bei Dr. Schmitt."}]}]
            },
            headers={"x-api-key": "test-key", "x-apf-session": "session-LC"},
        )
        # Check uncertain endpoint
        u = client.get("/v1/sessions/session-LC/uncertain")
        uncertain = u.json().get("uncertain", [])
        # We expect at least one uncertain entry from the implicit-PII paraphrase.
        if not uncertain:
            print("FAIL  no uncertain entries flagged for implicit-PII input")
            sys.exit(1)
        print(f"  ok    /v1/sessions/.../uncertain reports {len(uncertain)} entries")
        # Response should carry the header too
        if "x-apf-uncertain-count" not in resp_lc.headers:
            print("FAIL  response missing x-apf-uncertain-count header")
            sys.exit(1)
        print(f"  ok    x-apf-uncertain-count = {resp_lc.headers['x-apf-uncertain-count']}")

        # Test 4c: UX-feedback headers + status endpoint (apf-80c)
        print("\n=== Test 4c: replaced-count headers + /status endpoint ===")
        # session-A vault has at minimum: Anna (PERSON), thomas.weber@... (EMAIL),
        # Freitag (DATE) → 3 tier-A entries. The session-LC vault from Test 4b
        # adds more. Use session-A here because counts are predictable.
        for hdr in ("x-apf-replaced-count",
                    "x-apf-replaced-tiers",
                    "x-apf-replaced-categories"):
            if hdr not in resp.headers:
                print(f"FAIL  response missing {hdr} header")
                sys.exit(1)
        cnt = int(resp.headers["x-apf-replaced-count"])
        if cnt < 3:
            print(f"FAIL  x-apf-replaced-count too low: {cnt}")
            sys.exit(1)
        print(f"  ok    replaced-count={cnt}, "
              f"tiers={resp.headers['x-apf-replaced-tiers']!r}, "
              f"categories={resp.headers['x-apf-replaced-categories']!r}")
        s = client.get("/v1/sessions/session-A/status")
        st = s.json()
        if not st.get("exists") or st["summary"]["total"] != cnt:
            print(f"FAIL  /status mismatch with header: {st!r} vs cnt={cnt}")
            sys.exit(1)
        print(f"  ok    /status reports same total: {st['summary']['total']}")

        # Test 4d: bypass mechanic (apf-qzc)
        print("\n=== Test 4d: bypass — inline !raw + session whitelist ===")
        # Sub-test 1: inline marker passes a value through untokenised
        fake.next_response = {
            "id": "msg_bp", "type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-test", "stop_reason": "end_turn",
        }
        client.post(
            "/v1/messages",
            json={
                "model": "claude-opus-4-7", "max_tokens": 256,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text":
                     "ping !raw public-alias@example.com and tokenise "
                     "secret@example.com please"}]}]
            },
            headers={"x-api-key": "test-key", "x-apf-session": "session-BP"},
        )
        out_bp = fake.last_request_body["messages"][0]["content"][0]["text"]
        if "public-alias@example.com" not in out_bp:
            print(f"FAIL  inline !raw value did not pass through: {out_bp!r}")
            sys.exit(1)
        if "secret@example.com" in out_bp:
            print(f"FAIL  non-whitelisted value leaked: {out_bp!r}")
            sys.exit(1)
        if "!raw" in out_bp:
            print(f"FAIL  marker '!raw' was not stripped: {out_bp!r}")
            sys.exit(1)
        print(f"  ok    inline !raw: pass-through value + tokenise rest")
        print(f"        upstream saw: {out_bp!r}")

        # Sub-test 2: whitelist endpoint sets persistent bypass
        w = client.post(
            "/v1/sessions/session-WL/whitelist",
            json={"values": ["my-public-handle", "openly-known-email@me.de"]},
        )
        if w.json().get("added") != 2:
            print(f"FAIL  /whitelist did not add 2 values: {w.json()!r}")
            sys.exit(1)
        client.post(
            "/v1/messages",
            json={
                "model": "claude-opus-4-7", "max_tokens": 256,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text":
                     "From my-public-handle to openly-known-email@me.de about "
                     "the meeting with thomas.weber@example.de."}]}]
            },
            headers={"x-api-key": "test-key", "x-apf-session": "session-WL"},
        )
        out_wl = fake.last_request_body["messages"][0]["content"][0]["text"]
        # Whitelisted values must survive…
        for keep in ("openly-known-email@me.de",):
            if keep not in out_wl:
                print(f"FAIL  whitelisted value tokenised: {keep!r} missing from {out_wl!r}")
                sys.exit(1)
        # …non-whitelisted PII must still be tokenised
        if "thomas.weber@example.de" in out_wl:
            print(f"FAIL  non-whitelisted email leaked: {out_wl!r}")
            sys.exit(1)
        print(f"  ok    session whitelist: persistent pass-through")
        print(f"        upstream saw: {out_wl!r}")

        # Test 4e: locked-category refusal (apf-enr)
        print("\n=== Test 4e: locked-category triggers 422 refusal ===")
        # The real detector vocabulary doesn't emit ASYLUM_DETAIL etc. yet,
        # so we temporarily extend the locked set to include a label the
        # detector DOES emit. PERSON is reliable across our adapters.
        old_locked = os.environ.get("APF_LOCKED_LABELS")
        os.environ["APF_LOCKED_LABELS"] = "PERSON"
        try:
            fake.next_response = {  # should not be consumed
                "id": "msg_locked", "type": "message", "role": "assistant",
                "content": [{"type": "text", "text": "should not reach"}],
                "model": "claude-test", "stop_reason": "end_turn",
            }
            resp_locked = client.post(
                "/v1/messages",
                json={
                    "model": "claude-opus-4-7", "max_tokens": 256,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text":
                         "Hi Anna, just checking in about Friday."}]}]
                },
                headers={"x-api-key": "test-key", "x-apf-session": "session-LK"},
            )
            assert_eq(resp_locked.status_code, 422, "status 422 on locked label")
            body = resp_locked.json()
            if body.get("error", {}).get("type") != "apf_locked_category":
                print(f"FAIL  refusal body shape wrong: {body!r}")
                sys.exit(1)
            if "PERSON" not in body["error"]["locked_categories"]:
                print(f"FAIL  locked_categories missing PERSON: {body!r}")
                sys.exit(1)
            if "x-apf-locked-categories" not in resp_locked.headers:
                print("FAIL  x-apf-locked-categories header missing")
                sys.exit(1)
            print(f"  ok    refusal body: type=apf_locked_category, "
                  f"locked_categories={body['error']['locked_categories']}")
            # And: the locked value must NOT have been vaulted
            vault_lk = proxy._VAULTS.get("session-LK")
            if vault_lk is not None:
                anna_in_vault = any(e.original == "Anna"
                                    for e in vault_lk.all_entries())
                if anna_in_vault:
                    print(f"FAIL  locked value was vaulted despite refusal")
                    sys.exit(1)
            print(f"  ok    locked value never entered the vault")
        finally:
            if old_locked is None:
                del os.environ["APF_LOCKED_LABELS"]
            else:
                os.environ["APF_LOCKED_LABELS"] = old_locked

        # Test 4f: audit log off-by-default + opt-in (apf-ive)
        print("\n=== Test 4f: audit log scaffold (off default, opt-in) ===")
        # Default (env not set): /audit reports disabled
        a = client.get("/v1/sessions/session-A/audit")
        if a.json().get("enabled") is not False:
            print(f"FAIL  audit log enabled by default: {a.json()!r}")
            sys.exit(1)
        if a.json().get("entries"):
            print(f"FAIL  audit log had entries while disabled: {a.json()!r}")
            sys.exit(1)
        print(f"  ok    audit log disabled by default")
        # Turn it on, send a request, expect an entry
        os.environ["APF_AUDIT_LOG"] = "1"
        try:
            fake.next_response = {
                "id": "msg_au", "type": "message", "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "model": "claude-test", "stop_reason": "end_turn",
            }
            client.post(
                "/v1/messages",
                json={
                    "model": "claude-opus-4-7", "max_tokens": 256,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text":
                         "Mail an audit-test@example.com schicken"}]}]
                },
                headers={"x-api-key": "test-key", "x-apf-session": "session-AU"},
            )
            a2 = client.get("/v1/sessions/session-AU/audit")
            entries = a2.json().get("entries", [])
            if not entries:
                print(f"FAIL  audit log empty after request: {a2.json()!r}")
                sys.exit(1)
            entry = entries[-1]
            if "summary" not in entry or entry["summary"]["total"] < 1:
                print(f"FAIL  audit entry shape wrong: {entry!r}")
                sys.exit(1)
            # Critical: NO original value must appear in any entry
            entries_json = json.dumps(entries)
            if "audit-test@example.com" in entries_json:
                print(f"FAIL  audit log leaked original value: {entries_json!r}")
                sys.exit(1)
            print(f"  ok    audit entry recorded; values never stored")
            print(f"        summary: {entry['summary']}")
        finally:
            del os.environ["APF_AUDIT_LOG"]

        # Test 4: secrets stay opaque
        print("\n=== Test 4: Tier-C secrets stay opaque to the upstream ===")
        fake.next_response = {
            "id": "msg_4", "type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-test", "stop_reason": "end_turn",
        }
        client.post(
            "/v1/messages",
            json={
                "model": "claude-opus-4-7", "max_tokens": 256,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text":
                     "config: OPENAI_API_KEY=xk-fake-AAAAAAAAAAAAAAAAAAAA12345 "
                     "and PASSWORD=hunter2-fake"}]}]
            },
            headers={"x-api-key": "test-key", "x-apf-session": "session-C"},
        )
        out_secret = fake.last_request_body["messages"][0]["content"][0]["text"]
        for leak in ("xk-fake-AAAAAAAAAAAAAAAAAAAA12345", "hunter2-fake"):
            if leak in out_secret:
                print(f"FAIL  secret leaked to upstream: {leak!r}")
                print(f"  body: {out_secret!r}")
                sys.exit(1)
        if "<SECRET>" not in out_secret:
            print("FAIL  no <SECRET> opaque markers in upstream payload")
            print(f"  body: {out_secret!r}")
            sys.exit(1)
        print(f"  ok    secrets opaque to upstream:")
        print(f"        {out_secret!r}")

    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
