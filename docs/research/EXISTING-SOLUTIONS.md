# Existing solutions — landscape as of 2026-05

Survey of projects that solve all or part of "filter PII out of an LLM-agent's outgoing
traffic, restore it on the way back." Goal of this doc: avoid reinventing what already
works, and identify the actual gap.

## TL;DR

The **proxy pattern** (anonymize → LLM → de-anonymize) is well-established. Multiple
projects implement it. None of them combine **(a) local LLM detection on MLX**,
**(b) reversible round-trip**, **(c) multi-agent support**, **and (d) resolution of
placeholders at the tool boundary** — the last is the open problem.

## Capability matrix

| Project | Stack | Stars | License | Multi-agent | Reversible | Local LLM | MLX | Tool-call resolution |
|---|---|---:|---|:-:|:-:|:-:|:-:|:-:|
| [DontFeedTheAI][dfta] | Python / FastAPI | 544 | MIT | ❌ Claude Code | ✅ | ✅ Ollama | ❌ | ❌ |
| [PasteGuard][pg] | TypeScript / Bun | 630 | Apache-2.0 | ✅ broadest | ❌ (per fetch) | ❌ Presidio | ❌ | ❌ |
| [contextio][ctx] | TypeScript | 24 | MIT | ✅ | ✅ | ❌ regex only | ❌ | ❌ |
| [LLM-Redactor][lr] | Go | 5 | (unclear) | partial | ❌ | ❌ | ❌ | ❌ |
| [claude-code-local][ccl] | Python / MLX | n/a | n/a | ❌ Claude Code | n/a — full local backend | ✅ (full model) | ✅ | n/a |
| [anonLLM][al] | Python lib | n/a | MIT | n/a — library | ✅ | ❌ | ❌ | n/a |
| [Microsoft Presidio][prs] | Python lib | many | MIT | n/a — library | ✅ via Decrypt op | ❌ | ❌ | n/a |
| [LiteLLM (Presidio guardrail)][lite] | Python proxy | many | MIT | ✅ (LLM-side) | ✅ | ❌ | ❌ | ❌ |
| [OpenMed (Nemotron Privacy Filter MLX)][om] | Python / MLX | n/a | n/a | n/a — library | ✅ | ✅ | ✅ | n/a |

[dfta]: https://github.com/zeroc00I/DontFeedTheAI
[pg]: https://github.com/sgasser/pasteguard
[ctx]: https://github.com/larsderidder/contextio
[lr]: https://github.com/WangYihang/llm-redactor
[ccl]: https://github.com/nicedreamzapp/claude-code-local
[al]: https://github.com/fsndzomga/anonLLM
[prs]: https://github.com/microsoft/presidio
[lite]: https://docs.litellm.ai/docs/proxy/guardrails/pii_masking_v2
[om]: https://openmed.life/docs/anonymization/

## Per-project assessment

### DontFeedTheAI — closest conceptual match
- **Architecture:** Python/FastAPI reverse-proxy, only for Claude Code today.
- **Detection:** Dual-layer — local **Ollama LLM** for prose-context PII (hostnames, org names,
  credentials in narrative) + regex for structured patterns (IPs, hashes, API keys).
- **Mapping:** Per-engagement vault, original → surrogate stored locally.
- **Unique:** `wizard.py improve` — fixtures run through the regex layer, leaks and
  false positives surface, pattern suggestions for upstream contribution. Self-improving.
- **Limits for our use case:** Pentest-flavored (categories DOMAIN, CREDENTIAL, TOKEN, HASH).
  Hard-wired to Claude Code. Ollama, not MLX. No tool-call resolution.
- **Verdict:** **Most fork-able candidate** if we want to inherit a working dual-layer pipeline.

### PasteGuard — most mature codebase, most tools
- **Architecture:** TypeScript/Bun + Hono + SQLite, local privacy proxy.
- **Coverage:** ChatGPT, Claude (web + Code), Cursor, Copilot, Windsurf, Gemini, Open WebUI,
  LibreChat. Browser-extension beta.
- **Detection:** Microsoft Presidio — 30+ data types, 24 languages, NER + pattern.
- **Limits:** Per fetched README, masking is **not reversible** in the proxy-LLM round-trip
  sense (verify before forking). No local generative LLM. No MLX. No tool-call resolution.
- **Verdict:** Best **breadth of agent support** to draw from; would need significant
  surgery to add MLX-LLM + reversible round-trip + tool-call resolution.

### contextio — cleanest proxy architecture
- **Architecture:** Local HTTP reverse-proxy on :4040, TypeScript, **zero npm deps** in core.
  Tools with base-URL override (Claude CLI, Pi, Gemini CLI, Aider) route directly;
  tools without (Codex, Copilot CLI, OpenCode) chain via mitmproxy.
- **Detection:** Regex with three presets (`secrets`, `pii`, `strict`).
- **Mapping:** Session-stable placeholders, reversible. SSE reconstruction works across
  Anthropic, OpenAI, Gemini streaming formats.
- **Limits:** Regex-only. No LLM. README admits "stable enough for daily use, not
  battle-tested for months in production." TypeScript stack — fine for the proxy plane,
  awkward for hosting MLX inference.
- **Verdict:** Best **architectural reference** for proxy-plane work. Likely fork-base if
  TypeScript is acceptable; otherwise study the mitmproxy chaining + SSE rebuild approach.

### LLM-Redactor — narrower, not a fit
- Go, secrets-focused (Gitleaks rules), non-reversible. Useful for inspiration on
  "exec wrapper" mode; less interesting otherwise.

### claude-code-local / Rapid-MLX / vllm-mlx — orthogonal approach
- These projects replace the cloud LLM with a local one entirely (privacy via locality, not
  via filtering). Different design point. Not competition; could be a complementary fallback
  for "this conversation is too sensitive to go to the cloud at all."

### Libraries (anonLLM, Presidio, LiteLLM, OpenMed)
- **Building blocks**, not products. Worth pulling in:
  - **Presidio** — for its mature reversible anonymizer/deanonymizer API, especially the
    `Decrypt` operator that survives the LLM rewriting text around placeholders.
  - **OpenMed / Nemotron Privacy Filter MLX** — already MLX-native, German-capable.
    Could be a drop-in detection backend; worth benchmarking against a generic Anonymizer-SLM.
  - **LiteLLM** — could sit *behind* our filter as the actual cloud-LLM proxy. Stacking is fine.
  - **anonLLM** — small, possibly OBE by Presidio; not worth a dependency.

## What's actually missing

1. **MLX-native filter that combines fast NER + small SLM** in the same proxy.
   OpenMed gives us the MLX detector; nobody has wrapped that in a multi-agent proxy.
2. **Multi-agent reversible**. Contextio has multi-agent + reversible but is regex-only.
   DontFeedTheAI has the LLM but is Claude-Code-only.
3. **Tool-call resolution.** When the agent's plan needs the real value (write `grep "max@firma.de"`,
   call an API, send a message), the placeholder needs to be resolved at the tool boundary —
   *not* surfaced back into the LLM's context. None of the surveyed projects address this;
   they all treat outgoing-to-LLM and incoming-from-LLM as the only crossings. For coding
   agents this is the **central** unsolved problem, because the agent *will* produce
   bash/code/API calls referencing PII.

## Decision implications

- **Don't from-scratch the proxy plane.** Either fork contextio (TS) or DontFeedTheAI
  (Python). Re-implementing SSE reconstruction across three streaming formats is
  weeks of work and contextio already has it working.
- **Do build the MLX detector + tool-call boundary as new components**, because nobody else
  has them. These are the differentiators.
- **Pick stack by detector, not by proxy.** If the MLX model lives in Python (which is the
  default for `mlx_lm`), the path of least resistance is Python proxy → DontFeedTheAI fork
  or an in-process FastAPI proxy + Presidio + custom MLX detector.
