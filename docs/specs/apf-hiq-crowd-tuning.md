---
id: apf-hiq
title: Crowd-improvable filter tuning — users test + improve detection in operation
tag: feature
cluster: -
created: 2026-06-02
status: proposal-for-brainstorm
reference-fork: https://github.com/SigmaHQ/sigma
subitems: true
testable-surface: apf/rules.py, apf/shadow_mode.py
---

# Crowd-improvable filter tuning

> **Proposal, not a draft spec.** The owning bead (apf-hiq) is marked
> "AWAITING OWNER BRAINSTORM". Three architectural questions need an
> owner decision before this can be sliced into beads; this document
> lays out each question with options, a recommendation, and the
> downstream consequences of each choice.

## Context

The detector ensemble has a known recall floor (~0.75-0.82 tier-equality
per CLAUDE.md, confirmed by apf-1oy + the apf-abn split). The interesting
property of a privacy filter is that **every user sees blind spots that
nobody else sees** — local language, niche jargon, domain-specific PII
shapes. A privacy filter that improves only when its maintainers see a
miss can never reach those.

Goal: a path where users (a) safely test detection improvements against
their own traffic before promoting them, (b) contribute improvements
back in a structure that survives verification + community review.

Hard constraint already established in the bead notes: **shared rules,
NEVER user data.** No part of this system is allowed to leak the text
that produced a rule.

Prior-art survey done in apf-hiq notes (2026-05-24): CrowdSec
shadow-mode + Sigma rule-format are the closest models; VirusTotal /
Elastic Security ship rule distribution but at much higher
infrastructure cost than apf can carry.

## Acceptance Criteria

_Lock these only after the brainstorm answers Q1–Q3 below._

- [ ] Users can author a detection rule locally without touching Python
- [ ] Shadow mode: a rule runs alongside production, flags spans
      without acting on them, surfaces to the user for accept/reject
- [ ] At least one promotion path: shadow → local-active → upstream PR
- [ ] CI gate on upstream PRs: rule runs against a synthetic-fixture
      suite + an over-broad-pattern check
- [ ] Distributed rules ship as a versioned bundle that apf loads at
      startup; rule provenance (author + commit + version) preserved
- [ ] Hard constraint test: the shadow-mode pipeline must verifiably
      never write the original text that triggered a rule, only the
      rule id + masked-context

## Out of Scope

- A rule "marketplace" UI (web frontend)
- ML-trained rule generation from user data (would violate the
  no-user-data constraint)
- Cross-user rule sharing without a verification gate (rules must
  pass through a maintainer pipeline)
- Rule auto-tuning based on aggregated telemetry — the project's
  privacy stance forbids the telemetry that would feed it

## Reference Fork

**Sigma** ([https://github.com/SigmaHQ/sigma](https://github.com/SigmaHQ/sigma))
is the rule-format reference. Mature YAML schema, established
ecosystem for shared detection rules, language already familiar to
security folks. The semantics are a different domain (SIEM events vs.
text-span detection) but the schema patterns transfer:

```yaml
title: Austrian phone number with 0664 carrier prefix
id: <uuid>
status: experimental
author: <github-handle>
tags:
  - pii
  - phone
  - austria
detection:
  pattern: '\+43[\s\-]?6(64|99)[\s\-]?\d{3,}'
  label: PHONE
  tier: A
  confidence: 0.85
examples:
  - text: 'Meine Nummer ist +43 664 1234567'
    spans: [{start: 16, end: 32}]
anti_examples:
  - text: 'Telefon: 0900 12345'   # not a mobile, must not match
    spans: []
```

**CrowdSec** ([https://github.com/crowdsecurity/crowdsec](https://github.com/crowdsecurity/crowdsec))
is the shadow-mode reference. Their "shadow scenario" runs a new
detection alongside the production set, flags would-have-fired events
without acting on them, surfaces them for operator review. Same shape
applies cleanly to PII detection.

Sokratik-Frage: a rule-based shareable detection layer parallel to the
ML ensemble — is the goal "extend the regex catalog" (B-tier) or "extend
the structured-PII detection floor before ML kicks in"? They want
different ergonomics. Q1 covers this.

## Testable Surfaces

| Surface | Why this needs tests |
|---|---|
| `apf/rules.py` (proposed) | YAML parse + rule compile + match — pure-function, must round-trip examples/anti-examples |
| `apf/shadow_mode.py` (proposed) | Side-channel that flags without acting; must verifiably never persist source text |
| Promotion CLI (proposed) | shadow → local-active state change; signed bundle generation |

## Sub-Items

| # | Title | Rationale |
|---|---|---|
| .1 | Rule format + local execution (no sharing) | Smallest shippable slice — users can author rules and run them in their own apf install. No upstream/PR machinery yet. |
| .2 | Shadow mode + accept/reject UX | Builds on .1 — needs rule execution before shadow makes sense. |
| .3 | Distribution: bundle format + signing + CI | Last — only useful once .1+.2 have at least one real user. |

`/pickup apf-hiq` defaults to .1.

## Brainstorm questions

### Q1 — Declarative rule format

| Option | Sketch | Pro | Con |
|---|---|---|---|
| **A** | Sigma-style YAML (above) | Familiar to security folks; tooling reuse; supports examples + anti-examples as first-class fields | YAML; another schema to maintain; over-engineered for what's mostly regex + label + tier |
| **B** | TOML rules in the same shape as existing config (`config_dir() / "rules/*.toml"`) | Matches existing apf config idiom; less ceremony | Diverges from the broader detection-rule ecosystem; no off-the-shelf editor support |
| **C** | Python module per rule | Maximum expressiveness (rule can use context) | Each rule is executable code → trust/sandbox problem becomes hostile; can't safely import from another user |

**Recommendation: A.** The whole point is shared rules; Sigma's
familiarity + the examples/anti-examples-as-data property pay for the
schema complexity. B looks tidier in isolation but loses every
advantage of "the rest of the world already does it this way." C is
disqualified by the trust model — you cannot accept executable code
from a third party in a privacy filter. **Open question for owner**:
how literal should the Sigma compatibility be? Could we reuse pySigma
to parse, or do we need our own loader because the matcher semantics
are span-based, not log-event-based?

### Q2 — Shadow-mode UX

| Option | Surface | Pro | Con |
|---|---|---|---|
| **i** | In-proxy `/v1/shadow` API endpoint | Same process as the masking pipeline; cheapest plumbing | API needs UI on top; not great for a CLI-first user |
| **ii** | CLI: `apf rules shadow --rule new.yaml --fixtures my.jsonl` | Off-line, fits "test before deploying" workflow; works with private fixtures | Doesn't cover the "test against actual live traffic" use case |
| **iii** | Both — CLI for off-line + the in-proxy hook for on-line shadow | Covers both workflows | More surface to maintain |
| **iv** | Separate "apf-lab" tool | Keeps experimental code isolated from production proxy | User installs a second thing; rules can't easily flow CLI → proxy |

**Recommendation: iii.** Each surface answers a different real
workflow: CLI = "I'm tuning this rule against private fixtures
I'd never put through the proxy"; in-proxy = "I want shadow this
rule against my actual daily traffic for a week before promoting."
Cost is real but the two surfaces share the rule engine — only the
I/O differs. Start with CLI (smaller surface), add the in-proxy hook
in sub-item .2.

### Q3 — Trust / verification model for upstream PRs

The hard constraint is **no user data ever upstreams** — only rules.
That constrains the contribution surface to "rule + synthetic example
text + anti-example text." What gates a rule into the shipped bundle?

| Stage | What runs | Decided by |
|---|---|---|
| **Author** | local CLI test against own fixtures | author |
| **PR** | CI: rule runs against synthetic fixture suite; over-broad-pattern check (e.g. matches > N% of plain-English Wikipedia paragraph); examples must match, anti-examples must not | apf maintainers via PR review |
| **Bundle** | rule signed by maintainer key + included in versioned bundle on a tag | apf maintainers |
| **User install** | bundle verified at startup; rules opt-in by tag (`rules.enabled_tags = ["pii", "germany"]`) | end user |

**Brainstorm specifics for the owner:**

1. **Synthetic fixture suite for CI** — needs to live in-repo,
   needs broad coverage. Could seed from existing `fixtures/`
   (the public, non-PII fixtures) plus a curated "false-positive
   trap" set (Wikipedia text, code, configuration files).
2. **Over-broad-pattern test** — concrete heuristic: rule may not
   match more than X% of tokens in a 1000-paragraph Wikipedia sample.
   X needs a number; suggest 0.1% as a first proposal.
3. **Locale tags** — German rules don't help English users and
   vice-versa. Bundle structure should let users enable just their
   locales; default-on locales need a maintainer call.

**Recommendation**: ship .1 + .2 (author + local shadow) under a "no
distribution yet" caveat; only commit to the distribution model
(.3) after at least one external contributor has authored a rule
locally and the schema has survived contact with reality.

## References

- bd apf-hiq — original idea + 2026-05-24 prior-art triage notes
- bd apf-abn — GLiNER low-threshold experiment; if that lands, the
  "rules vs. ML" division becomes important (rules patch ML blind
  spots, not the other way round)
- bd apf-1oy — recall ceiling analysis; this work is the long-tail
  answer to "the ensemble caps out at ~0.75"
- SigmaHQ rule format docs
- CrowdSec shadow-mode design notes
- `fixtures/content.jsonl` / `fixtures/operational.jsonl` — existing
  public synthetic fixtures; candidate seed for the CI suite

## Notes

- Privacy invariants must be enforced **in code**, not by convention:
  the shadow-mode logger needs a unit test that asserts the only
  fields written are `{rule_id, span_label, span_length, run_id}` —
  never `text` or `before` or any field containing original input.
- Cross-platform: rules are pure YAML/regex, no platform dependence.
- The over-broad-pattern test in Q3 is the single biggest defence
  against "rule that matches everything and silently masks all
  output." Worth more brainstorming time than its size suggests.
- Open question for owner: does the bundle need a kill-switch for
  individual rules post-distribution? If a shipped rule turns out
  to over-fire badly, can users disable just that rule without
  rolling back the whole bundle? Suggested answer: yes, per-rule
  enable/disable in user config.
