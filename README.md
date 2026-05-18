# agent-privacy-filter

**Status (2026-05-18):** PoC end-to-end. FastAPI proxy speaks Anthropic
Messages **and** OpenAI Chat Completions, SSE streaming wired, opaque
`<SENSITIVE_N>` tokenisation with stable per-session IDs, secret resolver
hook at the tool-call boundary, regex+GLiNER+Nemotron ensemble detector,
endpoint trust map, off-by-default audit-log scaffold. 14 tests, all
green in 0.21 s (`.venv/bin/python -m pytest apf/`). Smoke runner spins
the proxy in-process (`.venv/bin/python -m apf.manual_smoke`).

What still needs work: daily-driver validation in a real agent (target:
Claude Code, with [Hermes](https://hermes-agent.nousresearch.com/) +
[oMLX](https://omlx.ai/) as the all-local test substrate),
local-only-category routing ([apf-sgz](../../#)), audit-log persistence
([apf-x1t](../../#)), and the implicit-PII UX confirmation flag from
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

A local privacy filter for coding agents (Claude Code, Cursor, Aider, Codex,
Hermes, …) that detects personal information in outgoing traffic, swaps it
for stable placeholders before it leaves the machine, and restores the
original values in incoming responses. Detection runs on a small local
LLM via **MLX** on Apple Silicon, augmented by regex/NER for known-good
patterns.

## Why another one?

Similar projects exist (see [`docs/research/EXISTING-SOLUTIONS.md`](docs/research/EXISTING-SOLUTIONS.md)).
None of them combine all four of the things this project is exploring:

1. **Local LLM on Apple Silicon (MLX-native)** for context-aware PII detection
   — beyond regex, beyond Presidio's classical NER
2. **Reversible** round-trip (anonymize → LLM → de-anonymize)
3. **Multi-agent** (not tied to one tool)
4. **Tool-call resolution at the tool boundary** — the open problem nobody has solved:
   when the agent needs the *real* value to execute a tool (grep, db query, send email),
   the placeholder must be resolved *only* at that boundary, never inside the LLM context

(1)–(3) are already done in pieces by [DontFeedTheAI][dfta], [PasteGuard][pg], and [contextio][ctx].
(4) is the differentiator and is implemented in this repo via
[`apf/resolver.py`](apf/resolver.py) +
[`apf/secrets.py`](apf/secrets.py).

[dfta]: https://github.com/zeroc00I/DontFeedTheAI
[pg]: https://github.com/sgasser/pasteguard
[ctx]: https://github.com/larsderidder/contextio

## Goals

- **PoC** — prove that an MLX-hosted small model (≤4B) plus a deterministic
  detector layer reaches usable quality and latency for in-path filtering
  → **engine decision made** ([`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md))
- **Daily driver** — usable as an HTTP proxy for at least Claude Code and one
  other agent → proxy ships, daily-driver validation pending
- **Open-source release** — if the PoC validates the approach

## Non-goals (for now)

- Replacing the cloud LLM (this is a *filter*, not a local-inference proxy — see
  [claude-code-local][ccl] / [Rapid-MLX][rm] for that)
- Compliance certification (HIPAA, GDPR audit) — useful direction later, not PoC concern
- Windows / Linux first-class support — Apple Silicon / MLX is the PoC target

[ccl]: https://github.com/nicedreamzapp/claude-code-local
[rm]: https://github.com/raullenchai/Rapid-MLX

## Target hardware (PoC)

M5 MacBook Air, 32 GB unified memory. The filter runs alongside the user's existing local
assistant; combined memory budget for filter models is ≤ 4 GB.

## Layout

```
apf/                          # filter runtime
  proxy.py                    # FastAPI: /v1/messages (Anthropic) + /v1/chat/completions (OpenAI)
  tokenizer.py / detokenizer.py
  vault.py                    # per-session vault, stable <SENSITIVE_N> IDs
  resolver.py + secrets.py    # tool-call-boundary resolution (the differentiator)
  sse.py / openai_shape.py    # streaming + OpenAI shape adapter
  endpoint_policy.py          # trust map (loopback + mDNS + cloud APIs)
  audit_log.py                # off-by-default in-memory ring buffer
  local_only.py               # never-forward refusal pathway (v1)
  demo.py / manual_smoke.py   # standalone + in-process smoke runners
  *_test.py                   # 14 pytest tests
benchmarks/                   # detector benchmark harness + 30 result files
fixtures/                     # PII fixtures (DE+EN, public + private)
tools/                        # ai4privacy corpus builders
scripts/                      # over-filter eval + dfta upstream check
docs/
  ARCHITECTURE.md             # design + decision log
  MODELS.md                   # candidate models for the MLX detector
  MODEL-EVALUATION.md         # current dossier on the detector layer
  THREAT-MODEL-PRIVATE.md     # private-person taxonomy (79 rows) + §5 decisions
  INDIVIDUAL-PRIVACY-FAILURES.md
  COVERAGE-AUDIT.md
  OVER-FILTER-EVAL.md
  INTEGRATION.md              # how-to: wire an agent through apf
  research/EXISTING-SOLUTIONS.md
  research/RESEARCH-NOTES.md
  sessions/                   # chronological work logs
```

## Running

```bash
# tests (14, ~0.2 s)
.venv/bin/python -m pytest apf/

# standalone demo: detector → tokenize → simulated round-trip → restore
.venv/bin/python -m apf.demo

# in-process smoke: spins the FastAPI proxy in-process with a fake upstream
.venv/bin/python -m apf.manual_smoke

# live smoke: sends to real Anthropic API
.venv/bin/python -m apf.manual_smoke --live --model claude-haiku-4-5
```

## Next steps

1. **Daily-driver validation** — run a real coding agent through apf with a
   realistic workload, measure over-filter rate against the
   [over-filter-eval methodology](docs/OVER-FILTER-EVAL.md). Target stack
   for local loopback: Hermes (NousResearch) → apf → oMLX (Apple Silicon
   MLX inference server) — no cloud dependency, full proxy + filter
   visibility. See [`docs/sessions/`](docs/sessions/) for the test plan.
2. **Local-only routing** ([apf-sgz](../../#)) — design the never-forward
   pathway for asylum / abuse / whistleblower / undocumented-immigration
   categories. Needs concrete scenario evaluation (~5–10 fixture-corpus
   examples) before any code.
3. **Audit log v2** ([apf-x1t](../../#)) — disk persistence + Keychain
   encryption + retention policy for the v1 in-memory scaffold.

## License

Undecided. MIT or Apache-2.0 are the two candidates if this reaches release.
