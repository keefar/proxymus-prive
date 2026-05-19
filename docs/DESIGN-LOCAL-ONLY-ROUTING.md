# Local-only categories — never-forward design (apf-sgz)

Resolves the open question from `docs/THREAT-MODEL-PRIVATE.md` §5.6
(deferred from the closed apf-5ue). Status as of 2026-05-19: **v1 refusal
stays; v2 local-routing deferred until detector emits the labels and
a worked integration scenario needs it.**

## TL;DR

- v1 (already shipped under apf-enr → `apf/local_only.py`) refuses any
  request whose detector spans hit the locked-label set. The set covers
  asylum/refugee status (L6), domestic abuse / DV (S10), whistleblower
  intent (P8), undocumented-immigration status (L5).
- v2 (silent route-to-local) is the natural follow-up but **defers** on
  three hard prerequisites: detector emits the labels, a local model is
  declared a dependency, and the composition story with the agent
  harness is concrete.
- For PoC scope, the answer is **stay with v1**. Adding v2 now would
  bake assumptions about a local-model architecture that the PoC has
  not validated yet.

## What v1 already does

`apf/local_only.py` exposes a label set (`DEFAULT_LOCKED_LABELS`, with
`APF_LOCKED_LABELS` env override). `apf/proxy.py` runs a read-only scan
BEFORE masking: if any locked label is detected, the request gets
a 422 with a structured body listing the categories (no values). The
locked values never enter the vault.

This is composed correctly with apf-ycu (endpoint trust map):
the locked-scan is skipped when the destination is trusted-local
(`policy = "off"`), since local-trusted endpoints don't pose the
exfiltration risk the locked set protects against. The scan fires only
when destination ∈ untrusted-cloud AND span ∈ locked-set.

Detector caveat: the production detector ensemble does not currently
emit the locked labels — they sit unused in the configuration until a
detector extension (fine-tuned GLiNER head or small classifier) is
plumbed in. The architecture is forward-compatible: once detection
lands, the refusal path activates without any proxy-layer change.

## What v2 was supposed to be

Original aspiration (apf-5ue §5.6 → this issue): instead of refusing,
silently route the request to a locally-resident model. The user gets
an answer; the locked content never leaves the machine.

Three sub-options were on the table:

- **2a — Refuse + surface error** *(v1, already shipped)*. Simple, no
  local-model dependency, but the user has to do something manual.
- **2b — Route whole request local**. Drops the cloud-model quality for
  the entire turn whenever any locked content is present. Conservative,
  but degraded answers may surprise the user.
- **2c — Split per locked span**. Local model answers the locked part;
  cloud answers the rest; the proxy stitches. **Hard** — message-level
  splitting on natural-language boundaries breaks turn structure, and
  the agent's tool-use plan likely depends on both halves.

## Why v2 stays deferred for now

Three prerequisites that aren't met in PoC scope:

1. **Detector emits the labels.** None of the four locked categories
   are in the current detector vocabulary (PERSON, EMAIL, ADDRESS,
   PHONE, LOCATION, DATE, ORG, plus Tier-B/C operational classes).
   Without detection, the routing layer has nothing to route on.
2. **Local-model dependency.** Routing-to-local turns an optional
   side feature (loopback rig) into a hard runtime requirement. That
   means picking a default model, documenting download/install,
   maintaining version compat across MLX engine upgrades. The PoC
   doesn't have user signal that this is worth carrying.
3. **Composition with the agent harness.** Agents are turn-by-turn;
   the proxy is stateless across turns. If a turn-1 user prompt
   contains locked content and routes to a local model, turn-2 may
   reference outputs the cloud model never saw. The agent harness
   would need to be aware that a turn happened "off-cloud" — and
   that's a change to the client, not just the proxy.

Until one of these is resolved, v1 refusal is the better answer:
clear failure mode, no degradation of legitimate cloud traffic, no
hidden state.

## What changes when v2 is on the table

When (and only when) the prerequisites above are met:

- **Detection sourcing.** Per-category config in `filter.toml` is
  overkill for a small set. `APF_LOCKED_LABELS` env override exists
  today and is sufficient for tuning. The detector itself needs a
  list of labels to emit; that should also live in `filter.toml` or
  similar once the detector is configurable.
- **Routing decision.** Default to option 2b (route whole turn local),
  not 2c (split). The complexity of 2c is not justified at v2; it can
  be a v3 if any user actually asks for it. 2b means: the locked-scan
  result also flips the upstream URL for this one request.
- **Local-model dependency.** Operator-configured. The user supplies
  an `APF_LOCAL_FALLBACK_UPSTREAM` (Ollama / mlx-lm / oMLX URL) and a
  default model name. The proxy stays vendor-neutral; no built-in
  model download.
- **UX.** The proxy adds an `x-apf-routed-local` response header so a
  UI layer can surface "this answer stayed on your machine". No
  in-band annotation in the response body (would be visible to the
  user's saved transcripts and pollute downstream tool flows).
- **False-positive cost.** If the detector lights up a locked label
  on benign text, the user gets a worse answer from the local model
  with no indication why. The `x-apf-routed-local` header is the
  remediation: a UI can show "answered locally because ASYLUM_DETAIL
  was matched in your message", and the user can either accept it or
  request `!override-local` (mirror of the `!raw` whitelist pattern,
  apf-qzc).
- **Audit log integration.** v2 audit log (apf-x1t, on the table next)
  should record locally-routed requests separately from cloud-forwarded
  ones, so self-review can answer "how much of my workload stayed
  local this week".

## Decision

PoC scope: stay on v1 (refuse). Re-open v2 once detector emits the
locked labels and a concrete agent-harness integration (e.g. Claude
Code session with locked content surfacing in a real-world prompt)
needs it.

This issue closes; the v2 follow-up can be a fresh ticket when the
prerequisites land.

## References

- `apf/local_only.py` — the v1 implementation.
- `apf/proxy.py` — the scan-and-refuse path (`_scan_body_for_locked`,
  the gate in `chat_completions` / `messages` handlers).
- `docs/THREAT-MODEL-PRIVATE.md` §2 (taxonomy), §3.1 (categorical
  leak), §5.6 (open question this resolves).
- apf-enr (closed) — v1 design + decision.
- apf-ycu (closed) — endpoint trust map composing with this layer.
- apf-x1t (next up) — audit log v2 that should record locally-routed
  requests once v2 of THIS feature exists.
