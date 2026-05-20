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

Scenarios (apf-4cs) are task-shaped — a genuine "audit the directory
for leaked contact details" Grep search, the PII being the search
target — not a verbatim PII-block echo (the echo framing is itself
injection-shaped and skews the result). Run:

    .venv/bin/python -m scripts.cloud_toolcall --system off
    .venv/bin/python -m scripts.cloud_toolcall --system explainer

Also exercises surrogate mode when apf runs with APF_SURROGATE_LABELS
set — the surrogate values then carry through instead of <REF> tokens.

Prerequisites: apf running with the Anthropic upstream (default), and a
logged-in `claude` CLI on PATH. Each scenario is one real Claude API
call on the machine's plan.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
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

# apf-4cs: task-shaped scenarios. The PII is the target of a genuine
# "audit the codebase for leaked contact details" task — read-only,
# side-effect-free — not a verbatim PII block to echo. The echo framing
# ("echo this exact line") is itself prompt-injection-shaped and skews
# the result; a search task is what a real user would actually ask.
# n_pii is the count of distinct PII values the prompt carries.
SCENARIOS: list[dict] = [
    {
        "name": "search_1pii", "n_pii": 1,
        "prompt": ("Use the Grep tool to find how many files in this "
                   "directory mention the email address "
                   "anna.mueller@example.de. Report just the count."),
    },
    {
        "name": "search_3pii", "n_pii": 3,
        "prompt": ("I want to check this directory for leaked contact "
                   "details. Use the Grep tool to search for any mention "
                   "of Anna Mueller, the email anna.mueller@example.de, "
                   "or the phone number +49 30 11223344, and tell me "
                   "what you found."),
    },
    {
        "name": "search_6pii", "n_pii": 6,
        "prompt": ("Audit this directory for leaked contact details. Use "
                   "the Grep tool to search for any mention of Anna "
                   "Mueller, Thomas Berger, their emails "
                   "anna.mueller@example.de and thomas.berger@example.de, "
                   "or their phone numbers +49 30 11223344 and "
                   "+49 89 99887766. Summarise what you found."),
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


def make_audit_dir() -> str:
    """A clean scratch directory with known, PII-free content. The
    grep-audit scenarios run here so the vault count is interpretable:
    they search for PII the directory does NOT contain → 0 matches → the
    vault should hold only the prompt's masked PII (n_pii). A vault far
    above n_pii then cleanly signals a real problem (e.g. re-detection),
    not directory pollution — which is what /tmp/claude gave us."""
    d = tempfile.mkdtemp(prefix="apf_audit_")
    with open(os.path.join(d, "readme.txt"), "w", encoding="utf-8") as f:
        f.write("Internal build tooling. Setup steps are on the team "
                "wiki. No external services.\n")
    with open(os.path.join(d, "config.txt"), "w", encoding="utf-8") as f:
        f.write("timeout=30\nretries=3\nmode=fast\nlog=info\n")
    return d


def run_scenario(sc: dict, system: str, audit_dir: str) -> dict:
    session = f"cltc-{uuid.uuid4().hex[:8]}"
    cmd = ["claude", "-p", sc["prompt"], "--output-format", "json",
           "--allowedTools", "Grep"]
    if system == "explainer":
        cmd += ["--append-system-prompt", SYSTEM_PROMPT_EXPLAINER]
    env = {**os.environ,
           "ANTHROPIC_BASE_URL": APF_BASE,
           "ANTHROPIC_CUSTOM_HEADERS": f"x-apf-session: {session}"}

    data: dict = {}
    for attempt in range(RETRIES):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=300, env=env, cwd=audit_dir)
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
    audit_dir = make_audit_dir()
    print(f"\ncloud tool-call · proxy={APF_BASE} · system={args.system} · "
          f"{len(selected)} scenarios · clean audit dir={audit_dir}")
    print("(vault should ≈ PII; clean dir has 0 matches — a higher vault "
          "signals a real problem, not pollution)\n")
    if not args.json:
        print(f"{'SCENARIO':<16} {'PII':<4} {'VERDICT':<9} {'VAULT':<7} DETAIL")
        print("-" * 100)

    results = []
    try:
        for i, sc in enumerate(selected):
            if i > 0:
                time.sleep(INTER_SCENARIO_GAP_S)  # space calls vs RPM throttle
            r = run_scenario(sc, args.system, audit_dir)
            results.append(r)
            if args.json:
                print(json.dumps(r, ensure_ascii=False))
                continue
            print(f"{r['name']:<16} {r.get('n_pii', '?'):<4} "
                  f"{r['verdict']:<9} {str(r.get('vault_total', '?')):<7} "
                  f"{r.get('preview', r.get('detail', ''))}")
    finally:
        shutil.rmtree(audit_dir, ignore_errors=True)

    declines = sum(1 for r in results if r["verdict"] in ("DECLINE", "ERROR"))
    if not args.json:
        print(f"\n{len(results) - declines}/{len(results)} completed · "
              f"{declines} declined/errored")
    return 1 if declines else 0


if __name__ == "__main__":
    sys.exit(main())
