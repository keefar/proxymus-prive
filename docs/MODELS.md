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

### Fixture set — to be assembled before the benchmark
- ~50 representative texts the filter must handle. Suggested mix:
  - German + English email body (5 + 5)
  - Calendar entry text, German + English (3 + 3)
  - Bash transcript with environment variables (5)
  - Source-code snippet containing emails / DSNs / hardcoded keys (5)
  - Prose mentioning real-feeling personal details — health, location, relationships (10)
  - Adversarial: implicit PII that regex would miss (e.g. "der Kollege aus der
    Finance-Abteilung, der nächste Woche heiratet") (10)
- Gold labels manually annotated. ~1 hour of work, one-time.

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
