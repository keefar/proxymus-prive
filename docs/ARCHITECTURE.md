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

- *(empty — first real decision is "which option" after the model benchmark runs)*
