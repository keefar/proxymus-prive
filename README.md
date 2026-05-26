# proxymus-prive

proxymus-prive is a local privacy filter for coding agents — Claude
Code, Cursor, Aider, Codex, Hermes, and similar tools. It runs as a
small proxy on your own machine and sits between the agent and the
cloud LLM. Every outgoing request is inspected for personal
information — names, addresses, file paths, API keys — and the
sensitive bits are replaced with stable placeholders *before* the
request leaves your machine. The cloud model only ever sees the
placeholders; in the reply that comes back, the originals are put back
in so you read your conversation normally. When the agent decides to
run a tool (`grep`, a file read, an API call), the real value is
plugged in only at that moment, so the cloud model never sees it
through a back door either.

Detection runs entirely on your machine — a small ensemble of regex,
Microsoft Presidio, and GLiNER NER models on Apple Silicon. No text is
ever sent anywhere for detection.

> **Claude Code is currently API-key only.** You can route Claude
> Code through proxymus when it authenticates with an
> `ANTHROPIC_API_KEY` (the standard metered-billing path). It does
> **not** work with a Pro/Max subscription login: Anthropic refuses
> proxied subscription OAuth — see the 2026-05-22 entry in the
> [decision log of `docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for
> the full reason. OpenAI-compatible agents (Hermes, Cursor, Aider,
> Codex, Cline) are unaffected.

## Hardware requirements

Apple Silicon Mac (M1 or newer) is the primary development target.
Linux is supported via the same `pip install -r requirements.txt` —
the production detector ensemble runs on PyTorch (CPU / CUDA / MPS).
Windows is untested in CI but should work the same way; WSL2 is the
pragmatic path. Pick the detector ensemble that fits your machine —
switch by setting the adapter when running the proxy:

| Ensemble                   | Resident | What it adds                                                                              | Platforms        |
|----------------------------|---------:|-------------------------------------------------------------------------------------------|------------------|
| `ensemble-fast`            |  ~600 MB | regex + GLiNER multi-PII                                                                  | macOS, Linux, Windows |
| `ensemble-max` *(default)* |  ~1.5 GB | + Presidio + a second GLiNER + locked-category regex                                      | macOS, Linux, Windows |
| `ensemble-full`            |    ~3 GB | + AnonymizerSLM 1.7 B (4-bit, MLX) — generative pass for implicit / paraphrased PII       | Apple Silicon only |

Even at the full ensemble the filter stays **≤ 4 GB** resident, so an
8 GB Mac runs the fast and default ensembles comfortably while the
machine is otherwise in normal use.

`mlx` and `mlx-lm` are listed in `requirements.txt` with pip
environment markers (`sys_platform == "darwin" and platform_machine ==
"arm64"`), so they install automatically on Apple Silicon and are
skipped silently elsewhere — Linux / Windows installs succeed without
manual flag handling.

**New here?** [`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md) walks the
pipeline end to end and gives an honest ledger of what was hard to build
and what is still unsolved.

**Status (2026-05-24):** working PoC, end-to-end. FastAPI proxy speaks
Anthropic Messages **and** OpenAI Chat Completions, SSE streaming wired,
opaque `<REF_N>` (or per-model surrogate) masking with stable per-session
IDs, secret resolver hook at the tool-call boundary, a regex + Presidio +
GLiNER ensemble detector, endpoint trust map, off-by-default audit-log
scaffold. 281 tests, all green (`.venv/bin/python -m pytest apf/
benchmarks/`). Smoke runner spins the proxy in-process
(`.venv/bin/python -m apf.manual_smoke`).

What still needs work: detector precision tuning (`PERSON` false
positives), audit-log persistence, and the implicit-PII UX confirmation
flag. End-to-end agent validation through
[Hermes](https://hermes-agent.nousresearch.com/) is done.
[`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md) §9 has the honest
open-issues list.

## Why another one?

Similar projects exist (see [`docs/research/EXISTING-SOLUTIONS.md`](docs/research/EXISTING-SOLUTIONS.md)).
None of them combine all four of the things this project is exploring:

1. **Local NER models** for context-aware PII detection — beyond plain
   regex, adding zero-shot GLiNER for paraphrased / implicit PII
   (runs on Apple Silicon, Linux, Windows — see hardware section)
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
- Windows native CI / packaging — works via WSL2; Apple Silicon and Linux are
  the actively tested platforms

[ccl]: https://github.com/nicedreamzapp/claude-code-local
[rm]: https://github.com/raullenchai/Rapid-MLX

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
# one-time setup (Python 3.13; macOS / Linux / Windows)
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

# tests (281, sub-second)
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
