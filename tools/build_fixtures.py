#!/usr/bin/env python3
"""Convert inline-marked fixture sources into JSONL with character-offset spans.

Source format: Markdown-ish files in fixtures/_source/<bucket>.md, with one
fixture per `## id: <fixture-id>` heading. PII spans are marked inline with
`⟦LABEL|text⟧` — the script strips the markers, computes character offsets
against the cleaned text, and emits one JSONL line per fixture.

Each heading line carries metadata as `key=value` pairs separated by whitespace
after the id:
    ## id: de-mail-01 lang=de bucket=content [notes="..."]

Body is everything until the next `## id:` heading. Leading/trailing
whitespace is stripped from each fixture body.

Run:
    python tools/build_fixtures.py
    python tools/build_fixtures.py --check    # validate only, no write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "fixtures" / "_source"
OUT_DIR = ROOT / "fixtures"

# Tier mapping — must match docs/MODELS.md label inventory.
LABEL_TIER = {
    "PERSON": "A", "EMAIL": "A", "PHONE": "A", "ADDRESS": "A", "LOCATION": "A",
    "ORG": "A", "DATE": "A", "APPOINTMENT": "A", "APPOINTMENT_HEALTH": "A",
    "HEALTH": "A", "RELATIONSHIP": "A", "FINANCIAL": "A",
    "NOTE_SENSITIVE": "A", "IMPLICIT_PII": "A",
    "PATH": "B", "FILENAME": "B", "HOSTNAME": "B", "IP": "B", "URL_LOCAL": "B",
    "CREDENTIAL": "C", "API_KEY": "C", "PRIVATE_KEY": "C",
    "PASSWORD": "C", "TOKEN": "C", "CONNECTION_STRING": "C",
}

# Inline marker. Uses U+27E6 ⟦ and U+27E7 ⟧ to avoid clashing with code content.
MARKER_RE = re.compile(r"⟦([A-Z_]+)\|([^⟧]+)⟧")

HEADING_RE = re.compile(r"^##\s+id:\s*(\S+)(?:\s+(.*))?$")
META_RE = re.compile(r'(\w+)=(?:"([^"]*)"|(\S+))')


def parse_meta(meta_str: str | None) -> dict:
    if not meta_str:
        return {}
    out = {}
    for key, qval, val in META_RE.findall(meta_str):
        out[key] = qval if qval else val
    return out


def parse_source(path: Path) -> list[dict]:
    fixtures = []
    current_id: str | None = None
    current_meta: dict = {}
    current_body: list[str] = []

    def flush():
        if current_id is None:
            return
        body = "\n".join(current_body).strip("\n")
        fixtures.append({"id": current_id, "meta": current_meta, "raw": body})

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        m = HEADING_RE.match(raw_line)
        if m:
            flush()
            current_id = m.group(1)
            current_meta = parse_meta(m.group(2))
            current_body = []
            continue
        if current_id is not None:
            current_body.append(raw_line)
    flush()
    return fixtures


def resolve_spans(raw: str) -> tuple[str, list[dict]]:
    """Strip ⟦LABEL|text⟧ markers and return (clean_text, spans)."""
    out = []
    spans = []
    pos = 0
    for m in MARKER_RE.finditer(raw):
        out.append(raw[pos:m.start()])
        label = m.group(1)
        text = m.group(2)
        start = sum(len(s) for s in out)
        out.append(text)
        end = start + len(text)
        if label not in LABEL_TIER:
            raise ValueError(f"Unknown label {label!r} at offset {start}")
        spans.append({
            "start": start,
            "end": end,
            "label": label,
            "tier": LABEL_TIER[label],
        })
        pos = m.end()
    out.append(raw[pos:])
    return "".join(out), spans


def validate_fixture(fix: dict) -> list[str]:
    errors = []
    for required in ("lang", "bucket"):
        if required not in fix:
            errors.append(f"{fix['id']}: missing {required}")
    for span in fix["spans"]:
        if span["start"] < 0 or span["end"] > len(fix["text"]):
            errors.append(f"{fix['id']}: span out of range {span}")
        if fix["text"][span["start"]:span["end"]] != fix.get("_span_text", {}).get(
            f"{span['start']}:{span['end']}", fix["text"][span["start"]:span["end"]]
        ):
            errors.append(f"{fix['id']}: span content mismatch {span}")
    return errors


def build_bucket(source_path: Path) -> tuple[list[dict], list[str]]:
    fixtures = []
    errors = []
    for entry in parse_source(source_path):
        try:
            text, spans = resolve_spans(entry["raw"])
        except ValueError as e:
            errors.append(f"{entry['id']}: {e}")
            continue
        fixture = {
            "id": entry["id"],
            "lang": entry["meta"].get("lang", "??"),
            "bucket": entry["meta"].get("bucket", source_path.stem),
            "source": "synthetic",
            "text": text,
            "spans": spans,
        }
        if "notes" in entry["meta"]:
            fixture["notes"] = entry["meta"]["notes"]
        errors.extend(validate_fixture(fixture))
        fixtures.append(fixture)
    return fixtures, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="Validate only, do not write JSONL.")
    args = parser.parse_args()

    if not SOURCE_DIR.exists():
        print(f"No source dir at {SOURCE_DIR}", file=sys.stderr)
        return 1

    all_errors = []
    summary = []
    for src in sorted(SOURCE_DIR.glob("*.md")):
        bucket = src.stem
        fixtures, errors = build_bucket(src)
        all_errors.extend(errors)
        summary.append((bucket, len(fixtures),
                        sum(1 for f in fixtures if f["lang"] == "de"),
                        sum(1 for f in fixtures if f["lang"] == "en"),
                        sum(len(f["spans"]) for f in fixtures)))
        if not args.check:
            out_path = OUT_DIR / f"{bucket}.jsonl"
            with out_path.open("w", encoding="utf-8") as fh:
                for fix in fixtures:
                    fh.write(json.dumps(fix, ensure_ascii=False) + "\n")
            print(f"wrote {out_path.relative_to(ROOT)} ({len(fixtures)} fixtures)")

    print()
    print(f"{'bucket':<14} {'total':>6} {'de':>4} {'en':>4} {'spans':>6}")
    for bucket, n, de, en, spans in summary:
        print(f"{bucket:<14} {n:>6} {de:>4} {en:>4} {spans:>6}")

    if all_errors:
        print(f"\n{len(all_errors)} error(s):", file=sys.stderr)
        for e in all_errors:
            print(f"  {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
