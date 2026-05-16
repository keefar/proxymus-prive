"""Detector adapters.

A detector takes a text and returns predicted PII spans. The base class is the
interface every model adapter must implement. The regex baseline is a deliberately
imperfect mock — it lets us validate the metrics code against a detector with
known characteristic blind spots (no implicit PII, no context-aware health,
etc.), before any MLX model is wired up.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    label: str
    tier: str  # "A" | "B" | "C"


class Detector(Protocol):
    """A detector consumes a text and emits predicted PII spans.

    Adapters MAY override `warmup` to load weights / prime caches before
    timing-relevant detection calls. `name` is what shows up in result files.
    """

    name: str

    def warmup(self) -> None: ...
    def detect(self, text: str) -> list[Span]: ...


LABEL_TIER = {
    "PERSON": "A", "EMAIL": "A", "PHONE": "A", "ADDRESS": "A", "LOCATION": "A",
    "ORG": "A", "DATE": "A", "APPOINTMENT": "A", "APPOINTMENT_HEALTH": "A",
    "HEALTH": "A", "RELATIONSHIP": "A", "FINANCIAL": "A",
    "NOTE_SENSITIVE": "A", "IMPLICIT_PII": "A",
    "PATH": "B", "FILENAME": "B", "HOSTNAME": "B", "IP": "B", "URL_LOCAL": "B",
    "CREDENTIAL": "C", "API_KEY": "C", "PRIVATE_KEY": "C",
    "PASSWORD": "C", "TOKEN": "C", "CONNECTION_STRING": "C",
}


class RegexBaseline:
    """Stage-1-only baseline: just regex. Will miss Tier A names, Tier A
    health/implicit PII, and any label that isn't structurally regular. Useful
    as a floor and as a sanity check for the metrics pipeline."""

    name = "regex-baseline"

    PATTERNS = [
        ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
        # NANP-style and intl with spaces/dashes
        ("PHONE", re.compile(r"\+\d{1,3}[\s-]?(?:\d{1,4}[\s-]?){2,4}\d{2,4}")),
        # IPv4 (loose; refined below to skip non-IPs)
        ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
        # Absolute POSIX paths
        ("PATH", re.compile(r"(?:^|[\s\"'(=])(/(?:Users|home|opt|srv|var|etc|usr)/[^\s\"'(),]+)")),
        # Hostnames with at least one dot, common internal/external TLDs
        ("HOSTNAME", re.compile(r"\b[a-z][\w-]*\.[\w.-]+\.(?:com|de|org|internal|lokal|local|invalid)\b")),
        # API-key-ish prefixes (sk-, ghp_, AKIA-...)
        ("API_KEY", re.compile(r"\b(?:sk[_-][a-zA-Z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,})")),
        # Generic JWT-ish triple-base64
        ("TOKEN", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_.-]+\b")),
        # IBAN (loose: starts with 2-letter country)
        ("FINANCIAL", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?\d{4}){2,5}\s?\d{0,4}\b")),
    ]

    def warmup(self) -> None:
        # Regex is compiled at import-time — nothing to do.
        return

    def detect(self, text: str) -> list[Span]:
        seen: list[Span] = []
        used: list[tuple[int, int]] = []
        for label, rx in self.PATTERNS:
            for m in rx.finditer(text):
                # PATH pattern wraps the match in a non-capturing prefix; use group 1 if present.
                if m.groups():
                    start = m.start(1)
                    end = m.end(1)
                else:
                    start, end = m.start(), m.end()
                if any(s < end and e > start for s, e in used):
                    continue
                used.append((start, end))
                seen.append(Span(start=start, end=end, label=label,
                                 tier=LABEL_TIER[label]))
        seen.sort(key=lambda s: s.start)
        return seen


ADAPTERS: dict[str, type] = {
    "regex": RegexBaseline,
}
