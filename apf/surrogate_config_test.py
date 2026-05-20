"""apf-okt: APF_SURROGATE_LABELS proxy wiring.

The env config is always intersected with the ratified hybrid set, so a
misconfiguration naming a sensitive category cannot surrogate it.
"""
from __future__ import annotations

import apf.proxy as proxy
from apf.masker import Span
from apf.surrogates import SURROGATE_LABELS
from apf.vault import Vault


def test_default_is_empty_opaque(monkeypatch) -> None:
    monkeypatch.delenv("APF_SURROGATE_LABELS", raising=False)
    assert proxy._load_surrogate_labels() == frozenset()


def test_explicit_label_list(monkeypatch) -> None:
    monkeypatch.setenv("APF_SURROGATE_LABELS", "person, email")
    assert proxy._load_surrogate_labels() == frozenset({"PERSON", "EMAIL"})


def test_all_keyword_expands_to_hybrid_set(monkeypatch) -> None:
    monkeypatch.setenv("APF_SURROGATE_LABELS", "all")
    assert proxy._load_surrogate_labels() == SURROGATE_LABELS


def test_sensitive_category_is_intersected_out(monkeypatch) -> None:
    # HEALTH is not in the ratified hybrid set — must be dropped
    monkeypatch.setenv("APF_SURROGATE_LABELS", "PERSON,HEALTH")
    assert proxy._load_surrogate_labels() == frozenset({"PERSON"})


def test_only_sensitive_yields_empty(monkeypatch) -> None:
    monkeypatch.setenv("APF_SURROGATE_LABELS", "HEALTH,API_KEY")
    assert proxy._load_surrogate_labels() == frozenset()


def _install_detector(monkeypatch) -> None:
    class _Stub:
        name = "stub"

        def detect(self, text: str):
            spans = []
            if "Anna" in text:
                i = text.index("Anna")
                spans.append(Span(start=i, end=i + 4, label="PERSON",
                                  tier="A", confidence=1.0))
            return spans
    monkeypatch.setattr(proxy, "_DETECTOR", _Stub())


def test_mask_text_opaque_when_config_empty(monkeypatch) -> None:
    _install_detector(monkeypatch)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_CONFIG", frozenset())
    out = proxy._mask_text("hi Anna there", Vault())
    assert out == "hi <REF_1> there"


def test_mask_text_surrogates_when_configured(monkeypatch) -> None:
    _install_detector(monkeypatch)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_CONFIG",
                        frozenset({"PERSON"}))
    vault = Vault()
    out = proxy._mask_text("hi Anna there", vault)
    assert "Anna" not in out               # original gone
    assert "<REF" not in out               # surrogate, not an opaque token
    assert vault.all_entries()[0].surrogate is not None
