"""apf-eg3: locked-category regex detector (v0).

Verifies the keyword/phrase matcher emits the right locked labels for
unambiguous statements + does NOT emit them for benign / scientific /
news-discussion text. Synthesised cases only — no real PII.
"""
from __future__ import annotations

from .adapters_locked import LockedCategoryRegexAdapter


def _detect_labels(text: str) -> set[str]:
    adapter = LockedCategoryRegexAdapter()
    adapter.warmup()
    return {s.label for s in adapter.detect(text)}


# ── Positive cases: must trigger the locked label ─────────────────────────

def test_asylum_en_interview() -> None:
    assert "ASYLUM_STATUS" in _detect_labels(
        "I need to prepare for my asylum interview next Tuesday.")


def test_asylum_en_application() -> None:
    assert "ASYLUM_STATUS" in _detect_labels(
        "I applied for asylum three months ago.")


def test_asylum_de_anhoerung() -> None:
    assert "ASYLUM_STATUS" in _detect_labels(
        "Mein Asylverfahren ist in der Anhörungsphase.")


def test_asylum_de_aufenthaltsgestattung() -> None:
    assert "ASYLUM_STATUS" in _detect_labels(
        "Ich habe momentan nur eine Aufenthaltsgestattung.")


def test_dv_en_domestic_abuse() -> None:
    assert "DOMESTIC_VIOLENCE" in _detect_labels(
        "I am leaving my abusive husband next week.")


def test_dv_en_restraining_order() -> None:
    assert "DOMESTIC_VIOLENCE" in _detect_labels(
        "There is a restraining order in place against my ex.")


def test_dv_de_haeusliche_gewalt() -> None:
    assert "DOMESTIC_VIOLENCE" in _detect_labels(
        "Ich bin Opfer häuslicher Gewalt und brauche Beratung.")


def test_dv_de_frauenhaus() -> None:
    assert "DOMESTIC_VIOLENCE" in _detect_labels(
        "Hast du die Frauenhausnummer für Berlin?")


def test_whistleblower_en_intent() -> None:
    assert "WHISTLEBLOWER_INTENT" in _detect_labels(
        "I'm thinking about reporting my manager to the SEC.")


def test_whistleblower_en_disclosure() -> None:
    assert "WHISTLEBLOWER_INTENT" in _detect_labels(
        "I'm drafting the disclosure for the press right now.")


def test_whistleblower_de_bafin() -> None:
    assert "WHISTLEBLOWER_INTENT" in _detect_labels(
        "Sollte ich das bei der BaFin melden?")


def test_undocumented_en_status() -> None:
    assert "UNDOCUMENTED_STATUS" in _detect_labels(
        "I am an undocumented immigrant living in the US.")


def test_undocumented_en_overstay() -> None:
    assert "UNDOCUMENTED_STATUS" in _detect_labels(
        "I overstayed my visa by eight months.")


def test_undocumented_de_duldung() -> None:
    assert "UNDOCUMENTED_STATUS" in _detect_labels(
        "Meine Duldung läuft im März aus.")


# ── Negative cases: benign or discussion text must NOT trigger ────────────

def test_negative_general_question() -> None:
    assert _detect_labels("What is the capital of France?") == set()


def test_negative_code_question() -> None:
    assert _detect_labels(
        "Write a Python function that computes a hash.") == set()


def test_negative_news_discussion() -> None:
    """Generic policy-discussion phrasing must not trigger. The ASYLUM
    patterns whitelist specific user-state phrases (asylum interview /
    application / status / process / hearing / decision); 'asylum
    policy' is intentionally not in that set."""
    assert _detect_labels(
        "The recent change in asylum policy has been controversial.") == set()


def test_negative_irrelevant_words() -> None:
    """Words that share substrings with locked terms must not trigger.
    'cassia' contains 'asia' (not 'asylum'); 'covet' contains 'cove' —
    pattern boundaries protect against substring leaks."""
    text = "I am studying biology, ecology, and economics."
    assert _detect_labels(text) == set()


def test_negative_safe_german_text() -> None:
    text = "Was bedeutet Photosynthese in zwei Sätzen?"
    assert _detect_labels(text) == set()
