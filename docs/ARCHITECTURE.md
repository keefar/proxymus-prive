# Architecture — design options and open questions

This is a decision-staging doc, **not** a commitment. The PoC's first technical job is to
pick between the options below. Recommendation at the bottom; not yet executed.

## Constraints

- **Host:** M5 MacBook Air, 32 GB unified memory, fanless
- **Inference:** MLX on Apple Silicon (Python ecosystem)
- **Detection budget:** ≤ 4 GB combined RAM, ≤ 1.5 s p95 stage-2 latency
- **First agent target:** Hermes + the OpenAI-compatible ecosystem (Cursor,
  Aider, Codex, Cline). The Claude Code path is blocked by Anthropic's
  subscription-auth policy — see the 2026-05-22 decision-log entry.
- **Boundary:** all PII detection / mapping happens locally; only sanitized text crosses
  the network

## Threat model — three handling tiers

What the filter must protect splits into three classes with **fundamentally different
mechanics**. Mixing them is a category error: a credential and a recipient name look
similar from the proxy's perspective but need opposite treatment.

### Tier A — Content PII (LLM may reason about it)

What lives here: people, email addresses, phone numbers, postal addresses, locations,
organisations, dates, appointments, **health information (doctor visits, diagnoses,
medication)**, relationship hints, financial fragments, sensitive note content,
implicit PII (paraphrased identifying details).

Handling: **mask → LLM works on tokens → resolve at the boundary** (either inside a
specific `tool_use` arg before local execution, or in the rendered response shown to the
user). Two-way reversible.

Examples of correct flow:
- `"Schick die Auswertung an Anna Müller"` → LLM sees
  `"Schick die Auswertung an <PERSON_1>"` → tool call `send_email(to="<EMAIL_3>")` is
  resolved against the vault at exec time → cloud LLM never saw `anna.mueller@…`.
- Health-Termin in calendar: `"Mittwoch 14:00 Dr. Bauer, Kontrolle"` →
  `"<DATE_2> <APPOINTMENT_HEALTH_1>"` → user sees original in the response.

### Tier B — Operational identifiers (LLM may need to reference them; tool calls almost always need the original)

What lives here: filesystem paths (`/Users/<you>/...`), filenames that encode user
identity, hostnames, local + public IP addresses, machine-specific URLs.

Handling: mask, but the **tool-call boundary resolver is the load-bearing piece** —
every `Read`, `Write`, `Bash`, `grep` needs the real value to execute. Cannot be left
purely to "resolve only in response to user" because the agent's own actions depend on
resolution.

Open sub-question: which subset of Tier B is *also* user-policy-configurable? Some users
want `/Users/<you>` masked end-to-end; others consider it harmless. The PoC will treat
all Tier B values as masked by default and let policy loosen later.

### Tier C — Secrets (LLM must never see the value)

What lives here: API keys, OAuth tokens, private keys (SSH, GPG, TLS), passwords,
database connection strings carrying credentials, `.env`-style secrets.

Handling: **opaque redaction, not reversible round-trip.** The LLM sees at most
bare `<REF>` with no type or hint (token shape refined in apf-0uo 2026-05-19 from earlier `<SECRET>`). When a tool needs the value, the local executor pulls
it from environment / keychain / vault directly and substitutes at exec time — the
secret never crosses the wire and never enters the prompt. Unlike Tier A and B,
reversibility is *not* a goal; *unobservability* is.

This is the only tier where the existing "anonymize → call LLM → de-anonymize" pattern
from Presidio etc. is the wrong shape — you don't want the LLM reasoning about secrets
at all, not even via tokens.

### Implication for the component map

The component map below operates uniformly on text spans, but the **policy table** that
maps detected labels to handling actions has three branches:

| Tier | Detect | Mask | Resolve in response | Resolve at tool boundary | Block & redact |
|------|:------:|:--------:|:--------------------:|:------------------------:|:--------------:|
| A — Content | ✅ | ✅ | ✅ | when needed | — |
| B — Operational | ✅ | ✅ | optional (policy) | **always** | — |
| C — Secret | ✅ | — | — | resolve from vault | ✅ (never to LLM) |

## Component map (target shape, regardless of fork choice)

```
                    ┌─────────────────────────────────────────────┐
agent ──HTTP───────▶│  proxy                                       │──HTTPS──▶  cloud LLM
(Claude Code, …)    │                                              │
                    │  1. parse request body (Anthropic / OpenAI)  │
                    │  2. stage-1 detect (regex + GLiNER/Presidio) │
                    │  3. stage-2 detect (MLX small LLM)           │
                    │  4. substitute placeholders                  │
                    │  5. forward to cloud                          │
                    │  6. on response (SSE-aware): rehydrate        │
                    │  7. on tool-call args: tag for boundary       │
                    │                                              │
                    │  session vault: original ↔ placeholder       │
                    └─────────────────────────────────────────────┘
                                       │
                            (4) tool-call boundary resolver
                            (lives where? — see §"Open question 1")
```

## Open question 1 — Where does tool-call resolution live?

Three candidate locations:

| Where | Pro | Con |
|---|---|---|
| **In the proxy** | Single place to reason about; no agent-side changes | Proxy can't know which tokens will be passed to a `Bash` tool vs. left in narrative. Would have to resolve everything in tool_use args — risks re-leaking via the agent's reasoning that follows |
| **In an agent-side wrapper** (Claude Code hook / MCP server) | Knows exactly when a token is about to hit a tool; can resolve only there | Requires per-agent integration; doesn't generalize cleanly across Cursor, Aider, Codex |
| **Hybrid** | Proxy resolves tokens *inside* `tool_use` blocks before they reach the agent's local executor; everything else stays masked | Most complex; needs to parse provider-specific message structures (Anthropic `tool_use`, OpenAI `tool_calls`) |

The hybrid is most likely correct but most expensive. **PoC plan:** start with the simplest
working version (resolve everything in tool args, accept leak risk), measure how often it
actually leaks via narrative, and only build the smarter version if needed.

**Note from the tier model:** the three tiers partition this question differently.

- Tier A (content) is mostly OK with proxy-only resolution — names in narrative are not
  load-bearing for tool execution.
- Tier B (operational paths/hosts/IPs) is exactly where the tool-call boundary matters;
  this is the class that drives the design.
- Tier C (secrets) sidesteps the question — they're never masked into the prompt at
  all; the agent harness fills them in from a secret store at exec time, independent of
  any in-proxy resolver.

So Open question 1 is really *"how does the proxy resolve Tier B at the tool boundary
without leaking via narrative?"* — Tiers A and C are easier sub-cases.

## Open question 2 — Stack & fork base

Four positions evaluated under the project-kickoff skill's framework:

### Option A — Fork DontFeedTheAI, retarget multi-agent
- **Inherits:** Python/FastAPI proxy, **dual-layer Ollama+regex pipeline already wired**,
  per-engagement vault, self-improving feedback loop. 544⭐, MIT.
- **Surgery needed:** Replace Ollama backend with MLX; remove pentest-specific category bias;
  generalize from Claude-Code-only to multi-agent (Anthropic + OpenAI APIs).
- **Effort:** Medium. Most of the conceptual core is already there.
- **Risk:** Codebase shape may resist generalization; small team / recent commits.

### Option B — Fork contextio, add MLX detection layer
- **Inherits:** TypeScript proxy with clean multi-agent design, working SSE reconstruction
  across 3 streaming formats, base-URL + mitmproxy chaining, regex presets, reversible
  mapping. 24⭐, MIT.
- **Surgery needed:** Add a JS↔Python bridge to call MLX (subprocess or sidecar HTTP),
  port the GLiNER stage, sort out latency of the bridge.
- **Effort:** Medium. Proxy plane is solid; ML plane is new.
- **Risk:** Heterogeneous stack (TS proxy + Python MLX sidecar) adds operational
  complexity for what's meant to be a daily-use tool.

### Option C — Fork PasteGuard, add reversibility + MLX
- **Inherits:** Broadest tool support (ChatGPT, Cursor, Copilot, Windsurf, Claude Code, …),
  Presidio integration, mature codebase. 630⭐, Apache-2.0.
- **Surgery needed:** Confirm reversibility status (the README scan suggested it isn't
  reversible — must verify before committing); add MLX backend; add tool-call resolver.
- **Effort:** High. Two big additions to a mature codebase usually means significant
  refactoring against the original maintainer's design.
- **Risk:** Largest fork-divergence risk.

### Option D — From scratch, Python / FastAPI, MLX-first
- **Inherits:** Nothing — but we'd write only the pieces we actually need.
- **Effort:** Highest. Re-implements SSE handling across formats (the boring-but-painful
  bit), session vault, message-format parsing.
- **Risk:** Solo project velocity; "redo what contextio already solved" tax.

### Option matrix

| Option | Stack fit (MLX) | Multi-agent ready | Reversible | Effort | Notes |
|---|:-:|:-:|:-:|:-:|---|
| **A — Fork DontFeedTheAI** | 🟡 (Python ✅, Ollama→MLX swap) | ❌ → 🟡 (refactor) | ✅ | Medium | Closest conceptual match |
| **B — Fork contextio** | 🔴 (TS proxy + Python sidecar) | ✅ | ✅ | Medium | Best proxy plane |
| **C — Fork PasteGuard** | 🔴 (Bun stack) | ✅ | ❓ verify | High | Broadest agents, biggest fork-tax |
| **D — From scratch** | 🟢 | n/a — design fresh | n/a — design fresh | High | Most flexibility, most boring work |

## Recommendation (subject to PoC validation)

**For the PoC: Option D (from-scratch, minimal).** Reason: the PoC's job is to validate the
**model layer** and the **tool-call resolver** — the two pieces no existing project gives us.
For that, a 200-line FastAPI proxy with a single message-format (Anthropic) and one agent
(Claude Code) is enough. Don't take on someone else's design debt for a throwaway scaffold.

**For the daily-driver phase: re-evaluate after PoC.** Likely path:
- If the MLX models work well and the tool-call resolver is feasible → **fork
  DontFeedTheAI** (closest conceptual match, Python, MIT) and port our PoC pieces in;
  retarget for multi-agent.
- If the PoC reveals the tool-call resolver is *not* feasible cleanly inside the proxy →
  shift to agent-side integration (Claude Code hooks, MCP wrappers) and use **contextio**
  or **PasteGuard** as the unmodified proxy plane; we contribute only the agent-side bits.

The "from scratch for PoC, fork for daily driver" split is unusual but defensible here:
the unknowns we need to retire (does an MLX SLM detect German PII well enough? does
tool-call resolution work?) live in code we'd write either way. The proxy plumbing only
becomes worth inheriting once those unknowns are retired.

## What the PoC will and will not prove

**Will prove or disprove:**
- MLX SLM PII detection quality on German + English coding-agent traffic
- Combined memory / latency feasibility on the M5
- Whether tool-call resolution can be done in-proxy at all (or whether it needs
  agent-side integration)

**Will not prove:**
- Productionizability — error handling, multi-session vaults, SSE edge cases all live in
  Phase 2
- Coverage across all the agents in the "daily driver" vision — Claude Code only for PoC

## Decision log

### 2026-05-16 — Stage-2 model benchmark results: no single-model winner

Ran three MLX-resident candidates against the 50-fixture set (`fixtures/*.jsonl`).
Full numbers in `benchmarks/results/`. Summary:

| Model                       | tier-recall | tier-precision | DE-rec | EN-rec | p95 ms | RAM   |
|-----------------------------|:-----------:|:--------------:|:------:|:------:|:------:|:-----:|
| Nemotron MLX 8bit (token-class) | 0.290 | 0.551 | 0.258 | 0.320 |  187 | 1.6 GB |
| Anonymizer-SLM 1.7B 4bit (gen)  | 0.355 | 0.516 | 0.382 | 0.330 | 2958 | 1.3 GB |
| Qwen3-1.7B 4bit (gen, zero-shot) | 0.226 | 0.712 | 0.213 | 0.237 | 1009 | 1.3 GB |
| regex baseline (floor)            | 0.194 | 0.900 | 0.112 | 0.268 |  <1  |  —     |

**Headline finding: no single Stage-2 model hits the ≥0.95 recall criterion.**
The best (Anonymizer-SLM) tops out at 0.355 tier-recall. The criterion isn't off
by a tuning factor — it's off by a category-of-approach factor.

**What each model is good at:**
- **Nemotron** — fastest by far (p95 187ms); strong on structurally regular
  Tier-A spans (emails, names, addresses). Useless for German content beyond
  emails (documented English-only). Useless for implicit/paraphrased PII.
- **Anonymizer-SLM** — best Tier-A recall, especially German (0.42 / 0.38 DE
  recall). Strongest on "natural-language" PII. Latency disqualifies for hot
  path (2.96s p95 vs. 1.5s budget).
- **Qwen3 zero-shot** — highest precision; lowest recall. Confirms PII fine-tune
  matters: same base as Anonymizer-SLM, with fine-tune adds 0.13 recall.
- **Regex** — high precision floor; complementary to all three on Tier-B/-C
  (the SLMs miss paths/IPs/keys; regex catches them).

**Categories all three models miss systematically:**
- Implicit PII / paraphrased identifiers (10 fixtures with `IMPLICIT_PII`
  spans — combined recall < 0.1).
- Health context not anchored on the word "Dr." or a medication name (German
  Arzttermine).
- Relationships ("der Kollege aus dem Controlling", "meine Schwiegermutter").
- Tier-B operational identifiers when not in structured config (e.g. a path
  mentioned in narrative).
- Tier-C secrets without the classic prefix (`sk-`, `ghp_`, …).

**Decision — Stage-2 engine pick is deferred.** No model in isolation is the
answer. Two viable architectures remain, both empirically grounded by this
benchmark:

1. **Stage 1+2 ensemble (recommended)**:
   - Stage 1 = regex + Nemotron (low confidence threshold) — fast, structural,
     covers Tier-B/-C and the "easy" Tier-A.
   - Stage 2 = Anonymizer-SLM, called only on segments where Stage 1 fires
     low-confidence or on text categories Stage 1 is known weak on (free-form
     prose, calendar entries, notes). Per-segment latency stays under budget
     because Stage 2 is not invoked for every span.
   - Open question: how to gate Stage-2 invocation cleanly. Probably a
     heuristic on input shape (free-form text vs. structured config/log).

2. **Re-scope the recall criterion**:
   - 0.95 across the full fixture mix may be the wrong target — the
     adversarial-paraphrase fixtures are inherently hard for a 1.7B SLM. A
     defensible alternative: 0.95 on **explicit Tier-A spans** (PERSON, EMAIL,
     PHONE, ADDRESS, HEALTH with anchor words, DATE) plus 0.80 on
     IMPLICIT_PII, plus 0.99 on Tier-C (the criticality leans here anyway).
   - This would unblock single-model paths if accompanied by clear UX about
     the IMPLICIT_PII coverage limit.

**Engineering follow-ups recorded in beads** (not done yet):
- `apf-fu6` — Tool-call resolution prototype (now informed by Tier-B
  detection floor: Nemotron + regex covers Tier-B well enough at p95 < 200ms
  to make boundary resolution feasible).
- Future: GLiNER multilingual as a fourth candidate for Stage 1 — was in
  `MODELS.md` from the start, not benchmarked yet because the Stage-2 question
  was meant to come first. Now the question is "what fills the recall gap on
  implicit PII for the ensemble", which GLiNER specifically may or may not
  answer.
- Future: BF16 variant of Nemotron — quantization-loss check. Unlikely to
  bridge the recall gap but cheap to verify.

**What the benchmark proved (and what it didn't):**
- ✅ MLX latency + RAM budgets are achievable.
- ✅ Tooling pipeline (fixtures → harness → adapters → metrics) works.
- ✅ German support is a real differentiator — Nemotron eliminated by it.
- ✅ The Tier model is the right framing — performance differs sharply across
  tiers per model.
- ❌ "Pick the best stage-2 model" is not the right question; the empirical
  shape rejects it.

### 2026-05-16 (later) — GLiNER multilingual reshapes the picture

Two GLiNER variants added to the benchmark after the initial decision. Both
roughly **2× the recall of the best generative model**, with latency in
Nemotron's ballpark — i.e. the same kind of tooling fit (token classifier,
batched-friendly, no prompt engineering) but with multilingual training and
implicit-PII coverage that Nemotron lacks.

| Model                              | tier-recall | tier-precision | DE-rec | EN-rec | p95 ms | RAM    |
|------------------------------------|:-----------:|:--------------:|:------:|:------:|:------:|:------:|
| **GLiNER `urchade/gliner_multi_pii-v1`** | **0.667** | 0.588 | **0.708** | 0.629 |  80  | 2.8 GB |
| **GLiNER `nvidia/gliner-PII`**          | **0.688** | 0.646 | 0.674 | 0.701 | 202  | 3.9 GB |
| Anonymizer-SLM 1.7B (gen)              | 0.355 | 0.516 | 0.382 | 0.330 | 2958 | 1.3 GB |
| Nemotron MLX 8bit (token-class)        | 0.290 | 0.551 | 0.258 | 0.320 |  187 | 1.6 GB |
| Qwen3-1.7B 4bit (gen, zero-shot)       | 0.226 | 0.712 | 0.213 | 0.237 | 1009 | 1.3 GB |
| regex baseline (floor)                 | 0.194 | 0.900 | 0.112 | 0.268 |  <1  |   —    |

**What GLiNER changes about the picture:**

- The headline "no model hits 0.95 — must build an ensemble" still stands.
  GLiNER tops at 0.69 tier-recall, not 0.95.
- But the **gap closes by ~0.33** vs. the previous best (Anonymizer-SLM at
  0.355). The remaining ~0.30 to the criterion now looks closeable by a
  thin ensemble layer, not a fundamentally different architecture.
- GLiNER **catches implicit PII** that all three earlier models missed —
  "Der Kollege aus dem Controlling" → person 0.70; "die einzige Mitarbeiterin
  im Team mit zwei Kindern und einer Diabetes-Diagnose" → person + health.
  This was the structural gap the earlier finding flagged.
- **German support is real and untrained for** — `multi_pii-v1` actually
  scores higher on DE than EN (0.708 vs. 0.629). The NVIDIA variant flips
  this (better EN), so the multilingual fine-tune *does* matter. Use
  `multi_pii-v1` for DE-heavy workloads.
- **Tier-B precision** is the NVIDIA variant's strength (0.960 vs. multi's
  0.731). Matters because Tier-B false positives mean the tool-call
  resolver wastes work on non-paths. NVIDIA is the better fit for
  config/log inputs; multi-v1 for free-form prose.

**Revised decision (still subject to ensemble verification):**

- **Stage 1 primary engine: GLiNER `multi_pii-v1`.** Fast (p95 80ms),
  multilingual, catches the hard categories. 2.8 GB RSS sits inside the
  combined 4 GB budget if Stage 2 stays under ~1 GB.
- **Stage 2 (residual): TBD.** Two candidates to evaluate against
  the residual fixtures (where Stage 1 misses):
  - Anonymizer-SLM, called selectively on free-form text and narrative
    notes where GLiNER's miss rate is concentrated. Latency cost
    amortised by selective invocation.
  - Regex secret patterns + GLiNER NVIDIA variant on operational/secret
    inputs. Higher Tier-B precision avoids tool-call-resolver thrash.
- **Stage 3 (escape valve)**: a "low-confidence summary" hand-off where
  the user is shown what *might* be sensitive but the system isn't sure.
  Avoids the false dichotomy between "block silently" and "leak".

The single-engine framing is still rejected, but the residual gap (~0.30)
is small enough that the ensemble architecture is now a tractable
engineering problem, not an open research question. Next concrete step is
the ensemble meta-adapter (`apf-857`) — combine regex + GLiNER + Anonymizer
with explicit routing, then re-measure.

**Updated PoC architecture sketch:**

```
input text
   │
   ├──▶ regex pre-pass (Tier-B/C structurally regular)       ←  apf-857
   │       │
   ├──▶ GLiNER multi_pii-v1  (all tiers, multilingual)
   │       │
   ├──▶ Anonymizer-SLM       (only if input looks like prose / notes)
   │       │
   ▼       ▼
  union, dedupe (longest span at each start wins)
   │
   ▼
 tier-tagged spans
```

This is the working hypothesis going into `apf-857`. The "fundamentally
different architecture" wording from this morning's entry is now demoted
to: "fundamentally different *engine*". The architecture is still the
proxy + tokens + tool-call resolver pipeline; only the engine grows from
"one model" to "regex + GLiNER + optional SLM".

### 2026-05-16 (evening) — Ensemble settles the engine question

Built and benchmarked two ensemble variants in `benchmarks/adapters_mlx.py`:

| Variant | Composition | tier-recall | tier-precision | DE | EN | p95 ms | RAM |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|
| **ensemble-fast** | regex + GLiNER multi_pii-v1 | **0.715** | 0.607 | 0.719 | 0.711 | **76** | 2.8 GB |
| ensemble-full | + Anonymizer-SLM | 0.747 | 0.574 | 0.764 | 0.732 | 3201 | 3.2 GB |

**Conclusion: ensemble-fast is the PoC engine.** Adding Anonymizer as a
third stage buys +3 pp tier-recall at **42× the p95 latency**. Even
worse, ensemble-full's Tier-C recall *drops* from 0.647 to 0.529 — the
Anonymizer's free-text mode emits replacement candidates that drown out
regex's high-precision secret hits in the merge.

**What this resolves:**
- The "engine question" (which detector(s)) is settled. The "1.5 s p95
  budget" was always premised on the assumption that one MLX SLM was the
  workhorse — turns out a token classifier (GLiNER) + regex hits 76 ms p95
  and frees the budget for everything else (vault lookup, tool-call
  resolution, response rewriting).
- Combined RAM ≤ 4 GB constraint: ensemble-fast at 2.8 GB leaves 1.2 GB
  headroom — enough to also resident GLiNER NVIDIA for high-precision
  Tier-B (e.g. when input "looks like" a config file) without exceeding
  the budget. Not needed for PoC but documented for later tuning.

**What this does NOT resolve:**
- Tier-recall 0.715 is not 0.95. The residual ≈ 0.28 lives in three
  pockets: adversarial paraphrases (`IMPLICIT_PII` fixtures), some
  Tier-A health context not anchored on medication/doctor words, and
  Tier-C secrets whose surface form doesn't trigger any regex.
- These are *inherently hard* for a 1.7B-class model and not closeable
  by more ensemble layering — every attempt adds latency without adding
  recall (see ensemble-full's Tier-C regression).

**Revised recall criterion** (formal proposal; supersedes the original
"≥ 0.95 in both languages on the fixture set" from `MODELS.md`):

| Category | Target | Rationale |
|---|:-:|---|
| Tier-A explicit (PERSON, EMAIL, PHONE, ADDRESS, DATE) | ≥ 0.95 | The structurally regular spans — leaks here are unforced errors |
| Tier-A implicit (IMPLICIT_PII, paraphrased) | ≥ 0.60 | Acknowledges the 1.7B-SLM-class ceiling; compensated by UX (see below) |
| Tier-B operational | ≥ 0.80 | Lower-stakes for content leak; high-stakes for tool-call thrash if precision suffers |
| Tier-C secrets | ≥ 0.99 | Hard requirement — secret leaks are the most expensive category |

Plus a **non-detection-based control**: a "low-confidence flag" UX
where the filter shows the user *what it thinks might be sensitive but
isn't sure*, so the human can confirm before sending. This converts the
0.60 implicit-PII recall into a tractable user-experience problem rather
than a silent leak.

**Implementation status — PoC engine is now buildable.** Outstanding pieces
(see beads):

- `apf-fu6` — Tool-call resolution prototype. Unblocked: Tier-B detection
  floor at 0.694 recall (ensemble-fast) is high enough that proxy-side
  resolution becomes feasible without massive false-positive noise.
- New: Tier-C regex pattern expansion. Current regex catches `sk-`,
  `ghp_`, JWT-shape, IBAN. Missing: bare base64-of-secret, .env-style
  `KEY=value` heuristic, PEM blocks. Cheap to add. Likely closes the
  Tier-C gap to 0.99.
- New: `IMPLICIT_PII` UX — the low-confidence-flag pathway. Not a model
  problem, a UI problem.
- New (deferred until PoC end): re-test against the `apf-4f4.10`
  BF16-vs-8bit Nemotron question is now moot — Nemotron is dominated
  by GLiNER across every metric. Close `apf-4f4.10` as not-going-to-do.

### 2026-05-22 — Delivery model: the HTTP proxy is blocked for subscription Claude Code

The PoC set out to validate the model layer and the tool-call resolver. It
did — and it also surfaced a delivery-model problem that outranks both.

**Finding.** Routing Claude Code through apf to the real Anthropic API
fails 100% with `429 rate_limit_error` whenever the account uses a
Free/Pro/Max **subscription** (OAuth) token. Anthropic's policy (~April
2026) refuses subscription auth for non-first-party use; a proxy hop makes
the request non-first-party, and the discriminator sits below the HTTP
layer (forwarding every client header + the query string does not help).
Direct `claude -p` works; via-apf does not. Not a throttle, not a capacity
incident, not an apf bug — deliberate policy.

**The agent-side alternative does not close the gap.** A capability review
of Claude Code's hooks + the Agent SDK: `UserPromptSubmit` cannot rewrite
the prompt, `PostToolUse` is read-only, and no hook can rewrite the model's
response before display. An HTTP proxy is the only mechanism for the
bidirectional round-trip apf needs. So for subscription Claude Code there
is no viable delivery mechanism — proxy blocked, hooks insufficient.

This retires Open question 1 from the wrong direction: the question was
*where* tool-call resolution lives; the answer is that for subscription
Claude Code the proxy cannot be in the path at all.

**Decision.** The proxy is not abandoned — only its Claude-subscription
path is. apf works unchanged for OpenAI-compatible / local agents (Hermes,
Cursor, Aider, Codex, Cline, local models via oMLX), and the core —
detector, vault, tool-call-boundary resolution — is auth-agnostic.

- **First agent target shifts from Claude Code to Hermes** + the
  OpenAI-compatible ecosystem. Develop and release there.
- The Anthropic path stays in the tree, marked blocked; re-enable trigger =
  an Anthropic policy change or a found solution.
- A feature request to Anthropic (`docs/ANTHROPIC-FEATURE-REQUEST.md`) asks
  for a sanctioned mechanism.

Full reasoning + workstreams: `docs/sessions/2026-05-22-apf-dtq-strategy.md`
(and `2026-05-21-surrogate-validation.md` for the investigation trail).
