# Project memory — agent-privacy-filter

Quick-orient for any Claude session entering this repo. Read top to bottom before acting.

## What this is

A local privacy filter for coding agents (Claude Code, Cursor, Aider, …) — intercepts
outgoing traffic, detects PII via a small MLX-hosted model + deterministic detector,
swaps it for stable placeholders before it leaves the machine, restores originals in
incoming responses. **Target hardware:** M5 MacBook Air, 32 GB unified memory.

**Current status:** research + scaffolding only. No code yet. The first technical task is
a model benchmark — see `docs/MODELS.md`.

## Where to look first

1. **`README.md`** — vision, scope, non-goals
2. **`docs/MODEL-EVALUATION.md`** — current dossier on the detector-model evaluation,
   recommended engine, tradeoffs, and what's still worth tuning. **Start here for the
   "where are we with the model layer" question.**
3. **`docs/sessions/`** — chronological session logs; latest one is always the best entry
   point for "what was decided and why"
4. **`docs/research/EXISTING-SOLUTIONS.md`** — survey of similar projects, capability matrix,
   identifies the actual gap this project addresses
5. **`docs/research/RESEARCH-NOTES.md`** — consolidated technical findings
6. **`docs/MODELS.md`** — candidate models + benchmark plan
7. **`docs/ARCHITECTURE.md`** — design options, open questions, decision log

## Hard rules

1. **No code until the model benchmark completes.** The PoC's whole point is to retire two
   unknowns first (does an MLX SLM detect German+English PII well enough? does tool-call
   resolution work?). Writing proxy code before those are answered is premature.
2. **Always re-check model versions via WebSearch before recommending an install command.**
   The HF / vendor pages move; the model names and quantization formats listed in
   `docs/MODELS.md` are direction, not a shopping cart.
3. **PII detection runs locally. Period.** No sending text to a cloud service to "help detect
   PII" — that defeats the entire project.
4. **Don't commit fixtures with real PII** — even pseudo-real test data lives in
   `fixtures/private/` (gitignored). Synthesized / clearly fake fixtures go in `fixtures/`
   and can be committed.
5. **Reversibility is a hard requirement.** Any solution that masks-without-restore is
   off-spec — agent responses must be readable to the user with originals intact.

## Constraints

- Apple Silicon / MLX-first (PoC scope)
- Combined filter RAM ≤ 4 GB (so it can co-exist with the user's 35B-4bit daily driver)
- Stage-2 p95 latency ≤ 1.5 s
- Detection recall ≥ 0.95 in **both** German and English on the fixture set

## Key architectural premise

The differentiator is **tool-call boundary resolution** — when the agent's plan references
a tokenized value (`grep "<EMAIL_3>"`), the proxy / agent harness must resolve the token
only at the moment of tool execution, never surface the resolved value back into the LLM
context. This is the piece nobody else solves and the reason this project is worth building
instead of using an existing solution.

## When in doubt

- The latest `docs/sessions/*.md` log explains the *why* behind any given decision in
  `ARCHITECTURE.md`. Read it before challenging a design choice.
- The recommendation in `ARCHITECTURE.md` (from-scratch for PoC) is **subject to PoC
  validation** — not a permanent commitment. The decision log at the bottom of that file
  is empty on purpose; first entry will be after the benchmark.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
