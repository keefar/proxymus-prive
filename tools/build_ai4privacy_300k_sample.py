#!/usr/bin/env python3
"""Sample from ai4privacy/pii-masking-300k.

Same shape as build_ai4privacy_sample.py but for the newer 300k dataset,
which uses capitalized language names ("German", "English") and includes
6 languages. We sample DE + EN like before.

Run:
    python tools/build_ai4privacy_300k_sample.py
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from tools.build_ai4privacy_sample import LABEL_MAP, LABEL_TIER  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures" / "ai4privacy_300k_sample.jsonl"

LANG_NORMALISE = {
    "German": "de", "English": "en", "French": "fr",
    "Italian": "it", "Spanish": "es", "Dutch": "nl",
    "de": "de", "en": "en",
}


def sample_dataset(de: int, en: int, seed: int) -> list[dict]:
    from datasets import load_dataset
    ds = load_dataset("ai4privacy/pii-masking-300k", split="train")
    rng = random.Random(seed)
    out_de: list[dict] = []
    out_en: list[dict] = []
    indices = list(range(len(ds)))
    rng.shuffle(indices)
    for i in indices:
        ex = ds[i]
        lang_norm = LANG_NORMALISE.get(ex["language"], "??")
        if lang_norm == "de" and len(out_de) < de:
            out_de.append(ex)
        elif lang_norm == "en" and len(out_en) < en:
            out_en.append(ex)
        if len(out_de) >= de and len(out_en) >= en:
            break
    return out_de + out_en


def to_fixture(ex: dict, idx: int) -> dict | None:
    text = ex["source_text"]
    spans = []
    for sp in ex["privacy_mask"]:
        ours = LABEL_MAP.get(sp["label"])
        if ours is None:
            continue
        spans.append({
            "start": int(sp["start"]),
            "end": int(sp["end"]),
            "label": ours,
            "tier": LABEL_TIER[ours],
            "native_label": sp["label"],
        })
    if not spans:
        return None
    lang = LANG_NORMALISE.get(ex["language"], "??")
    return {
        "id": f"a4p300k-{lang}-{idx:04d}",
        "lang": lang,
        "bucket": "ai4privacy_300k",
        "source": "ai4privacy/pii-masking-300k",
        "text": text,
        "spans": spans,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--de", type=int, default=200)
    parser.add_argument("--en", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260517)
    args = parser.parse_args()

    print(f"Sampling DE={args.de} EN={args.en} from ai4privacy/pii-masking-300k …")
    raw = sample_dataset(args.de, args.en, args.seed)
    fixtures = []
    for i, ex in enumerate(raw):
        fix = to_fixture(ex, i)
        if fix is not None:
            fixtures.append(fix)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for fx in fixtures:
            fh.write(json.dumps(fx, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(fixtures)} fixtures, "
          f"{sum(len(f['spans']) for f in fixtures)} spans")
    return 0


if __name__ == "__main__":
    sys.exit(main())
