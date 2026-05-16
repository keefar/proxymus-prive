"""Scoring for predicted PII spans against gold spans.

Match semantics — two scoring layers:

- **Tier-equality** (primary, per `docs/MODELS.md` decision): a predicted span
  matches a gold span if (a) they overlap by at least `overlap_threshold` of the
  gold span's character length and (b) their tiers agree. This is what we
  report against the ≥ 0.95 recall criterion.

- **Label-equality** (secondary): same as above plus identical label. Reported
  alongside for diagnostics — distinguishes "model finds *something* sensitive
  in the right place but mislabels it" from "model finds the right thing".

Each gold span resolves to exactly one TP or FN. Each predicted span resolves
to TP (if it's the best match for an unmatched gold) or FP. Greedy assignment
in gold order, ties broken by best overlap.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .adapters import Span


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class ScoreReport:
    overall_tier: Counts = field(default_factory=Counts)
    overall_label: Counts = field(default_factory=Counts)
    per_tier: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    per_label: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    per_lang: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    per_bucket: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))


def overlap_frac(a: Span, b: Span) -> float:
    """Fraction of `b` (gold) covered by `a` (predicted)."""
    start = max(a.start, b.start)
    end = min(a.end, b.end)
    if end <= start:
        return 0.0
    gold_len = b.end - b.start
    return (end - start) / gold_len if gold_len else 0.0


def score_fixture(
    gold: list[Span],
    pred: list[Span],
    overlap_threshold: float = 0.5,
) -> tuple[list[tuple[Span, Span | None]], list[Span]]:
    """Match predictions to gold, greedy by best overlap.

    Returns (gold-with-match-or-None, unmatched-predictions).
    """
    pred_remaining = list(pred)
    matched: list[tuple[Span, Span | None]] = []
    for g in gold:
        best_idx = -1
        best_overlap = 0.0
        for i, p in enumerate(pred_remaining):
            ov = overlap_frac(p, g)
            if ov >= overlap_threshold and ov > best_overlap:
                best_overlap = ov
                best_idx = i
        if best_idx >= 0:
            matched.append((g, pred_remaining.pop(best_idx)))
        else:
            matched.append((g, None))
    return matched, pred_remaining


def aggregate(
    fixtures: list[dict],
    predictions: dict[str, list[Span]],
    overlap_threshold: float = 0.5,
) -> ScoreReport:
    report = ScoreReport()
    for fix in fixtures:
        gold = [Span(**s) for s in fix["spans"]]
        pred = predictions[fix["id"]]
        matched, unmatched_pred = score_fixture(gold, pred, overlap_threshold)
        lang = fix["lang"]
        bucket = fix["bucket"]

        for g, p in matched:
            # Tier-equality layer.
            if p is not None and p.tier == g.tier:
                report.overall_tier.tp += 1
                report.per_tier[g.tier].tp += 1
                report.per_lang[lang].tp += 1
                report.per_bucket[bucket].tp += 1
            else:
                report.overall_tier.fn += 1
                report.per_tier[g.tier].fn += 1
                report.per_lang[lang].fn += 1
                report.per_bucket[bucket].fn += 1
            # Label-equality layer (stricter).
            if p is not None and p.label == g.label:
                report.overall_label.tp += 1
                report.per_label[g.label].tp += 1
            else:
                report.overall_label.fn += 1
                report.per_label[g.label].fn += 1

        # Unmatched predictions are false positives — bucket by predicted tier/label.
        for p in unmatched_pred:
            report.overall_tier.fp += 1
            report.per_tier[p.tier].fp += 1
            report.per_lang[lang].fp += 1
            report.per_bucket[bucket].fp += 1
            report.overall_label.fp += 1
            report.per_label[p.label].fp += 1

    return report


def serialise(report: ScoreReport) -> dict:
    def c(x: Counts) -> dict:
        return {"tp": x.tp, "fp": x.fp, "fn": x.fn,
                "precision": round(x.precision, 4),
                "recall": round(x.recall, 4),
                "f1": round(x.f1, 4)}
    return {
        "overall_tier": c(report.overall_tier),
        "overall_label": c(report.overall_label),
        "per_tier": {k: c(v) for k, v in sorted(report.per_tier.items())},
        "per_label": {k: c(v) for k, v in sorted(report.per_label.items())},
        "per_lang": {k: c(v) for k, v in sorted(report.per_lang.items())},
        "per_bucket": {k: c(v) for k, v in sorted(report.per_bucket.items())},
    }
