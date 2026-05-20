# 2026-05-21 — Surrogate validation + decision

Post-compact session. Continues `2026-05-21-surrogate-handoff.md`: the
surrogate-substitution pipeline (apf-okt) was built but unvalidated. This
session validated it and recorded the opaque-vs-surrogate decision.

## What shipped this session

- **`docs/HOW-IT-WORKS.md`** (apf-y7a, closed) — user-facing pipeline
  walk-through + honest difficulties ledger. Linked from README + CLAUDE.md.
- **Prior-art surveys** written into apf-auw (LLM gateways / privacy-aware
  routing — LiteLLM, PrivacyPAD, PRISM) and apf-hiq (crowd-improvable
  detection — CrowdSec shadow-mode, Sigma, YARA Hub). Design/brainstorm
  still pending with the user.
- **Surrogate validation** (this doc).

## The cloud path was throttle-dead

`scripts/cloud_toolcall.py` (the real-Claude validation) was unusable all
session: Anthropic returned a persistent 529 server-side throttle
("temporarily limiting requests"). `search_1pii` burned all four backoff
retries (15/30/60/120 s) without landing a single call. This is the
server-side RPM throttle, not a plan-quota issue — but it does not clear
on the timescale of a backoff loop at this hour.

**Pivot:** `scripts/toolcall_loopback.py --mode live` runs the same
mask → model → tool-call → resolve chain against the local oMLX server
(Qwen3.6-35B-A3B Holo3) instead of cloud Anthropic — throttle-immune. It
exercises the OpenAI path; the boundary mechanics are the same. Surrogate
mode is toggled via `APF_SURROGATE_LABELS` (the rig restarts apf and
inherits the env).

## Validation runs

Three runs, same model (Qwen3.6-35B Holo3), 7 scenarios each:

| Scenario | opaque + explainer | surrogate, system=off | surrogate + explainer |
|---|:--:|:--:|:--:|
| send_email_de | PASS | SKIP (length) | SKIP (length) |
| send_email_en | PASS | PASS | PASS |
| add_contact_phone | PASS | PASS | PASS |
| create_event | PASS | PASS | PASS |
| bash_path | SKIP (stop) | SKIP (stop) | SKIP (length) |
| http_secret | PASS | PASS | PASS |
| negative_no_pii | SKIP (stop) | SKIP (length) | SKIP (stop) |
| **totals** | **5P / 0F / 2S** | **4P / 0F / 3S** | **4P / 0F / 3S** |

### Reading the runs honestly

- **0 FAIL, 0 leak across all three runs.** Every scenario that emitted a
  tool call passed: originals resolved into the client-side tool args, no
  `<REF>` / surrogate token leaked, the fresh probe value in the tool
  result got masked. `create_event` passes in surrogate mode with a
  surrogated PERSON + DATE + LOCATION resolved together. **The surrogate
  tool-call boundary holds.**
- **The SKIPs are not failures and not a mode effect.** A SKIP is
  `no tool_call` — the reasoning model either chose to answer in text
  (`finish=stop`) or spiralled to the token cap (`finish=length`). Proof
  it is run-to-run model noise, not surrogate: **`bash_path` is
  byte-identical in opaque and surrogate mode** (its only PII is a PATH,
  and PATH is *not* in the surrogate label set — it stays opaque) — yet
  its SKIP reason varied `stop` → `stop` → `length` across the runs. An
  identical request producing different outcomes ⇒ Qwen-Holo3
  non-determinism (MoE routing + MLX numerics), not opaque-vs-surrogate.
- The first surrogate run was **confounded** (changed two variables:
  surrogate *and* `--system off`). The PII-free `negative_no_pii` scenario
  flipped `stop@65` → `length@4096` with no apf-side difference at all —
  pure system-prompt effect. The third run re-ran surrogate *with* the
  explainer to isolate the single variable; conclusion unchanged.

## Decision

**Opaque `<REF_N>` stays the default. Surrogate substitution is validated
as working but stays opt-in / experimental** (`APF_SURROGATE_LABELS`,
default empty).

Rationale:

1. Surrogate *works* — the boundary holds, round-trip verified above.
2. But it is strictly less robust than opaque on four independent axes,
   none of which `toolcall_loopback` exercises and all of which opaque is
   immune to:
   - re-detection (surrogates are PII-shaped; needed the apf-76m fix —
     opaque never had the problem);
   - path-composition collision (a common-word surrogate substring-
     collides; opaque `<REF_N>` is delimited and immune — proven by
     `apf/path_compose_test.py`);
   - value-rewrite mid-conversation (observed in a surrogate cloud run);
   - vault explosion (a surrogate cloud run hit vault = 130 on a 6-PII
     task).
3. The problem surrogate targets — apf-76s, models declining dense
   `<REF>` clusters — is already otherwise mitigated: the `<SENSITIVE_N>`
   → `<REF_N>` rename (apf-0uo), the default explainer injection, and the
   apf-4cs finding that the strongest declines were a test artifact
   ("echo this PII block" is itself injection-shaped).

So surrogate buys a mostly-redundant benefit at the cost of four
robustness regressions. It stays in the tree, flag-gated, for the cases
where natural-text fidelity matters more than the robustness margin.

**Open for the user:** the final default-vs-opt-in policy call. apf-okt
is left `in_progress` for the user to ratify — they were bullish on
surrogate, and this is a product call, not just an engineering one.

## Open / next

- Cloud validation (`cloud_toolcall`, real Claude) still owed once the
  Anthropic throttle clears — apf-4cs.
- The surrogate cloud run's vault = 130 is most likely the `cloud_toolcall`
  Grep escaping the clean audit dir (the `cc_matrix.py` hit in the output
  is not a file the audit dir contains). The audit-dir isolation is not
  enforced — a `cloud_toolcall` test-design fix, tracked under apf-4cs.
