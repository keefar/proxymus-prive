"""Session-scoped vault mapping original PII values to opaque tokens.

Token shape decisions
---------------------
- Tier A and B: `<{LABEL}_{N}>` where N is a per-label counter incremented on
  first sight in the session. Same original value → same token (stable within
  the session). LLM sees these tokens and may reference them in its output
  and tool calls.
- Tier C (secrets): always `<SECRET>` — opaque, no type, no number. The LLM
  must not gain any information about what kind of secret it is. When a tool
  needs the real value, the local executor pulls it from environment /
  keychain, NOT from the vault. The vault stores Tier C entries for
  *auditing* and for the rare case where the executor genuinely needs the
  original (e.g. password copy-paste), but the surface API for the LLM only
  ever exposes `<SECRET>`.

Determinism
-----------
Vaults are per-session. Two calls within one Vault instance get the same
token for the same value. Different sessions intentionally get fresh
counters so token IDs don't leak information across sessions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass(frozen=True)
class VaultEntry:
    token: str
    original: str
    label: str
    tier: str
    confidence: float = 1.0  # min over all detections that produced this entry


class Vault:
    """In-memory session vault. Not thread-safe across sessions; the lock
    here is for concurrent access *within* one session."""

    def __init__(self) -> None:
        # original-text → entry (so we deduplicate by value)
        self._by_original: dict[str, VaultEntry] = {}
        # token → entry (for fast reverse lookup)
        self._by_token: dict[str, VaultEntry] = {}
        # per-label counter
        self._counters: dict[str, int] = {}
        self._lock = Lock()

    def get_or_mint(self, original: str, label: str, tier: str,
                    confidence: float = 1.0) -> VaultEntry:
        """Return an existing entry for this value or mint a new one.

        If the value has been seen before, the entry's `confidence` is
        updated to the *minimum* of the existing and the new value — so if
        any detection of this string was uncertain, the entry stays flagged
        as uncertain. (A single high-confidence detection should not
        override an earlier low-confidence one.)
        """
        with self._lock:
            entry = self._by_original.get(original)
            if entry is not None:
                if confidence < entry.confidence:
                    entry = VaultEntry(
                        token=entry.token, original=entry.original,
                        label=entry.label, tier=entry.tier,
                        confidence=confidence,
                    )
                    self._by_original[original] = entry
                    # Refresh by_token map
                    for k, v in list(self._by_token.items()):
                        if v.original == original:
                            self._by_token[k] = entry
                return entry
            if tier == "C":
                token = "<SECRET>"
                internal_token = f"<SECRET#{len(self._by_token) + 1}>"
                entry = VaultEntry(token=token, original=original,
                                   label=label, tier=tier,
                                   confidence=confidence)
                self._by_original[original] = entry
                self._by_token[internal_token] = entry
            else:
                n = self._counters.get(label, 0) + 1
                self._counters[label] = n
                token = f"<{label}_{n}>"
                entry = VaultEntry(token=token, original=original,
                                   label=label, tier=tier,
                                   confidence=confidence)
                self._by_original[original] = entry
                self._by_token[token] = entry
            return entry

    def low_confidence_entries(self, threshold: float = 0.85) -> list[VaultEntry]:
        """Entries whose confidence is below the high-confidence threshold.
        These are candidates for a "low-confidence flag" UX pathway: the
        user should see them surfaced for confirmation, since the detector
        wasn't sure they're really PII."""
        return [e for e in self._by_original.values()
                if e.confidence < threshold]

    def get_original(self, token: str) -> str | None:
        """Look up the original value for a token. Returns None if not found
        or if the token is a Tier-C surface token (which is intentionally
        ambiguous — caller must use a Tier-C-aware resolver instead)."""
        if token == "<SECRET>":
            return None  # Tier C surface token — ambiguous by design.
        entry = self._by_token.get(token)
        return entry.original if entry else None

    def all_entries(self) -> list[VaultEntry]:
        return list(self._by_original.values())

    def __len__(self) -> int:
        return len(self._by_original)
