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
  - **`live` mode** — real models via oMLX (gemma, Qwen3.6-Holo3). apf
    resolved **every** tool call either model emitted — zero failures in
    any run. Whether a model emits a tool call at all degrades on masked
    prompts (finding below; reframed as apf-76s).
- Three artifacts: `scripts/apf_restart.sh`, `scripts/recording_upstream.py`,
  `scripts/toolcall_loopback.py`.
- Two apf-side findings surfaced: response unmask skips reasoning/thinking
  traces ([[apf-8pz]]); `apf_restart.sh` healthz timeout too short for a
  cold detector load under memory pressure (fixed).
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

## live mode — real models, and the model-behaviour finding

apf → oMLX, two real models. **apf resolved every tool call either model
emitted correctly — across every run, zero failures.** What varies is
whether the model emits a tool call at all on a masked prompt.

### The masked-token effect — a gradient, not a gemma bug

`gemma-4-26b-a4b-it-4bit`: `--system off` 3/7, `--system explainer` 4/7.
Single-variable testing (direct-to-oMLX, no apf) root-caused it:

- raw prompt → emits the tool call; one `<REF>` token → still emits;
- **two** `<REF>` tokens → declines: *"I'm sorry, I don't have the
  information for `<REF_1>` and `<REF_2>`"* — it reads the opaque tokens
  as missing data;
- two tokens **+ the apf-6l8 explainer** → emits again.

gemma is historically weak at MLX tool calling, so the effect was
re-tested on `Qwen3.6-35B-A3B-Holo3-Qwopus-mxfp4-mlx` (a reasoning model,
a strong tool caller). It does **not** disappear — it shifts the
threshold: Qwen handles two tokens fine but declines `create_event`
(four tokens, `<REF_1>`..`<REF_4>`), returning text — *"Please provide
the actual details for each reference: Event Title (REF_1), Attendee
(REF_2)…"*. So the effect is **general** — models read multiple opaque
tokens as missing information — and graded by tool-calling strength. It
is the [[apf-6l8]] family; reframed and filed as [[apf-76s]].

The **explainer mitigates it across models**: with `--system explainer`
Qwen passes 5/7 — all five real-PII scenarios (`send_email` de/en,
`add_contact`, `create_event`, `http_secret`), apf resolving every call.
`bash_path` both models decline regardless (they reason they cannot read
a file they "cannot see"); `negative_no_pii` Qwen answers in text. The
Qwen `--system off` run lands far lower but is unreliable: Qwen3.6 is an
MoE — **run-to-run nondeterministic even at temperature 0** (`add_contact`
emitted a call in a direct probe, skipped in a full run). A single live
run is not authoritative for an MoE backend. oMLX's forced `tool_choice`
is best-effort, not strict, for both models.

### Two apf-side findings surfaced

- **reasoning_content / thinking blocks are not unmasked** — apf's
  response paths restore `content` + tool calls but not a reasoning
  model's trace, so `<REF>` tokens surface there. Under-restoration, not
  a leak, but it breaks the readable-with-originals requirement. Filed as
  [[apf-8pz]].
- `scripts/apf_restart.sh` waited only 15 s for `/healthz`; a cold MLX
  detector load under memory pressure (a 35B model resident in oMLX)
  overruns that. Bumped to 180 s — the loop still returns instantly on a
  warm start.

*oMLX re-validation: an update (`HEAD-f6f4269`) was installed 01:54 but
the service only restarted 14:33, so the original gemma runs hit the
pre-update binary. Re-run on the updated build — identical results — so
the finding is oMLX-version-independent.*

## What this proves / does not prove

**Proves:**
- Tool-call boundary resolution works end-to-end through the running
  proxy: tokens in → originals out, for Tier A/B values and Tier-C
  secrets, OpenAI shape.
- The no-leak contract holds on the apf→upstream wire: resolved tool
  calls and tool results are re-masked before the next turn; a fresh
  probe value in a tool result is detected and masked.
- Real models drive the path: with the explainer, Qwen3.6-Holo3 passes
  all five real-PII scenarios, apf resolving every emitted call — and no
  run, on either model, ever produced a resolution failure.

**Does not prove:**
- SSE streaming tool-call path (rig is non-streaming — `openai_shape.py`
  has a separate `_emit_pending_tool_calls` streaming path; untested here).
- Anthropic-shape tool_use end-to-end (rig is OpenAI-shape; `proxy_test.py`
  covers Anthropic tool_use with a fake upstream).
- Behaviour against a real cloud model (Claude) — whether it too misreads
  `<REF>` tokens in tool calls is open ([[apf-nia]] territory).

## Follow-ups filed

- **apf-76s** (P2) — models decline tool calls on multi-token masked
  prompts (gradient by tool-calling strength, not gemma-specific);
  characterise across models, decide if apf should ship a default
  explainer / friendlier token shape.
- **apf-8pz** (P2) — response unmask skips reasoning/thinking blocks;
  `<REF>` tokens surface in a reasoning model's visible trace.
- **apf-3bx** (P3) — dedicated `apf/resolver_test.py` unit coverage
  (currently exercised only via `proxy_test.py` integration + the rig).

## Artifacts

- `scripts/apf_restart.sh` — stop/start/status for apf, wired to a
  chosen OpenAI upstream (oMLX by default). Lets a session restart apf
  itself instead of depending on a hand-launched process.
- `scripts/recording_upstream.py` — recording fake OpenAI upstream.
- `scripts/toolcall_loopback.py` — the rig (`--mode record|live`,
  `--system off|explainer`, `--grep`, `--json`).
