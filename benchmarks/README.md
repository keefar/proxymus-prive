# Benchmark harness

Measures stage-2 PII-detection models against the synthetic fixture set in
`fixtures/`. Stdlib-only (no MLX deps yet — those land with the per-model
adapters in `apf-4f4.5..7`).

## Layout

```
benchmarks/
├── adapters.py            ← Detector protocol + RegexBaseline (mock floor)
├── adapters_mlx.py        ← Apple-Silicon-only generative + GLiNER + Presidio adapters
├── adapters_http.py       ← OpenAI-compatible HTTP detector (Ollama/oMLX/LM Studio/…)
├── metrics.py             ← tier-equality + label-equality scoring, per-slice aggregation
├── run.py                 ← entry point: load, run, score, dump JSON
├── model_conformance.py   ← apf-vh8: probe an upstream model, classify its
│                            <REF_N> token handling, emit a model profile
└── results/               ← gitignored output dir
```

## Model-conformance harness (apf-vh8)

`model_conformance.py` is a separate harness — not a detector benchmark. It
probes an *upstream* model (the one apf forwards to), classifies how it
handles `<REF_N>` tokens, and emits an `apf-ao2` model profile.

```bash
# Probe a live OpenAI-compatible endpoint, print the profile TOML:
python -m benchmarks.model_conformance --mode live \
    --endpoint http://127.0.0.1:8000 --model my-model

# Classify built-in canned probe output (no network):
python -m benchmarks.model_conformance --mode demo

# Regression-check a model against its committed profile:
python -m benchmarks.model_conformance --mode live --check --model my-model
```

The classifier is a pure function (`classify`) unit-tested hermetically in
`conformance_classifier_test.py` — the live-probe run is a separate `--mode
live` entry point, mirroring the record/live split of
`scripts/toolcall_loopback.py`. See `docs/MODEL-PROFILES.md` for the full
contribution workflow.

## Run

```bash
python -m benchmarks.run --adapter regex
python -m benchmarks.run --adapter regex --fixtures fixtures/content.jsonl
python -m benchmarks.run --adapter regex --output - | jq .
```

Default fixture set is all three buckets. Results go to
`benchmarks/results/<adapter>.json` (gitignored — re-run any time).

## External generative detector via HTTP (`openai-compat`)

The `openai-compat` adapter drives any OpenAI-Chat-Completions–speaking
daemon — Ollama, oMLX, LM Studio, llama.cpp-server, vLLM — as a
generative PII detector. Cross-platform (pure httpx; works on Linux,
Windows, macOS).

Config is taken from env vars (the benchmark harness has no per-adapter
CLI):

```bash
# Default targets a local Ollama daemon — adjust to suit your setup.
export APF_GEN_DETECTOR_ENDPOINT="http://127.0.0.1:11434/v1"
export APF_GEN_DETECTOR_MODEL="qwen2.5:1.5b-instruct-q4_K_M"
# Optional:
# export APF_GEN_DETECTOR_API_KEY="..."         # for hosted/locked daemons
# export APF_GEN_DETECTOR_TIMEOUT_S="30"
# export APF_GEN_DETECTOR_MAX_TOKENS="512"

python -m benchmarks.run --adapter openai-compat
```

The adapter prompts the model with the same JSON-span contract as
`Qwen3Adapter` in `adapters_mlx.py`; output is parsed and offsets are
recovered by searching the input. Production / proxy integration goes
through model profiles (tracked separately — see beads `apf-yyz`).

## Scoring

Two layers, both reported:

- **Tier-equality** — predicted span overlaps gold by ≥ 50% AND tier agrees.
  Primary metric: drives the ≥ 0.95 recall decision criterion.
- **Label-equality** — same overlap AND identical label. Diagnostic — separates
  "found something sensitive in the right place but mislabeled it" from
  "found the right thing".

Per-tier, per-label, per-language, per-bucket counts are all aggregated.
Unmatched predictions become FPs and inherit their predicted tier/label.

## Latency / memory

- `time.perf_counter()` around each `detect(text)` call. Reports mean, p50,
  p95, max in ms.
- `resource.getrusage(...).ru_maxrss` for peak RSS. macOS-bytes vs.
  Linux-kilobytes is normalised. Reported before warmup, after warmup, and at
  end of run.

## Adding a new adapter

1. Implement a class with `name: str`, `warmup() -> None`, and
   `detect(text: str) -> list[Span]` in `adapters.py` (or a new module
   imported from there).
2. Register it in the `ADAPTERS` dict.
3. Run `python -m benchmarks.run --adapter <name>`.

The Detector Protocol is intentionally narrow — model-specific stuff
(tokeniser, generate args, output parsing) lives entirely inside each
adapter's `detect`.

## Current floor

The `regex` adapter is a deliberately weak baseline. On 2026-05-16 it scored
tier-recall 0.19 / tier-precision 0.90 on the 50-fixture set — useful as a
floor and as a sanity check for the metrics code, NOT as a real candidate.
