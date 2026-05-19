# Over-filter evaluation methodology

## Why this exists

Privacy filtering trades information against utility. A filter that
masks everything reaches recall 1.0 trivially but makes the
assistant agent useless. A filter that lets too much through is a
leak. The trade-off needs a *measurement* layer — not a feeling — and
that measurement is what this document defines (apf-00s).

The pair-eval method below pins three numbers per fixture:

1. **Leak rate** — fraction of `must_anonymize` spans that survived
   to the LLM. Lower is better.
2. **Task success rate** — does the agent's reply still complete the
   user's task? Three-level rubric (full / partial / impossible).
3. **Per-category utility loss** — which sensitive categories cost
   the most utility when filtered? This drives §5.1 / §5.3 tuning.

## Method (pair-eval)

For each fixture in `fixtures/private/private.jsonl`:

1. **Define 1–3 agent tasks** that a personal assistant would
   plausibly perform on this content. Tasks are short, single-turn,
   answerable from the fixture alone.

   Examples (de-repro-01):
   - *Summarise this referral letter in 2 sentences.*
   - *Extract the appointment date and clinic name.*
   - *Draft a forwarding email to the user's Hausarzt.*

2. **Run twice per fixture**:
   - **Control**: agent sees the original fixture text (no filtering).
   - **Treatment**: agent sees the masked text (filter applied with
     v1 settings — opaque tokens, eager defaults).

3. **Score both runs** with the same rubric. Comparison gives the
   task-utility delta caused by filtering, separated from
   agent-quality variance.

4. **Aggregate**:
   - **Δ-success rate** per category: how much utility we lost.
   - **Leak rate** per category from the treatment run (sanity check
     that detection works as expected).

## Scoring rubric

Per agent task, judge assigns one of:

- **full** (2): reply answers the task completely, no hallucination,
  no awkward placeholder retention.
- **partial** (1): reply answers part of the task; loss attributable
  to the filter (e.g. agent says "I can't tell you the date because
  I see `<REF_3>`" — that's a partial when the date is
  obviously the task).
- **impossible** (0): reply can't address the task at all; the agent
  refuses, hallucinates, or asks for missing values that *were*
  filtered.

For task-success rate, treat full+partial as success, impossible as
failure. We track partial separately because partial is the
interesting trade-off zone — that's where category opt-out (§5.3)
moves the needle.

## Judge

The rubric is intentionally simple enough to be judged by a small
LLM. v1 implementation uses Claude Sonnet as judge (1 call per (run,
task) pair = 2 × N_tasks per fixture). Future variants:

- **Self-judge**: the same model that produced the reply also grades
  it. Cheaper, biased toward leniency. Acceptable as a smoke signal,
  not as a primary measurement.
- **Human spot-check**: random 5% sample. Catches systematic judge
  failures (e.g., judge consistently rating coherent-but-empty
  replies as "full").

The harness is API-pluggable — the judge is a `JudgeFn(run, task)
-> Rating` callable. The current scaffold ships a `StubJudge` for
the pipeline-shape test (returns deterministic ratings from a hash
of run content). Replace with an Anthropic / OpenAI client for real
runs.

## What this is NOT

- **Not a replacement for real-world UX testing.** Synthetic fixtures
  give us comparable numbers across detector changes; they don't
  predict whether a real user is happy.
- **Not a measure of agent intelligence.** Both runs use the same
  agent; we're isolating the filter's contribution, not the
  underlying model.
- **Not a privacy guarantee.** Leak rate is a sample-level statistic
  on a synthetic corpus. A fixture-set leak of 0.0 does not mean
  zero-leak in production.

## Concrete tasks per fixture (initial set)

The 13 single-turn fixtures get 1–3 task specs each. The 14th
(multi-turn `de-profile-aggregation-01`) is reserved for the
cumulative-profile evaluation that's a separate measurement
direction (per-turn detection, profile-build-up over time).

Task specs live in `scripts/over_filter_eval.py` next to the runner
so the data + the harness stay synced.

## Pipeline

```
fixtures/private/private.jsonl
       │
       ├──── (apply filter v1 settings) ────┐
       │                                    │
       ▼                                    ▼
  Control text                       Treatment text
       │                                    │
       ▼                                    ▼
  Agent run                          Agent run
       │                                    │
       └──────── judge(reply, task) ────────┘
                          │
                          ▼
                 ratings per (fixture, task, condition)
                          │
                          ▼
                aggregate → docs/results/<date>.md
```

Run as `python scripts/over_filter_eval.py --fixtures
fixtures/private/private.jsonl --out docs/results/eval-2026-05-17.md`.

## When the numbers move

The numbers themselves are first estimates; tracking *change* is
more interesting than absolute values:

- A detector change → measurable shift in leak rate (expected
  direction: down).
- An opt-out being enabled by default → shift in success rate
  (expected: up) AND in leak rate (expected: up, controlled).
- A new category being added to the taxonomy → measurable on the
  fixtures that contain it.

The first run establishes the baseline. Subsequent runs measure
deltas.

## Open questions for future tuning

- **Per-category thresholds**: §5.4 multi-stage warning uses
  diversity counts; the empirical pin should come from where the
  utility/leak frontier kinks in the eval data.
- **Cumulative profile (§3.3)**: needs the multi-turn fixture
  (apf-h0j) and a different metric — profile-completeness against a
  re-identification threshold. Separate measurement direction.
