# 2026-05-21 — Pre-compact handoff: surrogate substitution

Checkpoint before a context compaction. Read this + run `bd prime` to
resume. Tree is clean, all work committed, suite green (155).

## The day's arc (what shipped, 2026-05-20 → 21)

Working backwards from "apf in front of real Claude Code":

- **apf-xt5** — apf over-masked Claude Code's `<system-reminder>`
  scaffolding (213-entry vault, Claude declined). Fixed: skip
  system-reminder blocks + an agent-term allowlist. Closed.
- **apf-uc1** — replayed `tool_use` blocks weren't re-masked on the
  Anthropic request path (resolved value leaked back). Fixed. Closed.
- **apf-8pz** — `reasoning_content` not unmasked (OpenAI); Anthropic
  `thinking` deliberately left masked (signature integrity). Closed.
- **apf-76s** — Claude declines dense `<REF>` clusters as
  "prompt-injection"; shipped a default explainer injection
  (`apf/explainer.py`, opt-out `APF_EXPLAINER`). Closed.
- **apf-okt** — surrogate substitution (this is the live work, below).
- **apf-76m** — surrogates re-detected on replay; fixed. Closed.

## Surrogate substitution (apf-okt) — built, NOT validated

Full pipeline shipped in 7 tested increments: `apf/surrogates.py`
(generator), vault dual-mapping (`surrogate` + `surface`), `mask_text`
`surrogate_labels`, `unmask_text` string-scan restore, resolver boundary
resolve, proxy `APF_SURROGATE_LABELS` wiring. **Flag default empty → the
opaque `<REF_N>` default is untouched** — surrogate mode is opt-in.

Hybrid scope (ratified): surrogate for non-sensitive Tier-A
(PERSON/EMAIL/PHONE/IP/LOCATION/DATE/ADDRESS); opaque stays for Tier-C
secrets and categorical-sensitive content; PATH is opaque too.

### Robustness ledger — opaque keeps winning

1. **Re-detection** — surrogates are PII-shaped, so apf re-flagged them
   on replay. Fixed (apf-76m: `_mask_text` skips known-surrogate ranges)
   — but it *needed* a fix; opaque never had the problem.
2. **Path composition** — opaque `<REF_N>` is atomic + delimited,
   survives composition / adjacency / reuse. A common-word surrogate
   **collides**: substring `str.replace` rewrites it wherever it repeats
   (`apf/path_compose_test.py` proves it; opaque is immune).
3. A live run had Claude flag a value-rewrite mid-conversation
   (un-diagnosed — needs a clean deterministic trace).

**Leaning: surrogate as opt-in per-label, not the default. Not decided.**

## Next concrete step

Run the **clean validation** — it is finally un-confounded:
`scripts/cloud_toolcall.py` now uses task-shaped scenarios (a Grep
"audit this directory" search, not a verbatim PII-block echo) and a
fresh clean scratch dir (`make_audit_dir`, not polluted `/tmp/claude`).

    .venv/bin/python -m scripts.cloud_toolcall --system off      # opaque
    # then with apf restarted APF_SURROGATE_LABELS=all APF_EXPLAINER=off

Watch: declines (expect 0 — task-shaped prompts don't trip the refusal,
confirmed); vault count (should be ≈ n_pii with the clean dir — far
higher signals a real problem); any value-rewrite / token leak. Note
Anthropic was rate-limiting earlier — `cloud_toolcall` has backoff.

## Open beads

- **apf-okt** (in progress) — surrogate mode, see above.
- **apf-4cs** (P2) — realistic test design; task-shaped scenarios + clean
  audit dir done, the clean validation run remains.
- **apf-nia** (P1, in progress) — cloud-smoke through Claude Code.
- **apf-hiq** / **apf-auw** (P3) — future ideas (crowd-improvable filter;
  endpoint routing) — research + brainstorm required, not started.
- deferred: apf-app / p8b / 4b8 / rdn (PR-upstream), apf-w33.
