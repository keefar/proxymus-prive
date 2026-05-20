"""apf-76s / apf-nia: tool-call behaviour of the real target — Claude.

Drives real Claude Code (`claude -p`) through apf to the Anthropic API
and measures whether Claude completes a tool-call task whose prompt
carries masked PII. This is the Anthropic-shape, real-cloud analogue of
scripts/toolcall_loopback.py (which covers the OpenAI/local path).

How it routes — no custom tooling, two env vars:
    ANTHROPIC_BASE_URL=http://127.0.0.1:8765         -> through apf
    ANTHROPIC_CUSTOM_HEADERS="x-apf-session: <id>"   -> pin one apf vault

The session header lets the script read /v1/sessions/<id>/status after
the run and see exactly what apf masked.

Finding it was built to capture (2026-05-20): Claude tolerates a few
masked <REF> tokens, but a dense cluster trips its prompt-injection
defence and it declines — `--system explainer` (the apf-6l8 token
explainer) fixes it. Run both modes to reproduce:

    .venv/bin/python -m scripts.cloud_toolcall --system off
    .venv/bin/python -m scripts.cloud_toolcall --system explainer

Prerequisites: apf running with the Anthropic upstream (default), and a
logged-in `claude` CLI on PATH. Each scenario is one real Claude API
call on the machine's plan.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid

from scripts.smoke_loopback import SYSTEM_PROMPT_EXPLAINER

APF_BASE = "http://127.0.0.1:8765"

# Anthropic 529 / RPM throttling ("Server is temporarily limiting requests")
# is server-side, not the account quota — retrying one-by-one with a delay
# clears it. Exponential backoff; a 529'd request does not consume quota.
_RETRY_NEEDLES = ("temporarily limiting", "overloaded", "rate limit",
                  "rate_limit", "529")
RETRIES = 4
BACKOFF_BASE_S = 15
INTER_SCENARIO_GAP_S = 6

# Each scenario is a Bash-echo task — side-effect-free, and every PII
# value becomes one <REF> token the model must cope with. n_pii is the
# masked-token count the prompt is built to produce.
SCENARIOS: list[dict] = [
    {
        "name": "echo_1pii", "n_pii": 1,
        "prompt": ("Use the Bash tool to echo exactly this line, nothing "
                   "else: ping anna.mueller@example.de"),
    },
    {
        "name": "echo_3pii", "n_pii": 3,
        "prompt": ("Use the Bash tool to echo exactly this line, nothing "
                   "else: contact Anna Mueller at anna.mueller@example.de "
                   "phone +49 30 11223344"),
    },
    {
        "name": "echo_6pii", "n_pii": 6,
        "prompt": ("Use the Bash tool to echo exactly this line, nothing "
                   "else: contact Anna Mueller at anna.mueller@example.de "
                   "phone +49 30 11223344 and Thomas Berger at "
                   "thomas.berger@example.de phone +49 89 99887766"),
    },
]

_DECLINE_NEEDLES = (
    "placeholder", "prompt-injection", "prompt injection", "i won't",
    "i will not", "can't", "cannot", "unable", "unresolved",
    "not specified", "no tool",
)


def _vault(session: str) -> dict:
    try:
        with urllib.request.urlopen(
                f"{APF_BASE}/v1/sessions/{session}/status", timeout=10) as r:
            return json.loads(r.read()).get("summary", {}) or {}
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)}


def _is_throttled(data: dict) -> bool:
    """True if the response is an Anthropic server-side throttle (529/RPM),
    which is retryable and does not consume quota."""
    if data.get("api_error_status"):
        return True
    return any(n in (data.get("result") or "").lower()
               for n in _RETRY_NEEDLES)


def run_scenario(sc: dict, system: str) -> dict:
    session = f"cltc-{uuid.uuid4().hex[:8]}"
    cmd = ["claude", "-p", sc["prompt"], "--output-format", "json",
           "--allowedTools", "Bash(echo:*)"]
    if system == "explainer":
        cmd += ["--append-system-prompt", SYSTEM_PROMPT_EXPLAINER]
    env = {**os.environ,
           "ANTHROPIC_BASE_URL": APF_BASE,
           "ANTHROPIC_CUSTOM_HEADERS": f"x-apf-session: {session}"}

    data: dict = {}
    for attempt in range(RETRIES):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=300, env=env, cwd="/tmp/claude")
            data = json.loads(proc.stdout)
        except Exception as e:  # noqa: BLE001
            return {"name": sc["name"], "verdict": "EXC", "detail": str(e)}
        if not _is_throttled(data) or attempt == RETRIES - 1:
            break
        wait = BACKOFF_BASE_S * (2 ** attempt)
        print(f"  {sc['name']}: throttled, retry in {wait}s "
              f"(attempt {attempt + 1}/{RETRIES})", file=sys.stderr)
        time.sleep(wait)

    result = (data.get("result") or "")
    declined = any(n in result.lower() for n in _DECLINE_NEEDLES)
    if data.get("is_error"):
        verdict = "ERROR"
    elif declined:
        verdict = "DECLINE"
    else:
        verdict = "OK"
    summary = _vault(session)
    return {
        "name": sc["name"],
        "n_pii": sc["n_pii"],
        "verdict": verdict,
        "vault_total": summary.get("total"),
        "turns": data.get("num_turns"),
        "preview": " ".join(result.split())[:150],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", choices=["off", "explainer"], default="off",
                    help="prepend the apf-6l8 token explainer as a system "
                         "prompt (--append-system-prompt). Default: off.")
    ap.add_argument("--grep", default="", help="substring filter on name")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    selected = [s for s in SCENARIOS if not args.grep or args.grep in s["name"]]
    print(f"\ncloud tool-call · proxy={APF_BASE} · system={args.system} · "
          f"{len(selected)} scenarios\n")
    if not args.json:
        print(f"{'SCENARIO':<16} {'PII':<4} {'VERDICT':<9} {'VAULT':<7} DETAIL")
        print("-" * 100)

    results = []
    for i, sc in enumerate(selected):
        if i > 0:
            time.sleep(INTER_SCENARIO_GAP_S)  # space calls to avoid RPM throttle
        r = run_scenario(sc, args.system)
        results.append(r)
        if args.json:
            print(json.dumps(r, ensure_ascii=False))
            continue
        print(f"{r['name']:<16} {r.get('n_pii', '?'):<4} "
              f"{r['verdict']:<9} {str(r.get('vault_total', '?')):<7} "
              f"{r.get('preview', r.get('detail', ''))}")

    declines = sum(1 for r in results if r["verdict"] in ("DECLINE", "ERROR"))
    if not args.json:
        print(f"\n{len(results) - declines}/{len(results)} completed · "
              f"{declines} declined/errored")
    return 1 if declines else 0


if __name__ == "__main__":
    sys.exit(main())
