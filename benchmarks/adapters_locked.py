"""Locked-category regex detector (apf-eg3 v0).

The production detector ensemble (regex baseline + Presidio + GLiNER
heads) covers Tier-A/B/C PII categories: PERSON, EMAIL, ADDRESS, PATH,
API_KEY, etc. It does NOT emit the never-forward "locked" categories
declared in apf/local_only.py: asylum status, domestic abuse,
whistleblower intent, undocumented immigration. Without detection,
the apf-enr refusal pathway is plumbed but dormant.

This adapter is a v0 keyword/phrase matcher — narrow recall by design,
high precision. It catches the obvious statements ("I need to prepare
for my asylum interview", "Soll ich BaFin melden was mein Chef macht")
but will miss paraphrases and indirect mentions. That's acceptable for
the v0 goal: validate the refusal pipeline end-to-end on real-looking
prompts and surface false-positives early.

A later iteration would replace this with a fine-tuned GLiNER head on
the four labels (probably trained on synthesised corpora — none of
these categories should be exfiltrated from real user data for
training). See apf-eg3 design notes.

Labels emitted match `apf/local_only.py:DEFAULT_LOCKED_LABELS`:
- ASYLUM_STATUS
- DOMESTIC_VIOLENCE
- WHISTLEBLOWER_INTENT
- UNDOCUMENTED_STATUS

All emitted at tier="A" (Tier-A content; the lockedness is orthogonal
and checked separately via apf/local_only.py).
"""
from __future__ import annotations

import re

from .adapters import Span


class LockedCategoryRegexAdapter:
    name = "locked-category-regex"

    # Each entry: label, list of compiled patterns. Patterns are
    # case-insensitive substring matches against the input text. The
    # match span covers the matched phrase only — narrow enough that
    # the refusal body's locked_categories list is the user-actionable
    # signal, not the matched text (which is discarded anyway).
    PATTERNS: list[tuple[str, list[re.Pattern[str]]]] = [
        ("ASYLUM_STATUS", [
            # English
            re.compile(r"\basylum\s+(?:interview|application|claim|"
                       r"process|status|hearing|decision)\b",
                       re.IGNORECASE),
            re.compile(r"\b(?:applying|applied|apply)\s+for\s+asylum\b",
                       re.IGNORECASE),
            re.compile(r"\brefugee\s+(?:status|application|claim|"
                       r"process|interview)\b", re.IGNORECASE),
            re.compile(r"\b(?:seeking|granted|denied)\s+asylum\b",
                       re.IGNORECASE),
            # German
            re.compile(r"\bAsyl(?:antrag|verfahren|anhörung|bescheid|"
                       r"gesuch|berechtigt|entscheidung)", re.IGNORECASE),
            re.compile(r"\bAsyl\s+beantragt", re.IGNORECASE),
            re.compile(r"\bFlüchtlings(?:status|eigenschaft|anerkennung)\b",
                       re.IGNORECASE),
            re.compile(r"\bAufenthaltsgestattung\b", re.IGNORECASE),
        ]),
        ("DOMESTIC_VIOLENCE", [
            # English
            re.compile(r"\bdomestic\s+(?:violence|abuse)\b", re.IGNORECASE),
            re.compile(r"\bintimate\s+partner\s+(?:violence|abuse)\b",
                       re.IGNORECASE),
            re.compile(r"\b(?:restraining|protective|no[\-\s]contact)\s+order\b",
                       re.IGNORECASE),
            re.compile(r"\babus(?:ive|er)\s+(?:partner|spouse|husband|"
                       r"wife|boyfriend|girlfriend|ex)\b", re.IGNORECASE),
            re.compile(r"\bIPV\b"),  # case-sensitive — common acronym
            re.compile(r"\bwomen[''']s\s+shelter\b", re.IGNORECASE),
            # German — match adjective declension endings (häusliche /
            # häuslicher / häuslichen / häusliches) before "Gewalt"
            re.compile(r"\bhäuslich(?:e|er|en|es)?\s+Gewalt\b", re.IGNORECASE),
            re.compile(r"\bFrauenhaus(?:nummer)?\b", re.IGNORECASE),
            re.compile(r"\bGewaltschutz(?:gesetz|anordnung)\b", re.IGNORECASE),
            re.compile(r"\bSchutzanordnung\b", re.IGNORECASE),
            re.compile(r"\bKontakt(?:s)?verbot\b", re.IGNORECASE),
        ]),
        ("WHISTLEBLOWER_INTENT", [
            # English
            re.compile(r"\bwhistleblow(?:er|ing|e)?\b", re.IGNORECASE),
            re.compile(r"\breport(?:ing)?\s+(?:my\s+|the\s+)?"
                       r"(?:employer|company|manager|boss)\s+to\s+"
                       r"(?:the\s+)?(?:press|media|authorities|regulator|"
                       r"SEC|FCA|BaFin|police|prosecutor)\b",
                       re.IGNORECASE),
            re.compile(r"\b(?:leak|disclos(?:e|ing|ure))\s+(?:the\s+|this\s+|"
                       r"these\s+)?(?:document|story|files|emails|memos|"
                       r"info|information)\b", re.IGNORECASE),
            re.compile(r"\bdrafting\s+(?:the\s+|a\s+)?disclosure\b",
                       re.IGNORECASE),
            # German
            re.compile(r"\bHinweisgeber(?:in)?\b", re.IGNORECASE),
            re.compile(r"\bWhistleblower(?:in)?\b", re.IGNORECASE),
            re.compile(r"\b(?:bei der )?(?:BaFin|Aufsichtsbehörde|"
                       r"Staatsanwaltschaft)\s+(?:melden|anzeigen)\b",
                       re.IGNORECASE),
            re.compile(r"\b(?:Pressemitteilung|Leak|Enthüllung)\s+"
                       r"(?:über|gegen|zu)\s+(?:meinen?|unseren?)\s+"
                       r"(?:Arbeitgeber|Chef|Vorgesetzten)\b",
                       re.IGNORECASE),
        ]),
        ("UNDOCUMENTED_STATUS", [
            # English
            re.compile(r"\bundocumented\s+(?:immigrant|status|resident|"
                       r"worker)\b", re.IGNORECASE),
            re.compile(r"\bunauthorized\s+(?:immigrant|migrant)\b",
                       re.IGNORECASE),
            re.compile(r"\bwithout\s+(?:legal\s+)?(?:papers|status|"
                       r"documents|documentation|residency)\b",
                       re.IGNORECASE),
            re.compile(r"\bin\s+the\s+(?:country|US|UK)\s+illegally\b",
                       re.IGNORECASE),
            re.compile(r"\bovers(?:t|p)ay(?:ed|ing)?\s+(?:my\s+|the\s+)?visa\b",
                       re.IGNORECASE),
            # German
            re.compile(r"\bDuldung\b"),  # case-sensitive — German legal term
            re.compile(r"\bohne\s+(?:gültige\s+)?Papiere\b", re.IGNORECASE),
            re.compile(r"\bohne\s+Aufenthalts(?:titel|recht|erlaubnis)\b",
                       re.IGNORECASE),
            re.compile(r"\billegal(?:er|e)?\s+Aufenthalt\b", re.IGNORECASE),
            re.compile(r"\babgelaufene?s?\s+Visum\b", re.IGNORECASE),
        ]),
    ]

    def warmup(self) -> None:
        pass  # nothing to load — patterns are compiled at class definition

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for label, patterns in self.PATTERNS:
            for pat in patterns:
                for m in pat.finditer(text):
                    spans.append(Span(
                        start=m.start(), end=m.end(),
                        label=label, tier="A",
                        confidence=1.0,  # deterministic regex match
                    ))
        return spans
