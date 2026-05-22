# 2026-05-22 — model-strategy epic, first `--parallel` run, W3 complete

Three threads in one session: a strategic decision (model-aware token
handling), a process test (`/ticket-flow:flow --parallel`), and the
completion of W3 (Hermes end-to-end testing). Read after
`2026-05-22-apf-dtq-strategy.md`.

## 1. Decision — model-aware token handling is hybrid (epic `apf-qnl`)

The question: when apf adapts to an upstream model's quirks, is that a
generalized mechanism or per-model? Evidence said neither alone works:

- `apf-2qz` — a weak 7B mangles opaque `<REF_N>` (drops brackets, makes it
  email-shaped); a 35B passes it verbatim.
- `apf-76s` — dense opaque-token clusters trip capable models' injection
  defences.
- `apf-okt` closeout — opaque is more robust than surrogate on 4 axes, so
  surrogate is not a blanket replacement.

→ Neither opaque nor surrogate is universally best, and which is best
depends on the upstream model. **Decision: hybrid.**

- **Generalized** (model-agnostic): detector, vault, masking mechanism, the
  Tier-C-always-opaque invariant, and a *tolerant resolver* — graceful
  degradation so an untested model never silently breaks.
- **Per-model** (contributable): the strategy choice (opaque vs surrogate),
  token shape, injection-mitigation toggles — as declarative profile data,
  looked up by the request's `model` field. Profiles are plain data so the
  community fills the registry for models we cannot all test.

Testing story: a model-conformance harness that classifies a model and
*emits* a profile — simultaneously profiler, contribution tool, and
regression test.

Epic `apf-qnl` with four children: `apf-tu9` tolerant resolver, `apf-ao2`
profile registry, `apf-vh8` conformance harness, `apf-dkf` strategy
selection wired to the profile.

## 2. First `/ticket-flow:flow --parallel` run

`apf-tu9` + `apf-ao2` — the two independent epic children — worked in
parallel via worktree-isolated subagents. **It worked cleanly:** concurrent
dispatch, both TDD, conflict-free sequential merges, full suite 180 green
(157 + 17 + 6), `apf.proxy_test` green. Both closed (no residual).

Observations on the mode: the shared `.venv` works from a worktree
(cwd-relative import tests the worktree's code); a missing spec is a DoR
*warning*, not an abort; `kanban-render.sh` was skipped on purpose
(beads-first mode — rendering would dump 86 beads into the vestigial
KANBAN.md). Verdict: usable for independent tickets.

Follow-up filed: `apf-6dt` — wire the resolver's `on_unresolved` fail-loud
hook into the proxy (the proxy has no general logger yet; scoped out of
`apf-tu9`).

## 3. W3 — Hermes end-to-end testing complete (`apf-liv` closed)

Three checks, real Hermes → apf → oMLX:

1. **Over-masking** — vault `total: 5` for a 3-PII prompt (PERSON 2,
   EMAIL 1, PHONE 1, DATE 1). Hermes scaffolding does **not** explode the
   vault, unlike Claude Code's `vault=130`. One PERSON false positive
   (feeds `apf-hrc`).
2. **Tool-call boundary** — a file-write task put `contact.txt` on disk
   with the *real* name/email/phone; apf resolved the masked tokens at the
   tool-call boundary, oMLX saw only tokens.
3. **`apf-2qz` e2e** — 3/3 clean 7B runs, correct email restored, no `REF`
   residue. `apf-2qz` closed: with `apf-tu9` merged, the weak-model
   round-trip break does not reproduce.

New finding filed — `apf-j4w` (bug): **FILENAME over-masking degrades agent
comprehension.** apf masked the benign generic filename `contact.txt` as a
Tier-B FILENAME token. Because every filename then masks to an
indistinguishable opaque token, the 35B lost track of *which* file it had
written and thrashed for many turns ("I wrote contact.txt but the user
asked for contact.txt"). The round-trip still held — this is a
degradation/precision bug, not a leak.

Tooling added: `GET /v1/sessions` (`apf-c1b`) — lists active session ids +
counts-only summaries, so anon sessions (a client with no `x-apf-session`
header, e.g. Hermes) become inspectable.

## State at session end

main green (182 tests). apf running, wired to oMLX. Epic `apf-qnl` half
done — `apf-vh8` + `apf-dkf` now unblocked and ready. Open precision
threads: `apf-j4w` (FILENAME), `apf-hrc` (PERSON false positives).
