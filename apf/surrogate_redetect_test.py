"""apf-76m: a surrogate already present in the text is not re-masked.

A surrogate is PII-shaped, so the detector re-flags it when it is
replayed from an earlier turn. _mask_text must drop detections that
overlap a value the vault already masked to a surrogate — whole or
partial (a fragment of the surrogate, e.g. its domain).
"""
from __future__ import annotations

import apf.proxy as proxy
from apf.masker import Span
from apf.vault import Vault


def _seed_surrogate(vault: Vault, original: str, surrogate: str,
                    label: str = "EMAIL") -> None:
    vault.get_or_mint(original, label, "A", surrogate_gen=lambda: surrogate)


def _detector(monkeypatch, *needles: str) -> None:
    """Stub: flags each needle wherever it appears, as EMAIL."""
    class _Stub:
        name = "stub"

        def detect(self, text: str):
            spans = []
            for needle in needles:
                start = 0
                while (i := text.find(needle, start)) != -1:
                    spans.append(Span(start=i, end=i + len(needle),
                                      label="EMAIL", tier="A",
                                      confidence=1.0))
                    start = i + len(needle)
            return spans
    monkeypatch.setattr(proxy, "_DETECTOR", _Stub())


def test_whole_surrogate_not_remasked(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", frozenset({"EMAIL"}))
    vault = Vault()
    _seed_surrogate(vault, "anna@real.de", "claudia@fake.de")
    _detector(monkeypatch, "claudia@fake.de")
    out = proxy._mask_text("contact claudia@fake.de now", vault)
    assert out == "contact claudia@fake.de now"   # surrogate left as-is
    assert len(vault.all_entries()) == 1          # no second entry


def test_partial_surrogate_fragment_not_remasked(monkeypatch) -> None:
    # the detector flags a fragment of the surrogate (e.g. its domain) —
    # it overlaps the surrogate range and must be dropped too
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", frozenset({"EMAIL"}))
    vault = Vault()
    _seed_surrogate(vault, "anna@real.de", "claudia@fake.de")
    _detector(monkeypatch, "fake.de")
    out = proxy._mask_text("the host is claudia@fake.de here", vault)
    assert out == "the host is claudia@fake.de here"
    assert len(vault.all_entries()) == 1


def test_genuine_pii_alongside_a_surrogate_still_masked(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", frozenset())
    vault = Vault()
    _seed_surrogate(vault, "anna@real.de", "claudia@fake.de")
    # a real, not-yet-seen e-mail must still be masked
    _detector(monkeypatch, "claudia@fake.de", "bob@new.de")
    out = proxy._mask_text("from claudia@fake.de to bob@new.de", vault)
    assert "claudia@fake.de" in out          # surrogate untouched
    assert "bob@new.de" not in out           # genuine PII masked
    assert "<REF" in out
    assert len(vault.all_entries()) == 2     # only the new one added
