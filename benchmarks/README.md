# Benchmark harness

Measures stage-2 PII-detection models against the synthetic fixture set in
`fixtures/`. Stdlib-only (no MLX deps yet — those land with the per-model
adapters in `apf-4f4.5..7`).

## Layout

```
benchmarks/
├── adapters.py        ← Detector protocol + RegexBaseline (mock floor)
├── metrics.py         ← tier-equality + label-equality scoring, per-slice aggregation
├── run.py             ← entry point: load, run, score, dump JSON
└── results/           ← gitignored output dir
```

## Run

```bash
python -m benchmarks.run --adapter regex
python -m benchmarks.run --adapter regex --fixtures fixtures/content.jsonl
python -m benchmarks.run --adapter regex --output - | jq .
```

Default fixture set is all three buckets. Results go to
`benchmarks/results/<adapter>.json` (gitignored — re-run any time).

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
