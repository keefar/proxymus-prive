"""apf-4cs / apf-okt: masked values composed into a filesystem path.

A real agent does not blindly use a path — it verifies (lists the
directory, checks the value against context) and only then assembles
the final path. These tests exercise that: a masked value used in a
verify tool call and then composed into a path in a follow-up call,
plus the both-sides composition case.

Opaque <REF_N> is delimited and unambiguous — it survives composition,
adjacency and reuse, and resolves only itself. A surrogate is plain
text: it resolves only while it appears verbatim and nowhere else; a
common-word surrogate collides with an identical substring elsewhere
in the path. These tests pin both behaviours and the contrast.
"""
from __future__ import annotations

from apf.masker import Span, mask_text
from apf.resolver import resolve_tool_call_args
from apf.vault import Vault


def _span(text: str, value: str, label: str, tier: str) -> Span:
    i = text.index(value)
    return Span(start=i, end=i + len(value), label=label, tier=tier,
                confidence=1.0)


# ── opaque: robust under composition, adjacency and reuse ───────────────────

def test_opaque_token_composed_into_a_larger_path() -> None:
    vault = Vault()
    text = "move quarterly-reports into /srv/archive/2026"
    mask_text(text, [_span(text, "quarterly-reports", "PATH", "B"),
                     _span(text, "/srv/archive/2026", "PATH", "B")], vault)
    folder = vault.get_or_mint("quarterly-reports", "PATH", "B").token
    dest = vault.get_or_mint("/srv/archive/2026", "PATH", "B").token
    # the model assembles a full destination path from both tokens
    args = {"command": f"mv {folder} {dest}/{folder}"}
    out = resolve_tool_call_args(args, vault)
    assert out["command"] == \
        "mv quarterly-reports /srv/archive/2026/quarterly-reports"


def test_opaque_token_adjacent_to_text_still_resolves() -> None:
    vault = Vault()
    tok = vault.get_or_mint("/home/u/data", "PATH", "B").token
    # token glued to a suffix — <REF_N> is delimited, the resolver still
    # finds it
    out = resolve_tool_call_args({"command": f"cp {tok} {tok}.bak"}, vault)
    assert out["command"] == "cp /home/u/data /home/u/data.bak"


def test_opaque_token_survives_verify_then_act_reuse() -> None:
    # the agent first verifies the path exists, then acts on it — the
    # same token, two tool calls, one vault
    vault = Vault()
    tok = vault.get_or_mint("/srv/archive/2026", "PATH", "B").token
    verify = resolve_tool_call_args({"command": f"ls -ld {tok}"}, vault)
    assert verify["command"] == "ls -ld /srv/archive/2026"
    act = resolve_tool_call_args({"command": f"mkdir {tok}/incoming"}, vault)
    assert act["command"] == "mkdir /srv/archive/2026/incoming"


# ── surrogate: works while distinctive, collides on a repeated substring ────

def test_surrogate_value_composed_into_path_when_distinctive() -> None:
    vault = Vault()
    vault.get_or_mint("Hamburg", "LOCATION", "A",
                      surrogate_gen=lambda: "Trier")
    # the model composes the (surrogated) location into a path
    out = resolve_tool_call_args(
        {"command": "cd /data/Trier/exports"}, vault)
    assert out["command"] == "cd /data/Hamburg/exports"


def test_surrogate_collision_corrupts_identical_substring() -> None:
    """Characterisation test — a KNOWN apf-okt limitation, not desired
    behaviour. Surrogate resolution is substring str.replace: a surrogate
    that is also a substring elsewhere in the tool args is rewritten
    there too. Opaque <REF_N> is immune (next test). If word-boundary or
    position-aware resolution is added, update this test."""
    vault = Vault()
    vault.get_or_mint("Hamburg", "LOCATION", "A",
                      surrogate_gen=lambda: "Bremen")
    # /archive/Bremen = the surrogate (masked Hamburg); /mnt/Bremen = an
    # unrelated real path the model wrote — the resolver cannot tell them
    # apart and rewrites both
    out = resolve_tool_call_args(
        {"command": "cp /mnt/Bremen/r.txt /archive/Bremen/"}, vault)
    assert out["command"] == "cp /mnt/Hamburg/r.txt /archive/Hamburg/"


def test_opaque_is_immune_to_the_collision() -> None:
    # same shape as the collision test, but opaque — the unrelated
    # /mnt/Bremen survives untouched, only the token resolves
    vault = Vault()
    tok = vault.get_or_mint("Hamburg", "LOCATION", "A").token  # opaque
    out = resolve_tool_call_args(
        {"command": f"cp /mnt/Bremen/r.txt /archive/{tok}/"}, vault)
    assert out["command"] == "cp /mnt/Bremen/r.txt /archive/Hamburg/"
