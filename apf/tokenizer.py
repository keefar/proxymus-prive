"""Apply detector spans to text → tokenized text + vault.

The detector emits character-offset spans. The tokenizer:
  1. Sorts spans, drops overlaps (later spans contained in earlier wins).
  2. Walks right-to-left so character offsets in the *remaining* text don't
     shift while substituting.
  3. For each span: get_or_mint a vault entry, replace the original substring
     with the surface token.
"""
from __future__ import annotations

from dataclasses import dataclass

from .vault import Vault


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str
    tier: str


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


def tokenize_text(text: str, spans: list[Span], vault: Vault) -> str:
    """Replace each span's substring with its vault token. Returns the
    tokenized text. Mutates the vault."""
    cleaned = _dedupe_spans(spans)
    # Sanity: spans within text bounds.
    pieces: list[str] = []
    cursor = 0
    for span in cleaned:
        if span.end <= span.start or span.start < 0 or span.end > len(text):
            continue
        original = text[span.start:span.end]
        entry = vault.get_or_mint(original, span.label, span.tier)
        pieces.append(text[cursor:span.start])
        pieces.append(entry.token)
        cursor = span.end
    pieces.append(text[cursor:])
    return "".join(pieces)
