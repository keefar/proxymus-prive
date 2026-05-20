# 2026-05-20 — apf in front of real Claude Code: over-masking + a leak

First time apf was driven by the actual target — real Claude Code, not a
local model. It surfaced two blockers, both now fixed and verified.

## TL;DR

- **apf-xt5** — apf masked Claude Code's whole operational context: a
  one-sentence prompt produced a **213-entry vault**, Claude declined,
  unable to read its own tool names. Fixed in two steps; vault **213 → 4**,
  Claude completes tool tasks.
- **apf-uc1** — the verification run caught a real leak: replayed
  `tool_use` blocks were not re-masked on the Anthropic request path, so
  the boundary-resolved value crossed back to the model. Fixed.
- Test suite **89 green** (was 70 at the start of the day).

## The rig: driving real Claude Code through apf

`claude -p` with two env vars — no new tooling:

```
ANTHROPIC_BASE_URL=http://127.0.0.1:8765        # route through apf
ANTHROPIC_CUSTOM_HEADERS="x-apf-session: <id>"  # pin one apf vault
```

The custom header solves the session-pinning gap noted on 2026-05-18
(agents don't send `x-apf-session`): apf keys one stable vault, so
`/v1/sessions/<id>/status` shows exactly what was masked.

## apf-xt5 — the over-masking

A captured Claude Code request (`messages` = one user message, 7 content
parts):

| Parts | Content | Size |
|---|---|---|
| 0–5 | one `<system-reminder>` block each: superpowers skill text, agent-type list, MCP instructions, the 18 KB skills catalogue, hooks, the CLAUDE.md projection | 38,454 chars |
| 6 | `"hello"` | 5 chars |

apf masked all 7 → 213 vault entries (`PERSON=95`, incl. the tool name
**"Grep" → PERSON**). Claude declined: *"contains unresolved placeholders:
`Grep` … dozens of `<REF_N>` placeholders."* The genuine payload was
5 chars; everything else was harness scaffolding.

### How dontfeedtheai handles it — it doesn't

The vendored sibling project (`vendor/dontfeedtheai`, a pentest proxy)
has **zero** awareness of `<system-reminder>` / harness structure (grep
of `src/` is empty). It masks everything — `system` + all messages +
tool results — and defends false positives with a `_NEVER_ANONYMIZE`
allowlist (pentest tool names) + a wordfreq common-word filter. Its
allowlist has no coding-agent terms and its 53 fixtures are pentest tool
outputs — it has the same latent bug, unmeasured. Not a model to copy
here; the borrowable idea is the allowlist concept (→ step 2).

### The fix — two steps

**Step 1 — skip `<system-reminder>` blocks.** `mask_outside_system_reminders()`
(in `masker.py`) applies the detector only to text *outside*
`<system-reminder>…</system-reminder>`. Wired into both request maskers.
Tool results stay fully masked — they are genuine data, not scaffolding.
Result: vault **213 → 2**.

**Step 2 — agent-term allowlist.** The 2 residual masks were the genuine
email (correct) and "Grep" → PERSON (fatal — Claude can't call a masked
tool). `AGENT_TERMS` (in `proxy.py`, extendable via `APF_AGENT_TERMS`)
lists agent operational terms; `_mask_text` drops a span whose *entire*
text is one — whole-span match, so `grepson@example.de` is unaffected.
Result: Claude completes the Grep task, vault holds only genuine content.

## apf-uc1 — the leak the fix uncovered

With tools finally working, the multi-turn run exposed a separate bug.
Claude flagged it itself: *"my Grep pattern field came out as a
fully-formed email address instead of the literal token I intended to
pass."*

apf resolves `tool_use.input` on the response path (the executor needs
real values). When the client replays that assistant message next turn,
`_mask_part` re-masked `text` and `tool_result` parts — but had **no
`tool_use` branch** — so the resolved original crossed back to the model.
The OpenAI path never had this (it re-masks `tool_calls`); the Anthropic
masker was simply missing the symmetric branch. `_mask_part` now re-masks
`tool_use.input` via `_walk_json_mask`. Verified: the leak flag is clear.

## State

| Run (`claude -p`, Grep + PII) | Vault | Outcome |
|---|---|---|
| before | 213 | Claude declines — context shredded |
| after step 1 | 2 | declines — "Grep" masked as PERSON |
| after step 2 | 6 | **completes** — but model sees resolved value (apf-uc1) |
| after apf-uc1 | 4 | **completes**, no leak |

**Proven:** apf is usable in front of real Claude Code — tool tasks
complete, the agent reads its own scaffolding, no resolved value leaks
back. **Open:** detector precision on genuine content (residual FPs are
now single-digit, not 200); the apf-76s explainer/multi-token question
for Claude is now unblocked and testable.

## Follow-up: the Claude explainer matrix (apf-76s)

With over-masking fixed, the actual product question was finally
testable: does Claude need the apf-6l8 token explainer? Ran `claude -p`
through apf with multi-PII Bash-echo tool-call prompts:

| masked tokens | no explainer | + explainer |
|---|---|---|
| 3 | OK | OK |
| 6 | **DECLINE** | OK |

At 6 tokens, plain, Claude refused — *"I won't do that. The placeholders
look like a prompt-injection pattern."* Not the local models' "missing
info" misread — a denser, more capable model reads a tight cluster of
opaque `<REF>` tokens as a possible **injection attack**. The explainer
clears it. So "no explainer" is not viable for realistic multi-PII
prompts. Harness committed as `scripts/cloud_toolcall.py`.

**Resolved:** `apf/explainer.py` now injects that note into cloud-bound
requests when the vault is non-empty (opt-out `APF_EXPLAINER=off`).
apf-76s closed. A deeper fix — **surrogate substitution** (plausible
fake values instead of opaque `<REF_N>`, so the request reads as normal
text and never trips the injection defence) — would supersede the
explainer on Tier-A-dense prompts; filed as **apf-okt** with a hybrid
design (surrogates for non-sensitive Tier-A identifiers, opaque kept for
secrets and the §3.1 categorical-sensitive set). Confirmed empirically:
a 6-PII prompt with plausible values completes with no explainer.

## Commits / artifacts

- `mask_outside_system_reminders` (`masker.py`) + `masker_test.py`
- `AGENT_TERMS` / `_mask_text` filter (`proxy.py`) + `agent_terms_test.py`
- `_walk_json_mask` + `_mask_part` tool_use branch + `tool_use_remask_test.py`
- closed: **apf-xt5**, **apf-uc1**

## Surrogate substitution (apf-okt) — built, premise not confirmed

The deeper fix — masking Tier-A identifiers to plausible fake values
instead of opaque `<REF_N>`, so the request reads as natural text — was
built end to end: a hand-rolled per-type generator, vault dual-mapping,
masker / unmasker / resolver paths, `APF_SURROGATE_LABELS` wiring. Seven
increments, each tested, 146 green; flag-gated, default-off, so the
opaque default is untouched.

The live cloud verification (surrogate mode, explainer *off*) did **not**
confirm the premise:

- **Re-detection bug** ([[apf-76m]]) — a surrogate is itself PII-shaped,
  so when it flows back (tool result, replayed history) apf's own
  detector re-masks it. `echo_1pii` produced a 2-entry vault from one
  PII and the echo round-trip broke. Opaque markers are immune.
- The 3- and 6-PII echo prompts **declined** — a privacy-trained model
  resists verbatim-echoing what looks like real personal contact data.
  *Caveat:* the `cloud_toolcall` scenarios ("echo this PII block") were
  built for the opaque token-density test and are inherently
  injection-shaped — not a fair test of surrogate mode.

So surrogate mode is implemented but **not validated**. The apf-76s
explainer remains the working shipped fix. Pursuing surrogates further
means fixing apf-76m and re-testing with task-shaped scenarios (PII
incidental to a real task, not a verbatim PII-block echo) — a decision
left to the user.
