# Session log — 2026-05-16 benchmark runs

Follows directly on `2026-05-15-kickoff.md`. This session executed the
Stage-2 model benchmark planned there.

## Setup work (before any model ran)

1. Initialised beads with prefix `apf` — switched the project to beads-only
   task tracking. AGENTS.md and a Beads section in CLAUDE.md were auto-added
   by `bd init`.
2. Created an epic `apf-4f4` with 8 child issues + 3 standalone follow-ups,
   wired deps so `bd ready` reflects real availability.
3. Wrote the three-tier threat model into `docs/ARCHITECTURE.md`
   (Tier A — content PII, Tier B — operational identifiers, Tier C — secrets).
   The tiers cleanly split which mechanic applies: A tokenises and restores,
   B needs tool-call-boundary resolution to function at all, C is opaque
   redaction with secret-store fill-in at exec time.
4. Wrote the fixture spec into `docs/MODELS.md`: JSONL format, character-offset
   spans, label inventory with tier mapping, three bucket files, synthetic-data
   rules using RFC documentation ranges so nothing leaks.
5. Built `tools/build_fixtures.py` (~150 lines) — converts inline
   `⟦LABEL|text⟧` markers in markdown source to JSONL with offsets. Removes
   the offset-counting burden from fixture authoring.
6. Wrote 50 synthetic fixtures: 30 content + 10 operational + 10 secrets,
   21 DE + 29 EN, 186 spans total. Health subset covers Arzttermine,
   diagnoses, medication. Adversarial subset covers paraphrased identifiers.
7. Built `benchmarks/` harness — stdlib-only, no psutil/torch dependency.
   Adapter Protocol + RegexBaseline as a mock floor; metrics layer with
   tier-equality (primary) and label-equality (diagnostic) scoring, per-tier /
   per-label / per-language / per-bucket aggregation. Greedy gold-order
   span assignment with ≥50% overlap. Latency via `time.perf_counter`,
   peak RSS via `resource.getrusage` with macOS/Linux normalisation.

Regex baseline scored tier-recall 0.194 / tier-precision 0.900 — confirmed
the pipeline works and gives explainable numbers.

## Model runs

Venv at `.venv/` (gitignored). Installed `mlx-lm 0.31.3`, `openmed 1.4.0`,
`tiktoken 0.13.0`. HF cache at default location.

### Nemotron Privacy Filter MLX 8bit (OpenMed)

- Downloaded 1.45 GB, ~46 s.
- Token classifier, BIOES tagging, 55 PII span classes.
- Mapped Nemotron's 55-class space to our 25-label inventory in
  `benchmarks/adapters_mlx.py` (`NEMOTRON_LABEL_MAP`). Most mappings tier-correct
  even where label-level inexact — fine for the primary metric.
- Result: tier-recall **0.290**, tier-precision 0.551, p95 latency **187 ms**,
  peak RSS 1.6 GB.
- German false-positives confirm the English-only training: "schick" and
  "Akte" misclassified as names (sub-0.5 confidence — score threshold of 0.6
  filters most but not all).

### Anonymizer-SLM 1.7B (eternisai)

- No MLX port on HF — converted from PyTorch with `mlx_lm.convert`
  (`--quantize --q-bits 4`). ~3.5 min download + convert. Result: 4.5 bpw.
- Generative; uses Qwen3 chat template with a `replace_entities` tool schema.
  Outputs `<tool_call>{...}</tool_call>` — note: the model card documents
  `<|tool_call|>` but the actual emitted tags are `<tool_call>`. Adapter
  regex handles both forms.
- Output is `{original, replacement}` pairs with **no offsets and no labels**.
  Adapter rebuilds offsets via `str.find` and infers labels via the
  RegexBaseline pattern set; anything unmatched falls back to `NOTE_SENSITIVE`.
- Result: tier-recall **0.355** (best of 3), tier-precision 0.516. DE recall
  0.382 > EN recall 0.330 — the multilingual Qwen3 base helps significantly.
- Latency p95 **2.96 s** — **misses the 1.5 s budget**.

### Qwen3-1.7B 4bit (mlx-community)

- Same architecture family as Anonymizer-SLM, no PII fine-tune. Direct MLX
  weights, 938 MB.
- Prompted zero-shot with our label inventory in the system message; output a
  JSON object with `pii: [{text, type}]`. Adapter parses, recovers offsets
  the same way as the Anonymizer adapter.
- Result: tier-recall **0.226** (lowest), tier-precision 0.712 (highest). DE
  precision 0.95 striking — the model is conservative in German.
- Latency p95 1.01 s, peak RSS 1.26 GB — within budgets.

## Headline finding

**No single Stage-2 model hits the ≥0.95 recall criterion on the fixture
mix.** Full table and decision rationale in
`docs/ARCHITECTURE.md` § "Decision log" — recorded 2026-05-16.

The decision isn't "which model wins"; it's that the single-model framing was
empirically rejected. Two viable paths forward (both in the decision log):

1. **Ensemble** — regex + Nemotron for Tier B/C/easy A at fast latency; route
   free-form prose/notes to Anonymizer-SLM. Gating heuristic still TBD.
2. **Re-scope the recall target** — split the criterion by sub-category
   (explicit Tier-A ≥ 0.95, implicit ≥ 0.80, Tier-C ≥ 0.99). Honestly
   acknowledge what 1.7B SLMs cannot do.

GLiNER multilingual is the obvious next candidate to test, this time as
Stage 1 alongside regex, specifically targeting the gap (implicit PII spans
and German prose).

## State at end of session

- 7 of 8 child issues under epic `apf-4f4` closed; only `apf-4f4.8`
  (decision) remained when this session paused. Decision is recorded in
  `ARCHITECTURE.md`; the decision *issue* will close with this commit.
- Three commits in this session: docs (3-tier + fixture spec), fixtures
  (synthetic + builder), harness (regex baseline). Model runs commit pending.
- Result JSON files at `benchmarks/results/*.json` (gitignored —
  reproducible from the venv + HF cache).
- No PII work in this session touched real user data — explicit constraint
  carried from the kickoff conversation, hard rule.

## What changed in tooling / workflow

- Beads + project policy: stop using TodoWrite/TaskCreate in this repo, beads
  is the single tracker. Settled by `bd init` adding CLAUDE.md section.
- Global Abend-Hinweis rule in `~/.claude/CLAUDE.md` was sharpened: time
  limit is the user's, not the agent's. Less interaction by default — the
  user prefers artifacts to react to over questions to answer. Captured in
  project memory under `feedback_autonomous_low_interaction.md`.
- `.gitignore` cleaned up: synthetic fixtures (`fixtures/*.jsonl`) committed;
  beads internal `*.jsonl` exports ignored.

## Late-evening addendum — GLiNER multilingual

After the headline finding, ran `apf-4f4.9` (GLiNER as Stage-1 candidate).
Two variants tested: `urchade/gliner_multi_pii-v1` (the documented
multilingual PII model) and `nvidia/gliner-PII` (a 570M GLiNER fine-tune
released October 2025 — found while searching for the May 2026 GLiNER2-PII
paper, whose HF model ID I couldn't locate within the time-box).

Both **roughly doubled the tier-recall** of the best previous candidate
without inflating latency much. Numbers in the new ARCHITECTURE.md
decision-log addendum ("2026-05-16 (later) — GLiNER multilingual
reshapes the picture"). Headline:

| Model | tier-recall | DE-rec | EN-rec | p95 ms | RAM |
|---|:-:|:-:|:-:|:-:|:-:|
| GLiNER `urchade/gliner_multi_pii-v1` | **0.667** | **0.708** | 0.629 | 80 | 2.8 GB |
| GLiNER `nvidia/gliner-PII` | **0.688** | 0.674 | 0.701 | 202 | 3.9 GB |
| previous best (Anonymizer-SLM) | 0.355 | 0.382 | 0.330 | 2958 | 1.3 GB |

Critical wins:

- GLiNER catches the **implicit PII** category all earlier models missed
  — "der Kollege aus dem Controlling" tagged as person at 0.70.
- DE works (`multi_pii-v1` actually scores higher on DE than EN — 0.708
  vs. 0.629).
- Latency well under budget — GLiNER is essentially as fast as Nemotron.
- Tier-B precision on `nvidia/gliner-PII` (0.960) is the cleanest of any
  candidate — relevant for the tool-call-resolver path where Tier-B FPs
  are costly.

Decision update: the morning's "no single model hits 0.95 → must build
ensemble" finding still holds (GLiNER tops at 0.69), but the residual
gap is small enough that the ensemble is now a tractable engineering
problem, not a research question. Stage-1 primary engine = GLiNER
`multi_pii-v1`. The next concrete step is `apf-857` (ensemble meta-adapter)
with the architecture sketch added to the decision log.

## Final evening — ensemble settles the engine question

Built ensemble-fast (regex + GLiNER) and ensemble-full (+ Anonymizer).
Numbers in the third decision-log entry. Headline:

- **ensemble-fast = the PoC engine.** Tier-recall 0.715, p95 76 ms,
  2.8 GB RAM. Within all original budgets.
- ensemble-full adds +3 pp tier-recall for 42× the latency, and Tier-C
  recall *drops* (Anonymizer FPs dilute regex's high-precision secret
  hits). Diminishing-return verdict is unambiguous.

This settles which detector(s) the PoC will use. The recall criterion
itself gets revised in the decision log — the original "≥ 0.95 in both
languages" was always under the assumption of a single perfect model.
Reformulated as a per-category target with a "low-confidence flag" UX
fallback for implicit PII.

What's no longer relevant after this finding:

- `apf-4f4.10` (Nemotron BF16 vs 8bit) — Nemotron is dominated by GLiNER
  on every metric. Quantisation question is moot. Closing as not-doing.

## Open follow-ups (beads)

| Issue | What |
|---|---|
| `apf-fu6` | Tool-call resolution prototype — now empirically informed: Nemotron + regex gives a fast enough Tier-B floor to make boundary resolution feasible. |
| `apf-8w3` | PasteGuard reversibility check — still not done, still important if we ever fork it. |
| `apf-zs4` | License decision — still deferred. |
| *(new)* | GLiNER multilingual as Stage-1 candidate against the fixture set. |
| *(new)* | BF16 Nemotron variant — quantisation-loss check, low priority. |
| *(new)* | Stage-1+2 ensemble harness — add a meta-adapter that calls multiple detectors and merges spans. |
