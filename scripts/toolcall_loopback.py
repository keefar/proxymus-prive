"""End-to-end tool-call boundary check for apf (apf-pk7).

The project's differentiator: when the LLM emits a tool call referencing
a masked value, apf resolves the <REF_N> token to the original ONLY at
the tool-call boundary (so the local executor gets real values) and the
original NEVER crosses back to the LLM. Until now this was covered only
by unit tests with a hardcoded fake upstream. This rig exercises it
through the *running* apf proxy.

Two modes:

  --mode record  (default, hard pass/fail)
      Points apf at an in-process recording upstream (scripts/
      recording_upstream.py). Deterministic — the upstream's tool call
      is canned, so there is no model flakiness. Because the rig records
      the apf -> upstream wire, it can *prove* the no-leak property:
      after the tool result is fed back, the bytes apf forwards upstream
      contain only <REF_N> tokens, never the originals.

  --mode live  (real-model reality check)
      Points apf at oMLX and drives a real model. Verifies a real model
      actually emits tool_calls through the masked pipeline and that apf
      resolves them. The apf -> oMLX wire is invisible here, so the
      no-leak check falls back to a vault-growth assertion.

Per scenario, two turns:
  Turn 1  user prompt with PII  ->  assistant tool_call.
          Assert A: the tool-call arguments the client receives hold the
          ORIGINAL values, with no <REF token left behind.
  Turn 2  assistant tool_call + tool result fed back.
          Assert B (wire, record-only): the recorded upstream request
          carries zero original PII / secret / probe — only tokens.
          Assert B (vault, both modes): a fresh probe value placed in the
          tool result got masked -> apf scanned the outbound tool path.

Usage:
    .venv/bin/python -m scripts.toolcall_loopback
    .venv/bin/python -m scripts.toolcall_loopback --mode live
    .venv/bin/python -m scripts.toolcall_loopback --grep email --json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from scripts.recording_upstream import serve_in_thread
from scripts.smoke_loopback import SYSTEM_PROMPT_EXPLAINER

APF_BASE = "http://127.0.0.1:8765"
REC_PORT = 8099
OMLX_UPSTREAM = "http://127.0.0.1:8000"
# A real tool-calling model: gemma is historically unreliable for tool
# calling under MLX. Qwen Holo3 is a reasoning model — it emits clean
# tool calls even on masked prompts, but needs token headroom + a long
# timeout (see MAX_TOKENS / _http_json timeout).
LIVE_MODEL = "Qwen3.6-35B-A3B-Holo3-Qwopus-mxfp4-mlx"
MAX_TOKENS = 4096
RESTART_SCRIPT = Path(__file__).resolve().parent / "apf_restart.sh"


# ── Tool schemas ───────────────────────────────────────────────────────────
def _fn(fn_name: str, desc: str, params: dict[str, str]) -> dict:
    """Compact OpenAI function-tool builder. params: arg name -> description."""
    return {
        "type": "function",
        "function": {
            "name": fn_name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": {p: {"type": "string", "description": d}
                               for p, d in params.items()},
                "required": list(params),
            },
        },
    }


SEND_EMAIL = _fn("send_email", "Send an email.",
                 {"to": "recipient address", "subject": "subject line",
                  "body": "body text"})
ADD_CONTACT = _fn("add_contact", "Save a contact.",
                  {"name": "full name", "phone": "phone number"})
CREATE_EVENT = _fn("create_event", "Create a calendar event.",
                   {"title": "event title", "attendee": "attendee name",
                    "date": "ISO date", "location": "location"})
RUN_BASH = _fn("run_bash", "Run a shell command.",
               {"command": "the command"})
HTTP_GET = _fn("http_get", "Perform an authenticated HTTP GET.",
               {"url": "target url", "auth_header": "Authorization header value"})
GET_WEATHER = _fn("get_weather", "Look up weather.",
                  {"query": "what to look up"})


# ── Scenarios ──────────────────────────────────────────────────────────────
# Each scenario:
#   name, lang, tier
#   tools / tool_name        OpenAI tool defs + which function is called
#   prompt                   turn-1 user message (PII ordered to match {tokN})
#   pii                      original Tier-A/B values: masked then resolved
#   secret                   optional Tier-C value: must NEVER surface anywhere
#   args_template            record-mode canned tool-call args; {tokN}/{REF}
#                            are filled from the tokens apf actually emitted
#   tool_result              turn-2 tool-result text; {piiN}=original value,
#                            {probe}=a fresh per-run probe email
#   expect_empty_vault       negative scenario: nothing should be detected
SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "send_email_de", "lang": "de", "tier": "A",
        "tools": [SEND_EMAIL], "tool_name": "send_email",
        "prompt": ("Schick eine E-Mail an thomas.weber@example.de mit dem "
                   "Betreff Quartalsbericht."),
        "pii": ["thomas.weber@example.de"],
        "args_template": {"to": "{tok0}", "subject": "Quartalsbericht",
                          "body": "Hallo, anbei der Quartalsbericht."},
        "tool_result": "E-Mail an {pii0} zugestellt. Kopie an {probe}.",
    },
    {
        "name": "send_email_en", "lang": "en", "tier": "A",
        "tools": [SEND_EMAIL], "tool_name": "send_email",
        "prompt": ("Send an email to sarah.connor@example.com about the "
                   "Friday schedule."),
        "pii": ["sarah.connor@example.com"],
        "args_template": {"to": "{tok0}", "subject": "Friday schedule",
                          "body": "Here is the updated schedule."},
        "tool_result": "Delivered to {pii0}. Receipt copy sent to {probe}.",
    },
    {
        "name": "add_contact_phone", "lang": "de", "tier": "A",
        "tools": [ADD_CONTACT], "tool_name": "add_contact",
        "prompt": ("Speichere den Kontakt: Anna Müller, Telefonnummer "
                   "+49 30 12345678."),
        "pii": ["Anna Müller", "+49 30 12345678"],
        "args_template": {"name": "{tok0}", "phone": "{tok1}"},
        "tool_result": "Kontakt {pii0} ({pii1}) gespeichert. Sync an {probe}.",
    },
    {
        "name": "create_event", "lang": "en", "tier": "A",
        "tools": [CREATE_EVENT], "tool_name": "create_event",
        "prompt": ("Schedule a review with Michael Brown on 2026-06-15 "
                   "in Hamburg."),
        "pii": ["Michael Brown", "2026-06-15", "Hamburg"],
        "args_template": {"title": "Review", "attendee": "{tok0}",
                          "date": "{tok1}", "location": "{tok2}"},
        "tool_result": "Event for {pii0} on {pii1} in {pii2} created; "
                       "invite mailed to {probe}.",
    },
    {
        "name": "bash_path", "lang": "de", "tier": "B",
        "tools": [RUN_BASH], "tool_name": "run_bash",
        "prompt": ("Lies die Datei /Users/chris/work/notes.txt und fasse "
                   "sie zusammen."),
        "pii": ["/Users/chris/work/notes.txt"],
        "args_template": {"command": "cat {tok0}"},
        "tool_result": "Datei {pii0} gelesen. Log an {probe} gesendet.",
    },
    {
        "name": "http_secret", "lang": "en", "tier": "C",
        "tools": [HTTP_GET], "tool_name": "http_get",
        "prompt": ("Do a GET on https://api.example.com/v1/data using the "
                   "API key xk-live-ABCDEF1234567890XYZ987."),
        "pii": [],
        "secret": "xk-live-ABCDEF1234567890XYZ987",
        "args_template": {"url": "https://api.example.com/v1/data",
                          "auth_header": "Bearer {REF}"},
        "tool_result": "Request sent. Audit notice mailed to {probe}.",
    },
    {
        "name": "negative_no_pii", "lang": "en", "tier": "-",
        "tools": [GET_WEATHER], "tool_name": "get_weather",
        "prompt": "Use the weather tool to check the forecast.",
        "pii": [],
        "args_template": {"query": "today forecast"},
        "expect_empty_vault": True,
    },
]


# ── HTTP helpers ───────────────────────────────────────────────────────────
def _http_json(method: str, path: str, body: dict | None = None,
               session: str | None = None, timeout: float = 600.0) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(APF_BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    if session:
        req.add_header("x-apf-session", session)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _string_leaves(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _string_leaves(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _string_leaves(v)]
    return []


def _tool_calls(resp: dict) -> list[dict]:
    msg = (resp.get("choices") or [{}])[0].get("message", {}) or {}
    return msg.get("tool_calls") or []


def _email_count(status: dict) -> int:
    return ((status.get("summary") or {}).get("per_label") or {}).get("EMAIL", 0)


def _vault_total(status: dict) -> int:
    return (status.get("summary") or {}).get("total", 0)


# ── Scenario runner ────────────────────────────────────────────────────────
def run_scenario(sc: dict, model: str, recorder, probe: str,
                 system_prompt: str | None = None,
                 max_tokens: int = MAX_TOKENS) -> dict:
    name = sc["name"]
    session = f"tc-{uuid.uuid4().hex[:8]}"
    fails: list[str] = []
    notes: list[str] = []
    pii: list[str] = sc.get("pii", [])
    secret: str | None = sc.get("secret")
    leak_targets = pii + ([secret] if secret else [])
    # apf leaves role=system messages unmasked (apf-lnr), so the explainer
    # is not itself tokenised. It mitigates the apf-6l8-family effect where
    # a model reads opaque <REF> tokens as "missing information" and
    # declines the tool call.
    sys_msgs = ([{"role": "system", "content": system_prompt}]
                if system_prompt else [])

    # -- Turn 1 ---------------------------------------------------------
    if recorder is not None:
        recorder.set_toolcall(sc["tool_name"], sc["args_template"])
    turn1 = {
        "model": model,
        "messages": sys_msgs + [{"role": "user", "content": sc["prompt"]}],
        "tools": sc["tools"],
        "tool_choice": {"type": "function",
                        "function": {"name": sc["tool_name"]}},
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    try:
        resp1 = _http_json("POST", "/v1/chat/completions", turn1, session)
    except urllib.error.HTTPError as e:
        # live oMLX may reject forced tool_choice — retry with "auto"
        if recorder is None:
            turn1["tool_choice"] = "auto"
            try:
                resp1 = _http_json("POST", "/v1/chat/completions",
                                   turn1, session)
                notes.append("tool_choice=auto fallback")
            except Exception as e2:
                return {"name": name, "ok": False,
                        "fails": [f"turn1 HTTP: {e2}"], "notes": notes}
        else:
            return {"name": name, "ok": False,
                    "fails": [f"turn1 HTTP {e.code}: {e.read()[:160]!r}"],
                    "notes": notes}
    except Exception as e:
        return {"name": name, "ok": False,
                "fails": [f"turn1: {e}"], "notes": notes}

    tcs = _tool_calls(resp1)
    if not tcs:
        if recorder is None:
            # real model declined to call a tool — a finding, not an apf
            # bug. finish_reason distinguishes 'stop' (model chose text)
            # from 'length' (max_tokens cut it off mid-reasoning).
            ch1 = (resp1.get("choices") or [{}])[0]
            ct = (resp1.get("usage") or {}).get("completion_tokens")
            return {"name": name, "ok": None, "fails": [],
                    "notes": notes + [f"no tool_call (finish="
                                      f"{ch1.get('finish_reason')}, "
                                      f"completion_tokens={ct})"]}
        fails.append("no tool_call in response (apf dropped it?)")
        return {"name": name, "ok": False, "fails": fails, "notes": notes}

    # Reasoning models put their trace in reasoning_content; apf's OpenAI
    # response path unmasks only content + tool_calls, so <REF> tokens can
    # surface there unrestored. Surfaced as a note — the rig's contract is
    # the tool-call boundary, not trace restoration (tracked separately).
    msg1 = (resp1.get("choices") or [{}])[0].get("message", {}) or {}
    if "<REF" in (msg1.get("reasoning_content") or ""):
        notes.append("reasoning_content carries unrestored <REF> tokens")

    # Assert A: arguments the client sees are resolved to originals
    try:
        args1 = json.loads(tcs[0]["function"]["arguments"])
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return {"name": name, "ok": False,
                "fails": [f"turn1 tool args unparseable: {e}"], "notes": notes}
    arg_blob = " ".join(_string_leaves(args1))

    for original in pii:
        if original not in arg_blob:
            fails.append(f"A: {original!r} not resolved into tool args")
    if "<REF_" in arg_blob:
        fails.append("A: <REF_N> token leaked into client-side tool args")
    # A resolved secret in the *client-side* tool args is correct — the
    # local executor needs the real key to authenticate. The no-leak
    # contract is about the *upstream* wire (Assert B), not this hop.
    if secret is not None:
        if secret in arg_blob:
            notes.append("secret resolved for executor")
        elif "<REF>" in arg_blob:
            notes.append("secret passthrough (<REF> kept, no store entry)")
        else:
            fails.append("A: secret token neither resolved nor preserved")

    status1 = _http_json("GET", f"/v1/sessions/{session}/status")
    if sc.get("expect_empty_vault"):
        if _vault_total(status1) != 0:
            fails.append(f"A: vault not empty on benign prompt "
                         f"(total={_vault_total(status1)})")
        return {"name": name, "ok": not fails, "fails": fails,
                "notes": notes + ["negative scenario, no turn 2"]}
    if _vault_total(status1) < max(1, len(pii)):
        fails.append(f"A: vault under-populated (total={_vault_total(status1)})")

    # -- Turn 2: feed the tool result back ------------------------------
    if recorder is not None:
        recorder.set_text("Done.")
    tool_result = sc["tool_result"].format(
        probe=probe, **{f"pii{i}": v for i, v in enumerate(pii)})
    turn2 = {
        "model": model,
        "messages": sys_msgs + [
            {"role": "user", "content": sc["prompt"]},
            {"role": "assistant", "content": None, "tool_calls": tcs},
            {"role": "tool", "tool_call_id": tcs[0].get("id", "call_rec_1"),
             "content": tool_result},
        ],
        "tools": sc["tools"],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    try:
        _http_json("POST", "/v1/chat/completions", turn2, session)
    except Exception as e:
        return {"name": name, "ok": False,
                "fails": fails + [f"turn2: {e}"], "notes": notes}

    status2 = _http_json("GET", f"/v1/sessions/{session}/status")

    # Assert B (vault): the fresh probe email got masked on the way out
    if _email_count(status2) <= _email_count(status1):
        fails.append("B-vault: probe value in tool result was NOT masked "
                      "(apf did not scan the outbound tool path)")

    # Assert B (wire): recorded upstream request carries no plaintext
    if recorder is not None:
        wire = recorder.last_blob()  # turn-2 request as apf forwarded it
        for original in leak_targets:
            if original and original in wire:
                fails.append(f"B-wire: {original!r} crossed to upstream "
                             f"in plaintext")
        if probe in wire:
            fails.append("B-wire: probe value crossed to upstream "
                          "in plaintext")
        if "<REF" not in wire:
            fails.append("B-wire: no tokens in upstream request "
                          "(masking did not run on turn 2)")

    return {"name": name, "ok": not fails, "fails": fails, "notes": notes}


# ── apf wiring ─────────────────────────────────────────────────────────────
def restart_apf(openai_upstream: str) -> None:
    env = {**os.environ, "APF_OPENAI_UPSTREAM": openai_upstream}
    res = subprocess.run([str(RESTART_SCRIPT), "restart"], env=env,
                         capture_output=True, text=True, timeout=90)
    if res.returncode != 0:
        raise RuntimeError(f"apf restart failed:\n{res.stdout}\n{res.stderr}")
    print(res.stdout.strip().splitlines()[0])


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["record", "live"], default="record")
    ap.add_argument("--grep", default="", help="substring filter on name")
    ap.add_argument("--model", default="", help="override model name")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--system", choices=["off", "explainer"], default=None,
                    help="system prompt: 'explainer' prepends the apf-6l8 "
                         "token-explainer (mitigates a real model declining "
                         "tool calls on opaque <REF> tokens). Default: "
                         "explainer for live mode, off for record mode.")
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS,
                    help=f"per-turn max_tokens (default {MAX_TOKENS}; "
                         f"reasoning models need headroom to think then "
                         f"emit the tool call)")
    ap.add_argument("--keep-omlx", action="store_true",
                    help="record mode: leave apf pointed at the recorder "
                         "instead of restoring the oMLX wiring")
    args = ap.parse_args()

    system = args.system or ("explainer" if args.mode == "live" else "off")
    sys_prompt = SYSTEM_PROMPT_EXPLAINER if system == "explainer" else None
    scenarios = [s for s in SCENARIOS if not args.grep or args.grep in s["name"]]
    probe = f"probe-{uuid.uuid4().hex[:10]}@leak-canary.test"
    recorder = None
    server = None

    if args.mode == "record":
        model = args.model or "recording-upstream"
        recorder, server = serve_in_thread(REC_PORT)
        restart_apf(f"http://127.0.0.1:{REC_PORT}")
    else:
        model = args.model or LIVE_MODEL
        restart_apf(OMLX_UPSTREAM)

    print(f"\nmode={args.mode}  model={model}  system={system}  "
          f"scenarios={len(scenarios)}  probe={probe}\n")
    if not args.json:
        print(f"{'SCENARIO':<20} {'TIER':<5} {'RESULT':<8}  DETAIL")
        print("-" * 96)

    results = []
    try:
        for sc in scenarios:
            r = run_scenario(sc, model, recorder, probe, sys_prompt,
                             args.max_tokens)
            results.append(r)
            if args.json:
                print(json.dumps(r, ensure_ascii=False))
                continue
            if r["ok"] is True:
                verdict, detail = "PASS", ", ".join(r["notes"]) or "ok"
            elif r["ok"] is None:
                verdict, detail = "SKIP", ", ".join(r["notes"])
            else:
                verdict, detail = "FAIL", "; ".join(r["fails"])
            print(f"{r['name']:<20} {sc['tier']:<5} {verdict:<8}  {detail}")
    finally:
        if args.mode == "record" and not args.keep_omlx:
            restart_apf(OMLX_UPSTREAM)
        if server is not None:
            server.shutdown()

    passed = sum(1 for r in results if r["ok"] is True)
    failed = sum(1 for r in results if r["ok"] is False)
    skipped = sum(1 for r in results if r["ok"] is None)
    if not args.json:
        print(f"\n{passed} passed · {failed} failed · {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
