# agent-privacy-filter

**Status (2026-05-24):** working PoC, end-to-end. FastAPI proxy speaks
Anthropic Messages **and** OpenAI Chat Completions, SSE streaming wired,
opaque `<REF_N>` (or per-model surrogate) masking with stable per-session
IDs, secret resolver hook at the tool-call boundary, a regex + Presidio +
GLiNER ensemble detector, endpoint trust map, off-by-default audit-log
scaffold. 279 tests, all green (`.venv/bin/python -m pytest apf/
benchmarks/`). Smoke runner spins the proxy in-process
(`.venv/bin/python -m apf.manual_smoke`).

What still needs work: detector precision tuning (`PERSON` false
positives), audit-log persistence, and the implicit-PII UX confirmation
flag. Daily-driver validation through a real agent is done —
[Hermes](https://hermes-agent.nousresearch.com/) → apf →
[oMLX](https://omlx.ai/), end to end.
[`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md) §9 has the honest
open-issues list.

A local privacy filter for coding agents (Claude Code, Cursor, Aider, Codex,
Hermes, …) that detects personal information in outgoing traffic, swaps it
for stable placeholders before it leaves the machine, and restores the
original values in incoming responses. Detection runs entirely on the
local machine — an ensemble of regex, Microsoft Presidio, and GLiNER NER
models on Apple Silicon. No text is sent anywhere for detection.

**New here?** [`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md) walks the pipeline
end to end and gives an honest ledger of what was hard to build and what is
still unsolved.

> **Agent support, honestly:** the HTTP proxy works today for
> OpenAI-compatible and local agents — Hermes, Cursor, Aider, Codex, Cline,
> local models. Routing **Claude Code on a Free/Pro/Max subscription** is
> currently **blocked by Anthropic's subscription-auth policy** (it refuses
> proxied subscription OAuth) — see the 2026-05-22 entry in
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The Claude path stays in
> the tree, ready to re-enable if that policy changes.

## Why another one?

Similar projects exist (see [`docs/research/EXISTING-SOLUTIONS.md`](docs/research/EXISTING-SOLUTIONS.md)).
None of them combine all four of the things this project is exploring:

1. **Local NER models on Apple Silicon** for context-aware PII detection
   — beyond plain regex, adding zero-shot GLiNER for paraphrased / implicit PII
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
- **Daily driver** — usable as an HTTP proxy for Hermes and the
  OpenAI-compatible agent ecosystem → proxy ships, validation Hermes-first
  (the Claude Code path is blocked upstream — see `docs/ARCHITECTURE.md`)
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
  masker.py / unmasker.py     # mask PII → placeholders, restore originals
  vault.py                    # per-session vault, stable <REF_N> IDs
  resolver.py + secrets.py    # tool-call-boundary resolution (the differentiator)
  surrogates.py               # opt-in plausible-fake substitution (apf-okt)
  model_profiles.py           # per-model token-handling profiles (apf-qnl)
  explainer.py                # system-prompt note explaining <REF_N> to the model
  sse.py / openai_shape.py    # streaming + OpenAI shape adapter
  endpoint_policy.py          # trust map (loopback + mDNS + cloud APIs)
  audit_log.py                # off-by-default in-memory ring buffer
  local_only.py               # never-forward refusal pathway (v1)
  demo.py / manual_smoke.py   # standalone + in-process smoke runners
  *_test.py                   # pytest suite (225 tests, run with benchmarks/)
benchmarks/                   # detector adapters, benchmark + model-conformance harness
model_profiles/               # shipped per-model token-handling profiles (TOML, apf-qnl)
fixtures/                     # PII fixtures (DE+EN, public + private)
tools/                        # ai4privacy corpus builders
scripts/                      # over-filter eval + dfta upstream check
docs/
  HOW-IT-WORKS.md             # pipeline walk-through + honest difficulties ledger
  ARCHITECTURE.md             # design + decision log
  MODELS.md                   # candidate models for the MLX detector
  MODEL-PROFILES.md           # contributing a profile for your upstream model
  OVER-FILTER-EVAL.md         # precision/utility evaluation methodology
  INTEGRATION.md              # how-to: wire an agent through apf
  research/EXISTING-SOLUTIONS.md
  research/INDIVIDUAL-PRIVACY-FRAMEWORKS.md
  research/RESEARCH-NOTES.md
```

(Detailed evaluation dossiers, threat-model notes, and chronological
session logs are kept locally rather than in the public repo.)

## Running

```bash
# one-time setup (Python 3.13, Apple Silicon)
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

# tests (279, sub-second)
.venv/bin/python -m pytest apf/ benchmarks/

# standalone demo: detector → mask → simulated round-trip → restore
.venv/bin/python -m apf.demo

# in-process smoke: spins the FastAPI proxy in-process with a fake upstream
.venv/bin/python -m apf.manual_smoke

# live smoke: sends to real Anthropic API
.venv/bin/python -m apf.manual_smoke --live --model claude-haiku-4-5
```

## Next steps

1. **Detector precision tuning** — `PERSON` false positives are the
   largest remaining lever; see [`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md) §8.
2. **Audit log v2** — disk persistence + Keychain encryption + retention
   policy for the v1 in-memory scaffold.
3. **Grow the model-profile registry** — community-contributed per-model
   profiles via the conformance harness (`benchmarks/model_conformance.py`).

## License

[MIT](LICENSE).
