# 2026-05-20 — Large false-positive benchmark + detector-change regression check

Ran `benchmarks/run.py --adapter ensemble-max` over all scoreable
fixture sets after a night of detector changes (Presidio NRP stoplist,
HEALTH science-term stoplist, locked-category regex adapter, `_merge_spans`
locked-label exception). Goal: confirm no precision/recall regression and
map where the detector's false positives actually are.

## Headline

**No regression.** Tonight's detector changes left the ai4privacy-300k
sample byte-identical and slightly improved the 250-fixture mixed set.

| Fixture set | Records | tier P | tier R | tier f1 | tier fp | vs. previous |
|---|---|---|---|---|---|---|
| 250-mix (ai4p_sample + content + operational + secrets) | 250 | 0.614 | 0.752 | 0.676 | 384 | P +0.006, R +0.018 |
| ai4privacy-300k sample | 303 | 0.324 | 0.765 | — | 1879 | identical |
| private (hand-crafted) | 13 | 0.679 | 0.767 | 0.721 | 42 | — |

Result JSONs refreshed: `benchmarks/results/ensemble-max{,-300k,-private}.json`.

## Precision varies by fixture provenance — and why

Precision is 0.68 (private) / 0.61 (250-mix) / 0.32 (300k). That spread
is **mostly a scoring artifact, not three different detector qualities**:

- `private.jsonl` is hand-crafted against apf's own label taxonomy, so
  the gold spans and the detector's output use the same scheme →
  precision reflects real detector behaviour.
- `ai4privacy-300k` uses ai4privacy's taxonomy and span boundaries.
  apf's detector emits labels ai4privacy never gold-labels — so they
  score as false positives by definition. Smoking gun: on the 300k set
  Tier-C is tp=0 / fn=0 / fp=70 — the sample has *no* secrets-class
  gold at all, yet every API-key/token the detector finds is counted FP.

So benchmark "fp" conflates three things: genuine hallucination,
span-boundary mismatch, and label-taxonomy mismatch. The 300k 0.32 is
not "68% hallucination" — it is mostly taxonomy mismatch.

## Where the false positives actually are (250-mix, per label)

| Label | fp | tp | precision | note |
|---|---|---|---|---|
| PERSON | 119 | 111 | 0.483 | biggest absolute FP source |
| ORG | 77 | 11 | 0.125 | now skipped in the proxy (apf-1f6) — production effect nil |
| DATE | 40 | 65 | 0.619 | |
| LOCATION | 31 | 29 | 0.483 | |
| APPOINTMENT | 28 | 0 | 0.000 | tp=0 → taxonomy mismatch, not hallucination |
| HEALTH | 27 | 6 | 0.182 | stoplist caught the science-term class; broader FP remains |
| NOTE_SENSITIVE | 15 | 14 | 0.483 | |
| IMPLICIT_PII | 7 | 0 | 0.000 | tp=0 → taxonomy mismatch |

Clean, high-precision labels: EMAIL 0.96, IP 0.93, FINANCIAL 0.92,
PATH 0.91, ADDRESS 0.90. The pattern is consistent: **structural
detectors (regex-shaped Tier-B/C) are precise; semantic / NER labels
(PERSON, ORG, DATE, LOCATION, HEALTH, APPOINTMENT) over-fire.**

## Caveats / what this run did NOT cover

- `benchmarks/run.py` is a pure detector eval — no proxy, no agent, no
  Hermes. The Hermes loopback FP check is `scripts/smoke_loopback.py`
  (21 cases incl. 8 benign negatives); it needs the proxy running on
  current code and is a separate run.
- A pure hallucination measure (detector over guaranteed-benign text)
  would isolate genuine FP from taxonomy mismatch — the 8 negative
  smoke cases are the current proxy for that; a larger benign corpus
  would sharpen it.

## Follow-up worth filing

- APPOINTMENT and IMPLICIT_PII score tp=0 against ai4privacy — confirm
  whether that is pure taxonomy mismatch (expected) or the labels are
  genuinely never correct, and if the latter, reconsider emitting them.
- PERSON precision 0.48 on the 250-mix is the largest real lever for
  overall precision — worth a dedicated over-detection investigation.
