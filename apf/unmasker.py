"""Restore originals in text emitted by the LLM.

Walks the text, finds `<REF_N>` patterns and (apf-okt) any surrogate
surface forms minted by the vault, swaps each for its original. The bare
`<REF>` surface token (Tier-C) is intentionally *not* resolved here —
that would expose the secret to LLM-facing output. Callers wanting to
resolve secrets must use the tool-call resolver path with an explicit
secret store lookup.
"""
from __future__ import annotations

import os
import re

from .vault import Vault

TOKEN_RE = re.compile(r"<([A-Z_][A-Z0-9_]*?)_(\d+)>")

# apf-b3j: opt-in debug marker. When APF_UNMASK_MARKER is set, every
# value the unmasker actually restores gets the marker string appended
# ('anna müller✓'). Makes the round-trip observable in test runs — lets
# you tell 'the unmasker restored this' apart from 'the value was never
# masked and passed through raw' (visually identical otherwise).
# Empty by default → output is byte-identical to no marker. Test/debug
# only; never enable in production (it mutates user-facing text).
_UNMASK_MARKER = os.environ.get("APF_UNMASK_MARKER", "")


def unmask_text(text: str, vault: Vault, restore_secrets: bool = False) -> str:
    """Replace each `<REF_N>` token in `text` with its vault original.

    Bare `<REF>` (Tier-C) is left as-is by default. Pass restore_secrets=True
    ONLY in contexts that should never reach the LLM (e.g. the user-facing
    rendered response shown locally), and ideally not even then — Tier C
    should be pulled from a secret store, not from the vault.
    """
    def replace(m: re.Match[str]) -> str:
        token = m.group(0)
        original = vault.get_original(token)
        if original is None:
            return token  # unresolved token — left as-is, no marker
        return original + _UNMASK_MARKER

    out = TOKEN_RE.sub(replace, text)

    # apf-okt: surrogate surface forms are plain strings (a fake name,
    # IP, …), not <REF_N> tokens — restore them by scan. Longest-first so
    # a short surrogate cannot corrupt a longer one it is a substring of.
    surrogates = [(e.surrogate, e.original) for e in vault.all_entries()
                  if e.surrogate is not None]
    for surrogate, original in sorted(surrogates, key=lambda p: -len(p[0])):
        if surrogate in out:
            out = out.replace(surrogate, original + _UNMASK_MARKER)

    if restore_secrets:
        # Replace bare `<REF>` markers — but the surface token is intentionally
        # ambiguous, so we can only restore if there's exactly one Tier C
        # entry in the vault. Otherwise leave them alone.
        secret_entries = [e for e in vault.all_entries() if e.tier == "C"]
        if "<REF>" in out and len(secret_entries) == 1:
            # `<REF>` and `<REF_N>` are distinct literals — the latter
            # contains `<REF_` not `<REF>`, so a plain replace is safe.
            out = out.replace("<REF>", secret_entries[0].original)

    return out
