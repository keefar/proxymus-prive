---
id: apf-auw
title: Endpoint routing layer — switch upstream per request, auto local on high-PII context
tag: feature
cluster: -
created: 2026-06-02
status: proposal-for-brainstorm
reference-fork: https://github.com/BerriAI/litellm
subitems: true
testable-surface: apf/routing.py, apf/routing_config.py
---

# Endpoint routing layer

> **Proposal, not a draft spec.** The owning bead (apf-auw) is marked
> "AWAITING OWNER BRAINSTORM". This document collects the three unresolved
> architecture questions in one place with options + a recommendation per
> question, so the brainstorm session can converge to a draft spec
> instead of starting from blank.

## Context

apf sits between the agent frontend and the upstream LLM endpoint.
Today the upstream is fixed at proxy boot (one OpenAI-compat URL, one
Anthropic URL). For agents like Hermes that normally choose their own
upstream per call this is a regression — apf removes a degree of
freedom they used to have.

Two demands stack on top of "let users switch upstream":

1. **Per-use-case routing**: a Hermes "research" skill goes to a big
   cloud model, a "summarize-my-notes" skill goes to local oMLX. The
   user wants to declare this once, not toggle env vars per session.
2. **Auto local on high-PII context**: when the filter detects a
   high-density-PII turn, route to a local model instead of cloud —
   either silently or with a one-line warning. This is the
   privacy-aware-routing piece that overlaps with research work
   (PrivacyPAD, PRISM, Privacy Guard).

Prior-art survey done in apf-auw notes (2026-05-24): LiteLLM is the
clear baseline for the routing layer itself; the auto-by-PII piece is
research-state with no production reference.

## Acceptance Criteria

_Lock these only after the brainstorm answers Q1–Q3 below._

- [ ] One config file (location: `config_dir() / "routing.toml"`,
      override `APF_ROUTING_CONFIG`) declares upstreams + routing rules
- [ ] Per-request routing key combines: agent identity (header or URL
      path), masked-sensitive-count for this turn, optional explicit
      override (session header or in-prompt sentinel)
- [ ] Auto-local trigger has at least one explicit threshold knob the
      user can tune (count, tier-C presence, locked-category presence)
- [ ] Routing decision logged per turn (audit_log already exists — extend)
- [ ] Healthz exposes "active upstreams" + "current routing rules count"
- [ ] No breaking change for users who set zero rules — the old
      single-upstream behaviour stays the default

## Out of Scope

- Token-cost-aware routing (apf doesn't see vendor pricing)
- Streaming-mid-flight upstream switching (route is decided per turn,
  before the first byte goes upstream)
- Multi-model fanout / shadow-comparison routing
- A separate "router daemon" process — routing logic lives inside apf

## Reference Fork

**LiteLLM** ([https://github.com/BerriAI/litellm](https://github.com/BerriAI/litellm))
covers the upstream-multiplexing + provider-translation problem
comprehensively. The brainstorm question is not "should we use
LiteLLM" but "how does apf relate to LiteLLM" — see Q1.

Forks of interest for the auto-by-PII piece:
- PrivacyPAD: research prototype, useful as design reference, not
  production-ready as a fork base
- LLM Guard (protectai): privacy redaction with policy hooks; relevant
  for the "deny" path more than the "route" path

Sokratik-Frage: form factor is "proxy with routing logic". An
alternative is "router daemon in front of apf" (LiteLLM proxy →
apf → upstream). The latter is operationally heavier (two processes
vs. one) but cleaner architecturally. Q1 covers this.

## Testable Surfaces

| Surface | Why this needs tests |
|---|---|
| `apf/routing.py` (proposed) | Per-request rule evaluation must be pure-function; integration test must not need a live upstream |
| `apf/routing_config.py` (proposed) | TOML parsing + validation; round-trips known good + bad configs |

## Sub-Items

| # | Title | Rationale |
|---|---|---|
| .1 | Static per-agent routing (no PII-aware piece) | Ship the simpler half first; gives "per-use-case routing" without committing on the auto-trigger design |
| .2 | Auto-local-on-high-PII routing | Builds on .1 — needs a working static layer underneath |

`/pickup apf-auw` defaults to .1; auto-chain into .2 after .1 ships.

## Brainstorm questions

### Q1 — Architecture: how does apf relate to LiteLLM?

| Option | Sketch | Pro | Con |
|---|---|---|---|
| **A** | apf-as-LiteLLM-plugin (Python callback) | Reuses LiteLLM's routing + provider catalogue out of the box | Inverts the trust boundary — apf becomes a plugin in someone else's process; harder to verify the masking pipeline can't be bypassed by a misconfigured plugin chain |
| **B** | LiteLLM-as-apf's-upstream | Apf owns privacy, LiteLLM owns routing — clean separation of concerns; each tool single-purpose | Two-process setup; user installs and configures two daemons; LiteLLM becomes a runtime dependency for routing |
| **C** | apf standalone, built-in router | One process, no extra dep | Reinvents LiteLLM's provider matrix; we'd ship a worse version of code that already exists |

**Recommendation: B.** The principle is "privacy filter is upstream of
routing, full stop" — that's exactly what B encodes. The two-process
cost is real but the alternative is either (A) compromising the apf
trust boundary or (C) duplicating LiteLLM's provider-translation
work. **Open question for owner**: is "user installs LiteLLM" an
acceptable additional setup step, or is one-process operation a hard
requirement? If hard requirement → revisit C.

### Q2 — Per-use-case config format

Proposed shape (TOML, lives in `config_dir() / "routing.toml"`):

```toml
[upstreams.openai]
url = "https://api.openai.com"
api_key_env = "OPENAI_API_KEY"

[upstreams.local-omlx]
url = "http://127.0.0.1:8000"

[[rules]]
# Match: an agent identifies itself via `x-apf-agent: <name>` header
match = { agent = "claude-code", path = "/v1/messages" }
upstream = "openai"

[[rules]]
match = { agent = "hermes", skill = "summarize-notes" }
upstream = "local-omlx"

[[rules]]
# Fallback rule — matches anything not caught above
match = { agent = "*" }
upstream = "openai"

[auto_local]
# Q3 lives here — see below
enabled = false
upstream = "local-omlx"
trigger.tier_c_count = 1
trigger.total_pii_count = 8
trigger.locked_category = true
```

**Match dimensions to brainstorm:**

- **agent**: header `x-apf-agent` set by the agent frontend, or URL
  path prefix as a fallback. Either needs a "well-known" header name.
- **skill / sub-route**: how does the agent declare its sub-purpose?
  Hermes can pass `x-apf-skill`; Claude Code has no such concept
  out of the box. Path-pattern-match as a fallback.
- **model**: requested model in the body — straightforward but
  duplicates LiteLLM's job in B above.

**Recommendation**: start with `agent + path` only for v1 (matches
existing `x-apf-session` precedent), add `skill` after the headers
question is settled with at least one real agent integration.

### Q3 — Auto-route-trigger tuning

The "high-PII context" signal is the novel piece. Options:

| Option | Signal | Notes |
|---|---|---|
| **i** | `tier_c_count ≥ 1` (any secret) | Strictest; routes any turn touching a Tier-C secret. Catches credential leakage in 1 dimension. |
| **ii** | `total_pii_count ≥ N` | Density signal; tunable. The "drowning in personal data" turn. Needs an N that doesn't fire on every email-with-greeting. |
| **iii** | `locked_category` match (asylum/abuse/whistleblower) | Already a category in apf; the strongest signal for "this turn must not leave the device". |
| **iv** | Composite: any of i+ii+iii triggers | Belt-and-braces. Recommended default if the auto-trigger ships at all. |

**Behaviour when triggered:**
- **silent route** → user notices nothing, audit-log says "routed local"
- **warn + route** → adds a one-line system note to the response
- **deny if no local** → fail closed if local upstream is unconfigured/unreachable

**Recommendation**: ship the static router (Q1+Q2) without auto-trigger
first (`auto_local.enabled = false` default). Auto-trigger lands as a
sub-item .2 once the static router has a real user; the trigger then
gets tuned against real `audit_log` data, not synthetic fixtures.

## References

- bd apf-auw — original idea + 2026-05-24 prior-art triage notes
- bd apf-dtq — hosted-agent subscription token problem (constrains
  which agents can realistically be a first target for routing)
- `apf/endpoint_policy.py` — existing per-host policy code (full/off/
  categorical) is the closest current analogue and a likely co-located
  module for the new routing code
- `apf/audit_log.py` — extend for routing decision logging
- LiteLLM proxy docs (routing + fallbacks)
- PrivacyPAD (academic), Privacy Guard (research)

## Notes

- The privacy claim of the project is "PII detection runs locally" —
  routing logic itself is also local-only by construction (route
  decisions never leak to a third party).
- Cross-platform constraint applies: routing module must be pure
  Python, no MLX dependency. The auto-trigger reads detector output
  that the proxy already has in-process — no extra inference cost.
- Open question for owner: does the routing layer need to support
  HTTP methods beyond POST? (Today apf serves chat-completions +
  messages — that's two POSTs. Embeddings / completions / batches /
  streaming-only paths each have their own request shape.)
