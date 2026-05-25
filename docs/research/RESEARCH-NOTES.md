# Research notes — consolidated findings

Cleaned-up version of the conversation that kicked this project off. Everything below is
material for design decisions, not commitments.

## The pattern: anonymize → process → de-anonymize

Standard round-trip used by every serious project in this space:

1. **Local detection** — find PII spans in outgoing text (regex + NER + optional small LLM)
2. **Placeholder substitution** — replace each PII span with a stable token
   (e.g. `<PERSON_0>`, `<EMAIL_0>`) and keep an in-memory mapping
3. **Cloud LLM call** — only sanitized text crosses the network boundary
4. **Rehydration** — swap placeholders back to original values in the response

Critically, **de-anonymization works even if the LLM rewrote the text around the
placeholders** (translated, summarized, restructured) — only the placeholders trigger
replacement, everything else passes through. This is the property that makes the pattern
robust enough to use in practice. Documented for Presidio's anonymizer/deanonymizer and
Microsoft's PII Shield.

## What counts as PII

For our scope (coding-agent traffic on a developer machine):

- **Direct identifiers:** names, email addresses, phone numbers, postal addresses
- **Government / financial IDs:** Steuer-ID, IBAN, credit cards, Sozialversicherungsnummer,
  Personalausweisnummer
- **Digital identifiers:** IP addresses, device IDs, usernames, **tokens / passwords / API keys**
  (technically "secrets" but lumped in for the same filter)
- **Contextual / implicit:** calendar entries (who meets whom, when, where), health data,
  location traces, relationships — the category regex and classical NER miss, where a small
  LLM classifier earns its keep
- Legal frame: US calls it PII, GDPR calls it "personenbezogene Daten" and the EU
  definition is broader

## Why coding agents are harder than chat

Three problems chat-only PII filters don't have to face:

### 1. Tool calls need the real value
If the agent is asked to `grep "max@firma.de"` over local files, or query a DB by an email,
or send a message — anonymizing the email breaks the tool call. The placeholder is useless
to `grep`. **No surveyed project addresses this.**

The principled solution: keep a token in the LLM-visible context, but resolve it to the
real value *only at the tool-execution boundary*, never back inside the LLM context.
Practically this means:
- Outbound (to LLM): real value → token
- Inbound (from LLM, on the way to tool dispatcher): token detected → look up → execute with
  real value → tool result re-tokenized before going back to LLM
- This is engineering, not a model-quality question

### 2. Append-only context (Claude Code specifically)
Claude Code's context window is permanent within a session. Once PII enters — via `Read` of
a `.env`, tool result echoing a secret, model response paraphrasing sensitive output — it
stays in every subsequent API call for the session lifetime. There is no in-place sanitization
hook. Feature request [#29434][cc29434] was closed as "not planned." Existing hooks
(`UserPromptSubmit`, `PreToolUse`, `PostToolUse`) can only **block** or **detect**, not
**modify**. The only interception point is the HTTP boundary.

[cc29434]: https://github.com/anthropics/claude-code/issues/29434

### 3. The proxy only sees network traffic
The proxy can stop PII from leaving the machine, but cannot stop the agent from *reading*
sensitive local files. Hardening the agent's read scope (sandbox, denylist for
`~/.ssh`, `~/Library/Mail`, calendar DBs, etc.) is a separate, complementary control.
"Defense in depth" — not part of this project's PoC scope, but worth flagging.

## Why a small specialized model beats a 35B daily driver here

User's daily-driver is a 35B-4bit Qwen with 64k context. For this task it's the wrong
tool — not just because of speed:

1. **Hot path.** The filter runs on every request. Latency compounds.
2. **Specialized beats generalist at small sizes.** Anonymizer-SLM 1.7B reportedly matches
   GPT-4.1 (≈9.55/10 LLM-judge) at PII replacement — ~1000× smaller than GPT-4.1, 20× smaller
   than the daily driver.
3. **Predictability.** Specialized SLMs drift and hallucinate less than large generalists
   on narrow tasks. For a security filter, predictability matters more than ceiling
   capability.

The 35B stays the assistant. The filter is a small, dedicated model — or two (NER + SLM).

## Hardware sanity check (Apple Silicon, 32 GB)

- GLiNER (BERT-base-class NER, quantized ONNX): hundreds of MB, CPU/ANE
- Small rewriter SLM 1.7–4B in 4-bit: ~1–3 GB on MLX
- Combined filter footprint: ≤ 4 GB
- With the 35B (~20 GB) loaded, still ≥ 8 GB headroom — and in practice the filter and the
  daily driver are different workflows, rarely simultaneously hot
- Latency target: < 1 s for the SLM step (documented for Anonymizer-SLM 1.7B at ~250 ms
  TTFT, < 1 s total)
- Thermal: fanless Air; filter alone is fine, sustained dual-model use will throttle —
  but that's not the steady state we care about

## Architectural shape (working assumption)

```
agent  ──HTTP──▶  proxy  ──HTTPS──▶  api.anthropic.com / api.openai.com / …
                    │
                    ├─ regex / NER (Presidio + GLiNER) for fast-path obvious PII
                    ├─ MLX small LLM for contextual / implicit PII
                    ├─ session-scoped token vault (original ↔ placeholder)
                    └─ tool-call boundary resolver (the differentiating piece)
```

Open question for design phase: does the tool-call resolver run *in the proxy*, or *in the
agent harness* (Claude Code hook, MCP tool wrapper)? The cleanest place might actually be
the **client side of each tool call**, not the proxy — because the proxy doesn't know
which placeholders are about to be passed to `Bash` vs. left in narrative. Needs prototype
work to decide.

## Sources

Original research links from the kickoff conversation:

- [Microsoft Presidio (anonymize/deanonymize)](https://microsoft.github.io/presidio/anonymizer/)
- [PII Shield — Microsoft tech blog](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/introducing-pii-shield-a-privacy-proxy-for-every-llm-call/4514726)
- [LiteLLM Presidio guardrail docs](https://docs.litellm.ai/docs/proxy/guardrails/pii_masking_v2)
- [LogRocket — build a local AI proxy to redact PII](https://blog.logrocket.com/build-local-ai-proxy-redact-pii-before-llms/)
- [Anonymizer SLM series (eternisai, HuggingFace)](https://huggingface.co/blog/pratyushrt/anonymizerslm)
- [knowledgator/gliner-pii-base-v1.0 (HF)](https://huggingface.co/knowledgator/gliner-pii-base-v1.0)
- [GLiNER as external NLP engine in Presidio](https://microsoft.github.io/presidio/samples/python/gliner/)
- [OpenMed — Nemotron Privacy Filter MLX](https://openmed.life/docs/anonymization/)
- [Claude Code issue #29434 — redact secrets/PII from context window (closed, not planned)](https://github.com/anthropics/claude-code/issues/29434)
- [Claude Code issue #39882 — pre/post-API-call hooks (open)](https://github.com/anthropics/claude-code/issues/39882)
- [Formal.ai — using proxies to hide secrets from Claude Code](https://www.formal.ai/blog/using-proxies-claude-code/)
- [Secure LLM usage with reversible data anonymization — DZone](https://dzone.com/articles/llm-pii-anonymization-guide)
- [AI Agent PII Protection — Waxell](https://waxell.ai/blog/pii-protection-ai-agents)
