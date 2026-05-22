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


# ── apf-tu9: tolerant resolution of mangled REF token variants ──────────────
#
# A weak upstream model does not always pass `<REF_N>` through verbatim. The
# tolerant resolver recognises a bounded set of mangling variants and still
# resolves them to the vaulted original — but only when the mangled form
# unambiguously maps to exactly one minted vault token. Where it does not, the
# value is left untouched so the breakage stays loud and detectable rather
# than a silent garbage passthrough.


def test_resolves_brackets_stripped() -> None:
    # variant class: brackets stripped — `<REF_1>` → `REF_1`
    vault, tok = _vault_with(("anna@example.de", "EMAIL"))
    # tok value is "<REF_1>"; the mangled form drops the angle brackets
    mangled = tok["anna@example.de"].strip("<>")
    out = resolve_tool_call_args(f"send to {mangled}", vault)
    assert out == "send to anna@example.de"


def test_resolves_case_changed_lower() -> None:
    # variant class: case changed — `<REF_1>` → `ref_1`
    vault, _ = _vault_with(("anna@example.de", "EMAIL"))
    out = resolve_tool_call_args("send to ref_1", vault)
    assert out == "send to anna@example.de"


def test_resolves_case_changed_title() -> None:
    # variant class: case changed — `<REF_1>` → `Ref_1`
    vault, _ = _vault_with(("anna@example.de", "EMAIL"))
    out = resolve_tool_call_args("send to Ref_1", vault)
    assert out == "send to anna@example.de"


def test_resolves_case_changed_with_brackets() -> None:
    # case change can also keep the brackets — `<ref_1>`
    vault, _ = _vault_with(("anna@example.de", "EMAIL"))
    out = resolve_tool_call_args("send to <ref_1>", vault)
    assert out == "send to anna@example.de"


def test_resolves_whitespace_inside_brackets() -> None:
    # variant class: whitespace injected — `< REF_1 >`
    vault, _ = _vault_with(("anna@example.de", "EMAIL"))
    out = resolve_tool_call_args("send to < REF_1 >", vault)
    assert out == "send to anna@example.de"


def test_resolves_whitespace_around_underscore() -> None:
    # variant class: whitespace injected — `REF 1` (underscore lost to space)
    vault, _ = _vault_with(("anna@example.de", "EMAIL"))
    out = resolve_tool_call_args("send to REF 1", vault)
    assert out == "send to anna@example.de"


def test_resolves_shape_normalised_email() -> None:
    # THE canonical apf-2qz case: Qwen2.5-Coder-7B turned `<REF_1>` into the
    # email-shaped string `REF_1@example.com`. The hallucinated `@example.com`
    # decoration is noise; the whole mangled token resolves to the original.
    vault, _ = _vault_with(("anna@example.de", "EMAIL"))
    out = resolve_tool_call_args("REF_1@example.com", vault)
    assert out == "anna@example.de"


def test_resolves_shape_normalised_url() -> None:
    # variant class: shape-normalised — `ref-1.example` (url-shaped)
    vault, _ = _vault_with(("https://intra.acme.test/x", "URL"))
    out = resolve_tool_call_args("fetch ref-1.example", vault)
    assert out == "fetch https://intra.acme.test/x"


def test_shape_normalised_email_in_nested_args() -> None:
    vault, _ = _vault_with(("anna@example.de", "EMAIL"))
    args = {"to": "REF_1@example.com", "cc": ["ref_1", "keep@as.is"]}
    out = resolve_tool_call_args(args, vault)
    assert out == {"to": "anna@example.de",
                   "cc": ["anna@example.de", "keep@as.is"]}


def test_mangled_unknown_id_left_literal() -> None:
    # a mangled token whose ID was never minted must NOT be resolved — it
    # stays literal so the breakage is loud, not a silent garbage value.
    vault, _ = _vault_with(("anna@example.de", "EMAIL"))  # mints <REF_1>
    out = resolve_tool_call_args("send to REF_99@example.com", vault)
    assert out == "send to REF_99@example.com"


def test_mangled_resolution_is_conservative_about_plain_words() -> None:
    # 'reference', 'referee', 'preferred' etc. contain 'ref' but no digit —
    # the tolerant matcher must require the REF<sep>digit shape and never
    # touch ordinary prose.
    vault, _ = _vault_with(("anna@example.de", "EMAIL"))
    text = "the preferred referee gave a reference"
    assert resolve_tool_call_args(text, vault) == text


def test_strict_token_still_resolves() -> None:
    # the tolerant layer must not regress the strict path.
    vault, tok = _vault_with(("anna@example.de", "EMAIL"))
    out = resolve_tool_call_args(tok["anna@example.de"], vault)
    assert out == "anna@example.de"


def test_bare_ref_not_touched_by_tolerant_layer() -> None:
    # bare Tier-C `<REF>` (no number) is cardinality-ambiguous by design.
    # The tolerant layer keys on the numeric ID, so a numberless `REF`
    # must never be resolved by it — secrets stay opaque.
    vault = Vault()
    vault.get_or_mint("xk-live-secret", "API_KEY", "C")
    # no secret_resolver passed → bare <REF> must survive untouched, and
    # 'REF' / 'ref' with no digit must likewise be ignored.
    assert resolve_tool_call_args("Bearer <REF>", vault) == "Bearer <REF>"
    assert resolve_tool_call_args("Bearer REF", vault) == "Bearer REF"
    assert resolve_tool_call_args("Bearer ref", vault) == "Bearer ref"


def test_mangled_does_not_shadow_secret_resolver() -> None:
    # bare <REF> still routes through the secret_resolver; the tolerant
    # layer for numbered tokens must not interfere.
    vault = Vault()
    out = resolve_tool_call_args(
        "Bearer <REF>", vault, secret_resolver=lambda: "xk-live-secret")
    assert out == "Bearer xk-live-secret"


def test_fail_loud_callback_fires_on_unresolved_mangled_token() -> None:
    # fail-loud contract: a token that *looks* mangled (REF + digit shape)
    # but maps to no minted vault ID is reported via the on_unresolved hook
    # so a caller can log / alert instead of shipping a broken value blind.
    vault, _ = _vault_with(("anna@example.de", "EMAIL"))  # mints <REF_1>
    seen: list[str] = []
    out = resolve_tool_call_args(
        "send to REF_99@example.com", vault,
        on_unresolved=lambda variant: seen.append(variant))
    assert out == "send to REF_99@example.com"  # still left literal
    assert seen == ["REF_99@example.com"]


def test_fail_loud_callback_silent_when_all_resolve() -> None:
    # the hook must NOT fire for tokens that resolve cleanly (strict or
    # tolerant) — only genuinely unresolvable mangled shapes.
    vault, tok = _vault_with(("anna@example.de", "EMAIL"))
    seen: list[str] = []
    resolve_tool_call_args(tok["anna@example.de"], vault,
                           on_unresolved=lambda v: seen.append(v))
    resolve_tool_call_args("ref_1 and REF_1@example.com", vault,
                           on_unresolved=lambda v: seen.append(v))
    assert seen == []


def test_fail_loud_callback_not_fired_for_bare_ref() -> None:
    # bare <REF> is deliberately ambiguous, not 'unresolved/mangled' —
    # it must never trip the fail-loud hook.
    vault = Vault()
    vault.get_or_mint("xk-live-secret", "API_KEY", "C")
    seen: list[str] = []
    resolve_tool_call_args("Bearer <REF>", vault,
                           on_unresolved=lambda v: seen.append(v))
    assert seen == []
