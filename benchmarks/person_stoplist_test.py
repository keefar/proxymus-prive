"""apf-5ds: PERSON over-detection cleanup.

Presidio's spaCy NER and the GLiNER PII models over-fire PERSON. The
misfires split into two kinds:

  - Pure non-PII noise (salutation closers, operational shell tokens) —
    `_drop_person_noise` drops these outright.
  - Role / relationship common nouns ('customer', 'Kollege', 'Nachbar') —
    a real but weak personal reference, mislabelled. `_drop_person_noise`
    relabels these PERSON -> RELATIONSHIP (same Tier A), which is
    recall-neutral and fixes the label.

Both are recall-safe by construction: no dropped or relabelled surface is
ever a person's name.
"""
from __future__ import annotations

from benchmarks.adapters import Span
from benchmarks.adapters_mlx import (
    PERSON_NONNAME_DROP,
    PERSON_PRONOUN_STOPLIST,
    PERSON_RELATIONSHIP_NOUNS,
    _drop_person_noise,
    _merge_spans,
)


def _span(text: str, word: str, label: str) -> Span:
    i = text.index(word)
    return Span(start=i, end=i + len(word), label=label, tier="A",
                confidence=0.85)


# --- drop path: pure non-PII noise -----------------------------------------

def test_drops_operational_token_person_span() -> None:
    text = "drwxr-xr-x  10 alice  staff   320 May 12"
    spans = [_span(text, "drwxr-xr-x", "PERSON")]
    assert _drop_person_noise(spans, text) == []


def test_drops_salutation_closer_person_span() -> None:
    text = "See you then.\n\nCheers,\nBob"
    spans = [_span(text, "Cheers", "PERSON")]
    assert _drop_person_noise(spans, text) == []


def test_drop_path_is_case_insensitive() -> None:
    text = "TODO: fix this"
    spans = [_span(text, "TODO", "PERSON")]
    assert _drop_person_noise(spans, text) == []


# --- relabel path: role / relationship nouns -------------------------------

def test_relabels_german_role_noun_to_relationship() -> None:
    text = "Der Kollege aus dem Controlling hat gefragt."
    spans = [_span(text, "Kollege", "PERSON")]
    kept = _drop_person_noise(spans, text)
    assert len(kept) == 1
    assert kept[0].label == "RELATIONSHIP"
    assert kept[0].tier == "A"  # recall-neutral: tier unchanged


def test_relabels_english_role_noun_to_relationship() -> None:
    text = "The customer's phone is +1-555-0142."
    spans = [_span(text, "customer", "PERSON")]
    kept = _drop_person_noise(spans, text)
    assert len(kept) == 1 and kept[0].label == "RELATIONSHIP"


def test_relabel_keeps_span_offsets() -> None:
    text = "Mit dem Nachbar besprochen."
    spans = [_span(text, "Nachbar", "PERSON")]
    kept = _drop_person_noise(spans, text)
    assert (kept[0].start, kept[0].end) == (8, 15)


def test_relabel_path_is_case_insensitive() -> None:
    text = "STAFF were notified."
    spans = [_span(text, "STAFF", "PERSON")]
    kept = _drop_person_noise(spans, text)
    assert len(kept) == 1 and kept[0].label == "RELATIONSHIP"


# --- recall safety ---------------------------------------------------------

def test_keeps_real_name_person_span() -> None:
    """A genuine name is untouched — recall must survive."""
    text = "Anna sitzt in Hannover."
    spans = [_span(text, "Anna", "PERSON")]
    kept = _drop_person_noise(spans, text)
    assert len(kept) == 1 and kept[0].label == "PERSON"


def test_keeps_name_that_contains_stoplist_word() -> None:
    """A multi-token span carrying a real name is untouched — only
    whole-surface matches are filtered."""
    text = "alice  staff"
    spans = [_span(text, "alice  staff", "PERSON")]
    assert _drop_person_noise(spans, text) == spans


def test_only_affects_person_label() -> None:
    """A non-PERSON span whose surface is a stoplisted word is untouched —
    the filter is scoped to the PERSON label."""
    text = "staff"
    spans = [_span(text, "staff", "ORG")]
    assert _drop_person_noise(spans, text) == spans


# --- integration with _merge_spans -----------------------------------------

def test_merge_spans_applies_person_cleanup_when_text_given() -> None:
    text = "Ask the customer about it."
    person = [_span(text, "customer", "PERSON")]
    merged = _merge_spans([person], text)
    assert len(merged) == 1 and merged[0].label == "RELATIONSHIP"
    # Without text, _merge_spans stays a pure merge (back-compat).
    assert _merge_spans([person])[0].label == "PERSON"


def test_merge_spans_drops_noise_person_when_text_given() -> None:
    text = "Cheers, Bob"
    person = [_span(text, "Cheers", "PERSON")]
    assert _merge_spans([person], text) == []


# --- stoplist hygiene ------------------------------------------------------

def test_stoplists_are_pairwise_disjoint() -> None:
    """The three PERSON stoplists do not overlap — no accidental
    double-classification."""
    assert not (PERSON_NONNAME_DROP & PERSON_RELATIONSHIP_NOUNS)
    assert not (PERSON_NONNAME_DROP & PERSON_PRONOUN_STOPLIST)
    assert not (PERSON_RELATIONSHIP_NOUNS & PERSON_PRONOUN_STOPLIST)
