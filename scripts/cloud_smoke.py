"""apf-nia: cloud-smoke that routes a PII-laden prompt through the apf
proxy to api.anthropic.com and reports what Claude does with the
masked `<REF_N>` markers.

This is the actual production validation the PoC was building toward:
the local Qwen-refusal experiments in apf-6l8 do NOT predict cloud-
model behaviour. Hence we test the real target scenario.

Prerequisites
-------------
1. apf proxy running with default upstream (api.anthropic.com):
       .venv/bin/python -m apf.proxy
   (Restart any old instance so the apf-0uo <REF_N> rename is active.)

2. Valid Anthropic auth. Two paths:
       (a) Direct API key for testing: export ANTHROPIC_API_KEY=sk-ant-...
       (b) Reuse an OAuth bearer from your Claude Code session:
           export ANTHROPIC_AUTH_TOKEN=...
       This script sets the same header Claude Code would set, then
       lets apf forward it to api.anthropic.com untouched.

Usage
-----
    .venv/bin/python -m scripts.cloud_smoke
    .venv/bin/python -m scripts.cloud_smoke --case multi-pii
    .venv/bin/python -m scripts.cloud_smoke --model claude-sonnet-4-6
    .venv/bin/python -m scripts.cloud_smoke --no-auth-warn

Output: per-case report showing what apf masked (vault summary via
the status endpoint), what Claude responded with (truncated preview),
and whether the response shows safety-refusal patterns ('I cannot…',
'I'm sorry', 'sensitive information') or engages with the tokens.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

APF_BASE = "http://127.0.0.1:8765"
DEFAULT_MODEL = "claude-opus-4-7"

# Cases mirror scripts/smoke_loopback.py so the same vault-shape
# expectations carry across local + cloud smokes.
CASES: list[dict] = [
    {
        "name": "single-person-de",
        "prompt": "Schreibe einen kurzen Satz über Anna Müller.",
        "must_have": ["PERSON"],
    },
    {
        "name": "single-person-en",
        "prompt": "Write one sentence about Sarah Johnson.",
        "must_have": ["PERSON"],
    },
    {
        "name": "email",
        "prompt": "Please send a follow-up to sarah.johnson@example.com.",
        "must_have": ["EMAIL"],
    },
    {
        "name": "phone-de",
        "prompt": "Meine Telefonnummer ist +49 30 12345678, melde dich bitte.",
        "must_have": ["PHONE"],
    },
    {
        "name": "multi-pii",
        "prompt": ("Hi, ich heiße Anna Müller, meine Mail ist "
                   "anna.mueller@example.de und ich wohne in der "
                   "Hauptstraße 42, 10115 Berlin. Schreib mir eine "
                   "kurze Begrüßung."),
        "must_have": ["PERSON", "EMAIL", "ADDRESS"],
    },
    {
        "name": "negative-no-pii",
        "prompt": "What is 2+2?",
        "must_have": [],
        "expect_empty_vault": True,
    },
]


REFUSAL_NEEDLES = (
    "i cannot", "i'm sorry", "kann ich nicht", "tut mir leid",
    "sensitive information", "i can't assist", "ich kann dir nicht",
)


def _auth_headers() -> dict[str, str]:
    headers = {"content-type": "application/json",
               "anthropic-version": "2023-06-01"}
    if os.environ.get("ANTHROPIC_API_KEY"):
        headers["x-api-key"] = os.environ["ANTHROPIC_API_KEY"]
    elif os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        headers["authorization"] = f"Bearer {os.environ['ANTHROPIC_AUTH_TOKEN']}"
    return headers


def _post(path: str, body: dict, headers: dict[str, str]) -> tuple[int, dict | str]:
    req = urllib.request.Request(
        f"{APF_BASE}{path}", method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def _get_status(session_id: str) -> dict:
    req = urllib.request.Request(
        f"{APF_BASE}/v1/sessions/{session_id}/status",
        headers={"accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def run_case(case: dict, model: str) -> dict:
    session_id = f"cloud-smoke-{uuid.uuid4().hex[:8]}"
    body = {
        "model": model,
        "max_tokens": 512,
        "messages": [{"role": "user", "content": case["prompt"]}],
    }
    headers = _auth_headers()
    headers["x-apf-session"] = session_id
    status, resp = _post("/v1/messages", body, headers)
    vault_summary = None
    try:
        vault_summary = _get_status(session_id).get("summary")
    except Exception as e:  # noqa: BLE001
        vault_summary = {"_error": str(e)}

    content_text = ""
    if isinstance(resp, dict):
        for block in resp.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "text":
                content_text += block.get("text", "")
        if not content_text and resp.get("error"):
            content_text = json.dumps(resp["error"])[:200]
    else:
        content_text = str(resp)[:200]

    refused = any(n in content_text.lower() for n in REFUSAL_NEEDLES)
    return {
        "name": case["name"],
        "status": status,
        "session_id": session_id,
        "vault": vault_summary,
        "refused": refused,
        "preview": content_text[:160].replace("\n", " "),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", help="run only the case with this name")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--no-auth-warn", action="store_true",
                    help="skip the auth-missing warning (the proxy may still "
                    "have credentials from a parent Claude Code process)")
    args = ap.parse_args()

    if not args.no_auth_warn and not (os.environ.get("ANTHROPIC_API_KEY")
                                       or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("⚠ no ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN in env; the\n"
              "  apf proxy may already have credentials from a parent\n"
              "  Claude Code session. If the requests 401, supply auth via\n"
              "  env and rerun. Pass --no-auth-warn to silence this.\n")

    selected = [c for c in CASES if not args.case or c["name"] == args.case]
    if not selected:
        print(f"no case matches {args.case!r}; available: "
              + ", ".join(c["name"] for c in CASES))
        return 2

    print(f"\nCloud-smoke · proxy={APF_BASE} · model={args.model}\n")
    print(f"{'CASE':<20} {'STATUS':<6} {'VAULT':<32} "
          f"{'REFUSED':<8}  PREVIEW")
    print("-" * 130)

    results = []
    for case in selected:
        r = run_case(case, args.model)
        results.append(r)
        vault = r.get("vault") or {}
        per_label = vault.get("per_label") or {}
        vault_str = (f"total={vault.get('total', '?')} · "
                     + ", ".join(f"{k}={v}" for k, v in per_label.items())) \
            if isinstance(vault, dict) and "total" in vault else str(vault)
        refused = "REFUSE" if r["refused"] else ""
        print(f"{r['name']:<20} {r['status']:<6} {vault_str:<32} "
              f"{refused:<8}  {r['preview']}")

    refusals = sum(1 for r in results if r["refused"])
    auth_fails = sum(1 for r in results if r["status"] in (401, 403))
    print(f"\n{len(results) - refusals - auth_fails}/{len(results)} engaged · "
          f"{refusals} refused · {auth_fails} auth-failed")
    return 0 if auth_fails == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
