"""Vendored DontFeedTheAI regex detector adapter.

Wraps `vendor/dontfeedtheai/src/regex_detector.py` (pinned via git submodule)
so its 181 regex patterns are available as a detector in our harness with
our tier-tagged Span output.

Upstream: https://github.com/zeroc00I/DontFeedTheAI (license claimed MIT in
README; LICENSE file pending — see upstream issue #3 we filed).

Why this is worth vendoring:
- 181 patterns vs our ~25, especially strong on:
  - vendor API-key prefixes (Anthropic sk-ant-, Groq gsk_, Cerebras csk-,
    SambaNova sk_sn-, Mistral, Together, OpenRouter, Replicate, ElevenLabs)
  - hash families (NTLM 32/48, SHA-1, SHA-256, MD5, NTLM-challenge)
  - national IDs (Brazilian CPF/CNPJ/RG, common patterns)
  - AD/Kerberos-shaped identifiers
- Maintained by an active community (62 forks, regular pushes).

Known issue with their API:
- `RegexMatch` has only `(text, entity_type)` — no character offsets, even
  though they track them internally in `detect()`. We recover offsets via
  `text.find(match.text)` here as a workaround. PR upstream to add optional
  start/end fields is a planned tier-1 contribution.

Tier mapping is a judgement call where their flat entity-type model doesn't
align with our A/B/C tiers. Documented inline below.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .adapters import LABEL_TIER, Span

_ROOT = Path(__file__).resolve().parent.parent
_VENDOR = _ROOT / "vendor" / "dontfeedtheai"

if _VENDOR.exists() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

try:
    from src import regex_detector as _dfta  # type: ignore[import-not-found]
    _DFTA_AVAILABLE = True
except Exception:
    _DFTA_AVAILABLE = False


# DFTA entity_type → our label inventory. Where their flat model doesn't
# match our tier model cleanly, the choice is documented:
DFTA_LABEL_MAP: dict[str, str] = {
    # Network operational (Tier B)
    "IP_ADDRESS": "IP",
    "CIDR": "IP",
    "MAC_ADDRESS": "IP",     # closest Tier-B mapping; MAC is a network identifier
    "URL": "URL_LOCAL",
    "DOMAIN": "HOSTNAME",
    "HOSTNAME": "HOSTNAME",
    "PATH": "PATH",
    # Content (Tier A)
    "EMAIL_ADDRESS": "EMAIL",
    "PERSON": "PERSON",
    "USERNAME": "PERSON",    # AD-style usernames map to PERSON in our model
    "ORGANIZATION": "ORG",
    "IDENTIFIER": "NOTE_SENSITIVE",  # generic ID — could be SSN, CPF, etc.
    # Secrets (Tier C)
    "HASH": "CREDENTIAL",    # pentest hashes are credential-equivalent (NTLM, MD5 of password)
    "TOKEN": "TOKEN",
    "CREDENTIAL": "PASSWORD",
    # Special / project-specific — drop
    "CONTOSO": None,         # MS test data, not real PII
    "OTHER": None,
}


def _find_offset(text: str, value: str, taken: set[tuple[int, int]]) -> tuple[int, int] | None:
    """Locate `value` in `text`, returning the first occurrence not already in
    `taken` (a set of (start,end) already used in this call)."""
    pos = 0
    while True:
        idx = text.find(value, pos)
        if idx < 0:
            return None
        end = idx + len(value)
        if not any(s <= idx < e or s < end <= e for s, e in taken):
            return idx, end
        pos = idx + 1


class DftaRegexAdapter:
    """The vendored regex set, run as a standalone detector. Tier-A spans
    (PERSON / ORGANIZATION etc.) will produce many false positives outside
    pentest contexts — these patterns assume LLM-orchestrated context. Use
    in ensembles where stronger NER (GLiNER) deduplicates."""

    name = "dfta-regex"

    def warmup(self) -> None:
        if not _DFTA_AVAILABLE:
            raise RuntimeError(
                "DontFeedTheAI submodule not initialized. "
                "Run: git submodule update --init vendor/dontfeedtheai"
            )

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        taken: set[tuple[int, int]] = set()
        for match in _dfta.detect(text):
            our_label = DFTA_LABEL_MAP.get(match.entity_type)
            if our_label is None:
                continue
            tier = LABEL_TIER.get(our_label)
            if tier is None:
                continue
            # Prefer native start/end (added upstream by our PR; default -1 on
            # older pins). Fall back to text.find() for compatibility.
            ms = getattr(match, "start", -1)
            me = getattr(match, "end", -1)
            if ms >= 0 and me > ms and text[ms:me] == match.text:
                start, end = ms, me
            else:
                offset = _find_offset(text, match.text, taken)
                if offset is None:
                    continue
                start, end = offset
            taken.add((start, end))
            spans.append(Span(
                start=start, end=end,
                label=our_label, tier=tier,
                confidence=1.0,
            ))
        spans.sort(key=lambda s: s.start)
        return spans


def register(adapters: dict) -> None:
    if _DFTA_AVAILABLE:
        adapters["dfta-regex"] = DftaRegexAdapter
