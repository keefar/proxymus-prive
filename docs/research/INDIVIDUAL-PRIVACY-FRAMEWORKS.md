# Individual-perspective privacy frameworks — survey

**Scope.** Phase 1 of beads issue `apf-dix`. Quick-scan (~30 min) of published
frameworks that catalog privacy threats **from the private individual's
perspective** — i.e. "what should I not hand out, knowing organizations may not
honor their obligations". Specifically tuned to: private user + personal AI
agent (Claude, ChatGPT, future personal assistant) + opaque-tokenization-via-
proxy threat model.

The legal corpus (GDPR Art. 9, AGG §1, HIPAA, EEOC) is explicitly **out of
scope** for this survey — those are organizational-frame obligations and were
already triaged in apf-1qh. The question here is whether anyone has published
the *inverse* view as a usable catalog.

---

## Frameworks evaluated

### 1. EFF Surveillance Self-Defense (SSD)

URL: https://ssd.eff.org/

User-centric and individually framed, but **not** a threat catalog. SSD is a
methodology — six questions ("what to protect / who from / consequences /
likelihood / effort / allies") plus scenario guides for journalists, activists,
LGBTQ youth, etc. It teaches a process, not an enumeration. No AI / LLM
content at all as of May 2026.

**Gap for our case:** zero coverage of LLM-specific failure modes; provides no
re-usable list of categorical risks we could map our taxonomy rows to.
Methodology useful for end-user docs later, not as the catalog scaffold.

### 2. OWASP Top 10 Privacy Risks (P1–P10)

URL: https://owasp.org/www-project-top-10-privacy-risks/

Pure organizational-frame: "Web Application Vulnerabilities", "Operator-sided
Data Leakage", "Insufficient Data Breach Response", "Insufficient Deletion of
User Data", etc. Predates the current LLM wave and reads as a checklist for
service operators.

**Gap:** wrong frame entirely. Useful as a contrast to motivate the
individual-frame catalog, not as a basis.

### 3. OWASP Top 10 for LLM Applications (2025)

URL: https://genai.owasp.org/llm-top-10/

Application/developer-frame. The 10 entries (Prompt Injection, Sensitive
Information Disclosure, Supply Chain, Data and Model Poisoning, Improper
Output Handling, Excessive Agency, System Prompt Leakage, Vector/Embedding
Weaknesses, Misinformation, Unbounded Consumption) all describe failures the
*application owner* should defend against. LLM02 ("Sensitive Information
Disclosure") is the closest hit and does include a short "Educate Users on
Safe LLM Usage" mitigation, but it is a one-line note inside an organization-
facing entry — not a user-side catalog.

**Gap:** does not enumerate the user-side disclosure failure modes; cross-
references on a single mitigation bullet at best.

### 4. IETF RFC 6973 — Privacy Considerations for Internet Protocols

URL: https://datatracker.ietf.org/doc/html/rfc6973

Person-centered, threat-enumerating, and durable (2013). Categories:
Surveillance, Stored Data Compromise, Intrusion, Misattribution, Correlation,
Identification, Secondary Use, Disclosure, Exclusion. Written for protocol
designers but framed around "harms to individuals' autonomy, reputation,
solitude, safety".

**Gap:** protocol-layer, not interaction-layer. Useful primitives but does
not name failure modes specific to giving an AI agent a question and getting
back text that hits a downstream tool. The taxonomy is a good cross-reference
target for IPF entries but is too generic on its own to drive product
decisions about "should I let this token through?".

### 5. NIST Privacy Framework

URL: https://www.nist.gov/privacy-framework

Voluntary control catalog (Identify-P, Govern-P, Control-P, Communicate-P,
Protect-P) for organizations managing privacy risk in their systems. No
individual perspective. No LLM specifics.

**Gap:** wrong frame; not useful as a basis.

### 6. Solove's Taxonomy of Privacy (2006)

URL: https://wiki.openrightsgroup.org/wiki/A_Taxonomy_of_Privacy

16 harm subtypes in 4 groups: Information Collection (Surveillance,
Interrogation); Information Processing (Aggregation, Identification,
Insecurity, Secondary Use, Exclusion); Information Dissemination (Breach of
Confidentiality, Disclosure, Exposure, Increased Accessibility, Blackmail,
Appropriation, Distortion); Invasion (Intrusion, Decisional Interference).
Descriptive (catalogs harm patterns), philosophical/legal in tone, individual-
harm centered. Has become the de-facto vocabulary for downstream taxonomies.

**Gap:** abstract and pre-LLM. Doesn't tell a user what to *do* with a prompt
in 2026. But the vocabulary is solid and is the foundation that the better
AI-specific work below builds on. Worth adopting as the parent taxonomy our
IPF entries map up to.

### 7. Sweeney's k-anonymity / quasi-identifier line of work

URL: https://en.wikipedia.org/wiki/K-anonymity

Re-identification science, not a threat catalog. Foundational for understanding
why IPF-02 (quasi-identifier triangulation in the seed list) is a real risk
class — three "boring" data points combine to identify one person — but it
doesn't *enumerate* user-side risks, it gives the math behind one of them.

**Gap:** narrow but precise. Cite as the theoretical anchor for the quasi-
identifier IPF entries; not a substitute for a catalog.

### 8. Nissenbaum — Contextual Integrity

URL: https://en.wikipedia.org/wiki/Contextual_integrity

Analytical lens, not a catalog. Privacy = appropriate information flow,
evaluated across five parameters (sender, recipient, subject, information
type, transmission principle). Strong empirical fit for our problem: an LLM
provider is a recipient with very different transmission norms than a friend
or a doctor, and users are routinely confused about that. The 2025 arXiv
study "Understanding Privacy Norms Around LLM-Based Chatbots" (2508.06760)
applies CI to chatbots and finds users perceive chatbot conversations as
highly sensitive but share anyway, with only consent, anonymization, and PII-
removal moving the needle on perception.

**Gap:** CI provides the diagnostic frame ("is this flow appropriate?") but
no enumerated list. It is the right *method* for evaluating each IPF entry's
worst-case violation, not a replacement for the catalog.

### 9. EFF activist op-sec / Citizen Lab Pegasus guides

URL: https://ssd.eff.org/ (security scenarios), https://citizenlab.ca/

High-threat-model operational manuals: device hygiene, communication
metadata, secure-drop journalism workflows. Excellent advice for targeted
individuals, but the threat model is "nation-state adversary with exploit
budget", not "private user hands data to a commercial LLM provider under TOS".
No LLM content.

**Gap:** wrong threat model. Useful for IPF-07 (power-asymmetry / state-scale
harms) as a worst-case anchor; not relevant to the bulk of our catalog.

### 10. Tactical Tech Data Detox / CPJ digital safety

URL: https://www.tacticaltech.org/projects/data-detox-kit/

Consumer-friendly digital hygiene curriculum (phone habits, app permissions,
passwords, ads, misinformation). No structured threat catalog, no AI focus.

**Gap:** pedagogical, not analytical. Not a basis.

### 11. Privacy-by-Design (Cavoukian, 7 principles)

URL: https://privacy.ucsc.edu/resources/privacy-by-design---foundational-principles.pdf

Design methodology for system builders (Proactive not Reactive, Privacy as
Default, etc.). Not a threat list and not user-side.

**Gap:** orthogonal. Not useful as a basis.

### 12. Mozilla *Privacy Not Included* / Common Sense Privacy ratings

URLs: https://foundation.mozilla.org/privacynotincluded/ ,
https://privacy.commonsense.org/

Product-rating projects — they assess apps and devices, output a privacy
score. They have done LLM-product reviews (chatbot ratings exist in *PNI*),
but the output is per-product red/yellow/green, not a reusable threat
taxonomy.

**Gap:** wrong output shape. Could later be a distribution channel for
user-facing guidance, not a foundation.

### 13. PrivacyTools / PrivacyGuides / The New Oil

URLs: https://www.privacyguides.org/en/basics/common-threats/ ,
https://thenewoil.org/en/guides/prologue/threat-model/

Curated directories with a threat-modeling preamble. PrivacyGuides' "Common
Threats" page enumerates 9 categories: Anonymity, Targeted Attacks, Supply
Chain Attacks, Passive Attacks, Service Providers, Mass Surveillance,
Surveillance Capitalism, Public Exposure, Censorship. Individual-framed,
explicitly designed for "pick the threats that apply to you". No AI / LLM
entries as of May 2026.

**Gap:** general consumer-privacy threats with no AI specificity. The
*structure* (curated 9-item list, individual-frame, "pick what applies")
is exactly the OWASP-style shape we want for our catalog. Worth borrowing
the editorial style and tone; the content needs to be rebuilt for the AI-agent
use case.

### 14. AI-specific user-perspective work

The newest and most relevant body of work:

- **Lee, Yang, Von Davier, Forlizzi, Das — "Deepfakes, Phrenology,
  Surveillance, and More! A Taxonomy of AI Privacy Risks" (CHI 2024).**
  URL: https://hankhplee.com/papers/chi24_privacy_taxonomy.pdf .
  Builds on Solove. Analyses 321 real AI privacy incidents from the AIAAIC
  database. Produces 12 operationalizable risk labels: Surveillance,
  Identification, Aggregation, **Phrenology/Physiognomy (new)**, Secondary
  Use, Exclusion, Insecurity, Exposure, Distortion, Disclosure, Increased
  Accessibility, Intrusion. Each label is tagged as new / exacerbated /
  mapped relative to Solove. Individual-rights framed, but the unit of
  analysis is "an AI product/service caused a privacy incident", not "a user
  decided to share X". So: the *vocabulary* is excellent, the *frame* is
  still product-incident, not user-decision.

- **Zhang, Apthorpe et al. — "User Privacy Harms and Risks in
  Conversational AI: A Proposed Framework" (arXiv 2402.09716).**
  9 harms + 9 risks specific to text-chatbot interactions, derived from
  user interviews. Extends Solove, individual-user perspective, chatbot-
  specific. Output is academic framework, not OWASP-style catalog, but the
  closest hit in spirit. Worth deep-reading for Phase 2.

- **IAPP / CMU dynamic AI privacy risk taxonomy (2025).** Living-document
  reframing of the Lee 2024 taxonomy with continuous incident updates.
  URL: https://iapp.org/news/a/shaping-the-future-a-dynamic-taxonomy-for-ai-privacy-risks/

- **"Privacy in the Age of AI: A Taxonomy of Data Risks" (arXiv 2510.02357,
  2025).** 19 risks across 4 categories (dataset-level, model-level,
  infrastructure-level, insider). Skews back toward developer/operator frame.

- **LINDDUN-for-GenAI (arXiv 2603.06051).** Extends LINDDUN's 7 threats
  (Linking, Identifying, Non-repudiation, Detecting, Data Disclosure,
  Unawareness, Non-compliance) with 6 "Common Attacker Models" for GenAI.
  Explicitly for developers, not end-users.

- **Anthropic / OpenAI vendor docs.** Model specs and transparency hubs cover
  what *the provider* commits to filter or retain. No published user-side
  threat catalog from either vendor.

**Gap pattern across the AI-specific work:** every framework either (a) names
*risk categories* and stops short of operational user advice (Lee 2024, IAPP
dynamic taxonomy), or (b) targets developers (LINDDUN-GenAI, "Age of AI"
taxonomy), or (c) is an empirical study not a reusable catalog (Zhang/
Apthorpe, the 2508.06760 CI study). Nothing matches the OWASP-style "10
patterns the private user should recognize and act on" shape we want.

---

## Synthesis

| Framework | Individual frame? | LLM-specific? | Catalog shape? | Usable as base? |
|---|---|---|---|---|
| EFF SSD | yes | no | no (methodology) | no |
| OWASP Privacy Top 10 | no | no | yes | no |
| OWASP LLM Top 10 | partial (1 entry) | yes | yes | no |
| RFC 6973 | yes | no | yes | partial — vocabulary |
| NIST Privacy Framework | no | no | controls | no |
| Solove 2006 | yes | no | yes (16 subtypes) | yes — as parent taxonomy |
| Sweeney k-anonymity | yes (data subject) | no | no (single risk class) | as theory anchor |
| Nissenbaum CI | yes | partial via 2025 CI-LLM study | no (analytical lens) | yes — as evaluation method |
| EFF/Citizen Lab op-sec | yes | no | scenario-driven | no |
| Tactical Tech | yes | no | pedagogical | no |
| Privacy-by-Design | no | no | principles | no |
| Mozilla PNI / CSM | yes | partial | product ratings | no |
| PrivacyGuides | yes | no | yes (9 categories) | borrow style only |
| Lee et al. CHI 2024 | partial (product-frame) | yes | yes (12 labels) | yes — as vocabulary |
| Zhang/Apthorpe 2024 | yes | yes | partial (9+9) | yes — Phase-2 deep read |
| IAPP dynamic AI risks | partial | yes | living catalog | partial |
| LINDDUN-GenAI | no | yes | yes | no |

Three observations:

1. **The vocabulary problem is solved.** Solove (2006) → Lee et al. (CHI 2024)
   → IAPP dynamic taxonomy gives us a clean 12-label vocabulary of AI privacy
   risks, with each label traceable to either a Solove subtype or marked as
   new (Phrenology/Physiognomy). Using anything else would be re-inventing.

2. **The frame problem is unsolved.** Every available catalog is either
   product/incident-framed (Lee, IAPP, LINDDUN-GenAI), organizational-frame
   (OWASP Privacy, NIST, OWASP LLM), or scenario-rather-than-catalog (EFF SSD,
   PrivacyGuides). Nothing exists in the shape "10 things a private user
   should refuse to type into an LLM and why", traceable back to the academic
   vocabulary above.

3. **Our seed list maps cleanly onto the existing vocabulary** but adds value
   the existing work doesn't capture — IPF-08 (lock-in via accumulated history)
   and IPF-04 (cumulative provider profile) are agent-relationship-specific
   harms that the product-incident corpora don't see because they only fire
   over years of use, not in a single incident.

---

## Verdict: (b) — combine, don't rebuild from scratch

No single framework is a 70%+ fit. But Solove (2006) + Lee et al.'s CHI 2024
AI-extension + Nissenbaum's contextual-integrity evaluation method together
cover **roughly 80%** of what we need at the *vocabulary and conceptual* level.
What is missing is purely the **frame translation**: turning "Aggregation is a
privacy harm" (Solove/Lee, descriptive) into "do not feed your full chat
history to a new model on day 1 of using it" (operational, individual-user
prescriptive). That gap is small enough to fill with a thin layer, not a new
catalog.

**Recommended Phase 2 shape:**

1. **Write a short "mapping doc"** — `docs/INDIVIDUAL-PRIVACY-FAILURES.md` —
   that defines 8–12 IPF entries in OWASP style (title, harm chain, scenarios,
   detection signals, mitigations), and for *each* entry includes a one-line
   "Maps to: Solove[X], Lee2024[Y], CI-violation-of[Z]". This makes the
   document an editorial, agent-scenario layer over an existing academic
   spine rather than a competing catalog.
2. **Adopt the Lee et al. 12-label vocabulary as the upper bound.** Every
   IPF must map to at least one Lee label. If it doesn't, either the label
   set needs extending (rare) or the IPF is not a real new risk.
3. **Use Nissenbaum's CI five-parameter check as the per-entry "is this a
   norm violation" worksheet.** Each IPF's example scenarios should call out
   the transmission-principle change (e.g., "user says X to a friend under
   confidence" → "user says X to LLM under retention-and-training TOS"),
   which is exactly what makes the failure concrete.
4. **Borrow PrivacyGuides' editorial style** — terse, individual-second-person,
   "pick what applies to you" — rather than academic prose.
5. **Add the two agent-relationship-specific entries** missing from the
   academic corpus: IPF-04 (cumulative provider profile / disproportionate
   single-recipient learning, partly maps to Solove "Aggregation" but the
   *single-recipient* aspect is new) and IPF-08 (lock-in via accumulated
   history, no clean Solove map — closest is Decisional Interference).
6. **Cross-link to the `apf` taxonomy.** Each IPF lists which taxonomy rows
   participate in mitigating it, closing the loop with apf-1qh.

The seed list in `apf-dix`'s description (IPF-01 through IPF-10) is a sound
starting point. After this survey, the only edits I'd suggest before Phase 2
drafting:

- Keep IPF-01 through IPF-10 as drafted.
- Add **IPF-11 Phrenology/Physiognomy inference**, mapping to Lee2024's
  one new-vs-Solove category — relevant whenever the user feeds an image or
  audio sample to the agent and the model infers protected attributes.
- Consider merging IPF-02 (quasi-identifier triangulation) and IPF-06
  (inferential disclosure) into one IPF with two sub-patterns — they share
  a harm chain and split the reader's attention.

**Phase 2 deliverable size estimate:** ~3000-4000 words, 1–2 days of focused
work. Significantly cheaper than building a freestanding catalog because the
vocabulary and academic anchors already exist.
