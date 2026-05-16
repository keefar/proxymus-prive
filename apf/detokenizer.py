"""Restore originals in text emitted by the LLM.

Walks the text, finds `<LABEL_N>` patterns, swaps each for its vault original.
The `<SECRET>` surface token is intentionally *not* resolved here — that
would expose the secret to LLM-facing output. Callers wanting to resolve
secrets must use the tool-call resolver path with an explicit secret store
lookup.
"""
from __future__ import annotations

import re

from .vault import Vault

TOKEN_RE = re.compile(r"<([A-Z_][A-Z0-9_]*?)_(\d+)>")


def detokenize_text(text: str, vault: Vault, restore_secrets: bool = False) -> str:
    """Replace each `<LABEL_N>` token in `text` with its vault original.

    `<SECRET>` is left as-is by default. Pass restore_secrets=True ONLY in
    contexts that should never reach the LLM (e.g. the user-facing rendered
    response shown locally), and ideally not even then — Tier C should be
    pulled from a secret store, not from the vault.
    """
    def replace(m: re.Match[str]) -> str:
        token = m.group(0)
        original = vault.get_original(token)
        return original if original is not None else token

    out = TOKEN_RE.sub(replace, text)

    if restore_secrets:
        # Replace `<SECRET>` markers — but the surface token is intentionally
        # ambiguous, so we can only restore if there's exactly one Tier C
        # entry in the vault. Otherwise leave them alone.
        secret_entries = [e for e in vault.all_entries() if e.tier == "C"]
        if "<SECRET>" in out and len(secret_entries) == 1:
            out = out.replace("<SECRET>", secret_entries[0].original)

    return out
