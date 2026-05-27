# Project memory — proxymus-prive

Quick-orient for any Claude session entering this repo. Read top to bottom before acting.

## What this is

A local privacy filter for coding agents (Claude Code, Cursor, Aider, …) — intercepts
outgoing traffic, detects PII via a deterministic regex layer plus PyTorch-hosted
NER models (Presidio + GLiNER); on Apple Silicon an optional MLX generative pass
(`ensemble-full`) joins the ensemble. Originals restored in incoming responses.
**Target hardware:** Apple Silicon Mac (primary), Linux (supported — `mlx`
pip-markered out, GLiNER+Presidio path is platform-neutral), Windows via WSL2
(untested in CI; native Windows nice-to-have). Filter footprint stays ≤ 4 GB so it
co-exists with a separate local LLM. The README hardware-requirements table is
authoritative.

**Current status:** working PoC. FastAPI proxy (Anthropic Messages + OpenAI Chat
Completions, both streaming), PyTorch-hosted detector ensemble (regex + Presidio +
GLiNER; MLX generative pass optional on Apple Silicon), vault round-trip, tool-call
boundary resolution — shipped with a green test suite. Past the research stage.

**Delivery constraint (apf-dtq, 2026-05-22):** routing some hosted-agent
subscription tokens through apf is currently not viable — those tokens are
verified against direct-from-vendor request patterns and refuse proxied OAuth.
First agent target is therefore **Hermes + OpenAI-compatible** agents; the
hosted-agent path stays in-tree, marked, re-enableable. The proxy and the
whole filter are unaffected for OpenAI-compatible / local upstreams.

## Where to look first

1. **`README.md`** — vision, scope, non-goals
2. **`docs/HOW-IT-WORKS.md`** — user-facing pipeline walk-through + honest ledger of
   difficulties (resolved and open) with `apf-*` references. Best single overview of
   what the filter does and where it's weak.
3. **`docs/research/EXISTING-SOLUTIONS.md`** — survey of similar projects, capability matrix,
   identifies the actual gap this project addresses
4. **`docs/research/RESEARCH-NOTES.md`** — consolidated technical findings
5. **`docs/MODELS.md`** — candidate models + benchmark plan
6. **`docs/MODEL-PROFILES.md`** — model-profile contract + how to contribute a profile
7. **`docs/OVER-FILTER-EVAL.md`** — methodology for the precision/utility trade-off
8. **`docs/ARCHITECTURE.md`** — design options, open questions, decision log
9. **`docs/INTEGRATION.md`** — wiring the proxy into client tools

Detailed evaluation dossiers, session logs, and per-issue decision narratives
live outside the public repo (kept locally; see `.gitignore` for the list).

**Code map gotcha:** the detector ensemble is `benchmarks/adapters_mlx.py`
(`EnsembleMaxAdapter`) — the proxy imports it from `benchmarks/`, not `apf/`.
Placeholders are `<REF_N>` / `<REF>`; the masking verbs are `mask` / `unmask`
(older issues and docs say "tokenize" — same operation, renamed in apf-ocq).
The proxy's `_DETECTOR` is built by `apf/detector_stage.build_proxy_detector()`
(apf-yyz), not instantiated directly — without opt-in config that returns the
bare EnsembleMax, with `[detector.generative_stage]` set it returns a
`CompositeDetector(EnsembleMax + SoftDegradeWrapper(http))`.

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
- `.venv/bin/python -m apf.proxy_test` — end-to-end proxy test (round-trip,
  masking, tool-call resolution, OpenAI path). A script-test — **not**
  pytest-collected, so the `pytest` gate misses it; run it too when changing the proxy.
- `.venv/bin/python -m apf.demo --text "..."` — standalone tokenise → tool-call → restore (no proxy)
- `.venv/bin/python -m apf.manual_smoke` — in-process FastAPI smoke with fake upstream
- `.venv/bin/python -m scripts.smoke_loopback` — bulk test vs. a running proxy (incl. benign no-PII cases)
- `.venv/bin/python -m scripts.toolcall_loopback` — end-to-end tool-call boundary
  check; `record` mode = deterministic no-leak proof, `--mode live` = real model
- `.venv/bin/python -m scripts.cloud_toolcall --system {off,explainer}` — drives
  real Claude Code (`claude -p`) through apf; tool-call behaviour on the cloud target
- `scripts/apf_restart.sh [restart|stop|status]` — restart apf wired to a chosen
  OpenAI upstream (oMLX by default); lets a session restart the proxy itself
- **Cloud-test routing — note on hosted-agent subscription auth (apf-dtq):**
  hosted-agent subscription tokens (the kind issued to an agent's first-party
  client) may be rejected when proxied — they're verified against direct-from-
  vendor request patterns. Cloud validation against such an endpoint needs a
  metered API key instead (those work through proxies) or an agent-side
  integration. For throttle-immune cloud-shaped validation use the **local
  oMLX rig** (`toolcall_loopback --mode live`). `ANTHROPIC_CUSTOM_HEADERS=
  "x-apf-session: <id>"` still pins one vault if a working auth path exists.
- `.venv/bin/python -m benchmarks.run --adapter ensemble-max --fixtures <f>` — detector
  precision/recall/FP benchmark; result JSON lands in `benchmarks/results/` (gitignored)
- `curl 127.0.0.1:8765/healthz` — detector status + active sessions + upstream
- `curl 127.0.0.1:8765/v1/sessions/<id>/status` — vault counts (no originals leaked) — the diagnostic of choice when the upstream LLM has no request log
- **Unit-testing masking offline:** `proxy._DETECTOR` is set in the FastAPI lifespan — monkeypatch it with a span-returning stub (see `apf/skip_labels_test.py`) to test `_mask_text` without the MLX model. For proxy HTTP-path tests (streaming, error propagation), also patch `proxy.httpx.AsyncClient` and use `TestClient` *without* its context manager (skips the lifespan/MLX load) — see `apf/stream_error_test.py`.
- **Local-loopback gotcha:** `127.0.0.1` defaults to `POLICY_OFF` (no filtering) per `apf/endpoint_policy.py`. For local-test rigs override via `~/.config/apf/endpoints.toml` — see [`docs/INTEGRATION.md`](docs/INTEGRATION.md) "Local-loopback testing".
- **Optional generative HTTP stage:** `[detector.generative_stage]` in `~/.config/apf/config.toml` (env-override via `APF_CONFIG`) opts into an external OpenAI-compat detector (Ollama / oMLX / LM Studio / vLLM) on top of EnsembleMax. Failure semantics: warmup hard-fails, per-detect soft-degrades with counter on the wrapper. See `apf/detector_config.py` + `apf/detector_stage.py` (apf-yyz).

## Constraints

- Apple Silicon primary; Linux supported (mlx pip-markered out, GLiNER+Presidio+regex
  path runs on PyTorch CPU/CUDA/MPS); Windows via WSL2 (untested in CI)
- Combined filter RAM ≤ 4 GB (small enough to leave headroom on an 8 GB host)
- Stage-2 p95 latency ≤ 1.5 s
- Detection recall: realistically **~0.75–0.82** tier-equality on the fixture set
  (no German/English gap). The earlier "≥ 0.95" figure was aspirational — span-NER
  tops out here; implicit / paraphrased PII needs a generative detector. **Not** a
  release gate ("the system can only be as good as it is" — user, 2026-05-22).
  See `apf-1oy` for the differentiated analysis and follow-on tuning beads.

## Key architectural premise

The differentiator is **tool-call boundary resolution** — when the agent's plan references
a masked value (`grep "<REF_3>"`), the proxy / agent harness must resolve the token
only at the moment of tool execution, never surface the resolved value back into the LLM
context. This is the piece nobody else solves and the reason this project is worth building
instead of using an existing solution.

## When in doubt

- The recommendation in `ARCHITECTURE.md` (from-scratch for PoC) is **subject to PoC
  validation** — not a permanent commitment. The decision log at the bottom of that file
  is empty on purpose; first entry will be after the benchmark.
- `bd show <apf-id>` is the in-repo source of why-decisions for tracked issues. Per-decision
  narrative beyond the bd notes lives outside the public repo (see `.gitignore`).


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
- `bd dep add <task> <epic>` fails — only task→task dependencies allowed. Reference the epic in the task's description/notes instead, and use `bd update <epic> --notes "…subtask apf-XXX…"` to keep the epic's child list current.

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
