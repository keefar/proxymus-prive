"""apf-t7t FP-2: HEALTH science-term stoplist.

GLiNER PII models flag general science vocabulary ('Photosynthese') as
personal HEALTH info. _drop_health_stoplist removes those — recall-safe
by construction (the stoplist only contains non-personal terms).
"""
from __future__ import annotations

from benchmarks.adapters import Span
from benchmarks.adapters_mlx import _drop_health_stoplist, _merge_spans


def _span(text: str, word: str, label: str) -> Span:
    i = text.index(word)
    return Span(start=i, end=i + len(word), label=label, tier="A",
                confidence=0.79)


def test_drops_science_term_health_span() -> None:
    text = "Was bedeutet Photosynthese?"
    spans = [_span(text, "Photosynthese", "HEALTH")]
    assert _drop_health_stoplist(spans, text) == []


def test_keeps_real_health_span() -> None:
    text = "Ich habe Depression."
    spans = [_span(text, "Depression", "HEALTH")]
    kept = _drop_health_stoplist(spans, text)
    assert len(kept) == 1 and kept[0].label == "HEALTH"


def test_only_filters_health_label() -> None:
    """A non-HEALTH span whose surface happens to be a stoplisted word is
    NOT dropped — the filter is scoped to the HEALTH label."""
    text = "biology"
    spans = [_span(text, "biology", "PERSON")]
    assert _drop_health_stoplist(spans, text) == spans


def test_merge_spans_applies_stoplist_when_text_given() -> None:
    text = "Explain photosynthesis briefly."
    health = [_span(text, "photosynthesis", "HEALTH")]
    # With text supplied, the merged result drops the stoplisted HEALTH span.
    assert _merge_spans([health], text) == []
    # Without text, _merge_spans stays a pure merge (back-compat).
    assert len(_merge_spans([health])) == 1
