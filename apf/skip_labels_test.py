"""apf-1f6: SKIP_LABELS — labels detected but not masked.

ORG is opt-out by default (public-company mentions in coding-agent
prompts aren't user-PII and masking them breaks the prompt). Verifies
the skip filter in proxy._mask_text.
"""
from __future__ import annotations

import apf.proxy as proxy
from apf.masker import Span
from apf.vault import Vault


def _install_detector(monkeypatch) -> None:
    """Stub detector: PERSON span on 'ANNA', ORG span on 'ACME'."""
    class _Stub:
        name = "stub"
        def detect(self, text: str):
            spans = []
            if "ANNA" in text:
                i = text.index("ANNA")
                spans.append(Span(start=i, end=i + 4, label="PERSON",
                                  tier="A", confidence=1.0))
            if "ACME" in text:
                i = text.index("ACME")
                spans.append(Span(start=i, end=i + 4, label="ORG",
                                  tier="A", confidence=1.0))
            return spans
    monkeypatch.setattr(proxy, "_DETECTOR", _Stub())


def test_org_skipped_by_default(monkeypatch) -> None:
    _install_detector(monkeypatch)
    monkeypatch.setattr(proxy, "SKIP_LABELS", frozenset({"ORG"}))
    vault = Vault()
    out = proxy._mask_text("ANNA works at ACME", vault)
    assert "ACME" in out, "ORG value must pass through raw by default"
    assert "ANNA" not in out, "PERSON must still be masked"
    assert "<REF_" in out
    # ACME never entered the vault
    assert all(e.label != "ORG" for e in vault.all_entries())


def test_org_masked_when_skip_labels_cleared(monkeypatch) -> None:
    _install_detector(monkeypatch)
    monkeypatch.setattr(proxy, "SKIP_LABELS", frozenset())
    vault = Vault()
    out = proxy._mask_text("ANNA works at ACME", vault)
    assert "ACME" not in out, "with SKIP_LABELS empty, ORG is masked too"
    assert "ANNA" not in out
    assert any(e.label == "ORG" for e in vault.all_entries())


def test_filename_skipped_by_default(monkeypatch) -> None:
    """apf-j4w: a bare generic filename is detected but not masked —
    masking it adds vault noise and makes filenames indistinguishable to
    the model (the W3 Hermes comprehension thrash)."""
    class _Stub:
        name = "stub"

        def detect(self, text: str):
            i = text.index("notes.txt")
            return [Span(start=i, end=i + 9, label="FILENAME",
                         tier="B", confidence=1.0)]
    monkeypatch.setattr(proxy, "_DETECTOR", _Stub())
    monkeypatch.setattr(proxy, "SKIP_LABELS", frozenset({"ORG", "FILENAME"}))
    vault = Vault()
    out = proxy._mask_text("write it to notes.txt", vault)
    assert "notes.txt" in out, "FILENAME must pass through raw by default"
    assert "<REF_" not in out
    assert all(e.label != "FILENAME" for e in vault.all_entries())


def test_load_skip_labels_default(monkeypatch) -> None:
    monkeypatch.delenv("APF_SKIP_LABELS", raising=False)
    assert proxy._load_skip_labels() == frozenset({"ORG", "FILENAME"})


def test_load_skip_labels_empty_masks_everything(monkeypatch) -> None:
    monkeypatch.setenv("APF_SKIP_LABELS", "")
    assert proxy._load_skip_labels() == frozenset()


def test_load_skip_labels_custom(monkeypatch) -> None:
    monkeypatch.setenv("APF_SKIP_LABELS", "ORG, DATE ,LOCATION")
    assert proxy._load_skip_labels() == frozenset({"ORG", "DATE", "LOCATION"})
