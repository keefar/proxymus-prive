"""apf-okt: mask_text surrogate substitution.

A span whose label is surrogate-enabled gets a plausible fake surface
form; everything else (and the empty-set default) stays opaque.
"""
from __future__ import annotations

from apf.masker import Span, mask_text
from apf.vault import Vault


def _span(text: str, value: str, label: str, tier: str = "A") -> Span:
    i = text.index(value)
    return Span(start=i, end=i + len(value), label=label, tier=tier,
                confidence=1.0)


def test_default_is_opaque() -> None:
    text = "mail to Anna Müller"
    out = mask_text(text, [_span(text, "Anna Müller", "PERSON")], Vault())
    assert out == "mail to <REF_1>"


def test_surrogate_label_gets_a_fake_value() -> None:
    text = "mail to Anna Müller"
    vault = Vault()
    out = mask_text(text, [_span(text, "Anna Müller", "PERSON")], vault,
                    surrogate_labels=frozenset({"PERSON"}))
    assert "Anna Müller" not in out
    assert "<REF" not in out          # surrogate, not an opaque token
    entry = vault.all_entries()[0]
    assert entry.surrogate is not None
    assert out == f"mail to {entry.surrogate}"


def test_label_not_in_set_stays_opaque() -> None:
    text = "Anna Müller on 2026-06-15"
    vault = Vault()
    out = mask_text(text, [_span(text, "Anna Müller", "PERSON"),
                           _span(text, "2026-06-15", "DATE")], vault,
                    surrogate_labels=frozenset({"PERSON"}))
    # PERSON surrogated, DATE still opaque
    assert "<REF" in out
    assert "Anna Müller" not in out


def test_non_hybrid_label_cannot_be_surrogated() -> None:
    # a misconfig naming a sensitive category must NOT surrogate it —
    # HEALTH is not in surrogates.SURROGATE_LABELS
    text = "diagnosis: Lexapro prescription"
    vault = Vault()
    out = mask_text(text, [_span(text, "Lexapro", "HEALTH")], vault,
                    surrogate_labels=frozenset({"HEALTH"}))
    assert out == "diagnosis: <REF_1> prescription"


def test_tier_c_secret_stays_opaque_alongside_a_surrogate() -> None:
    text = "Anna Müller key xk-live-XYZ"
    vault = Vault()
    out = mask_text(text, [_span(text, "Anna Müller", "PERSON"),
                           _span(text, "xk-live-XYZ", "API_KEY", tier="C")],
                    vault, surrogate_labels=frozenset({"PERSON"}))
    assert "<REF>" in out             # the secret
    assert "Anna Müller" not in out and "xk-live-XYZ" not in out


def test_surrogate_round_trips_via_vault() -> None:
    text = "call Anna Müller"
    vault = Vault()
    out = mask_text(text, [_span(text, "Anna Müller", "PERSON")], vault,
                    surrogate_labels=frozenset({"PERSON"}))
    surrogate = out.removeprefix("call ")
    assert vault.get_original(surrogate) == "Anna Müller"
