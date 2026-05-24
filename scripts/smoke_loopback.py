"""Bulk smoke test for the running apf OpenAI-shape proxy.

Sends a curated set of single-turn prompts through apf, then reads the
per-session vault summary via /v1/sessions/{id}/status to verify
masking behaviour. Inspects only counts (the status endpoint never
returns originals or tokens), so the script is safe to run unattended
and to commit example outputs from.

Prerequisite: apf running on http://127.0.0.1:8765 with an OpenAI
upstream reachable. For local-loopback tests against oMLX/mlx-lm/etc.
you also need ~/.config/apf/endpoints.toml overriding 127.0.0.1 to
policy = "full" (see docs/INTEGRATION.md).

Usage:
    .venv/bin/python -m scripts.smoke_loopback
    .venv/bin/python -m scripts.smoke_loopback --grep tier_c
    .venv/bin/python -m scripts.smoke_loopback --model Qwen2.5-...
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any

APF_BASE = "http://127.0.0.1:8765"
# apf-6l8: comparison run 2026-05-19 across 4 backends with raw <SENSITIVE_N>
# tokens (no system explainer). Refusal rates:
#   Gemma-4-26B-A4B-it-4bit:    2/14  ← chosen default
#   Qwen3.6-35B-A3B-mxfp4:      3/14  (some false-positives from thinking traces)
#   granite-4.1-8b-mxfp8:       7/14
#   Qwen2.5-Coder-7B-MLX-4bit: 13/14  (baseline that motivated apf-6l8)
# Gemma matches Qwen2.5-Coder+variant-B explainer (2/14) WITHOUT needing the
# explainer at all, which is the cleaner end-to-end rig.
DEFAULT_MODEL = "gemma-4-26b-a4b-it-4bit"


# Each case:
#   name:        identifier
#   lang:        informational
#   tier:        informational ("A"/"B"/"C"/"-")
#   prompt:      single-turn user message
#   must_have:   labels that must have count >= 1 in the vault (OR semantics)
#   min_total:   minimum total vault entries (default 1)
#   max_total:   optional upper bound (used by no-PII case)
CASES: list[dict[str, Any]] = [
    {
        "name": "de_person_single",
        "lang": "de", "tier": "A",
        "prompt": "Schreibe einen Satz zu Anna Müller.",
        "must_have": ["PERSON"], "min_total": 1,
    },
    {
        "name": "en_person_single",
        "lang": "en", "tier": "A",
        "prompt": "Write one sentence about Sarah Johnson.",
        "must_have": ["PERSON"], "min_total": 1,
    },
    {
        "name": "de_email",
        "lang": "de", "tier": "A",
        "prompt": "Schreibe eine Mail an anna.mueller@beispiel.de.",
        "must_have": ["EMAIL"], "min_total": 1,
    },
    {
        "name": "en_email",
        "lang": "en", "tier": "A",
        "prompt": "Please send a note to sarah.johnson@example.com.",
        "must_have": ["EMAIL"], "min_total": 1,
    },
    {
        "name": "de_phone",
        "lang": "de", "tier": "A",
        "prompt": "Meine Telefonnummer ist +49 30 12345678, ruf mich an.",
        "must_have": ["PHONE"], "min_total": 1,
    },
    {
        "name": "de_address",
        "lang": "de", "tier": "A",
        "prompt": "Ich wohne in der Hauptstraße 42, 10115 Berlin.",
        "must_have": [],  # label varies (LOCATION / ADDRESS / etc.) — just expect something
        "min_total": 1,
    },
    {
        "name": "en_date",
        "lang": "en", "tier": "A",
        "prompt": "The meeting is on 2026-05-22 at 14:00 in Berlin.",
        "must_have": [], "min_total": 1,
    },
    {
        "name": "tier_b_path",
        "lang": "any", "tier": "B",
        "prompt": "Read the file at /Users/alice/work/secrets.env and summarise.",
        "must_have": [], "min_total": 1,
    },
    {
        "name": "tier_b_ip",
        "lang": "any", "tier": "B",
        "prompt": "Connect to the server at 192.168.1.42 on port 8080.",
        "must_have": [], "min_total": 1,
    },
    {
        "name": "tier_c_sk_key",
        "lang": "any", "tier": "C",
        "prompt": "My API key is xk-abc123def456ghi789jklmnopqrstuvwxyzABCDEF",
        "must_have": [], "min_total": 1,
    },
    {
        "name": "tier_c_jwt",
        "lang": "any", "tier": "C",
        "prompt": ("Use this bearer token to authenticate: "
                   "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                   "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
                   "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"),
        "must_have": [], "min_total": 1,
    },
    {
        "name": "tier_c_env_assign",
        "lang": "any", "tier": "C",
        "prompt": "Set DATABASE_PASSWORD=hunter2secret123 in your shell.",
        "must_have": [], "min_total": 1,
    },
    {
        "name": "negative_no_pii",
        "lang": "any", "tier": "-",
        "prompt": "What is 2 + 2? Answer with just the number.",
        "must_have": [], "min_total": 0, "max_total": 0,
    },
    # apf-zzk: benign-prompt expansion. The detector should produce zero
    # vault entries for all of these. Cases that DO populate the vault
    # surface detector false-positives worth investigating separately.
    {
        "name": "negative_math_integral",
        "lang": "en", "tier": "-",
        "prompt": "Compute the indefinite integral of x squared with respect to x.",
        "must_have": [], "min_total": 0, "max_total": 0,
    },
    {
        "name": "negative_code_reverse_list",
        "lang": "en", "tier": "-",
        "prompt": "Write a Python function that reverses a list in place.",
        "must_have": [], "min_total": 0, "max_total": 0,
    },
    {
        "name": "negative_code_concept_hashtable",
        "lang": "en", "tier": "-",
        "prompt": "Explain how a hash table handles collisions in one paragraph.",
        "must_have": [], "min_total": 0, "max_total": 0,
    },
    {
        "name": "negative_translation",
        "lang": "en", "tier": "-",
        "prompt": "Translate the phrase 'Hello, how are you?' to German.",
        "must_have": [], "min_total": 0, "max_total": 0,
    },
    {
        "name": "negative_concept_de",
        "lang": "de", "tier": "-",
        "prompt": "Was bedeutet Photosynthese in zwei Sätzen?",
        "must_have": [], "min_total": 0, "max_total": 0,
    },
    {
        "name": "negative_creative_haiku",
        "lang": "en", "tier": "-",
        "prompt": "Write a haiku about clouds at sunset.",
        "must_have": [], "min_total": 0, "max_total": 0,
    },
    {
        "name": "negative_brainstorm",
        "lang": "en", "tier": "-",
        "prompt": "Brainstorm five names for a coffee shop. Keep it short.",
        "must_have": [], "min_total": 0, "max_total": 0,
    },
    {
        "name": "multi_pii_safety_probe",
        "lang": "de", "tier": "A",
        "prompt": ("Anna Müller, anna.mueller@beispiel.de, +49 30 12345678, "
                   "Hauptstraße 42 in Berlin. Bitte fasse zusammen."),
        "must_have": ["PERSON", "EMAIL"], "min_total": 3,
    },
]


def _http_json(method: str, path: str, body: dict | None = None,
               session_hdr: str | None = None, timeout: float = 120.0) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        APF_BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    if session_hdr:
        req.add_header("x-apf-session", session_hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# apf-76s: the explainer text is the shared canonical constant — the proxy
# now injects it itself; this re-export keeps the smoke flags working.
from apf.explainer import EXPLAINER_TEXT as SYSTEM_PROMPT_EXPLAINER  # noqa: E402


def run_case(case: dict, model: str, system_prompt: str | None = None) -> dict:
    session = f"smoke-{uuid.uuid4().hex[:8]}"
    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": case["prompt"]})
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 80,
    }
    try:
        resp = _http_json("POST", "/v1/chat/completions", body, session)
        content = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
        content = " ".join(content.split())
    except urllib.error.HTTPError as e:
        return {"case": case["name"], "ok": False, "error": f"HTTP {e.code}: {e.read()[:200]!r}"}
    except Exception as e:
        return {"case": case["name"], "ok": False, "error": str(e)}

    try:
        status = _http_json("GET", f"/v1/sessions/{session}/status")
    except Exception as e:
        return {"case": case["name"], "ok": False, "error": f"status: {e}"}

    summary = status.get("summary") or {"total": 0, "per_label": {}}
    total = summary.get("total", 0)
    labels = summary.get("per_label", {})

    ok = True
    reasons: list[str] = []
    if total < case.get("min_total", 1):
        ok = False
        reasons.append(f"total<{case['min_total']}")
    if "max_total" in case and total > case["max_total"]:
        ok = False
        reasons.append(f"total>{case['max_total']}")
    must = case.get("must_have", [])
    if must and not any(labels.get(m, 0) > 0 for m in must):
        ok = False
        reasons.append(f"missing any of {must}")

    refusal_hit = any(needle in content.lower() for needle in
                      ["tut mir leid", "i'm sorry", "i cannot", "kann ich nicht",
                       "sensitive information"])

    return {
        "case": case["name"],
        "tier": case["tier"],
        "ok": ok,
        "reasons": reasons,
        "total": total,
        "labels": labels,
        "response_preview": content[:80],
        "refusal_hit": refusal_hit,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grep", default="", help="substring filter on case name")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="model name to send")
    ap.add_argument("--json", action="store_true", help="emit one JSON result per line")
    ap.add_argument("--system", choices=["off", "explainer"], default="off",
                    help="prepend a system message: 'off' = no system msg, "
                         "'explainer' = the built-in token-explanation prompt "
                         "(see SYSTEM_PROMPT_EXPLAINER) — used to test the "
                         "apf-6l8 workaround for safety-refusal behaviour.")
    args = ap.parse_args()
    sys_prompt = SYSTEM_PROMPT_EXPLAINER if args.system == "explainer" else None

    selected = [c for c in CASES if not args.grep or args.grep in c["name"]]

    if not args.json:
        print(f"\nRunning {len(selected)} cases · model={args.model} · system={args.system}\n")
        print(f"{'CASE':<28} {'TIER':<4} {'VAULT':<38} {'SAFETY':<7} {'OK':<3}  RESPONSE")
        print("-" * 130)

    results = []
    for c in selected:
        r = run_case(c, args.model, sys_prompt)
        results.append(r)
        if args.json:
            print(json.dumps(r, ensure_ascii=False))
            continue
        labels = r.get("labels", {})
        vault_str = f"{r.get('total', '?')}: " + ", ".join(f"{k}={v}" for k, v in labels.items())
        if not vault_str.endswith(": "):
            pass
        else:
            vault_str = vault_str.rstrip(": ") + " (empty)"
        ok_mark = "✓" if r["ok"] else "✗"
        refusal_mark = "REFUSE" if r.get("refusal_hit") else ""
        resp = r.get("response_preview", r.get("error", ""))[:60]
        print(f"{r['case']:<28} {r.get('tier', '?'):<4} {vault_str:<38} {refusal_mark:<7} {ok_mark:<3}  {resp}")

    passed = sum(1 for r in results if r["ok"])
    refusals = sum(1 for r in results if r.get("refusal_hit"))
    if not args.json:
        print(f"\n{passed}/{len(results)} passed · {refusals} model refusals")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
