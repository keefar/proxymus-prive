"""apf-3bx: unit coverage for the tool-call boundary resolver.

resolve_tool_call_args walks a JSON-shaped tool-call argument structure
and substitutes vault tokens (<REF_N>) with originals and the bare
Tier-C secret marker (<REF>) via a secret_resolver callback. It was
covered only transitively (proxy_test.py integration + the loopback
rig); these pin the unit-level edge cases directly.
"""
from __future__ import annotations

from apf.resolver import resolve_tool_call_args
from apf.vault import Vault


def _vault_with(*pairs: tuple[str, str]) -> tuple[Vault, dict[str, str]]:
    """Build a vault from (original, label) pairs; return (vault,
    {original: token})."""
    vault = Vault()
    tokens = {}
    for original, label in pairs:
        tokens[original] = vault.get_or_mint(original, label, "A").token
    return vault, tokens


def test_resolves_token_in_plain_string() -> None:
    vault, tok = _vault_with(("anna müller", "PERSON"))
    out = resolve_tool_call_args(tok["anna müller"], vault)
    assert out == "anna müller"


def test_resolves_token_embedded_in_larger_string() -> None:
    vault, tok = _vault_with(("/Users/chris/notes.txt", "PATH"))
    out = resolve_tool_call_args(f"cat {tok['/Users/chris/notes.txt']}", vault)
    assert out == "cat /Users/chris/notes.txt"


def test_resolves_nested_dict_and_list() -> None:
    vault, tok = _vault_with(("anna@example.de", "EMAIL"),
                             ("Anna Müller", "PERSON"))
    args = {
        "to": tok["anna@example.de"],
        "cc": [tok["anna@example.de"], "plain@nowhere.test"],
        "meta": {"sender": tok["Anna Müller"]},
    }
    out = resolve_tool_call_args(args, vault)
    assert out == {
        "to": "anna@example.de",
        "cc": ["anna@example.de", "plain@nowhere.test"],
        "meta": {"sender": "Anna Müller"},
    }


def test_non_string_leaves_pass_through() -> None:
    vault, _ = _vault_with(("anna müller", "PERSON"))
    args = {"count": 3, "ratio": 1.5, "enabled": True, "missing": None}
    assert resolve_tool_call_args(args, vault) == args


def test_plaintext_without_tokens_unchanged() -> None:
    vault, _ = _vault_with(("anna müller", "PERSON"))
    assert resolve_tool_call_args("no tokens here", vault) == "no tokens here"


def test_unknown_token_is_left_literal() -> None:
    # a <REF_N> the vault never minted must pass through untouched, not
    # raise and not resolve to something else.
    vault, _ = _vault_with(("anna müller", "PERSON"))
    out = resolve_tool_call_args("ref <REF_99> here", vault)
    assert out == "ref <REF_99> here"


def test_bare_ref_filled_by_secret_resolver() -> None:
    vault = Vault()
    out = resolve_tool_call_args(
        "Bearer <REF>", vault, secret_resolver=lambda: "xk-live-secret")
    assert out == "Bearer xk-live-secret"


def test_bare_ref_kept_when_no_resolver() -> None:
    vault = Vault()
    # explicit is better than silently leaking: <REF> stays put.
    assert resolve_tool_call_args("Bearer <REF>", vault) == "Bearer <REF>"


def test_bare_ref_kept_when_resolver_returns_none() -> None:
    vault = Vault()
    out = resolve_tool_call_args(
        "Bearer <REF>", vault, secret_resolver=lambda: None)
    assert out == "Bearer <REF>"


def test_returns_new_structure_not_mutated_input() -> None:
    vault, tok = _vault_with(("anna müller", "PERSON"))
    args = {"to": tok["anna müller"]}
    out = resolve_tool_call_args(args, vault)
    assert args == {"to": tok["anna müller"]}  # input untouched
    assert out == {"to": "anna müller"}


# ── apf-okt: surrogate resolution at the tool boundary ──────────────────────

def _surrogate(vault: Vault, original: str, surrogate: str,
               label: str = "PERSON") -> str:
    vault.get_or_mint(original, label, "A", surrogate_gen=lambda: surrogate)
    return surrogate


def test_resolves_surrogate_to_original() -> None:
    vault = Vault()
    s = _surrogate(vault, "Anna Müller", "Petra Vogel")
    assert resolve_tool_call_args(f"email {s}", vault) == "email Anna Müller"


def test_resolves_surrogate_in_nested_args() -> None:
    vault = Vault()
    s = _surrogate(vault, "anna@real.de", "petra@fake.de", label="EMAIL")
    args = {"to": s, "cc": [s, "keep@as.is"]}
    assert resolve_tool_call_args(args, vault) == {
        "to": "anna@real.de", "cc": ["anna@real.de", "keep@as.is"]}


def test_resolves_surrogate_and_token_together() -> None:
    vault = Vault()
    s = _surrogate(vault, "Anna Müller", "Petra Vogel")
    tok = vault.get_or_mint("/secret/path", "PATH", "B").token
    out = resolve_tool_call_args(f"{s} -> {tok}", vault)
    assert out == "Anna Müller -> /secret/path"


def test_surrogate_longest_first() -> None:
    vault = Vault()
    _surrogate(vault, "Bonn", "Trier", label="LOCATION")
    _surrogate(vault, "Bonn Hauptbahnhof", "Trier Süd Terminal",
               label="LOCATION")
    out = resolve_tool_call_args("go to Trier Süd Terminal", vault)
    assert out == "go to Bonn Hauptbahnhof"


def test_surrogate_resolution_carries_no_marker(monkeypatch) -> None:
    # the resolver path must never append the unmask debug marker
    import apf.unmasker as unmasker
    monkeypatch.setattr(unmasker, "_UNMASK_MARKER", "✓")
    vault = Vault()
    s = _surrogate(vault, "Anna Müller", "Petra Vogel")
    assert resolve_tool_call_args(s, vault) == "Anna Müller"
