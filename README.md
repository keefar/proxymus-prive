# agent-privacy-filter

**Status:** Early research / PoC scaffolding. **No working code yet.** This repo currently holds
research notes and architecture decisions; implementation begins after model benchmarking.

A local privacy filter for coding agents (Claude Code, Cursor, Aider, Codex, …) that detects
personal information in outgoing traffic, swaps it for stable placeholders before it leaves the
machine, and restores the original values in incoming responses. Detection runs on a small local
LLM via **MLX** on Apple Silicon, augmented by regex/NER for known-good patterns.

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
(4) is the differentiator.

[dfta]: https://github.com/zeroc00I/DontFeedTheAI
[pg]: https://github.com/sgasser/pasteguard
[ctx]: https://github.com/larsderidder/contextio

## Goals

- **PoC** — prove that an MLX-hosted small model (≤4B) plus a deterministic detector layer
  reaches usable quality and latency for in-path filtering
- **Daily driver** — usable as an HTTP proxy for at least Claude Code and one other agent
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
docs/
  research/
    EXISTING-SOLUTIONS.md     # what's already out there, and what it does / doesn't do
    RESEARCH-NOTES.md         # consolidated findings on PII filtering for LLM agents
  MODELS.md                   # candidate models for the MLX benchmark
  ARCHITECTURE.md             # design options and the open Tool-Call problem
```

## Next steps

1. Pick 2–3 candidate models from `docs/MODELS.md` and run a small benchmark
   (German+English PII coverage, latency, RAM footprint on M5/32GB).
2. Decide between **fork** (DontFeedTheAI / contextio / PasteGuard) and **from-scratch** —
   see `docs/ARCHITECTURE.md` for the option matrix.
3. Stand up a minimal HTTP proxy that runs at least one agent through the filter end-to-end.

## License

Undecided. MIT or Apache-2.0 are the two candidates if this reaches release.
