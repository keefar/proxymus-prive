# Project memory — agent-privacy-filter

Quick-orient for any Claude session entering this repo. Read top to bottom before acting.

## What this is

A local privacy filter for coding agents (Claude Code, Cursor, Aider, …) — intercepts
outgoing traffic, detects PII via a small MLX-hosted model + deterministic detector,
swaps it for stable placeholders before it leaves the machine, restores originals in
incoming responses. **Target hardware:** M5 MacBook Air, 32 GB unified memory.

**Current status:** working PoC. FastAPI proxy (Anthropic Messages + OpenAI Chat
Completions, both streaming), MLX detector ensemble, vault round-trip, tool-call
boundary resolution — shipped with a green test suite. Past the research stage.

## Where to look first

1. **`README.md`** — vision, scope, non-goals
2. **`docs/HOW-IT-WORKS.md`** — user-facing pipeline walk-through + honest ledger of
   difficulties (resolved and open) with `apf-*` references. Best single overview of
   what the filter does and where it's weak.
3. **`docs/MODEL-EVALUATION.md`** — current dossier on the detector-model evaluation,
   recommended engine, tradeoffs, and what's still worth tuning. **Start here for the
   "where are we with the model layer" question.**
4. **`docs/sessions/`** — chronological session logs; latest one is always the best entry
   point for "what was decided and why"
5. **`docs/research/EXISTING-SOLUTIONS.md`** — survey of similar projects, capability matrix,
   identifies the actual gap this project addresses
6. **`docs/research/RESEARCH-NOTES.md`** — consolidated technical findings
7. **`docs/MODELS.md`** — candidate models + benchmark plan
8. **`docs/ARCHITECTURE.md`** — design options, open questions, decision log

**Code map gotcha:** the detector ensemble is `benchmarks/adapters_mlx.py`
(`EnsembleMaxAdapter`) — the proxy imports it from `benchmarks/`, not `apf/`.
Placeholders are `<REF_N>` / `<REF>`; the masking verbs are `mask` / `unmask`
(older issues and docs say "tokenize" — same operation, renamed in apf-ocq).

## Hard rules

1. **Tests must stay green.** `.venv/bin/python -m pytest apf/ benchmarks/` before
   committing changes to `apf/` or the detector — sub-second run, no excuse to skip.
   Detector-adapter tests live under `benchmarks/`; don't scope pytest to `apf/` alone.
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

## Verification & debug toolkit

- `.venv/bin/python -m pytest apf/` — unit tests
- `.venv/bin/python -m apf.demo --text "..."` — standalone tokenise → tool-call → restore (no proxy)
- `.venv/bin/python -m apf.manual_smoke` — in-process FastAPI smoke with fake upstream
- `.venv/bin/python -m scripts.smoke_loopback` — bulk test vs. a running proxy (incl. benign no-PII cases)
- `.venv/bin/python -m scripts.toolcall_loopback` — end-to-end tool-call boundary
  check; `record` mode = deterministic no-leak proof, `--mode live` = real model
- `.venv/bin/python -m scripts.cloud_toolcall --system {off,explainer}` — drives
  real Claude Code (`claude -p`) through apf; tool-call behaviour on the cloud target
- `scripts/apf_restart.sh [restart|stop|status]` — restart apf wired to a chosen
  OpenAI upstream (oMLX by default); lets a session restart the proxy itself
- **Cloud-test routing — BLOCKED for Max-plan auth (apf-dtq, 2026-05-21):** routing
  `claude -p` through apf to the real Anthropic API fails 100% with `429
  rate_limit_error` ("Server is temporarily limiting requests"). This is **not** a
  throttle and **not** burstiness — it is Anthropic policy (since ~April 2026):
  Pro/Max **subscription OAuth** tokens are refused for non-first-party use, and a
  proxy hop makes the request non-first-party (detected below the HTTP layer —
  forwarding all headers + query does not help). Direct `claude -p` works; via-apf
  does not. Cloud validation against real Claude needs an **Anthropic API key**
  (metered billing works through proxies) or an agent-side integration. For
  throttle-immune cloud-shaped validation use the **local oMLX rig**
  (`toolcall_loopback --mode live`). `ANTHROPIC_CUSTOM_HEADERS="x-apf-session: <id>"`
  still pins one vault if a working auth path exists.
- `.venv/bin/python -m benchmarks.run --adapter ensemble-max --fixtures <f>` — detector
  precision/recall/FP benchmark; result JSON lands in `benchmarks/results/` (gitignored)
- `curl 127.0.0.1:8765/healthz` — detector status + active sessions + upstream
- `curl 127.0.0.1:8765/v1/sessions/<id>/status` — vault counts (no originals leaked) — the diagnostic of choice when the upstream LLM has no request log
- **Unit-testing masking offline:** `proxy._DETECTOR` is set in the FastAPI lifespan — monkeypatch it with a span-returning stub (see `apf/skip_labels_test.py`) to test `_mask_text` without the MLX model.
- **Local-loopback gotcha:** `127.0.0.1` defaults to `POLICY_OFF` (no filtering) per `apf/endpoint_policy.py`. For local-test rigs override via `~/.config/apf/endpoints.toml` — see [`docs/INTEGRATION.md`](docs/INTEGRATION.md) "Local-loopback testing".

## Constraints

- Apple Silicon / MLX-first (PoC scope)
- Combined filter RAM ≤ 4 GB (so it can co-exist with the user's 35B-4bit daily driver)
- Stage-2 p95 latency ≤ 1.5 s
- Detection recall ≥ 0.95 in **both** German and English on the fixture set

## Key architectural premise

The differentiator is **tool-call boundary resolution** — when the agent's plan references
a masked value (`grep "<REF_3>"`), the proxy / agent harness must resolve the token
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
- Writing `bd --notes`/`--description` from Bash: **no backticks** in the string — the shell command-substitutes them and corrupts the note. Plain text only.

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
