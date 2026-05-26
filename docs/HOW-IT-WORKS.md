# How the filter works — and where it gets hard

A practical walk-through of proxymus-prive (`apf` in code and tooling):
what happens to a
request, how the personal data is detected, and an honest ledger of the
problems we hit building it and what we did about each one.

If you want the *vision*, read the [README](../README.md). If you want the
*design rationale and decision log*, read [ARCHITECTURE.md](ARCHITECTURE.md).
This document is the middle layer — enough to trust, or distrust, the filter
on the right grounds.

> **Status:** working proof-of-concept. The pipeline runs end-to-end against a
> real cloud agent (Claude Code) and an all-local stack. Every number below
> comes from the fixture benchmarks and PoC test runs — not a production
> security audit. Where something is unsolved, this doc says so.

---

## 1. The round trip in one picture

```
                          ┌───────────────────────────────────────┐
 coding agent ──HTTP──────▶│  apf proxy                            │──HTTPS──▶  cloud LLM
 (Claude Code, Cursor,    │                                        │            (Anthropic /
  Aider, Codex, …)        │  request path:                         │             OpenAI)
                          │   1. parse body (Anthropic / OpenAI)   │
                          │   2. detect PII spans (ensemble)       │
                          │   3. swap each span for a placeholder  │
                          │   4. forward only placeholders         │
                          │                                        │
                          │  response path:                        │
                          │   5. restore originals in the text     │
       user ◀─────────────│   6. resolve placeholders inside       │
        sees originals    │      tool-call args at the boundary    │
                          │                                        │
                          │  per-session vault: original ↔ token   │
                          └────────────────────────────────────────┘
```

apf is an HTTP proxy. A coding agent points its API base URL at apf instead of
`api.anthropic.com`. Every request is inspected; personal data is swapped for
placeholders *before it leaves the machine*; the original values are restored
in the response the user sees. **The cloud model only ever sees placeholders.**

Three things make this more than a regex find-and-replace:

1. **It is reversible.** The user reads the agent's answer with the real names,
   paths and values in place — masking that cannot restore is off-spec.
2. **It resolves placeholders at the tool-call boundary.** When the model says
   `grep "<REF_3>"`, the *real* value is substituted only at the moment the
   tool runs locally — and never travels back into the model's context.
3. **It treats secrets differently from content.** An API key and a recipient
   name look alike to a proxy but need opposite handling (see §3).

---

## 2. The three-tier model

What the filter protects splits into three classes with **fundamentally
different mechanics**. Treating them uniformly is a category error.

| Tier | What lives here | Placeholder | Reversible? | Resolved where |
|---|---|---|:--:|---|
| **A — Content PII** | names, emails, phones, addresses, locations, dates, health info, financial fragments, implicit/paraphrased identifiers | `<REF_N>` | yes | in the response shown to the user; in tool args if needed |
| **B — Operational identifiers** | filesystem paths, identity-encoding filenames, hostnames, local + public IPs, machine-specific URLs | `<REF_N>` | yes | **always** at the tool-call boundary — every `Read`/`Bash`/`grep` needs the real value |
| **C — Secrets** | API keys, OAuth tokens, private keys, passwords, DSN strings with credentials | bare `<REF>` | **no** | pulled from env / keychain at exec time — never enters the prompt at all |

For Tiers A and B the goal is **reversibility**. For Tier C the goal is
**unobservability** — the model should not reason about the secret even via a
token, so the secret placeholder carries no number and no type hint. This is
the one place the classic "anonymize → call LLM → de-anonymize" pattern is the
wrong shape.

---

## 3. Detection: an ensemble, not a magic model

The honest headline first: **there is no large language model doing the
detection.** The project name says "MLX" — that is the *hardware* target
(Apple Silicon). The detector that actually shipped is an ensemble of small,
fast, local components:

- **Regex baseline** — emails, IBANs, API-key prefixes, PEM blocks,
  `KEY=VALUE` env assignments, Bearer tokens, DSN strings. Sub-millisecond,
  near-perfect precision on known shapes, blind to anything contextual.
- **Microsoft Presidio** — regex catalogue + spaCy NER, ~6 ms, catches German
  and English names/locations that the GLiNER models sometimes miss.
- **GLiNER `multi_pii-v1`** — multilingual zero-shot NER; strong on German
  prose and *paraphrased* identifiers ("der Kollege aus dem Controlling").
- **GLiNER `nvidia/gliner-PII`** — higher precision on structured operational
  inputs (paths, URLs, code); 0.96 Tier-B precision.
- **Locked-category regex** — a dedicated pass for asylum / abuse /
  whistleblower / undocumented-status language; see §8.4.

Each detector emits character spans with a label and a confidence. They are
merged **longest-span-wins** at each position (`EnsembleMaxAdapter` in
`benchmarks/adapters_mlx.py`). The vault keeps the *minimum* confidence seen
for a value, so one uncertain detection flags the whole entry for review.

**Why no generative model?** We benchmarked them. A generative SLM
(Anonymizer-SLM) added +3 points of recall for **40× the latency** and
actually *lowered* Tier-C secret recall — its free-text candidates drowned out
regex's high-precision secret hits in the merge. The decision log in
[ARCHITECTURE.md](ARCHITECTURE.md) has the full table.

### Where the numbers stand

Engine: `ensemble-max`. Measured on two sets (full evaluation dossier
kept locally; benchmark rig is in `benchmarks/run.py`):

| Set | Tier-recall | DE | EN | p95 latency | RAM |
|---|:--:|:--:|:--:|:--:|:--:|
| Our synthetic fixtures (50 cases, adversarial) | **0.82** | 0.79 | 0.84 | ~270 ms | ~4 GB |
| ai4privacy pii-masking-300k sample (303 cases) | **0.77** | 0.76 | 0.77 | — | — |

Broken down by tier on our fixtures: **Tier A 0.73**, **Tier B 0.86**,
**Tier C 0.94** (up from 0.57 — see §8.2). Latency and the 4 GB RAM budget are
comfortably met; recall is the open front.

---

## 4. Masking and the vault

For each detected span, `mask_text` (`apf/masker.py`) asks the per-session
**vault** (`apf/vault.py`) for a placeholder via `get_or_mint`:

- The **same original value always gets the same token within a session** —
  stable IDs let the model reason consistently ("send it to `<REF_1>`" two
  turns apart still means the same person).
- Tier A/B values get an incrementing `<REF_1>`, `<REF_2>`, … Tier C values
  get a bare `<REF>` — no number, so the model cannot even count how many
  secrets exist.
- The vault stores the original, label, tier and confidence. **The original
  never leaves the vault**; only the token is forwarded.
- Sessions are isolated and pinned by the `x-apf-session` header (or an
  auto-generated anonymous ID).

Two things are deliberately **not** masked, because masking them broke the
agent (see §8.4): Claude Code's `<system-reminder>` scaffolding blocks, and a
small allowlist of operational terms (`AGENT_TERMS` — tool names like `Grep`).
The `ORG` label is also off by default (its precision was unusable, §8.1).

---

## 5. The tool-call boundary — the part nobody else solves

This is the project's reason to exist. Similar tools mask text and de-mask
responses; none of them solve what happens when the agent's *plan* references
a masked value.

When the cloud model emits a tool call — `grep "<REF_3>"`,
`mv <REF_5> <REF_8>` — the proxy intercepts the `tool_use` block on the
response path and `resolve_tool_call_args` (`apf/resolver.py`) walks the
arguments:

- `<REF_N>` tokens are looked up in the vault and replaced with the real value.
- A bare `<REF>` triggers the **secret resolver** (`apf/secrets.py`), which
  pulls the value from environment variables or the keychain — the secret was
  never in the prompt and is never returned to the model.
- The resolved arguments go to the local executor. The model's *context* is
  never updated with the resolved value; only the tool *result* comes back,
  and that result is re-masked before the next request.

So the real value exists for exactly the moment the tool runs, on the local
machine, and nowhere in the cloud model's context.

**Known limitation:** multiple secrets in a single tool call are resolved by
order of insertion, which is fragile. The fix — numbered Tier-C tokens
(`<REF_S1>`, `<REF_S2>`) — is noted in `apf/secrets.py` and not yet built.

---

## 6. Restoring the response

The response path runs the masking in reverse (`apf/unmasker.py`):

- **Text** parts: `<REF_N>` tokens are replaced with the originals so the user
  reads a normal answer.
- **Streaming (SSE):** the rewriter buffers a partial token tail so a
  placeholder split across two chunks (`<RE` … `F_3>`) is never half-restored.
- **Reasoning traces:** OpenAI `reasoning_content` is unmasked for display.
  Anthropic `thinking` blocks are **deliberately left masked** — they are
  cryptographically signed over the *masked* input the model saw; unmasking
  them would break the signature when the block is replayed (see §8.3).

---

## 7. When the model rejects the placeholders

A masked prompt is an unusual prompt, and models react to it.

- A local model (Qwen2.5-Coder) **safety-refused 13 of 14** masked test
  prompts — it read the old placeholder `<SENSITIVE_N>` as evidence that
  someone was illicitly sharing personal data. Renaming the token to the
  neutral `<REF_N>` removed both that trigger *and* a meta-leak (the word
  "sensitive" itself revealed a judgment about the content).
- Cloud and local models alike sometimes decline a dense cluster of `<REF>`
  tokens as suspected prompt-injection, or treat them as missing data.

The mitigation is a short **explainer** (`apf/explainer.py`) injected as a
system note when masking actually happened: it tells the model that `<REF_N>`
is a privacy placeholder, that it should reason about it normally, and that it
will be resolved automatically. It is on by default and can be disabled with
`APF_EXPLAINER=off`. Some declines are orthogonal model safety (e.g. a model
refusing a bash task regardless of masking) — those are not filter bugs.

---

## 8. The hard parts — a difficulties ledger

This is the section the rest of the doc exists to set up. Every item is a real
problem the project hit; each links to the issue (`apf-*`) and notes whether
it is **fixed**, **mitigated**, or **still open**.

### 8.1 The detector over-flags (false positives)

A reversible filter can *afford* some over-masking — a false positive just
means a slightly degraded model input; the token is restored on the way back,
so no data is lost. False *negatives* are the expensive class. But
over-masking is not free (see §8.4), so precision still matters.

| Problem | Symptom | Status |
|---|---|---|
| `PERSON` over-detection | precision **0.48** on the 250-case mixed benchmark — 119 false positives vs 111 true positives, the single largest FP source | **partly open** — span-boundary cleanup (`apf-hgk`) and dropping pronouns + single-character spans (`apf-8l1`) help; precision is still the main remaining lever |
| `ORG` over-detection | precision **0.125** (11 TP, 77 FP) | **mitigated** — `ORG` dropped from the default masking set (`apf-1f6`: opt-out, not opt-in) |
| `HEALTH` fires on generic medical vocabulary | science/anatomy terms flagged as health PII | **mitigated** — science-term stoplist (`apf-t7t`) plus Presidio's language-name stoplist |

### 8.2 The detector misses things (false negatives)

| Problem | Symptom | Status |
|---|---|---|
| No single model reaches 0.95 recall | best generative SLM topped out at **0.36** tier-recall | **mitigated** — the ensemble reaches 0.82 (synthetic) / 0.77 (ai4privacy-300k) |
| Tier-C secret recall was the weak point | **0.57** recall — secret leaks are the most expensive failure | **fixed** — regex expansion for PEM blocks, `KEY=VALUE`, Bearer tokens, DSN strings, base64 heuristic lifted Tier-C to **0.94** (`apf-1qo`) |
| Implicit / paraphrased PII | "der Kollege aus dem Controlling, der nächste Woche heiratet" — combined recall under 0.1 for early single models | **structural limit** — the ensemble + GLiNER closes much of it, but span-NER cannot reliably classify implicit PII without world knowledge. Two opt-in routes lift recall further at a known cost: `ensemble-full` adds AnonymizerSLM 1.7 B in-process (Apple Silicon only, +1.5 GB resident); `[detector.generative_stage]` in `~/.config/apf/config.toml` delegates to any local OpenAI-compatible daemon (Ollama / oMLX / LM Studio / vLLM, cross-platform — `apf-yyz`). Neither is on by default: deterministic detectors give the Tier-A guarantee, the generative pass is a recall booster |

### 8.3 Round-trip integrity bugs

These are the bugs that matter most — caught while routing **real Claude
Code** through the proxy.

| Problem | Symptom | Status |
|---|---|---|
| `tool_use` replay leak | a `tool_use` block replayed in a follow-up request was not re-masked on the request path — a resolved original value crossed *back* to the model | **fixed** (`apf-uc1`): the request masker now walks and re-masks `tool_use` args symmetrically |
| Reasoning traces showed raw tokens | `<REF>` tokens surfaced in reasoning-model output, breaking the readable-with-originals contract | **fixed** for OpenAI `reasoning_content`; Anthropic `thinking` is **intentionally** left masked to preserve its signature (`apf-8pz`) |
| `anthropic-beta` header dropped | proxy stripped the beta header → upstream 400 on `context_management` and other beta fields | **fixed** (`apf-3mb`) |

### 8.4 Over-masking broke the agent

The most instructive failure. A one-sentence user message wrapped in Claude
Code's system scaffolding (~38 KB of `<system-reminder>` blocks) produced a
**213-entry vault**: skill names and tool names were masked as `PERSON`, the
tool name `Grep` resolved to an email address, and **Claude declined the task**
because its operational context had become unintelligible.

Fix, in two steps (`apf-xt5`): skip `<system-reminder>` blocks entirely, and
add the `AGENT_TERMS` allowlist for operational terms. The vault dropped
**213 → 4**, and Claude Code now completes a real `Grep` task through the
proxy. Lesson: a privacy filter has to know the difference between the user's
data and the agent's own plumbing.

### 8.5 The categorical-leak problem

The hardest *conceptual* difficulty, and not fully a code problem. A threat-
model review found that roughly **60% of private-person sensitive categories
are "categorical-only"**: masking the *value* still leaks the *topic*. A
placeholder named `<MEDICATION_1>` hides the drug name but still tells the
cloud model "this user takes medication / is in therapy".

Resolution (threat-model §5.1, `apf-5ue`): placeholders are deliberately
**opaque**. Never `<MEDICATION_1>`, never `<SENSITIVE_N>` — always `<REF_N>`.
The category never reaches the surface token. Where an agent genuinely needs
the category to do its job, that information is meant to travel out-of-band
via tool metadata, not embedded in the prompt (a future hook).

For the most dangerous categories — asylum, abuse, whistleblower,
undocumented-status language — apf does not mask-and-forward at all. A
locked-category scan refuses the request outright; those values never enter
the vault and nothing leaves the machine.

**Still open:** the *cumulative* version. Postcode + employer + therapy
appointment time, each individually masked, can still re-identify a person by
structure across a conversation. A diversity-weighted warning is designed in
the threat model but not implemented.

### 8.6 Surrogate substitution — validated, but kept opt-in

An alternative to opaque tokens: substitute a *plausible fake* instead —
"Anna Müller" → "Petra Vogt", a real-looking email instead of `<REF_3>`. It
reads more naturally to the model and should provoke fewer refusals.

It is **built, flag-gated, and off by default** (`APF_SURROGATE_LABELS`).
End-to-end validation (2026-05-21, against a local OpenAI-compatible test
engine) confirmed surrogate mode **holds the tool-call boundary** —
originals resolve correctly into tool args, nothing leaks. It works. Three reasons it still stays opt-in:

1. **Re-detection** — a surrogate is PII-shaped, so the detector flags it
   again on the next turn. Fixed (`apf-76m`: the masker skips known-surrogate
   ranges) — but opaque tokens never had the problem.
2. **Path-composition collision** — a surrogate is plain text. If the model
   composes it into a filesystem path and the same word appears elsewhere in
   the arguments, substring restore rewrites the wrong occurrence. Opaque
   `<REF_N>` is delimited and immune. This is pinned by
   `apf/path_compose_test.py`.
3. **Observed value rewrite** — in a cloud test run the model noticed its own
   tool arguments changing mid-conversation ("something is rewriting my Grep
   patterns in flight").

Surrogate works, but it is strictly less robust than opaque on every count
above — and the model-refusal problem it was meant to solve is already
mitigated by the explainer (§7). So opaque stays the default; surrogate is a
per-label opt-in for cases where natural-text fidelity matters more than the
robustness margin. The full opaque-vs-surrogate evidence is in the local
session logs; the tests in `apf/openai_shape_test.py` and the loopback rigs
(`scripts/toolcall_loopback.py`) cover the resulting behaviour.

---

## 9. What still isn't solved

An honest list — these are limits, not oversights:

- **0.95 recall on the original spec is unreachable** with a local small-model
  setup. Implicit PII without world knowledge is an architectural limit. The
  low-confidence UX flag — showing the user what *might* be sensitive — is
  therefore part of the security model, not a nice-to-have.
- **`PERSON` precision (~0.48)** is the biggest remaining false-positive lever.
- **Cumulative profile leak** across conversation turns (§8.5) is designed but
  not implemented.
- **Streaming tool-call resolution** is not yet validated end-to-end; the unit
  tests cover it but no running-proxy proof exists.
- **Surrogate mode** is unvalidated (§8.6).
- **Benchmark honesty:** the recall numbers depend on a gold-label set built
  in-house; an estimated 10–20% of spans are debatable edge cases (is
  "Freitag" PII in this context?). The numbers are directionally sound, not
  audit-grade. The detector layer is good — but "safe" as an absolute claim it
  is not. The full per-label "honesty box" lives in the local evaluation
  dossier; you can reproduce the headline numbers from `benchmarks/run.py`.

---

## 10. Verify it yourself

Nothing here has to be taken on trust — the repo ships the rigs:

```bash
# detector precision/recall/FP benchmark
.venv/bin/python -m benchmarks.run --adapter ensemble-max --fixtures <f>

# standalone: detect → mask → simulated tool call → restore, no proxy
.venv/bin/python -m apf.demo --text "..."

# end-to-end tool-call boundary, deterministic no-leak proof
.venv/bin/python -m scripts.toolcall_loopback   # record mode

# drive real Claude Code through apf and inspect what was masked
.venv/bin/python -m scripts.cloud_toolcall --system off

# the full test suite (sub-second)
.venv/bin/python -m pytest apf/ benchmarks/

# live: detector status, active sessions, vault counts (no originals leaked)
curl 127.0.0.1:8765/healthz
curl 127.0.0.1:8765/v1/sessions/<id>/status
```

Decision narratives (per-issue *why* logs) are kept locally rather than in
the public repo; the in-tree `apf-*` issue references in code comments
point to the same decision IDs used in the local tracker.
