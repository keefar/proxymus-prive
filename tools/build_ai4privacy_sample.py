#!/usr/bin/env python3
"""Sample a subset of ai4privacy/pii-masking-200k, map labels to our tier-tagged
inventory, write as fixtures/ai4privacy_sample.jsonl in our standard JSONL
format. This lets us measure all existing detector adapters against a
standardised, externally-curated multilingual PII set for comparability.

Run:
    python tools/build_ai4privacy_sample.py
    python tools/build_ai4privacy_sample.py --de 100 --en 100
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures" / "ai4privacy_sample.jsonl"

# Map ai4privacy's 56 native labels to our tier-tagged inventory. Spans whose
# labels aren't in the map are dropped (rather than turned into NOTE_SENSITIVE)
# so the benchmark doesn't penalise detectors for missing labels we don't care
# about (e.g. EYECOLOR).
LABEL_MAP: dict[str, str] = {
    # → PERSON (Tier A)
    "FIRSTNAME": "PERSON", "LASTNAME": "PERSON", "MIDDLENAME": "PERSON",
    "USERNAME": "PERSON", "PREFIX": "PERSON",
    # → EMAIL
    "EMAIL": "EMAIL",
    # → PHONE
    "PHONENUMBER": "PHONE", "PHONEIMEI": "PHONE",
    # → ADDRESS / LOCATION
    "STREET": "ADDRESS", "BUILDINGNUMBER": "ADDRESS",
    "SECONDARYADDRESS": "ADDRESS", "ZIPCODE": "ADDRESS",
    "CITY": "LOCATION", "STATE": "LOCATION",
    "COUNTY": "LOCATION", "COUNTRY": "LOCATION",
    "NEARBYGPSCOORDINATE": "LOCATION",
    # → DATE
    "DATE": "DATE", "TIME": "DATE", "DOB": "DATE",
    # → ORG
    "COMPANYNAME": "ORG", "ACCOUNTNAME": "ORG",
    # → FINANCIAL
    "CREDITCARDNUMBER": "FINANCIAL", "CREDITCARDISSUER": "FINANCIAL",
    "IBAN": "FINANCIAL", "BIC": "FINANCIAL",
    "ACCOUNTNUMBER": "FINANCIAL", "AMOUNT": "FINANCIAL",
    "BITCOINADDRESS": "FINANCIAL", "ETHEREUMADDRESS": "FINANCIAL",
    "LITECOINADDRESS": "FINANCIAL",
    # → IP / URL (Tier B)
    "IPV4": "IP", "IPV6": "IP", "IP": "IP", "MAC": "IP",
    "URL": "URL_LOCAL",
    # → secrets / access (Tier C)
    "PASSWORD": "PASSWORD",
    "CREDITCARDCVV": "PASSWORD",
    "PIN": "PASSWORD",
    # → NOTE_SENSITIVE (Tier A catch-all for sensitive identifiers)
    "SSN": "NOTE_SENSITIVE",
    "MASKEDNUMBER": "NOTE_SENSITIVE",
    "USERAGENT": "NOTE_SENSITIVE",
    "JOBTITLE": "NOTE_SENSITIVE", "JOBAREA": "NOTE_SENSITIVE",
    "JOBTYPE": "NOTE_SENSITIVE",
    "VEHICLEVIN": "NOTE_SENSITIVE", "VEHICLEVRM": "NOTE_SENSITIVE",
    "AGE": "NOTE_SENSITIVE", "SEX": "NOTE_SENSITIVE",
    "GENDER": "NOTE_SENSITIVE", "HEIGHT": "NOTE_SENSITIVE",
    "EYECOLOR": "NOTE_SENSITIVE",
    "CURRENCY": "NOTE_SENSITIVE", "CURRENCYSYMBOL": "NOTE_SENSITIVE",
    "CURRENCYNAME": "NOTE_SENSITIVE", "CURRENCYCODE": "NOTE_SENSITIVE",
    "ORDINALDIRECTION": "NOTE_SENSITIVE",
}

LABEL_TIER = {
    "PERSON": "A", "EMAIL": "A", "PHONE": "A", "ADDRESS": "A", "LOCATION": "A",
    "ORG": "A", "DATE": "A", "FINANCIAL": "A", "NOTE_SENSITIVE": "A",
    "PATH": "B", "FILENAME": "B", "HOSTNAME": "B", "IP": "B", "URL_LOCAL": "B",
    "CREDENTIAL": "C", "API_KEY": "C", "PRIVATE_KEY": "C",
    "PASSWORD": "C", "TOKEN": "C", "CONNECTION_STRING": "C",
}


def sample_dataset(de: int, en: int, seed: int) -> list[dict]:
    from datasets import load_dataset
    ds = load_dataset("ai4privacy/pii-masking-200k", split="train")
    rng = random.Random(seed)
    out_de: list[dict] = []
    out_en: list[dict] = []
    # Shuffle indices once, walk until both buckets filled.
    indices = list(range(len(ds)))
    rng.shuffle(indices)
    for i in indices:
        ex = ds[i]
        lang = ex["language"]
        if lang == "de" and len(out_de) < de:
            out_de.append(ex)
        elif lang == "en" and len(out_en) < en:
            out_en.append(ex)
        if len(out_de) >= de and len(out_en) >= en:
            break
    return out_de + out_en


def to_fixture(ex: dict, idx: int) -> dict | None:
    text = ex["source_text"]
    spans: list[dict] = []
    raw_spans = ex["privacy_mask"]
    for sp in raw_spans:
        native_label = sp["label"]
        ours = LABEL_MAP.get(native_label)
        if ours is None:
            continue
        spans.append({
            "start": int(sp["start"]),
            "end": int(sp["end"]),
            "label": ours,
            "tier": LABEL_TIER[ours],
            "native_label": native_label,
        })
    if not spans:
        return None
    return {
        "id": f"a4p-{ex['language']}-{idx:04d}",
        "lang": ex["language"],
        "bucket": "ai4privacy",
        "source": "ai4privacy/pii-masking-200k",
        "text": text,
        "spans": spans,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--de", type=int, default=100)
    parser.add_argument("--en", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260516)
    args = parser.parse_args()

    print(f"Sampling DE={args.de} EN={args.en} from ai4privacy/pii-masking-200k …")
    raw = sample_dataset(args.de, args.en, args.seed)
    fixtures: list[dict] = []
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
    import sys
    sys.exit(main())
