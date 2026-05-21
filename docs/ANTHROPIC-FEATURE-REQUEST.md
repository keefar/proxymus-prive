# Feature request: a sanctioned path for a user-controlled privacy filter in Claude Code

*Draft for filing with Anthropic (e.g. a GitHub issue on `anthropics/claude-code`,
or the appropriate feedback channel). Written 2026-05-22.*

## Summary

Please provide a supported mechanism that lets a Claude Code user run **their
own local privacy filter** in the request/response path — to redact personal
data before it leaves the machine and restore it in what they read back.
Today there is no sanctioned way to do this on a Claude subscription
(Pro/Max) account.

## The use case

Coding agents see a lot of personal and sensitive data — file contents,
filesystem paths that encode identity, names, e-mail addresses, and
credentials. A local filter that **masks personal data on the way out and
restores it on the way back** lets privacy-sensitive users, and people in
regulated environments, use Claude Code without raw personal data leaving
the machine.

We have built an open-source proof-of-concept that does exactly this: a
local detector replaces personal data with placeholders, the cloud model
only ever sees placeholders, the originals are restored in the response the
user reads, and placeholders are resolved to real values only at the moment
a tool executes locally — never re-entering the model context.

This is a data-loss-prevention / privacy capability, and it is something
privacy-conscious and regulated users actively want.

## The blocker

A bidirectional filter has to sit in the request/response path: mask
outbound content, restore placeholders in the response, and resolve
placeholders in tool-call arguments at execution time.

Today the only mechanism for that is an HTTP proxy via `ANTHROPIC_BASE_URL`,
and that path is closed for subscription users:

- A subscription (Pro/Max) **OAuth** token is refused when the request
  reaches Anthropic through a proxy — it returns `429 rate_limit_error`.
  We understand the intent: the policy stops third-party apps and resellers
  from monetising subscription quota. But **a user's own local privacy
  filter — processing only their own traffic, on their own machine — is a
  different case** from a third-party reseller, and the current policy
  cannot tell them apart.
- Claude Code's **hook system cannot substitute**: `UserPromptSubmit` can
  append context but not rewrite the prompt; `PostToolUse` is read-only; and
  there is no hook that can rewrite the model's response before it is shown
  to the user.

The result: a subscription user currently cannot run any privacy filter on
their own Claude Code traffic.

## What would unblock it — either of these

1. **A sanctioned local-egress-filter mode.** Let a user designate a local
   proxy as trusted for their own subscription token — an explicit opt-in
   setting, or a locally-attested loopback proxy. This legitimises the
   proxy approach, which already works technically.

2. **Write-capable and response-side hooks.** Extend the hook system so an
   extension can (a) rewrite the outgoing prompt/context, (b) modify tool
   results, and (c) rewrite the assistant's response text before display.
   A privacy filter could then run as a hook bundle, with no proxy at all.

Either one solves it. (1) is the smaller change and reuses an architecture
that already works end to end; (2) fits the existing hooks framework but is
a larger surface area.

## Why this is worth doing

- Privacy and DLP are a real adoption blocker for regulated and
  privacy-conscious users. A user-controlled redaction path expands who can
  safely adopt Claude Code.
- It is consistent with Anthropic's own privacy positioning.
- A sanctioned mechanism also gives Anthropic a cleaner, more precise line
  than blanket-blocking all proxied subscription traffic — it separates
  "my own local privacy filter" from "a third-party reselling my quota".

## About the request

This comes from **agent-privacy-filter**, an open-source proof-of-concept
privacy filter for coding agents. The filter pipeline, the tool-call
boundary resolution, and the detector are all working and tested; the only
missing piece is a sanctioned delivery path for subscription Claude Code.
We are happy to share design details and to collaborate on the mechanism.
