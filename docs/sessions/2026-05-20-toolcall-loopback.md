# 2026-05-20 — Tool-call boundary resolution: end-to-end validation rig

Session question: *"do the fixtures need to go through Hermes? what about
checking tool calling?"* Answer to part one — **no**: `fixtures/*.jsonl`
are flat PII strings, detector-eval material; `benchmarks/run.py` already
covers them and no agent adds signal. Part two was the real gap, and this
session closed it ([[apf-pk7]]).

## TL;DR

- Tool-call boundary resolution — the project differentiator — was only
  covered by unit tests with a *hardcoded* fake upstream. The 2026-05-18
  log explicitly listed end-to-end tool-call detokenisation as unproven.
- Built a two-mode rig that exercises it through the **running apf proxy**:
  - **`record` mode** — deterministic, hard pass/fail. **7/7 green.**
    Proves resolution + the no-leak contract on the apf→upstream wire.
  - **`live` mode** — real gemma model via oMLX. apf resolved **every**
    tool call the model emitted (4/4, zero failures); the model emits
    them inconsistently on masked prompts (finding below).
- Three artifacts: `scripts/apf_restart.sh`, `scripts/recording_upstream.py`,
  `scripts/toolcall_loopback.py`.
- Test suite still green (56 passed).

## Why a recording upstream

The differentiator's contract has two halves:

1. **Resolve at the boundary** — a tool call carrying `<REF_N>` tokens is
   resolved to originals before the local executor sees it.
2. **Never leak back** — when the resolved tool call + tool result are fed
   back, the originals must not cross to the LLM.

Half 1 is observable in the HTTP response from apf. Half 2 needs the
apf→upstream wire, which is otherwise invisible (the 2026-05-18 log noted
oMLX exposes no request log). `scripts/recording_upstream.py` is a fake
OpenAI Chat Completions upstream that records every request body apf
forwards and returns a deterministic, script-controlled response — so the
rig can assert on the exact bytes that crossed the boundary.

## record mode — 7/7, the airtight proof

`apf` is restarted (via `apf_restart.sh`) pointed at the in-process
recorder. Per scenario, two turns:

- **Turn 1** — user prompt with PII → canned `tool_calls` echoing the
  tokens apf produced. Assert: the arguments the *client* receives hold
  the originals, no `<REF_N>` left behind.
- **Turn 2** — resolved tool call + a tool result fed back. The tool
  result embeds a fresh **probe** email never seen before. Assert:
  - *wire* — the recorded upstream request carries zero original PII /
    secret / probe, only tokens;
  - *vault* — the probe got masked → apf scanned the outbound tool path.

| Scenario | Tier | Result |
|---|---|---|
| send_email_de / _en | A | PASS |
| add_contact_phone | A | PASS |
| create_event | A | PASS |
| bash_path | B | PASS |
| http_secret | C | PASS — `<REF>` resolved for the executor, not leaked upstream |
| negative_no_pii | – | PASS — benign tool prompt, empty vault |

Tier-C detail: the bare `<REF>` secret token resolved to the real key in
the *client-side* tool args (correct — the executor needs it to
authenticate) and did **not** appear in the recorded upstream request.

## live mode — real model, and the finding

`apf` → oMLX → `gemma-4-26b-a4b-it-4bit`. apf correctly resolved every
tool call gemma emitted (4 PASS, 0 FAIL). But gemma emits them
inconsistently on masked prompts — 3 scenarios skipped (no tool call).

Root-caused by single-variable testing (direct-to-oMLX, no apf):

- Raw prompt, real PII → gemma emits the tool call.
- Prompt with **one** `<REF>` token → still emits.
- Prompt with **two** `<REF>` tokens → gemma declines:
  *"I'm sorry, but I don't have the information for `<REF_1>` and
  `<REF_2>`."* It reads the opaque tokens as missing information.
- Same two-token prompt **+ the apf-6l8 system explainer** → emits again.

So this is the **[[apf-6l8]] family** (model misreads `<REF>` tokens),
surfacing in the tool-calling path rather than as a flat refusal. The
explainer mitigates it but not fully — `live` mode defaults to
`--system explainer` and still skips `send_email_de` / `create_event`;
`bash_path` gemma declines regardless (it reasons it cannot read a file
it "cannot see"). oMLX's forced `tool_choice` is best-effort, not strict.

This is a model / test-backend property, **not an apf correctness bug** —
apf's resolution was correct on every emitted call. Filed as [[apf-76s]].

## What this proves / does not prove

**Proves:**
- Tool-call boundary resolution works end-to-end through the running
  proxy: tokens in → originals out, for Tier A/B values and Tier-C
  secrets, OpenAI shape.
- The no-leak contract holds on the apf→upstream wire: resolved tool
  calls and tool results are re-masked before the next turn; a fresh
  probe value in a tool result is detected and masked.
- A real model (gemma) drives the path successfully when it cooperates.

**Does not prove:**
- SSE streaming tool-call path (rig is non-streaming — `openai_shape.py`
  has a separate `_emit_pending_tool_calls` streaming path; untested here).
- Anthropic-shape tool_use end-to-end (rig is OpenAI-shape; `proxy_test.py`
  covers Anthropic tool_use with a fake upstream).
- Behaviour against a real cloud model (Claude) — whether it too misreads
  `<REF>` tokens in tool calls is open ([[apf-nia]] territory).

## Follow-ups filed

- **apf-76s** (P2) — gemma declines tool calls on multi-token masked
  prompts; characterise across models, decide if apf should ship a
  default explainer / friendlier token shape.
- **apf-3bx** (P3) — dedicated `apf/resolver_test.py` unit coverage
  (currently exercised only via `proxy_test.py` integration + the rig).

## Artifacts

- `scripts/apf_restart.sh` — stop/start/status for apf, wired to a
  chosen OpenAI upstream (oMLX by default). Lets a session restart apf
  itself instead of depending on a hand-launched process.
- `scripts/recording_upstream.py` — recording fake OpenAI upstream.
- `scripts/toolcall_loopback.py` — the rig (`--mode record|live`,
  `--system off|explainer`, `--grep`, `--json`).
