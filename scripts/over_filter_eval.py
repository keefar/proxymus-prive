"""Over-filter evaluation harness (apf-00s scaffold).

Methodology lives in docs/OVER-FILTER-EVAL.md. This file implements the
pair-eval pipeline: per fixture, run agent on (original | masked),
score with a judge, aggregate.

The judge is API-pluggable. The default `StubJudge` returns
deterministic ratings derived from a hash of the reply content — useful
only for pipeline-shape testing. Real evaluation requires plugging in
an Anthropic/OpenAI client (or local model) via the JudgeFn protocol.

Usage:
    python scripts/over_filter_eval.py \
        --fixtures fixtures/private/private.jsonl \
        --out docs/results/eval-YYYY-MM-DD.md

Stub mode (no API calls):
    python scripts/over_filter_eval.py --stub
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parent.parent


# ── Task specs per fixture ──────────────────────────────────────────────
# The agent tasks below describe what a personal assistant would
# plausibly do with each fixture. Each task is single-turn and
# answerable from the fixture alone.

TASK_SPECS: dict[str, list[str]] = {
    "de-health-mental-01": [
        "Fasse den Inhalt der Nachricht in einem Satz zusammen.",
        "Was möchte die Person konkret von der Therapeutin?",
    ],
    "de-repro-01": [
        "Fasse den Überweisungsbrief in 2 Sätzen zusammen.",
        "Extrahiere das Datum und den Namen der ausführenden Klinik.",
    ],
    "en-mental-substance-01": [
        "Summarise this journal entry briefly.",
        "What follow-up actions did the writer plan?",
    ],
    "de-asylum-01": [
        "Fasse die ergänzende Stellungnahme in 2 Sätzen zusammen.",
        "Wann ist die Anhörung und wer ist der Anwalt?",
    ],
    "en-custody-01": [
        "Summarise the mediation notes.",
        "What is the writer's position on Wednesday overnight stays?",
    ],
    "en-immigration-01": [
        "Summarise the visa status timeline.",
        "What is the priority date and category?",
    ],
    "de-finanz-insolvenz-01": [
        "Fasse die E-Mail in einem Satz zusammen.",
        "Wie hoch ist die Gesamtverschuldung?",
    ],
    "de-politik-spende-01": [
        "Welche Information soll die E-Mail enthalten?",
    ],
    "en-political-activism-01": [
        "Draft a 2-sentence summary suitable as a Twitter post.",
    ],
    "de-third-party-health-01": [
        "Worum bittet der Nutzer den Agenten konkret?",
    ],
    "en-third-party-confidence-01": [
        "Summarise the emotional weight of this journal entry.",
    ],
    "de-sex-orientation-01": [
        "Was ist die Aufgabe für den Agenten?",
    ],
    "de-substanz-rezept-01": [
        "Erkläre dem Nutzer das Rezept in einfachen Worten.",
    ],
}


@dataclass
class Run:
    fixture_id: str
    condition: str   # "control" | "treatment"
    task: str
    text_seen: str   # what the agent input was
    reply: str       # what the agent produced (or stub-marker)


@dataclass
class Rating:
    score: int        # 0 / 1 / 2
    label: str        # "impossible" / "partial" / "full"
    rationale: str


JudgeFn = Callable[[Run], Rating]


def _hash_to_score(reply: str) -> int:
    """Deterministic stub score from reply hash; only for pipeline test."""
    h = int(hashlib.sha1(reply.encode("utf-8")).hexdigest(), 16) % 3
    return h


def stub_judge(run: Run) -> Rating:
    score = _hash_to_score(run.fixture_id + run.condition + run.task)
    return Rating(
        score=score,
        label={0: "impossible", 1: "partial", 2: "full"}[score],
        rationale="stub judge (deterministic hash); replace with real judge for actual eval",
    )


def stub_agent(text: str, task: str) -> str:
    """Stub agent for pipeline test. Returns a marker that names what
    was seen — for real evals, plug in an actual API call to your
    agent of choice."""
    return f"[STUB-REPLY for task={task!r} on {len(text)}-char input]"


def load_fixtures(path: Path) -> list[dict]:
    items: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def apply_v1_filter(text: str, spans: list[dict]) -> str:
    """Apply v1 filter settings (opaque tokens) to text given gold spans.
    For the eval harness we use the gold spans rather than the live
    detector — this isolates over-filter assessment from detector
    accuracy. Detector accuracy is measured separately by benchmarks/run.py.
    """
    if not spans:
        return text
    spans_sorted = sorted(spans, key=lambda s: s["start"], reverse=True)
    counter = len(spans_sorted)
    pieces: list[str] = []
    cursor = len(text)
    out = text
    # Walk right-to-left, replacing each span with <REF_N>.
    for s in spans_sorted:
        token = f"<REF_{counter}>"
        out = out[:s["start"]] + token + out[s["end"]:]
        counter -= 1
    return out


def evaluate(
    fixtures: list[dict],
    *,
    agent: Callable[[str, str], str] = stub_agent,
    judge: JudgeFn = stub_judge,
) -> dict:
    """Run the pair-eval on each fixture's tasks. Returns aggregate
    results suitable for the markdown report."""
    rows: list[dict] = []
    for fix in fixtures:
        if "turns" in fix:
            continue  # multi-turn fixtures evaluated separately
        fid = fix["id"]
        tasks = TASK_SPECS.get(fid, [])
        if not tasks:
            continue
        original = fix["text"]
        masked = apply_v1_filter(original, fix.get("spans", []))
        for task in tasks:
            ctrl = Run(fid, "control", task, original, agent(original, task))
            trt = Run(fid, "treatment", task, masked, agent(masked, task))
            r_ctrl = judge(ctrl)
            r_trt = judge(trt)
            rows.append({
                "fixture": fid,
                "task": task,
                "control_score": r_ctrl.score,
                "control_label": r_ctrl.label,
                "treatment_score": r_trt.score,
                "treatment_label": r_trt.label,
                "delta": r_trt.score - r_ctrl.score,
            })
    if not rows:
        return {"rows": [], "summary": {}}
    deltas = [r["delta"] for r in rows]
    summary = {
        "n_pairs": len(rows),
        "mean_control": statistics.mean(r["control_score"] for r in rows),
        "mean_treatment": statistics.mean(r["treatment_score"] for r in rows),
        "mean_delta": statistics.mean(deltas),
        "impossible_treatment": sum(1 for r in rows if r["treatment_label"] == "impossible"),
        "partial_treatment": sum(1 for r in rows if r["treatment_label"] == "partial"),
        "full_treatment": sum(1 for r in rows if r["treatment_label"] == "full"),
    }
    return {"rows": rows, "summary": summary}


def render_markdown(results: dict, *, out_path: Path) -> None:
    s = results["summary"]
    lines = [
        "# Over-filter evaluation report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Pairs evaluated: {s.get('n_pairs', 0)}",
        "",
        "## Aggregate",
        "",
        f"- mean control: {s.get('mean_control', 0):.2f}",
        f"- mean treatment: {s.get('mean_treatment', 0):.2f}",
        f"- mean Δ: {s.get('mean_delta', 0):+.2f}",
        f"- treatment outcomes: full={s.get('full_treatment', 0)}, "
        f"partial={s.get('partial_treatment', 0)}, "
        f"impossible={s.get('impossible_treatment', 0)}",
        "",
        "## Per-task ratings",
        "",
        "| Fixture | Task | Control | Treatment | Δ |",
        "|---|---|---|---|---|",
    ]
    for r in results["rows"]:
        lines.append(
            f"| {r['fixture']} | {r['task'][:60]}… | "
            f"{r['control_label']} | {r['treatment_label']} | "
            f"{r['delta']:+d} |"
        )
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", default="fixtures/private/private.jsonl",
                        help="Path to JSONL fixture file")
    parser.add_argument("--out", default="-",
                        help="Markdown output path (default stdout)")
    parser.add_argument("--stub", action="store_true",
                        help="Use stub agent + stub judge (no API calls)")
    args = parser.parse_args()

    path = (ROOT / args.fixtures) if not Path(args.fixtures).is_absolute() else Path(args.fixtures)
    if not path.exists():
        raise SystemExit(f"fixtures not found at {path}")
    fixtures = load_fixtures(path)
    if not fixtures:
        raise SystemExit(f"no fixtures loaded from {path}")

    if not args.stub:
        # In v1, only stub agent + stub judge are wired up. A real run
        # requires an API client; refusing here keeps the user from
        # accidentally treating stub numbers as real measurements.
        print("Real-agent/real-judge wiring not yet shipped. "
              "Use --stub for the pipeline-shape test.", file=sys.stderr)
        return 2

    results = evaluate(fixtures, agent=stub_agent, judge=stub_judge)
    if args.out == "-":
        render_markdown(results, out_path=Path("/dev/stdout"))
    else:
        out_path = Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        render_markdown(results, out_path=out_path)
        print(f"wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
