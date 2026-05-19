"""End-to-end smoke test: spins up the proxy in-process and exercises it
with a realistic PII-laden prompt.

Default mode: uses a fake upstream (same fake as proxy_test) so no API
key or network is needed. Reports what the upstream sees vs. what the
client receives, so you can verify the round-trip visually.

Live mode (`--live`): sends to the real Anthropic API. Requires
ANTHROPIC_API_KEY and a model the key is allowed to use.

Run:
    .venv/bin/python -m apf.manual_smoke
    .venv/bin/python -m apf.manual_smoke --live --model claude-haiku-4-5
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from fastapi.testclient import TestClient

# Pre-set upstream so the lifespan import works in fake mode too.
os.environ.setdefault("APF_UPSTREAM_BASE", "http://mock-upstream.invalid")

import apf.proxy as proxy  # noqa: E402


REALISTIC_PROMPT = (
    "Hallo Anna,\n\n"
    "kannst du den Quartalsreport an thomas.weber@example.de schicken bis Freitag?\n"
    "Mein Handy für Rückfragen: +49 30 9900 4471. Bin Mittwoch beim Arzt — Termin bei "
    "Dr. Bauer in der Kardiologie.\n\n"
    "Auf dem Server liegt die Datei unter /Users/alice/reports/q3-final.pdf. "
    "API-Key für den S3-Upload: OPENAI_API_KEY=xk-fake-AAAAAAAAAAAAAAAAAAAAAA12345.\n\n"
    "Gruß, Aylin"
)


class FakeUpstream:
    def __init__(self) -> None:
        self.last_request_body = None

    async def post(self, url, json=None, headers=None):
        self.last_request_body = json

        class _Resp:
            status_code = 200
            content = b'{"id":"msg_smoke","type":"message"}'
            headers = {"content-type": "application/json"}
            def json(self):
                return {
                    "id": "msg_smoke",
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "text",
                         "text": "Klar, ich kümmere mich darum. Versende den Report "
                                 "an <REF_1>. Bei Rückfragen erreichst du mich auf "
                                 "<REF_2>."},
                    ],
                    "model": "claude-test",
                    "stop_reason": "end_turn",
                }
        return _Resp()


def header_line(label: str, char: str = "─") -> str:
    return f"\n{char * 4} {label} " + char * max(2, 70 - len(label))


def run_fake() -> int:
    fake = FakeUpstream()

    class _AsyncCtx:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return fake
        async def __aexit__(self, *a): return False
    proxy.httpx.AsyncClient = _AsyncCtx

    with TestClient(proxy.app) as client:
        print(header_line("INPUT (what the user sends to Claude Code)"))
        print(REALISTIC_PROMPT)

        resp = client.post(
            "/v1/messages",
            json={
                "model": "claude-opus-4-7", "max_tokens": 512,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": REALISTIC_PROMPT}]}],
            },
            headers={"x-api-key": "test", "x-apf-session": "smoke"},
        )

        upstream_text = fake.last_request_body["messages"][0]["content"][0]["text"]
        print(header_line("UPSTREAM (what Anthropic would receive)"))
        print(upstream_text)

        body = resp.json()
        print(header_line("CLIENT (what Claude Code sees back)"))
        print(json.dumps(body, indent=2, ensure_ascii=False))

        print(header_line("VAULT SNAPSHOT"))
        vault = proxy._VAULTS["smoke"]
        for e in vault.all_entries():
            extra = f"  [key={e.secret_key_name}]" if e.secret_key_name else ""
            label_w_conf = f"{e.label} (conf={e.confidence:.2f})"
            print(f"  {e.token:24s} ← {e.original!r}  [{label_w_conf}]{extra}")

        print(header_line("UNCERTAIN ENTRIES (for UX confirmation)"))
        u = client.get("/v1/sessions/smoke/uncertain").json()
        for entry in u.get("uncertain", []):
            print(f"  {entry}")

        print(header_line("HEADERS"))
        for k, v in resp.headers.items():
            if k.lower().startswith("x-apf"):
                print(f"  {k}: {v}")

    print(header_line("DONE", "═"))
    return 0


def run_live(model: str) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — live mode needs a real key.", file=sys.stderr)
        return 1
    os.environ["APF_UPSTREAM_BASE"] = "https://api.anthropic.com"
    # Reload proxy module so the new upstream takes effect.
    import importlib
    importlib.reload(proxy)

    with TestClient(proxy.app) as client:
        print(header_line("LIVE INPUT"))
        print(REALISTIC_PROMPT)
        resp = client.post(
            "/v1/messages",
            json={
                "model": model, "max_tokens": 512,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": REALISTIC_PROMPT}]}],
            },
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "x-apf-session": "smoke-live",
            },
        )
        print(header_line("LIVE STATUS / HEADERS"))
        print(f"status: {resp.status_code}")
        for k, v in resp.headers.items():
            if k.lower().startswith("x-apf"):
                print(f"  {k}: {v}")
        print(header_line("LIVE RESPONSE BODY"))
        try:
            body = resp.json()
            print(json.dumps(body, indent=2, ensure_ascii=False))
        except Exception:
            print(resp.text)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="Send to real Anthropic API (needs ANTHROPIC_API_KEY).")
    parser.add_argument("--model", default="claude-haiku-4-5",
                        help="Model name for --live mode (default: claude-haiku-4-5).")
    args = parser.parse_args()

    if args.live:
        return run_live(args.model)
    return run_fake()


if __name__ == "__main__":
    sys.exit(main())
