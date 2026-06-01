# Live integration guide

How to wire the PoC proxy into Claude Code (or any other Anthropic-API
client). After this setup, every request goes through the filter: PII is
masked before it leaves for the cloud and restored in the response,
Tier-C secrets stay opaque to the LLM and are re-inserted from the
local env / vault at the tool-call boundary.

## Prerequisites

- A host machine running **macOS (Apple Silicon)**, **Linux**, or
  **Windows** (WSL2 recommended). The production detector ensemble
  (regex + Presidio + GLiNER) runs on PyTorch (CPU / CUDA / MPS) and is
  cross-platform. The optional `ensemble-full` adapter uses MLX and
  requires Apple Silicon — it is auto-skipped on other platforms via
  pip environment markers in `requirements.txt`.
- Python 3.13 + a venv with the dependencies installed:
  ```bash
  python3.13 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  ```
- An authentication mechanism for the cloud API:
  - **API-key mode** (classic): set `ANTHROPIC_API_KEY` on the client.
    The proxy forwards the `x-api-key` header transparently.
  - **OAuth mode** (Pro/Max / Claude.ai login): Claude Code uses an
    OAuth token in the `Authorization` header. The proxy passes that
    through too. Caveat: not every client respects `ANTHROPIC_BASE_URL`
    during the OAuth flow — test before relying on it.

## Starting the proxy

```bash
# Default: port 8765, upstream api.anthropic.com
.venv/bin/python -m apf.proxy

# Custom port / upstream for testing
APF_PORT=9000 APF_UPSTREAM_BASE=http://localhost:8080 \
    .venv/bin/python -m apf.proxy
```

On first start the proxy loads every detector model (~10–15 s warmup),
then logs "Application startup complete".

Healthcheck:

```bash
curl http://127.0.0.1:8765/healthz
# {"status":"ok","detector":"ensemble-max","active_sessions":0,
#  "upstream":"https://api.anthropic.com"}
```

### Optional: generative detector stage (HTTP)

The default `ensemble-max` pipeline (regex + Presidio + GLiNER ×2 +
locked-category) handles explicit PII reliably but cannot catch
*implicit* / paraphrased PII (the colleague-from-Controlling-who-is-
getting-married case). A generative detector closes that gap. Instead
of running it in-process (the MLX-only `ensemble-full` route), apf can
delegate to any locally-running OpenAI-compatible daemon — **Ollama**,
**oMLX**, **LM Studio**, **llama.cpp-server**, **vLLM**, etc. — over
HTTP. Cross-platform; the daemon owns model download and lifecycle.

Opt in by creating `~/.config/apf/config.toml` (Windows: `%APPDATA%\apf\config.toml`;
override on any platform with the `APF_CONFIG_DIR` env var — apf-d6y):

```toml
[detector.generative_stage]
endpoint    = "http://127.0.0.1:11434/v1"     # Ollama default
model       = "qwen2.5:1.5b-instruct-q4_K_M"  # whatever your daemon serves
api_key_env = "DETECTOR_API_KEY"               # optional, env var name
timeout_s   = 30                               # optional, default 30
max_tokens  = 512                              # optional, default 512
```

Setting the section is the opt-in — no further flags needed. The proxy
adds the HTTP detector as an extra stage of the production ensemble.
Behaviour:

- **Startup**: the proxy refuses to come up if the daemon is unreachable
  or the model is wrong (hard-fail, so misconfig surfaces early).
- **Per request**: if the daemon times out or errors on a single turn,
  that stage returns no spans for the turn and a failure counter
  increments; the request still flows. Use it as a recall booster, not
  as a privacy-critical layer — Tier-A guarantees come from the
  deterministic detectors below it.

The same adapter is also available to the benchmark harness as
`openai-compat` — see `benchmarks/README.md` for the env-var contract
when benchmarking against a real daemon.

## Configuring Claude Code

```bash
# Terminal A: proxy running on 127.0.0.1:8765
# Terminal B: start Claude Code with the proxy as its API endpoint

export ANTHROPIC_BASE_URL=http://127.0.0.1:8765
export ANTHROPIC_API_KEY=<your-key>   # if you're in API-key mode
claude
```

If everything is wired correctly, Claude Code answers as usual, but:

- Every outgoing text with detected PII is masked (visible in the proxy
  logs when running with `--log-level debug`).
- The `x-apf-session` header is set on every response — Claude Code
  ignores it for now, but the vault state stays cleanly partitioned per
  session.
- Tool-use args are resolved back from the vault on the way to the
  client, so Claude Code's tool executor sees the real values.

## Smoke helper: manual end-to-end check

`apf/manual_smoke.py` boots the proxy, sends a test request with
PII-bearing content, and reports whether the masking made it through to
the upstream. You can point it at a mock upstream or, briefly, at a real
Anthropic endpoint.

```bash
# Against the mock upstream (default):
.venv/bin/python -m apf.manual_smoke

# Against the real Anthropic API (needs an API key):
ANTHROPIC_API_KEY=sk-ant-... \
APF_UPSTREAM_BASE=https://api.anthropic.com \
    .venv/bin/python -m apf.manual_smoke --live
```

## Local-loopback testing (Hermes + oMLX + apf, no cloud)

For PoC validation without any cloud dependency, the whole stack can be
wired together locally on Apple Silicon:

```
Hermes Agent (CLI) ──▶ apf:8765 ──▶ oMLX:8000 ──▶ MLX model
                                          │
                                          └── vault, detector, audit log
                                              stay inside apf
```

### Endpoint trust-map override (important)

By default apf classifies `127.0.0.1` as a **trusted local engine**
(`POLICY_OFF` — no filtering; rationale in `apf/endpoint_policy.py`).
That is the right default in production (local models don't need
masking), but **breaks the test use-case** — if you want to validate
against a local oMLX, you *want* apf to filter. Drop a config override:

```bash
mkdir -p ~/.config/apf
cat > ~/.config/apf/endpoints.toml << 'EOF'
[[endpoints]]
host = "127.0.0.1"
policy = "full"
EOF
```

The value is read at module import time, so **restart apf** after the
change. Verify: `/v1/sessions/<id>/status` shows a non-empty vault after
the first PII-bearing request.

### Starting apf for the loopback

```bash
APF_OPENAI_UPSTREAM=http://127.0.0.1:8000 \
    .venv/bin/python -m apf.proxy
```

### Hermes config (`~/.hermes/config.yaml`)

```yaml
model:
  provider: custom
  base_url: http://127.0.0.1:8765/v1   # apf, NOT oMLX directly
  api_key: irrelevant-but-required
  model: <exact model ID as oMLX returns it under /v1/models>
  max_tokens: 4096
```

Heads-up: `hermes model` (the interactive picker) overwrites `base_url`
with the direct upstream. If you use it, follow up with
`hermes config set model.base_url http://127.0.0.1:8765/v1`.

### Bulk smoke

`scripts/smoke_loopback.py` sends 14 curated single-turn requests
through apf (DE + EN, all three tiers, plus a negative case), reads the
vault state per session, and reports whether the expected detector
labels showed up and whether the model returned a safety refusal.

```bash
.venv/bin/python -m scripts.smoke_loopback             # everything
.venv/bin/python -m scripts.smoke_loopback --grep tier_c
.venv/bin/python -m scripts.smoke_loopback --json      # JSONL output
```

Expected output on the first successful run against
Qwen2.5-Coder-7B-Instruct-MLX-4bit: 14/14 vault assertions ✓, 13/14
model refusals (Qwen-specific safety behaviour — see bd `apf-6l8`).

## Known constraints

- **Auth pass-through:** the proxy stores no credentials. Whatever the
  client sends is forwarded. If the client uses OAuth, it works
  automatically — provided the client respects `ANTHROPIC_BASE_URL`.

- **OAuth refresh:** if the client refreshes its OAuth token before
  sending (e.g. Claude Code's internal auth flow), that happens *before*
  the proxy. The proxy only ever sees the final token in the
  `Authorization` header.

- **Streaming:** fully supported since `apf-jfi`. Text tokens are
  buffered across chunk boundaries; tool-use input JSON is accumulated
  and resolved in one shot at the `content_block_stop` event.

- **Pro/Max subscription:** if you use Claude Code via the Pro/Max
  login (no explicit API key), the client probably uses OAuth. Whether
  that cooperates with `ANTHROPIC_BASE_URL` depends on the exact Claude
  Code build. Test it.

- **Secret store:** the default is `EnvSecretStore` +
  `VaultFallbackStore`. For production hardening, set
  `APF_VAULT_FALLBACK=0` — unknown secrets at tool-use time will no
  longer be resolved from the vault but stay unset (the tool must fail
  explicitly rather than receive a value the vault has happened to see).

- **System-prompt masking (apf-lnr):** default is OFF — `role=system`
  messages (Anthropic's `system` field + OpenAI `messages[0]` with
  `role=system`) are **not** masked. Rationale: control-plane prompts
  (filter explainer, agent persona, tool schemas) are usually PII-free
  and would otherwise show up as a false-positive baseline in every
  vault summary. If your system prompt legitimately contains user PII
  (e.g. user-profile-fed agents), set `APF_MASK_SYSTEM=1` and masking
  runs on system messages too. Locked-category refusal (apf-enr) checks
  system messages **regardless** of the flag — the safety net for
  never-forward categories stays active either way.

- **Unmasker marker (apf-b3j, debug):** `APF_UNMASK_MARKER` appends a
  marker to every value the unmasker actually resolved back —
  `APF_UNMASK_MARKER=✓` turns "anna müller" into "anna müller✓". This
  lets you tell whether the round-trip really happened or whether a
  value just slipped through unmasked (visually identical otherwise).
  Test/debug only — **never in production** (it changes user-visible
  text). Default empty = output unchanged. Applies only on the text
  path, not in the tool-call resolver.

- **Skip labels (apf-1f6):** `APF_SKIP_LABELS` is a comma-separated
  list of detector labels that are detected but **not** masked — the
  value passes through verbatim. Default: `ORG`. Rationale: in the
  coding-agent context, ORG mentions are almost always public software
  / services (GitHub, Stripe, OpenAI) — masking buys ~zero privacy and
  wrecks the prompt (`<REF_N>` API client instead of `Stripe` API
  client). Genuinely sensitive org references (employer, asylum-/
  violence-related orgs) are covered by other labels or the
  locked-category list. `APF_SKIP_LABELS=` (empty) masks everything
  including ORG; `APF_SKIP_LABELS=ORG,DATE` extends the list.

## Troubleshooting

- **"Connection refused" on the client:** proxy isn't running, or the
  port doesn't match. Test with
  `curl http://127.0.0.1:8765/healthz`.
- **"401 Unauthorized" from the upstream:** API key missing or wrong.
  The proxy itself holds no key — it just forwards the client header.
- **PII slips through unmasked:** the detector missed it.
  `GET /v1/sessions/{id}/uncertain` shows what was tagged as
  low-confidence. For clean misses: run the benchmark against the
  fixtures (`benchmarks/run.py`) and extend the Tier-C regex / GLiNER
  labels as needed.
- **Tool use fails because secrets are missing:** the env-var name has
  to match the pattern the detector recognised (`OPENAI_API_KEY`,
  `STRIPE_KEY`, etc.). If the detector sees a different KEY name, use
  `EnvSecretStore(aliases={"DETECTED_NAME": "REAL_ENV_VAR"})`.

## Pro/Max — concrete instructions

If you use `claude.ai/code` via a Pro/Max account:

1. Pro/Max login is OAuth-based, no API key.
2. The CLI should still accept `ANTHROPIC_BASE_URL` — Claude Code
   converts OAuth into `Authorization: Bearer ...`, which our proxy
   forwards.
3. If Claude Code refuses to accept a different `ANTHROPIC_BASE_URL`
   because the cloud-login domain has to match: either file an issue on
   the Claude Code project, or fall back to API-key mode.
