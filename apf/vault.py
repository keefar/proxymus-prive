"""Session-scoped vault mapping original PII values to opaque tokens.

Token shape decisions (per docs/THREAT-MODEL-PRIVATE.md §5.1)
-------------------------------------------------------------
- Tier A and B: `<SENSITIVE_{N}>` where N is a single session-global counter.
  All categories share the same opaque surface so the LLM cannot deduce
  what kind of thing the placeholder represents (no <MEDICATION_1> /
  <DIAGNOSIS_2> distinction to cascade-leak the original value via context
  inference). Same original value → same token (stable within session).
  The internal `label` and `third_party` attributes survive on the entry
  for evaluation, audit, and out-of-band metadata channels — they're just
  not exposed in the surface token name.
- Tier C (secrets): always `<SECRET>` — opaque, no type, no number. The LLM
  must not gain any information about what kind of secret it is. When a tool
  needs the real value, the local executor pulls it from environment /
  keychain, NOT from the vault. The vault stores Tier C entries for
  *auditing* and for the rare case where the executor genuinely needs the
  original (e.g. password copy-paste), but the surface API for the LLM only
  ever exposes `<SECRET>`.

Third-party flag (per §5.2)
---------------------------
Entries carry an orthogonal `third_party` attribute when the original value
identifies someone other than the user (a friend, family member, colleague).
This does NOT change the surface token — all sensitive values are equally
opaque — but it is preserved for audit and for future cumulative-profile
warnings that should weight third-party leakage separately.

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
    third_party: bool = False
    # For Tier-C entries detected via a KEY=VALUE pattern: the KEY name.
    # The secret resolver can look this up in env/Keychain at tool-call time
    # so the real secret is supplied by the local store, not the vault.
    secret_key_name: str | None = None


class Vault:
    """In-memory session vault. Not thread-safe across sessions; the lock
    here is for concurrent access *within* one session."""

    def __init__(self) -> None:
        # original-text → entry (so we deduplicate by value)
        self._by_original: dict[str, VaultEntry] = {}
        # token → entry (for fast reverse lookup)
        self._by_token: dict[str, VaultEntry] = {}
        # single session-global counter for Tier A/B opaque tokens
        self._sensitive_counter: int = 0
        # User-declared bypass values (per apf-qzc). Spans matching any of
        # these are NOT tokenised — the original passes through to the LLM.
        # Populated by inline `!raw VALUE` markers and the
        # POST /v1/sessions/{id}/whitelist endpoint.
        self._whitelist: set[str] = set()
        self._lock = Lock()

    def add_whitelist(self, value: str) -> None:
        with self._lock:
            self._whitelist.add(value)

    def is_whitelisted(self, value: str) -> bool:
        return value in self._whitelist

    def whitelist_size(self) -> int:
        return len(self._whitelist)

    def get_or_mint(self, original: str, label: str, tier: str,
                    confidence: float = 1.0,
                    secret_key_name: str | None = None,
                    third_party: bool = False) -> VaultEntry:
        """Return an existing entry for this value or mint a new one.

        If the value has been seen before, the entry's `confidence` is
        updated to the *minimum* of the existing and the new value — so if
        any detection of this string was uncertain, the entry stays flagged
        as uncertain. (A single high-confidence detection should not
        override an earlier low-confidence one.)

        The internal `label` is preserved on the entry but does NOT appear
        in the surface token — see module docstring §5.1.
        """
        with self._lock:
            entry = self._by_original.get(original)
            if entry is not None:
                if confidence < entry.confidence:
                    entry = VaultEntry(
                        token=entry.token, original=entry.original,
                        label=entry.label, tier=entry.tier,
                        confidence=confidence,
                        third_party=entry.third_party,
                        secret_key_name=entry.secret_key_name,
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
                                   confidence=confidence,
                                   third_party=third_party,
                                   secret_key_name=secret_key_name)
                self._by_original[original] = entry
                self._by_token[internal_token] = entry
            else:
                self._sensitive_counter += 1
                token = f"<SENSITIVE_{self._sensitive_counter}>"
                entry = VaultEntry(token=token, original=original,
                                   label=label, tier=tier,
                                   confidence=confidence,
                                   third_party=third_party)
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

    def summary(self) -> dict:
        """Compact session summary for the UX-feedback header.

        Returns counts only — no original values or surface tokens — so this
        can be exposed via response header / status endpoint without itself
        becoming a leak channel. The keys are stable strings safe to render
        in a UI.
        """
        per_tier: dict[str, int] = {}
        per_label: dict[str, int] = {}
        third_party = 0
        for e in self._by_original.values():
            per_tier[e.tier] = per_tier.get(e.tier, 0) + 1
            per_label[e.label] = per_label.get(e.label, 0) + 1
            if e.third_party:
                third_party += 1
        return {
            "total": len(self._by_original),
            "per_tier": per_tier,
            "per_label": per_label,
            "third_party": third_party,
        }

    def __len__(self) -> int:
        return len(self._by_original)
