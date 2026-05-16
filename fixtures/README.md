# Fixtures

Synthetic test data for the model benchmark. **All data here is invented** —
see `docs/MODELS.md` § "Synthetic-data rules" for the constraints and
`docs/ARCHITECTURE.md` § "Threat model — three handling tiers" for the
tier model the labels map to.

## Layout

```
fixtures/
├── _source/              ← author here (inline ⟦LABEL|text⟧ markers)
│   ├── content.md
│   ├── operational.md
│   └── secrets.md
├── content.jsonl         ← generated; do NOT edit by hand
├── operational.jsonl     ← generated
├── secrets.jsonl         ← generated
└── private/              ← gitignored; for real user data after the filter exists
```

## Regenerate

```bash
python tools/build_fixtures.py            # writes the three *.jsonl files
python tools/build_fixtures.py --check    # validate only
```

The build script strips inline `⟦LABEL|text⟧` markers from each fixture, computes
character offsets against the resulting clean text, and validates that every
label is in the inventory.

## Adding fixtures

1. Open the matching source file under `_source/`.
2. Add a new `## id: <bucket-prefix>-<nn>` heading with `lang=` and `bucket=`.
3. Write the text naturally; wrap PII spans with `⟦LABEL|the actual text⟧`.
4. Run the build script.

## Stats (current)

| Bucket | Tier | Count | DE | EN | Spans |
|---|:-:|:-:|:-:|:-:|:-:|
| content | A | 30 | 17 | 13 | 126 |
| operational | B | 10 | 2 | 8 | 42 |
| secrets | C | 10 | 2 | 8 | 18 |
| **total** | | **50** | **21** | **29** | **186** |

Operational/secrets skew English because code, config files, and shell sessions
are almost always English in practice — the asymmetry is realistic, not a bug.
