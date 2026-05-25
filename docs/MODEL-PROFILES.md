# Model profiles — contributing a profile for your model

`apf` masks PII before it leaves your machine. It can do this two ways:

- **opaque** — replace the value with an `<REF_N>` placeholder (the default);
- **surrogate** — replace it with a plausible fake value of the same kind.

Which one works best depends on the **upstream model**. A small model often
*mangles* opaque tokens — renumbers them, drops the underscore, paraphrases
them — which breaks the round-trip restore (apf-2qz). A strong model keeps
them verbatim. Separately, dense clusters of opaque tokens can trip a capable
model's prompt-injection defences and make it decline the request (apf-76s).

apf cannot test every model. The **model profile registry** is how that
knowledge is shared: a small declarative file per model that records how that
model behaves. We ship profiles for the models we have evidence for; the
community fills in the rest.

> Scope note: this registry is the *data layer*. As of apf-ao2 it is not yet
> consulted by the proxy when it picks a masking strategy — that wiring is
> tracked separately (apf-dkf). Adding a profile now means it is ready the
> moment that lands.

## Profile format

A profile is a TOML `[[models]]` table:

```toml
[[models]]
model = "Your-Model-Id-Exactly-As-Sent"
token_passthrough = "verbatim"        # verbatim | mangles | unknown
recommended_strategy = "opaque"       # opaque | surrogate
injection_sensitivity = "low"         # low | high
notes = "How you tested this and what you saw."
```

### Fields

| Field | Values | Meaning |
|---|---|---|
| `model` | string | The model id **exactly as it appears** in the `model` field of the outgoing OpenAI/Anthropic request. This is the lookup key — it must match byte-for-byte. |
| `token_passthrough` | `verbatim` / `mangles` / `unknown` | Does the model return `<REF_N>` tokens unchanged? `verbatim` = yes; `mangles` = no, it alters them; `unknown` = not tested. |
| `recommended_strategy` | `opaque` / `surrogate` | Which masking strategy apf should use for this model. Use `surrogate` only when the model `mangles` opaque tokens — surrogate values have known robustness costs, so `opaque` is the safe choice whenever the model can handle it. |
| `injection_sensitivity` | `low` / `high` | `high` if the model declines or behaves oddly when the prompt contains dense clusters of opaque tokens (apf-76s). `low` otherwise. |
| `notes` | string | Free text. **Please record how you tested** — your evidence trail is what makes the profile trustworthy for the next person. |

## Where profiles live

There are two locations, layered:

1. **Shipped profiles** — `model_profiles/` in the repo. One `*.toml` file per
   model (filename matches the model id by convention; multiple `[[models]]`
   tables per file are also accepted). These are the profiles apf ships with.
2. **Your own overrides** — `~/.config/apf/model_profiles.toml`. Any entry here
   **replaces** the shipped profile for the same `model` id. Use this for
   private fine-tunes, or when you have tested a shipped model on your own
   hardware and disagree with the shipped profile.

   You can point apf at a different override file with the
   `APF_MODEL_PROFILE_CONFIG` environment variable.

Unknown model ids — anything with no profile in either location — fall back to
a **conservative default**: `token_passthrough=unknown`,
`recommended_strategy=opaque`, `injection_sensitivity=low`. apf will never
silently switch an untested model to `surrogate`.

A malformed file, or a single malformed `[[models]]` entry, is logged to
stderr and skipped — it never crashes the proxy and never poisons the rest of
the registry.

## Adding a profile for your own model (local override)

1. Create `~/.config/apf/model_profiles.toml` (the `~/.config/apf/` directory
   is the same one `endpoints.toml` lives in).
2. Add a `[[models]]` table using the format above. The `model` value must
   match what your agent actually sends — check apf's request log or
   `curl 127.0.0.1:8765/healthz` if you are unsure.
3. Restart is not required — apf re-reads the registry on each lookup.

Example:

```toml
[[models]]
model = "my-org/my-private-coder-finetune"
token_passthrough = "mangles"
recommended_strategy = "surrogate"
injection_sensitivity = "low"
notes = "Tested 2026-05 on a 32 GB Apple Silicon Mac. Opaque <REF_3> came back as 'REF 3' ~40% of the time, surrogate values survived intact."
```

## Contributing a profile back to the project

If you have tested a model others are likely to use, please contribute the
profile so everyone benefits:

1. Add a `model_profiles/<Your-Model-Id>.toml` file using the format above.
2. Fill in `notes` with **how you tested it** — what you sent, what you saw,
   roughly how often opaque tokens were mangled. The evidence trail is the
   point; a profile with no notes is hard to trust.
3. Run the suite to confirm nothing broke:
   `.venv/bin/python -m pytest apf/ benchmarks/`
4. Open a PR. Mention the hardware and quantization you tested on — token
   behaviour can differ between quant levels of the "same" model.

### How to test a model

The fastest way is the **conformance harness** (`apf-vh8`,
`benchmarks/model_conformance.py`). It runs a fixed four-probe suite against
an OpenAI-compatible endpoint, classifies the model, and emits a profile TOML
in exactly this schema:

```bash
# Probe a model and print the profile TOML to stdout:
.venv/bin/python -m benchmarks.model_conformance --mode live \
    --endpoint http://127.0.0.1:8000 --model my-model

# Or write it straight to a contributable file:
.venv/bin/python -m benchmarks.model_conformance --mode live \
    --endpoint http://127.0.0.1:8000 --model my-model \
    --out model_profiles/my-model.toml
```

`--endpoint` defaults to `http://127.0.0.1:8000`; point it at any
OpenAI-compatible Chat Completions server. `--api-key` adds a
Bearer token if the endpoint needs one. `--mode demo` classifies built-in
canned probe output with no network — a quick check that the tool works.

The four probes:

- **verbatim passthrough** — sends a prompt full of `<REF_N>` tokens and
  checks they come back byte-identical → `token_passthrough`.
- **mangling pattern** — when not verbatim, captures *how* the model mangled
  the tokens (the `apf-2qz` shape: `<REF_1>` → `REF_1@example.com`) into the
  profile `notes`.
- **injection sensitivity** — sends a dense opaque-token cluster (`apf-76s`)
  and checks whether the model declines / flags it → `injection_sensitivity`.
- **tool-call boundary** — a prompt that should yield a tool call carrying a
  token; checks whether the token survives inside the tool-call arguments.

`recommended_strategy` follows automatically: `surrogate` if the model
mangles, otherwise `opaque`.

The harness writes the verdict into the `notes` field as an evidence trail —
review it, then add the hardware and quantization you tested on before
committing.

**Regression mode.** For a model that already has a committed profile, add
`--check`: the harness classifies the live model and exits non-zero if the
classification has drifted from the shipped profile. Useful in CI or after a
model/quant bump.

> The classifier itself is unit-tested hermetically
> (`benchmarks/conformance_classifier_test.py`) — canned probe outputs in,
> asserted profile out — so the `pytest` suite never hits a live model.

If you prefer a manual check: run an `<REF_N>`-heavy masked request through
apf and see whether the tokens come back byte-identical (mangled → set
`mangles`); send a dense opaque cluster and watch for a decline (→
`injection_sensitivity = high`).

## Currently shipped profiles

| Model | passthrough | strategy | sensitivity |
|---|---|---|---|
| `Qwen2.5-Coder-7B-Instruct-MLX-4bit` | mangles | surrogate | low |
| `Qwen3.6-35B-A3B-Holo3-Qwopus-mxfp4-mlx` | verbatim | opaque | low |

See each file in `model_profiles/` for the full evidence notes.
