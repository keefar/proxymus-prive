"""apf-okt: unmask_text restores surrogate surface forms.

A surrogate is a plain string (a fake name, IP, …), not a <REF_N>
token, so it is restored by scan — longest-first so a short surrogate
cannot corrupt a longer one.
"""
from __future__ import annotations

import apf.unmasker as unmasker
from apf.unmasker import unmask_text
from apf.vault import Vault


def _mint(vault: Vault, original: str, surrogate: str, label: str = "PERSON"):
    return vault.get_or_mint(original, label, "A",
                             surrogate_gen=lambda: surrogate)


def test_restores_a_surrogate() -> None:
    vault = Vault()
    _mint(vault, "Anna Müller", "Petra Vogel")
    assert unmask_text("call Petra Vogel today", vault) \
        == "call Anna Müller today"


def test_restores_surrogate_and_opaque_token_together() -> None:
    vault = Vault()
    _mint(vault, "Anna Müller", "Petra Vogel")
    opaque = vault.get_or_mint("secret-path", "PATH", "B")  # opaque <REF_N>
    text = f"Petra Vogel edited {opaque.surface}"
    assert unmask_text(text, vault) == "Anna Müller edited secret-path"


def test_longest_first_avoids_substring_corruption() -> None:
    vault = Vault()
    _mint(vault, "Hamburg", "Bremen")
    _mint(vault, "Bremerhaven harbour", "Bremen Nord harbour")
    # "Bremen" is a substring of "Bremen Nord harbour" — the longer
    # surrogate must be restored first.
    out = unmask_text("trip: Bremen Nord harbour", vault)
    assert out == "trip: Bremerhaven harbour"


def test_surrogate_absent_from_text_is_noop() -> None:
    vault = Vault()
    _mint(vault, "Anna Müller", "Petra Vogel")
    assert unmask_text("nothing to see", vault) == "nothing to see"


def test_opaque_only_vault_unchanged_behaviour() -> None:
    vault = Vault()
    e = vault.get_or_mint("Anna Müller", "PERSON", "A")  # no surrogate
    assert unmask_text(f"hi {e.surface}", vault) == "hi Anna Müller"


def test_marker_applies_to_surrogate_restores(monkeypatch) -> None:
    monkeypatch.setattr(unmasker, "_UNMASK_MARKER", "✓")
    vault = Vault()
    _mint(vault, "Anna Müller", "Petra Vogel")
    assert unmask_text("Petra Vogel", vault) == "Anna Müller✓"
