"""Apply detector spans to text → masked text + vault.

The detector emits character-offset spans. The masker:
  1. Sorts spans, drops overlaps (later spans contained in earlier wins).
  2. Walks right-to-left so character offsets in the *remaining* text don't
     shift while substituting.
  3. For each span: get_or_mint a vault entry, replace the original substring
     with the surface token.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .vault import Vault


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str
    tier: str
    confidence: float = 1.0
    context_key: str | None = None  # for Tier-C: env-var name from KEY=VALUE
    third_party: bool = False       # value identifies someone other than user


def _dedupe_spans(spans: list[Span]) -> list[Span]:
    """Drop spans that are contained inside another span we already kept.
    Keep the *longest* span at each character position (consistent with the
    ensemble merge logic in benchmarks/adapters_mlx.py)."""
    by_start = sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
    kept: list[Span] = []
    for s in by_start:
        if any(k.start <= s.start and s.end <= k.end for k in kept):
            continue
        # If this span fully covers a kept smaller one, drop the smaller —
        # the outer span subsumes it.
        kept = [k for k in kept
                if not (s.start <= k.start and k.end <= s.end and s != k)]
        kept.append(s)
    return sorted(kept, key=lambda s: s.start)


def mask_text(text: str, spans: list[Span], vault: Vault) -> str:
    """Replace each span's substring with its vault token. Returns the
    masked text. Mutates the vault.

    Spans whose substring matches a user-declared bypass value
    (vault._whitelist, populated via inline `!raw` markers or the
    /v1/sessions/{id}/whitelist endpoint) are passed through unmodified.
    """
    cleaned = _dedupe_spans(spans)
    pieces: list[str] = []
    cursor = 0
    for span in cleaned:
        if span.end <= span.start or span.start < 0 or span.end > len(text):
            continue
        original = text[span.start:span.end]
        if vault.is_whitelisted(original):
            # User explicitly opted this value out — let it through raw.
            continue
        entry = vault.get_or_mint(original, span.label, span.tier,
                                  confidence=span.confidence,
                                  secret_key_name=span.context_key,
                                  third_party=span.third_party)
        pieces.append(text[cursor:span.start])
        pieces.append(entry.token)
        cursor = span.end
    pieces.append(text[cursor:])
    return "".join(pieces)


_SYSTEM_REMINDER_RE = re.compile(
    r"<system-reminder>.*?</system-reminder>", re.DOTALL)


def mask_outside_system_reminders(text: str, mask_fn) -> str:
    """Apply mask_fn only to text *outside* <system-reminder>...</system-reminder>
    blocks (apf-xt5).

    Claude Code injects its operational scaffolding — skill catalogues,
    agent-type lists, hook output, the CLAUDE.md projection — into the
    messages array as <system-reminder>-wrapped content. That text carries
    no user PII; running the detector over it wastes work and over-masks
    operational tokens (tool names, paths) into placeholders the model can
    no longer read, leaving it unable to follow its own instructions. Keep
    those blocks verbatim; mask only the genuine surrounding content.

    mask_fn takes a text fragment and returns it masked — the caller binds
    the vault. An unclosed <system-reminder> (truncated input) does not
    match and is masked defensively.
    """
    if "<system-reminder>" not in text:
        return mask_fn(text)
    pieces: list[str] = []
    pos = 0
    for m in _SYSTEM_REMINDER_RE.finditer(text):
        pieces.append(mask_fn(text[pos:m.start()]))
        pieces.append(m.group(0))
        pos = m.end()
    pieces.append(mask_fn(text[pos:]))
    return "".join(pieces)
