# Candidate models for the PoC benchmark

The filter pipeline is two stages: a fast deterministic detector + a small LLM for
contextual / implicit PII and semantic pseudonym generation. This doc lists candidates for
both stages and what we'd want to benchmark before committing.

> **Versions and exact model IDs to be confirmed before the benchmark run** — never install
> from memory. Re-check HF / vendor pages at benchmark time. The list below is direction,
> not a shopping cart.

## Stage 1 — Detection (fast, deterministic)

### GLiNER (Generalist Lightweight NER) — primary candidate
- **Why:** BERT-base size, labels supplied at inference time (`person`, `email`,
  `credit_card`, `iban`, …). No fine-tune needed for new entity types — just add the label.
- **PoC starting point:** `knowledgator/gliner-pii-base-v1.0`, fine-tuned for 60+ PII/PHI
  categories. Reported F1 0.98 (PII-specific fine-tune), well above Gemini-2.5-Pro at 0.845
  on the same eval.
- **Backend:** quantized ONNX, runs on CPU; ANE possible via Core ML conversion.
- **Integration:** Microsoft Presidio supports GLiNER as an external NLP engine — buys us
  Presidio's mature anonymizer / deanonymizer for free.
- **Footprint:** few hundred MB.

### Microsoft Presidio (alone, no GLiNER) — baseline
- Pattern-based + spaCy NER. Fast, mature, multilingual.
- Weak on implicit / contextual PII — that's what stage 2 is for.
- **Use it for the round-trip plumbing (anonymizer + deanonymizer) regardless of detector choice.**

### Regex / pattern set — for known-good structured patterns
- IBAN, credit card numbers (Luhn-checked), API key prefixes (`sk-ant-…`, `ghp_…`, etc.),
  JWT shape, IPv4/IPv6.
- Borrow from contextio's preset list or Gitleaks rules; deterministic backstop only.
- Always run regardless of LLM verdict — defense in depth.

## Stage 2 — Contextual classifier / pseudonymizer (small LLM, MLX)

### Anonymizer-SLM 1.7B / 4B (eternisai) — purpose-built
- **Trained for this task.** Replaces PII with *semantically equivalent* placeholders
  (name → name of similar culture, company → fictional company in same industry/size,
  date → shifted preserving relative timing). Reported 9.20 / 9.55 LLM-judge score for 1.7B / 4B
  vs. 9.77 for GPT-4.1.
- **Local:** <250 ms TTFT, <1 s total (1.7B), <2 s (4B).
- **MLX:** weights on HF; convert with `mlx_lm.convert` if no native MLX build exists.
- **Verify at benchmark time:** German coverage (training data?). If weak on German,
  fall back to Nemotron.

### Nemotron Privacy Filter MLX (OpenMed) — already MLX, German-capable
- Distributed as part of OpenMed (`pip install openmed[mlx]`). Multilingual including
  **German**. Targets HIPAA Safe Harbor categories plus general PII.
- Native MLX — least friction on M5.
- May be over-fitted to medical text; benchmark on general dev-machine content
  (emails, calendar, code comments) before committing.

### Generic small Qwen / Gemma / Phi as fallback
- If specialized models don't cover German well enough, a generic 1.7–4B instruct
  with a structured JSON prompt (`{ replacements: [{original, replacement}] }`) is the
  fallback. Lower quality on PII recall vs. purpose-trained, but works as a sanity baseline.
- Candidates worth benchmarking: Qwen 3 1.7B / 4B, Gemma 3 2B, Phi-4-mini.

## Benchmark plan (what we actually need to measure)

Once the PoC scaffold is in place, run all stage-2 candidates against the same fixture set.
Don't optimize, just measure.

### Fixture set — spec

See `ARCHITECTURE.md` § "Threat model — three handling tiers" for the tier model that
this fixture set covers. Goal: ~50 texts, three buckets aligned with the tiers, all
synthetic (no real PII — committable).

**Format.** One JSON object per line (JSONL), one file per bucket under `fixtures/`:

```json
{
  "id": "de-mail-01",
  "lang": "de",            // "de" | "en"
  "bucket": "content",     // "content" | "operational" | "secret"
  "source": "synthetic",   // always "synthetic" in fixtures/; real cases go to fixtures/private/
  "text": "Hallo Anna, schick mir bitte das Protokoll an thomas.weber@beispiel.de bis Freitag.",
  "spans": [
    {"start": 6,  "end": 10, "label": "PERSON",  "tier": "A"},
    {"start": 41, "end": 65, "label": "EMAIL",   "tier": "A"},
    {"start": 70, "end": 77, "label": "DATE",    "tier": "A"}
  ],
  "notes": "implicit recipient identity via first-name only"
}
```

Span offsets are **character offsets into `text`** (not byte offsets — UTF-8-aware).
Half-open intervals: `text[start:end]` is the span.

**Label inventory.** A label belongs to exactly one tier. The benchmark scores per-label
recall and aggregates per-tier so we can see "does this model miss health stuff
specifically?"

| Label | Tier | Notes |
|---|:-:|---|
| PERSON | A | Names, also first-name-only references |
| EMAIL | A | Mail addresses |
| PHONE | A | Phone numbers, any format |
| ADDRESS | A | Postal addresses |
| LOCATION | A | Cities, regions, landmarks tied to the user |
| ORG | A | Employer, clients, vendors |
| DATE | A | Specific dates / weekdays in a personal context |
| APPOINTMENT | A | Calendar entries (use `APPOINTMENT_HEALTH` when health-tagged) |
| HEALTH | A | Diagnoses, medication, body parts, doctor names |
| RELATIONSHIP | A | "meine Frau", "Kollege aus dem Controlling", … |
| FINANCIAL | A | IBAN, balances, salary, transaction fragments |
| NOTE_SENSITIVE | A | Catch-all for sensitive note content not covered above |
| IMPLICIT_PII | A | Paraphrased identifying details ("der Nachbar, dessen Sohn…") |
| PATH | B | Filesystem paths |
| FILENAME | B | When filename alone identifies a user/project |
| HOSTNAME | B | Machine names |
| IP | B | Local + public IP addresses |
| URL_LOCAL | B | URLs to local services / private intranet |
| CREDENTIAL | C | Generic credential where type unknown |
| API_KEY | C | Vendor API keys |
| PRIVATE_KEY | C | SSH / GPG / TLS private keys |
| PASSWORD | C | Plain passwords |
| TOKEN | C | OAuth / bearer / session tokens |
| CONNECTION_STRING | C | DB DSNs with embedded credentials |

If two labels overlap on the same span, pick the most specific (e.g. `APPOINTMENT_HEALTH`
over `APPOINTMENT` over `DATE`). Models that emit a less-specific label still count as a
correct detection at the *tier* level, but lose precision at the *label* level.

**Bucket distribution.**

| Bucket | File | Count | Tier(s) covered | Content |
|---|---|:-:|:-:|---|
| Content | `fixtures/content.jsonl` | ~30 | A | Mail bodies, calendar entries, sensitive notes, prose with implicit PII, adversarial paraphrases. Health subset ≥ 5 (Arzttermine, Diagnose-Notizen, Medikation). DE/EN split ≈ 50/50. |
| Operational | `fixtures/operational.jsonl` | ~10 | B | Bash transcripts, shell config, log lines, code referencing user paths/hostnames/IPs. |
| Secrets | `fixtures/secrets.jsonl` | ~10 | C | `.env` snippets, hardcoded API keys in source, ssh-config blocks, DSNs, OAuth-token paste-ins. All values clearly fake (use known dummy ranges: example.com, 192.0.2.0/24, etc.). |

**Synthetic-data rules** (so nothing in `fixtures/` accidentally exposes real PII):

- Names: pick from a Swiss/German/English name list, mix common + uncommon; no real
  public figures.
- Emails: `*@example.com`, `*@example.de`, `*@beispiel.de`, `*@test.invalid`.
- Domains: `example.{com,de,org}`, `test.invalid` per RFC 2606.
- IPs: documentation ranges `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`,
  `2001:db8::/32`; for local: `127.0.0.1`, `10.0.0.42`, `192.168.1.x`.
- Phone numbers: prefix `+49 30 9900 xxxx` (Berlin reserved 9900) or
  `+1-555-01xx` (NANP fictional range).
- Credentials/keys: obviously fake (`sk-test-...`, `ghp_AAAAAAA...`, all-X placeholders),
  formatted to look real but never copy real vendor patterns verbatim.
- Paths: `/Users/alice/...`, `/home/bob/...` — not the author's actual paths.
- Health: invented conditions and dosages, no real clinical detail.

**Annotation procedure.**

1. Write the text first, naturally. Don't pre-tokenize.
2. Mark spans in the source (`fixtures/_annotated.md` per bucket?) using `‹label:text›`
   inline markers — easier to author than offsets.
3. A small `tools/build_fixtures.py` later converts inline-marked text → JSONL with
   character offsets. (Issue: bd `apf-4f4.4` — benchmark harness — will include this.)
4. Each fixture gets a unique `id` like `de-mail-01`, `en-bash-03`, `de-health-02`.

**Out of scope for the fixture set.**

- Round-trip preservation testing (a different artifact — uses the same texts but pipes
  them through a cloud LLM call).
- Real personal data: stays in `fixtures/private/` (gitignored), only added by the user
  after the filter exists.

### Metrics
- **Recall** on PII spans (false negatives = leaks — the only metric that really matters)
- **Precision** (false positives = over-redaction → degraded LLM quality)
- **Round-trip preservation** — fraction of placeholders correctly restored after a
  representative LLM call (use the same cloud model the real system will use)
- **Latency** — TTFT and total for stage 2, measured cold and warm
- **RAM** — RSS at steady state with model resident
- **German vs. English delta** — separate columns; either language failing is disqualifying

### Decision criteria
- Recall ≥ 0.95 on the fixture set in **both** German and English
- p95 stage-2 latency ≤ 1.5 s on M5
- Combined RAM (stage 1 + stage 2) ≤ 4 GB resident

If no candidate passes, fall back to a two-model ensemble or accept the weaker model and
strengthen stage 1 to compensate.

## Out of scope for the model benchmark

- Tool-call resolution quality — that's an architecture / engineering problem, not a model
  quality problem (see `ARCHITECTURE.md`).
- Cloud-LLM-side behavior — assume the placeholder-preservation property documented for
  Presidio / PII Shield holds; verify spot-checks on the actual cloud model.
