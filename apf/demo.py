"""End-to-end demo: detector → tokenize → simulated LLM round-trip → restore.

Usage:
    .venv/bin/python -m apf.demo
    .venv/bin/python -m apf.demo --text "Hallo Anna, mein Schlüssel ist xk-fake-AAA."

Without --text, runs over a handful of representative fixtures and shows
before/after, the vault contents, a simulated tool-call resolution, and a
simulated response detokenisation.

This is a development demo, not the production runtime. The real
integration point will be the FastAPI proxy or an in-process detector
service.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .tokenizer import Span, tokenize_text
from .detokenizer import detokenize_text
from .resolver import resolve_tool_call_args
from .vault import Vault

ROOT = Path(__file__).resolve().parent.parent


def make_detector():
    """Lazy-construct the ensemble-max detector."""
    from benchmarks.adapters_mlx import EnsembleMaxAdapter
    detector = EnsembleMaxAdapter()
    detector.warmup()
    return detector


def detect_spans(detector, text: str) -> list[Span]:
    spans = detector.detect(text)
    return [Span(start=s.start, end=s.end, label=s.label, tier=s.tier)
            for s in spans]


def show(label: str, text: str) -> None:
    print(f"\n── {label} " + "─" * max(2, 60 - len(label)))
    print(text)


def demo_round_trip(text: str, detector) -> None:
    print("\n" + "=" * 72)
    print("DEMO ROUND-TRIP")
    print("=" * 72)
    show("Original input", text)

    vault = Vault()
    spans = detect_spans(detector, text)
    tokenised = tokenize_text(text, spans, vault)

    show(f"Tokenised ({len(vault)} vault entries)", tokenised)

    # Show the vault.
    print("\n── Vault ──────────────────")
    for entry in vault.all_entries():
        suffix = "  [SECRET — opaque to LLM]" if entry.tier == "C" else ""
        print(f"  {entry.token:24s} ← {entry.original!r}{suffix}")

    # Simulate an LLM that reasons about the tokenised text and emits a
    # tool call referencing some of the tokens.
    fake_tool_call_args = {
        "command": tokenised,  # whole tokenised text as a "search query"
        "to": next((e.token for e in vault.all_entries()
                    if e.label == "EMAIL"), "no-email@example.com"),
        "options": {"max_results": 5, "include_secrets": False},
    }
    show("Simulated LLM tool_use args (tokens, NOT resolved)",
         json.dumps(fake_tool_call_args, indent=2, ensure_ascii=False))

    resolved = resolve_tool_call_args(
        fake_tool_call_args, vault,
        secret_resolver=lambda: "[SECRET-FROM-ENV-VAR]",
    )
    show("Resolved at tool-call boundary (originals; NEVER goes back to LLM)",
         json.dumps(resolved, indent=2, ensure_ascii=False))

    # Simulate an LLM response that references the same tokens — what the
    # user sees after detokenisation.
    fake_response = (
        f"Ich habe die Email an {fake_tool_call_args['to']} verschickt. "
        f"Der Termin bleibt bei "
        f"{next((e.token for e in vault.all_entries() if e.label == 'DATE'), '?')}."
    )
    show("Simulated LLM response (tokens)", fake_response)
    show("Detokenised for user", detokenize_text(fake_response, vault))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", help="Custom text to filter. If absent, uses a few fixtures.")
    parser.add_argument("--fixture", help="A specific fixture id from fixtures/*.jsonl")
    args = parser.parse_args()

    detector = make_detector()

    if args.text:
        demo_round_trip(args.text, detector)
        return 0

    # Load a handful of demonstrative fixtures.
    fixture_files = [
        ROOT / "fixtures" / "content.jsonl",
        ROOT / "fixtures" / "operational.jsonl",
        ROOT / "fixtures" / "secrets.jsonl",
    ]
    picks = {"de-mail-02", "de-note-04", "en-bash-01", "en-env-01", "de-cal-01"}
    if args.fixture:
        picks = {args.fixture}

    seen = set()
    for fp in fixture_files:
        with fp.open(encoding="utf-8") as fh:
            for line in fh:
                fix = json.loads(line)
                if fix["id"] in picks and fix["id"] not in seen:
                    demo_round_trip(fix["text"], detector)
                    seen.add(fix["id"])
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
