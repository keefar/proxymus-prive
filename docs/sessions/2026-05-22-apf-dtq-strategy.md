# 2026-05-22 — apf-dtq: delivery-model decision

The strategic resolution of apf-dtq. Read with the two prior logs:
`2026-05-21-surrogate-validation.md` (the throttle pivot) and the apf-dtq
bead notes (the investigation).

## The finding (recap)

apf cannot proxy Claude Code's traffic when the user is on a Free/Pro/Max
**subscription** plan:

- Routing `claude -p` (or any Claude Code session) through apf to the real
  Anthropic API fails 100% with `429 rate_limit_error`. Anthropic blocks
  subscription **OAuth** tokens from non-first-party use (policy since
  ~April 2026); a proxy hop makes the request non-first-party. Forwarding
  all client headers + the query string does not help — the discriminator
  is below the HTTP layer. Direct `claude -p` works; via-apf does not.
- The agent-side alternative does not close the gap: a `claude-code-guide`
  capability review found Claude Code hooks / the Agent SDK **cannot** do
  the bidirectional round-trip. `UserPromptSubmit` cannot rewrite the
  prompt; `PostToolUse` is read-only; **no hook can rewrite the model's
  response** before display. An HTTP proxy is the only mechanism for
  bidirectional request/response transformation.

So: for subscription Claude Code there is currently no viable delivery
mechanism — not as a proxy (blocked), not as a hook (insufficient).

## The decision (user, 2026-05-22)

Not a fork — pursue all of it:

> Feature-request an Anthropic, mit Hermes weiterentwickeln und für
> Hermes/OpenAI-kompatible Agents releasen; Claude warmhalten — wenn
> Anthropic die Policy ändert oder wir eine Lösung finden, wird apf auch
> für Claude wieder nutzbar.

The proxy is not dead — only its Claude-subscription path is. apf works
unchanged for OpenAI-compatible / local agents (Hermes, Cursor, Aider,
Codex, Cline, local models via oMLX). The core IP — detector, vault,
tool-call-boundary resolution — is auth-agnostic and fully retained.

## Workstreams

1. **Anthropic feature request** — a concrete written ask for the missing
   primitive (a response-side / egress-redaction extension point, or
   sanctioned local-proxy use for subscription auth). apf drafts it; the
   user files it. Small, one-off, file early.
2. **Framing re-scope** — README / docs / ARCHITECTURE.md lead with
   "Claude Code first". Re-position honestly: Hermes + OpenAI-compatible
   agents as the served audience; the Anthropic path documented as
   policy-blocked and re-enableable. (Subsumes "keep Claude warm" — the
   Anthropic-path code stays, clearly marked; re-enable trigger = Anthropic
   policy change *or* a found solution.)
3. **Hermes end-to-end testing** — the original "daily-driver validation",
   now Hermes-first instead of Claude-first. Throttle- and policy-free.
4. **Release-readiness for Hermes / OpenAI-compatible** — the gap to a
   low-bar release: detector precision (PERSON false positives), the
   licence decision (README says "undecided"), integration docs. Low bar
   first — clean repo, honest docs, installable, licence set — not a
   polished product launch.

Sequence (user-approved): **1 + 2 first** (small, autonomous, "sets the
record straight"), then **3** as the ongoing thrust toward **4**.

## Bead map

- `apf-dtq` — closed, this decision is its resolution.
- `apf-nia` — closed, superseded: "cloud-smoke through Claude Code" cannot
  be done (the subscription block); Hermes testing replaces it.
- New: feature request (W1), framing re-scope (W2), Hermes e2e (W3),
  release-readiness (W4). `apf-4cs` (realistic scenarios) stays, feeds W3.
