"""Benchmark harness entry point.

Loads fixtures, runs a detector adapter, scores against gold spans, measures
latency and peak RSS, writes a result JSON to `benchmarks/results/<name>.json`.

Usage:
    python -m benchmarks.run --adapter regex
    python -m benchmarks.run --adapter regex --fixtures fixtures/content.jsonl
    python -m benchmarks.run --adapter regex --output -      # stdout instead of file
"""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from .adapters import ADAPTERS, Span
from .metrics import aggregate, serialise

# MLX adapters are optional — only register if the deps are installed.
try:
    from . import adapters_mlx as _mlx
    _mlx.register(ADAPTERS)
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "fixtures"
RESULTS_DIR = ROOT / "benchmarks" / "results"


def load_fixtures(paths: list[Path]) -> list[dict]:
    fixtures: list[dict] = []
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    fixtures.append(json.loads(line))
    return fixtures


def peak_rss_bytes() -> int:
    """ru_maxrss is bytes on macOS, kilobytes on Linux. Normalise to bytes."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return rss
    return rss * 1024


def run(adapter_name: str, fixture_paths: list[Path]) -> dict:
    if adapter_name not in ADAPTERS:
        raise SystemExit(f"unknown adapter {adapter_name!r}; have: {sorted(ADAPTERS)}")
    detector = ADAPTERS[adapter_name]()

    fixtures = load_fixtures(fixture_paths)
    if not fixtures:
        raise SystemExit(f"no fixtures loaded from {fixture_paths}")

    rss_before_warmup = peak_rss_bytes()
    t0 = time.perf_counter()
    detector.warmup()
    t_warmup = time.perf_counter() - t0
    rss_after_warmup = peak_rss_bytes()

    predictions: dict[str, list[Span]] = {}
    latencies: list[float] = []
    for fix in fixtures:
        t1 = time.perf_counter()
        pred = detector.detect(fix["text"])
        latencies.append(time.perf_counter() - t1)
        predictions[fix["id"]] = pred

    rss_peak = peak_rss_bytes()
    report = aggregate(fixtures, predictions)

    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)

    return {
        "adapter": adapter_name,
        "fixtures": {
            "files": [str(p.relative_to(ROOT)) for p in fixture_paths],
            "count": len(fixtures),
        },
        "scores": serialise(report),
        "latency_ms": {
            "mean": round(sum(latencies) * 1000 / n, 2),
            "p50": round(latencies_sorted[n // 2] * 1000, 2),
            "p95": round(latencies_sorted[min(n - 1, int(n * 0.95))] * 1000, 2),
            "max": round(latencies_sorted[-1] * 1000, 2),
        },
        "memory_mb": {
            "before_warmup": round(rss_before_warmup / (1024 * 1024), 1),
            "after_warmup": round(rss_after_warmup / (1024 * 1024), 1),
            "peak": round(rss_peak / (1024 * 1024), 1),
        },
        "warmup_s": round(t_warmup, 3),
    }


def format_summary(result: dict) -> str:
    s = result["scores"]
    lat = result["latency_ms"]
    mem = result["memory_mb"]
    lines = [
        f"adapter:     {result['adapter']}",
        f"fixtures:    {result['fixtures']['count']} from {', '.join(result['fixtures']['files'])}",
        f"",
        f"tier-equality   precision={s['overall_tier']['precision']:.3f}  recall={s['overall_tier']['recall']:.3f}  f1={s['overall_tier']['f1']:.3f}",
        f"label-equality  precision={s['overall_label']['precision']:.3f}  recall={s['overall_label']['recall']:.3f}  f1={s['overall_label']['f1']:.3f}",
        f"",
        f"by tier:",
    ]
    for tier, c in s["per_tier"].items():
        lines.append(f"  {tier}    precision={c['precision']:.3f}  recall={c['recall']:.3f}  f1={c['f1']:.3f}  (tp={c['tp']} fp={c['fp']} fn={c['fn']})")
    lines.append("")
    lines.append("by language:")
    for lang, c in s["per_lang"].items():
        lines.append(f"  {lang}    precision={c['precision']:.3f}  recall={c['recall']:.3f}  f1={c['f1']:.3f}  (tp={c['tp']} fp={c['fp']} fn={c['fn']})")
    lines.append("")
    lines.append(f"latency:     mean={lat['mean']}ms  p50={lat['p50']}ms  p95={lat['p95']}ms  max={lat['max']}ms")
    lines.append(f"memory MB:   before={mem['before_warmup']}  after-warmup={mem['after_warmup']}  peak={mem['peak']}")
    lines.append(f"warmup:      {result['warmup_s']}s")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    parser.add_argument("--fixtures", action="append",
                        help="Fixture file (default: all three buckets). May be repeated.")
    parser.add_argument("--output", default=None,
                        help="Path for result JSON; default = benchmarks/results/<adapter>.json. Use '-' for stdout.")
    parser.add_argument("--quiet", action="store_true", help="Don't print the human summary.")
    args = parser.parse_args()

    if args.fixtures:
        fixture_paths = [Path(p) for p in args.fixtures]
    else:
        fixture_paths = sorted(FIXTURE_DIR.glob("*.jsonl"))
        if not fixture_paths:
            raise SystemExit(f"no fixture files in {FIXTURE_DIR}")

    result = run(args.adapter, fixture_paths)

    if not args.quiet:
        print(format_summary(result), file=sys.stderr)

    if args.output == "-":
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        out_path = Path(args.output) if args.output else (RESULTS_DIR / f"{args.adapter}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        try:
            display = out_path.resolve().relative_to(ROOT)
        except ValueError:
            display = out_path.resolve()
        print(f"\nwrote {display}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
