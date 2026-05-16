# Architecture — design options and open questions

This is a decision-staging doc, **not** a commitment. The PoC's first technical job is to
pick between the options below. Recommendation at the bottom; not yet executed.

## Constraints

- **Host:** M5 MacBook Air, 32 GB unified memory, fanless
- **Inference:** MLX on Apple Silicon (Python ecosystem)
- **Detection budget:** ≤ 4 GB combined RAM, ≤ 1.5 s p95 stage-2 latency
- **First agent target:** Claude Code (most important to user); second target Cursor or Aider
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

Handling: **tokenize → LLM works on tokens → resolve at the boundary** (either inside a
specific `tool_use` arg before local execution, or in the rendered response shown to the
user). Two-way reversible.

Examples of correct flow:
- `"Schick die Auswertung an Anna Müller"` → LLM sees
  `"Schick die Auswertung an <PERSON_1>"` → tool call `send_email(to="<EMAIL_3>")` is
  resolved against the vault at exec time → cloud LLM never saw `anna.mueller@…`.
- Health-Termin in calendar: `"Mittwoch 14:00 Dr. Bauer, Kontrolle"` →
  `"<DATE_2> <APPOINTMENT_HEALTH_1>"` → user sees original in the response.

### Tier B — Operational identifiers (LLM may need to reference them; tool calls almost always need the original)

What lives here: filesystem paths (`/Users/chris/...`), filenames that encode user
identity, hostnames, local + public IP addresses, machine-specific URLs.

Handling: tokenize, but the **tool-call boundary resolver is the load-bearing piece** —
every `Read`, `Write`, `Bash`, `grep` needs the real value to execute. Cannot be left
purely to "resolve only in response to user" because the agent's own actions depend on
resolution.

Open sub-question: which subset of Tier B is *also* user-policy-configurable? Some users
want `/Users/chris` masked end-to-end; others consider it harmless. The PoC will treat
all Tier B values as tokenized by default and let policy loosen later.

### Tier C — Secrets (LLM must never see the value)

What lives here: API keys, OAuth tokens, private keys (SSH, GPG, TLS), passwords,
database connection strings carrying credentials, `.env`-style secrets.

Handling: **opaque redaction, not reversible round-trip.** The LLM sees at most
`<SECRET>` with no type or hint. When a tool needs the value, the local executor pulls
it from environment / keychain / vault directly and substitutes at exec time — the
secret never crosses the wire and never enters the prompt. Unlike Tier A and B,
reversibility is *not* a goal; *unobservability* is.

This is the only tier where the existing "anonymize → call LLM → de-anonymize" pattern
from Presidio etc. is the wrong shape — you don't want the LLM reasoning about secrets
at all, not even via tokens.

### Implication for the component map

The component map below operates uniformly on text spans, but the **policy table** that
maps detected labels to handling actions has three branches:

| Tier | Detect | Tokenize | Resolve in response | Resolve at tool boundary | Block & redact |
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
| **Hybrid** | Proxy resolves tokens *inside* `tool_use` blocks before they reach the agent's local executor; everything else stays tokenized | Most complex; needs to parse provider-specific message structures (Anthropic `tool_use`, OpenAI `tool_calls`) |

The hybrid is most likely correct but most expensive. **PoC plan:** start with the simplest
working version (resolve everything in tool args, accept leak risk), measure how often it
actually leaks via narrative, and only build the smarter version if needed.

**Note from the tier model:** the three tiers partition this question differently.

- Tier A (content) is mostly OK with proxy-only resolution — names in narrative are not
  load-bearing for tool execution.
- Tier B (operational paths/hosts/IPs) is exactly where the tool-call boundary matters;
  this is the class that drives the design.
- Tier C (secrets) sidesteps the question — they're never tokenized into the prompt at
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
