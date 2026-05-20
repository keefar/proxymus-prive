"""apf-okt (7/7): full surrogate round-trip.

Composes the whole pipeline against one vault — mask (surrogate surface
forms), unmask (response restore), resolve (tool-call boundary) — to
verify the layers fit together, and that the hybrid boundary holds:
Tier-A identifiers are surrogated, a Tier-C secret stays opaque.
"""
from __future__ import annotations

from apf.masker import Span, mask_text
from apf.resolver import resolve_tool_call_args
from apf.unmasker import unmask_text
from apf.vault import Vault


def _span(text: str, value: str, label: str, tier: str = "A") -> Span:
    i = text.index(value)
    return Span(start=i, end=i + len(value), label=label, tier=tier,
                confidence=1.0)


def test_mask_unmask_resolve_round_trip() -> None:
    vault = Vault()
    enabled = frozenset({"PERSON", "EMAIL"})
    text = "email Anna Müller at anna@example.de"
    spans = [_span(text, "Anna Müller", "PERSON"),
             _span(text, "anna@example.de", "EMAIL")]

    masked = mask_text(text, spans, vault, surrogate_labels=enabled)
    # the wire carries plausible surrogates — no originals, no opaque tokens
    assert "Anna Müller" not in masked
    assert "anna@example.de" not in masked
    assert "<REF" not in masked

    # response path: the model echoes the surrogates → user sees originals
    assert unmask_text(masked, vault) == text

    # tool-call boundary: the model emits a tool call with the surrogate
    # values it saw → the local executor must get the real values
    by_label = {e.label: e for e in vault.all_entries()}
    tool_args = {"to": by_label["EMAIL"].surrogate,
                 "body": f"Hi {by_label['PERSON'].surrogate}"}
    resolved = resolve_tool_call_args(tool_args, vault)
    assert resolved == {"to": "anna@example.de", "body": "Hi Anna Müller"}


def test_hybrid_secret_stays_opaque_in_round_trip() -> None:
    vault = Vault()
    text = "Anna Müller key xk-live-SECRET42"
    spans = [_span(text, "Anna Müller", "PERSON"),
             _span(text, "xk-live-SECRET42", "API_KEY", tier="C")]

    masked = mask_text(text, spans, vault,
                       surrogate_labels=frozenset({"PERSON"}))
    assert "<REF>" in masked                  # secret stays opaque
    assert "Anna Müller" not in masked         # person is surrogated
    assert "xk-live-SECRET42" not in masked

    restored = unmask_text(masked, vault)
    assert "Anna Müller" in restored           # person restored
    assert "<REF>" in restored                 # secret left for the executor
