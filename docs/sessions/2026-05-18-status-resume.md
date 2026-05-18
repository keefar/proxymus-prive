# 2026-05-18 — Resume after long gap: status, scaffolding, test plan

After ~24h pause, this session re-established orientation on the repo,
caught the docs up to where the code actually is, filed open follow-ups
from the threat-model decisions, and planned the next two pieces of
concrete work.

## TL;DR

- README synced with reality (was claiming "no working code"; repo
  ships an end-to-end PoC with 14 green tests).
- `bd remember` for the §3.1 "categorical-only" finding was stale
  ("decision pending in apf-5ue" — apf-5ue closed 2026-05-17 with
  §5.1 resolution); refreshed in place.
- Two open follow-ups filed:
  - **apf-sgz** (P2) — local-only-category never-forward design
    (§5.6, deferred from apf-5ue)
  - **apf-x1t** (P3) — audit log v2: disk persistence + Keychain
    encryption + retention (§5.7, apf-ive shipped v1 in-memory)
- `THREAT-MODEL-PRIVATE.md` §5.6–5.8 now link to concrete issues
  instead of "OPEN — tracked separately".
- ticket-flow tooling scaffolded (init / discover / bd-detox), but
  **beads remains source of truth**; KANBAN.md is dormant.
- Memory Coexistence Policy now in AGENTS.md so beads `bd remember`
  and Claude Code auto-memory coexist without one diverting the other.

## Where the project actually is

Read `README.md` for the headline. The structured view:

| Layer | Code | Tests | State |
|---|---|---|---|
| Detector ensemble | `benchmarks/adapters_*.py`, results in `benchmarks/results/` | — | engine pinned (apf-4f4.8); recall criterion revised in `ARCHITECTURE.md` |
| Tokenisation core | `apf/tokenizer.py`, `apf/detokenizer.py`, `apf/vault.py`, `apf/resolver.py`, `apf/secrets.py` | covered by `proxy_test.py` + `secrets_test.py` | round-trip + tool-boundary resolution working |
| Proxy | `apf/proxy.py` (710 LOC) | `apf/proxy_test.py` (602 LOC) | Anthropic Messages + OpenAI Chat Completions, both incl. streaming |
| SSE | `apf/sse.py` (234) + `apf/openai_shape.py` (371) | `apf/sse_test.py` (171) | partial-token buffering for Anthropic + OpenAI shapes |
| Endpoint policy | `apf/endpoint_policy.py` | `apf/endpoint_policy_test.py` | trust map: loopback + mDNS + 8 cloud APIs |
| Audit log | `apf/audit_log.py` | (none) | v1 off-by-default in-memory ring buffer (apf-ive) |
| Local-only refusal | `apf/local_only.py` | (none) | v1 refuse-and-route per apf-enr (NOT the same as apf-sgz scope) |
| Fixtures (public) | `fixtures/*.jsonl` | — | 553 items across content/operational/secrets/ai4privacy |
| Fixtures (private) | `fixtures/private/` (gitignored) | — | 14 multi-turn scenarios (apf-baw) |

What is **not** validated yet: behaviour under a real coding agent driving
the proxy with a realistic workload. That's the next gate.

## Test setup: Hermes → apf → oMLX (all-local loopback)

User's idea (good one): build a loopback stack with no cloud dependency
and full proxy visibility.

```
┌─────────────┐ chat_completions    ┌──────┐ chat_completions  ┌──────┐
│ Hermes CLI  │ ──────────────────▶ │ apf  │ ────────────────▶ │ oMLX │
│ (agent)     │  http://127.0.0.1:8000/v1   │ (filter)     http://127.0.0.1:8000/v1  │ (LLM) │
└─────────────┘                      └──────┘                    └──────┘
                                         │
                                         └── vault, detector, audit log
                                             stay local to apf
```

Key facts I verified today:

- **Hermes Agent** (NousResearch, v0.14.0, 2026-05-16). Config at
  `~/.hermes/config.yaml`. Supports three wire protocols:
  `chat_completions`, `anthropic_messages`, `codex_responses`.
  `base_url` is configurable per task (auxiliary, delegation, …).
  API key fallback: `OPENAI_API_KEY` env var.
- **oMLX** (jundot/omlx, also marketed at omlx.ai). MLX-native
  inference server for Apple Silicon. Speaks **both** OpenAI Chat
  Completions and Anthropic Messages on the same port. Default port:
  **8000** (note: `apf/proxy.py:74` and `apf/local_only.py:105`
  comments say 8081 — that's stale, separate fix-up).
- **apf** already serves both `/v1/messages` and `/v1/chat/completions`
  on its FastAPI server.

Protocol pick: **`chat_completions`** end-to-end. Reason: oMLX's OpenAI
endpoint is the better-tested shape, apf already handles it
(`apf/openai_shape.py`), and Hermes treats it as first-class.

### Known compatibility gap: session pinning

apf keys the per-session vault on the `x-apf-session` HTTP header. If
the header is absent, it falls back to **per-request** session, meaning
the same originals get *different* `<SENSITIVE_N>` IDs on each turn —
that confuses an agent that's reasoning over multi-turn context.

Hermes' configured custom-header support is not documented. Three
options:

1. **Accept the gap for v1 smoke** — single-turn fixtures only, no
   multi-turn agent loops. Quickest path to first signal.
2. **Patch apf to derive a session ID from something else** — e.g.
   take a hash of the `system` / first-user-message prefix and use
   that as a fallback session key when no header. Cheap, ~30 LOC.
3. **Wrap Hermes with a tiny shim that injects the header** — e.g. a
   one-file Python middleware that proxies localhost:7999 → apf
   and adds `x-apf-session: <uuid>`. Most correct, ~50 LOC.

My recommendation: start with (1) for the day-1 smoke, then (2) before
any meaningful multi-turn evaluation. (3) is overkill for our scope.

## Step-by-step: validate apf in the loopback stack

### What you do (sequential)

1. **Install oMLX** — `omlx.ai` or `brew install jundot/omlx/omlx`
   (verify the tap before running). Launch via menubar, pick a coding
   model (Qwen-Coder-2.5-7B or similar). Confirm it answers at
   `http://127.0.0.1:8000/v1/models`.
2. **Install Hermes** — `pipx install hermes-agent` (verify install
   path), run `hermes init` so the config file at `~/.hermes/config.yaml`
   exists.
3. **Tell me when both are running.** I'll do the wiring.

### What I do (after you confirm)

4. **Wire Hermes → apf** — edit `~/.hermes/config.yaml` so the agent
   `base_url` points at `http://127.0.0.1:7000/v1` (apf's default port)
   and `api_mode: chat_completions`.
5. **Wire apf → oMLX** — start apf with
   `APF_OPENAI_UPSTREAM=http://127.0.0.1:8000` so the filter forwards
   to oMLX. Verify via `apf/manual_smoke.py` first that the chain is
   round-tripping.
6. **First smoke** — single-turn prompt with known PII (e.g. one of
   the `de-mail-02` fixtures): "Schreib eine kurze E-Mail an
   anna.mueller@beispiel.de für den Termin am 2026-05-22 um 14:00".
   Compare:
   - what Hermes sends → what oMLX receives (via oMLX log)
   - what oMLX returns → what Hermes shows you
   - apf's vault state (debug endpoint or audit log)
7. **Capture findings** — write a follow-up session log
   (`docs/sessions/2026-05-19-loopback-smoke.md`) with what worked,
   what didn't, and concrete issues to file.
8. **Decide next step from findings** — typical outcomes:
   - over-filter found → file a bd issue, refine detector thresholds
   - tool-call resolution misfires → trace through `resolver.py`
   - session-pinning bites → flip the workaround switch (option 2 above)
   - clean pass → graduate to multi-turn fixtures from
     `fixtures/private/`

### Skills I'll lean on

- `superpowers:systematic-debugging` for any unexpected behaviour
  during the smoke (Phase 1 = web search + repro, not guessing)
- `webapp-testing` (Playwright) for any UI / inspector flows if needed
- `simplify` for code-shape cleanups after we know what works

## Plan: tackling apf-sgz (local-only category routing)

Not in scope for tonight, but here's the shape so future-you sees it.

### Phase A — scenario evaluation (no code)

A1. Pick 8–10 scenarios from `fixtures/private/` that exercise the
    candidate-local-only categories:
    - S10 (DV history), L5 (undocumented), L6 (asylum), P8
      (whistleblower intent). Pull 2–3 multi-turn fixtures per
      category.
A2. For each scenario, document the realistic agent action sequence
    (what tools would the agent call? what's the *value* of a cloud
    answer vs. a local answer?).
A3. From that, decide:
    - which subset is **always** local
    - which subset is **policy-configurable** with eager default
    - which subset is **never** local (covered by normal Tier-A)
A4. Write findings to `docs/DESIGN-LOCAL-ONLY-ROUTING.md` (new doc).

### Phase B — local-model integration spike (small code)

B1. Decide which local model is the "fallback" — likely the same
    oMLX-hosted model we're using as the LLM backend in the test
    setup. Single bullet.
B2. Prototype the routing decision in `apf/local_only.py` — when a
    detected span is in the local-only set AND the destination
    endpoint is in the untrusted-cloud trust class (`endpoint_policy.py`),
    route the *whole request* to the local model. Don't do
    split-routing for v2; that's a separate design.
B3. Add tests: each in-scope category triggers local routing,
    out-of-scope categories don't.

### Phase C — UX / metadata surface (deferred until B works)

C1. Statusline / response-header indicator: "this request stayed
    local". Build on the existing `X-APF-Restored` header pattern.
C2. Per-category config in `~/.config/apf/filter.toml`: opt-out
    individual categories.

### My role per phase

- **Phase A**: I'm the workshop facilitator. I read the fixtures
  with you, propose the routing call per scenario, you ratify or
  redirect. Output: the design doc.
- **Phase B**: I implement against the spec from A. You review
  diffs and run the tests. Likely TDD; I'll use
  `superpowers:test-driven-development` skill.
- **Phase C**: probably not for the PoC unless A/B reveal that
  C is load-bearing.

### Dependencies / gating

- Phase A doesn't need any new dependencies. Could start tomorrow.
- Phase B depends on the test setup from §"Step-by-step" above
  being green — we need to know apf works end-to-end before
  layering routing-decisions on top.
- Phase C depends on B.

## Open thread: stale port number for oMLX

In `apf/proxy.py:74` and `apf/local_only.py:105` the comments
mention "oMLX (default 8081)". oMLX's actual default is 8000.
The trust map in `endpoint_policy.py` should still work (loopback
is loopback regardless of port) but the comments mislead. Filed
mental note; will fix when we touch those files for the test setup.
