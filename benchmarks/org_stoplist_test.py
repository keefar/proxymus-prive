"""apf-zac: ORG over-detection cleanup.

GLiNER PII models over-fire ORG on generic capitalised common nouns
('team', 'gym', 'lab', 'startup', 'HR', 'Kardiologie'). The fix mirrors
the apf-5ds PERSON stoplist: drop ORG spans whose whole surface is a
known common noun. Recall-safe by construction — no entry is ever a
real organisation name; multi-token spans carrying a real org name
remain untouched.
"""
from __future__ import annotations

from benchmarks.adapters import Span
from benchmarks.adapters_mlx import (
    ORG_COMMON_NOUN_STOPLIST,
    PERSON_NONNAME_DROP,
    PERSON_RELATIONSHIP_NOUNS,
    _drop_org_noise,
    _merge_spans,
)


def _span(text: str, word: str, label: str) -> Span:
    i = text.index(word)
    return Span(start=i, end=i + len(word), label=label, tier="B",
                confidence=0.85)


# --- drop path: generic common nouns ---------------------------------------

def test_drops_english_common_noun_org_span() -> None:
    text = "the team meets on Monday"
    spans = [_span(text, "team", "ORG")]
    assert _drop_org_noise(spans, text) == []


def test_drops_german_common_noun_org_span() -> None:
    text = "die Praxis hat heute geschlossen"
    spans = [_span(text, "Praxis", "ORG")]
    assert _drop_org_noise(spans, text) == []


def test_drops_medical_specialism_org_span() -> None:
    text = "Termin in der Kardiologie um 14 Uhr"
    spans = [_span(text, "Kardiologie", "ORG")]
    assert _drop_org_noise(spans, text) == []


def test_drop_path_is_case_insensitive() -> None:
    text = "HR will email you"
    spans = [_span(text, "HR", "ORG")]
    assert _drop_org_noise(spans, text) == []


# --- recall safety ---------------------------------------------------------

def test_keeps_real_org_name() -> None:
    """A real organisation name is untouched — recall must survive."""
    text = "We met at Anthropic yesterday."
    spans = [_span(text, "Anthropic", "ORG")]
    kept = _drop_org_noise(spans, text)
    assert len(kept) == 1 and kept[0].label == "ORG"


def test_keeps_multi_token_span_carrying_real_name() -> None:
    """A multi-token span where part of the surface is a stoplisted word
    is untouched — only whole-surface matches fire."""
    text = "HR Berlin GmbH announced layoffs"
    spans = [_span(text, "HR Berlin GmbH", "ORG")]
    assert _drop_org_noise(spans, text) == spans


def test_only_affects_org_label() -> None:
    """A non-ORG span whose surface is a stoplisted word is untouched —
    the filter is scoped to the ORG label. ('team' as PERSON would be
    handled by the PERSON cleanup, not this one.)"""
    text = "team"
    spans = [_span(text, "team", "PERSON")]
    # PERSON-scoped cleanup is _drop_person_noise, so this filter leaves
    # the span alone.
    assert _drop_org_noise(spans, text) == spans


def test_keeps_specialism_inside_full_practice_name() -> None:
    """'Praxis für Kardiologie XYZ' is a real org name with a generic
    field name inside — must survive."""
    text = "Termin in der Praxis für Kardiologie Dr. Müller"
    spans = [_span(text, "Praxis für Kardiologie Dr. Müller", "ORG")]
    assert _drop_org_noise(spans, text) == spans


# --- integration with _merge_spans -----------------------------------------

def test_merge_spans_applies_org_cleanup_when_text_given() -> None:
    text = "Treffen mit der Gym-Crew"
    org = [_span(text, "Gym", "ORG")]
    merged = _merge_spans([org], text)
    assert merged == []
    # Without text, _merge_spans stays a pure merge (back-compat).
    assert _merge_spans([org])[0].label == "ORG"


def test_merge_spans_keeps_real_org_through_cleanup() -> None:
    text = "Anthropic released a new model."
    org = [_span(text, "Anthropic", "ORG")]
    merged = _merge_spans([org], text)
    assert len(merged) == 1 and merged[0].label == "ORG"


# --- stoplist hygiene ------------------------------------------------------

def test_org_stoplist_disjoint_from_person_stoplists() -> None:
    """ORG common nouns must not overlap with the PERSON-scoped lists —
    otherwise a span would be ambiguously claimed by two cleanups."""
    assert not (ORG_COMMON_NOUN_STOPLIST & PERSON_NONNAME_DROP)
    assert not (ORG_COMMON_NOUN_STOPLIST & PERSON_RELATIONSHIP_NOUNS)


def test_org_stoplist_entries_are_lowercase() -> None:
    """Whole-surface match is done after .lower() — every entry must be
    already lowercased so the comparison can never miss due to case."""
    for entry in ORG_COMMON_NOUN_STOPLIST:
        assert entry == entry.lower(), f"non-lowercase entry: {entry!r}"
