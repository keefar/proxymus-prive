"""apf-b3j: unmasker test-marker.

APF_UNMASK_MARKER appends a marker to every value the unmasker
actually restores — makes the round-trip observable in test runs.
Default (unset) → output byte-identical to no marker. The marker must
NOT bleed into the tool-call resolver path (would corrupt tool args).
"""
from __future__ import annotations

import apf.unmasker as detok
from apf.unmasker import unmask_text
from apf.resolver import resolve_tool_call_args
from apf.vault import Vault


def _vault_with(original: str, label: str = "PERSON", tier: str = "A") -> tuple[Vault, str]:
    vault = Vault()
    entry = vault.get_or_mint(original, label, tier)
    return vault, entry.token


def test_no_marker_by_default(monkeypatch) -> None:
    monkeypatch.setattr(detok, "_UNMASK_MARKER", "")
    vault, token = _vault_with("anna müller")
    out = unmask_text(f"hello {token} how are you", vault)
    assert out == "hello anna müller how are you"


def test_marker_appended_when_set(monkeypatch) -> None:
    monkeypatch.setattr(detok, "_UNMASK_MARKER", "✓")
    vault, token = _vault_with("anna müller")
    out = unmask_text(f"hello {token}", vault)
    assert out == "hello anna müller✓"


def test_marker_on_every_restored_value(monkeypatch) -> None:
    monkeypatch.setattr(detok, "_UNMASK_MARKER", "✓")
    vault = Vault()
    t1 = vault.get_or_mint("anna", "PERSON", "A").token
    t2 = vault.get_or_mint("bob@x.de", "EMAIL", "A").token
    out = unmask_text(f"{t1} mailed {t2}", vault)
    assert out == "anna✓ mailed bob@x.de✓"


def test_unresolved_token_gets_no_marker(monkeypatch) -> None:
    """A <REF_N> not present in the vault is left as-is — no marker, so
    the marker genuinely signals 'restored', not just 'token-shaped'."""
    monkeypatch.setattr(detok, "_UNMASK_MARKER", "✓")
    vault = Vault()  # empty
    out = unmask_text("dangling <REF_9> token", vault)
    assert out == "dangling <REF_9> token"


def test_marker_does_not_leak_into_tool_resolver(monkeypatch) -> None:
    """The resolver path (tool-call args) must stay marker-free — a marker
    in a tool argument would corrupt real tool execution."""
    monkeypatch.setattr(detok, "_UNMASK_MARKER", "✓")
    vault, token = _vault_with("anna@example.de", "EMAIL", "A")
    resolved = resolve_tool_call_args({"to": token}, vault)
    assert resolved == {"to": "anna@example.de"}, \
        "tool-call resolution must not carry the debug marker"
