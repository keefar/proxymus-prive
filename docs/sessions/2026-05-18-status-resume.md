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

---

## Loopback smoke results (2026-05-18 ~20:30)

Stack went live tonight. Chain confirmed working end-to-end via
`scripts/smoke_loopback.py` (new this session).

### Setup gotchas hit on the way

1. **Hermes `model` picker overrides custom config.** Running
   `hermes model` (interactive picker) rewrote `model.base_url` to
   point directly at oMLX, bypassing apf. Fix: explicit
   `hermes config set model.base_url http://127.0.0.1:8765/v1` after
   any model change.
2. **Endpoint trust map auto-disables filtering on localhost.** apf
   classifies 127.0.0.1 as `POLICY_OFF` by default (per apf-ycu —
   local engines are trusted). For a local-loopback *test* you want
   filtering ON. Override via `~/.config/apf/endpoints.toml`:
   ```toml
   [[endpoints]]
   host = "127.0.0.1"
   policy = "full"
   ```
   Reload requires apf restart (policy is computed at module import).
3. **No clear oMLX request log.** oMLX (jundot/omlx) doesn't surface
   per-request prompt text in its menubar UI. We worked around it
   using apf's `/v1/sessions/{id}/status` vault-counts endpoint —
   gives us category-level proof of tokenisation without exposing
   originals. Good enough for verification; insufficient for raw
   diff (would need a recording proxy for that, deferred).

### Bulk test results

14 curated cases (DE+EN × 3 tiers × negative case × multi-PII probe).
Run target: Qwen2.5-Coder-7B-Instruct-MLX-4bit on oMLX.

| Tier | Cases | Vault assertion | Notes |
|---|---|---|---|
| A | 7 | 7/7 ✓ | PERSON, EMAIL, PHONE, DATE, LOCATION, ADDRESS all detected DE+EN |
| B | 2 | 2/2 ✓ | PATH, IP detected |
| C | 3 | 3/3 ✓ | API_KEY, TOKEN (JWT 2 parts), PASSWORD (env-assign) all detected |
| neg | 1 | 1/1 ✓ | Empty vault on "What is 2+2?" |
| multi | 1 | 1/1 ✓ | 5 entries in one call: PERSON+EMAIL+PHONE+ADDRESS+LOCATION |

**Totals: 14/14 vault assertions ✓, 13/14 model refusals ✗.**

### The big finding: Qwen2.5-Coder safety-refuses (apf-6l8, P1)

Every prompt that produced a non-empty vault triggered a model refusal:
"Es tut mir leid, aber ich kann keine Sensitive Informationen
verarbeiten" or English equivalent. Single-token contexts refused
just as readily as multi-token ones. The mechanism appears to be
Qwen's safety training reading `<SENSITIVE_N>` markers as evidence
the user is sharing personal data, regardless of what task was asked.

Filed as [[apf-6l8]] (P1 bug). Workaround hypotheses to test next:
1. System-prompt explainer: "Texts marked <SENSITIVE_N> are
   placeholder substitutions; treat them as opaque variables."
2. Less alarming token shape: `<X_N>` instead of `<SENSITIVE_N>`.
3. Different backend model (Hermes-3-Llama, Mistral, gpt-oss).
4. Accept the limitation and validate full agent flows against real
   cloud APIs (Claude Code → apf → Anthropic) — the local loopback
   then becomes detector-validation-only rather than end-to-end.

### What this run proves and doesn't prove

**Proves:**
- apf-fwt (OpenAI Chat Completions shape) tokenisation works end-to-end.
- Detector ensemble correctly tags all major label classes across both
  languages, including Tier-C secrets.
- Vault-status endpoint is a workable verification channel when the
  upstream LLM doesn't expose request logs.
- The trust-map design is correct (loopback-trusted is the right
  production default) but needs documentation as a testing footgun.

**Does not prove:**
- Detokenisation across tool-call boundaries (would need an agent
  flow that survives Qwen's refusals — blocked on apf-6l8).
- SSE streaming path under real agent load (Hermes has streaming off;
  the proxy supports it but the rig didn't exercise it).
- Behaviour under multi-turn context with stable session pinning
  (Hermes doesn't send x-apf-session; workaround discussion still
  pending in earlier section of this log).
- Real-world over-filter rate (deterministic single-shot prompts; the
  realistic corpus eval lives in apf-00s).

### Artifacts committed

- `scripts/smoke_loopback.py` — bulk test runner (14 cases, --grep filter, --json mode)
- `docs/INTEGRATION.md` — new "Local-loopback testing" section with TOML override
- `~/.config/apf/endpoints.toml` — user-machine config (not in repo)
- `apf-6l8` — Qwen safety-refusal bug (P1)
