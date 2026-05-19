# Individual Privacy Failures (IPF) — failure-pattern catalog

Phase 2 deliverable for `apf-dix`. Untracked working document; promote after review.

## 0. Intro

Almost every public privacy framework — GDPR Art. 9, NIST Privacy Framework,
OWASP Top 10 Privacy Risks, OWASP LLM Top 10 — is written for *organisations*.
The implicit user is a DPO or platform engineer. From that frame, "the user"
appears once, as a counterparty whose rights must be honoured.

`docs/THREAT-MODEL-PRIVATE.md` inverts the frame: the user as a private
individual whose data is *handled* by a personal AI agent whose upstream
provider may not honour its commitments. That doc catalogues **what to
detect** — 74 substance rows across 9 clusters plus 5 third-party patterns,
each tagged by tier and detector difficulty. Mechanically complete enough to
drive the filter's content rules.

What it does *not* do is explain, from the user's perspective, **why** each
detection matters as a *pattern of failure*. This doc is that WHY-it-matters
layer: 11 entries, each ~250 words, citation-grounded.

Three parent frameworks together cover ~80 % of what a user-side catalog
needs (Phase 1 survey,
`docs/research/INDIVIDUAL-PRIVACY-FRAMEWORKS.md`):

- **Solove (2006)** — 16 harm subtypes across Collection / Processing /
  Dissemination / Invasion. Pre-LLM, supplies the foundational vocabulary.
- **Lee et al. (CHI 2024)** — operationalises Solove for AI systems against
  321 real AIAAIC incidents; 12 risk labels with one net-new category
  (Phrenology/Physiognomy).
- **Nissenbaum (2010), Contextual Integrity (CI)** — analytical lens.
  Privacy = appropriate information flow across five parameters: *sender*,
  *recipient*, *subject*, *information type*, *transmission principle*.
  Used per-entry as a worksheet so each norm violation is concrete.

Each entry ends with an `apf taxonomy mapping` line linking back to
`THREAT-MODEL-PRIVATE.md` §2 rows.

### Note on IPF-02 vs IPF-06 (Phase 1 merge question)

Phase 1 suggested merging quasi-identifier triangulation (IPF-02) and
inferential disclosure (IPF-06). They share a "combination > sum of parts"
shape but split on *what* is re-identified: IPF-02 joins multiple *identity
fields* to identify a *person*; IPF-06 leaks a sensitive *category or
value* from the *context around a single masked span*. The mitigations
also split: IPF-02 needs cross-turn profile-awareness, IPF-06 needs opaque
tokens plus paraphrase/local-only. Kept separate, with cross-reference.

---

## 1. IPF entries

### IPF-01 — Future-self damage (statements aging badly)

**Kernel.** Today's truthful, contextually appropriate disclosure becomes
tomorrow's discoverable record against an older, different self.

**Description.** Content honest in its moment — a 2026 political opinion,
an addiction-recovery milestone, a relationship complaint — is held in
provider logs, training sets, or breach dumps. Years later, in a different
life-phase (new job, custody dispute, clearance, asylum interview), the
same text is read by an audience the user never imagined and cannot now
contextualise to. Harm = *temporal asymmetry*: the record outlives the
context that made it appropriate.

**Maps to.** Solove → *Secondary Use*, *Exposure*, *Distortion* (a 5-year-
old quote about "the depression diagnosis" presented out-of-context
distorts who the person is now). Lee 2024 → *Secondary Use*, *Disclosure*,
*Distortion*.

**Nissenbaum CI Worksheet.**
- Sender: user.
- Recipient: provider *and its future temporal selves* — successors,
  acquirers, retention-policy revisions.
- Subject: user (frequently a younger, no-longer-current self).
- Information type: candid first-person disclosure.
- Transmission principle: user expects *"ephemeral confidence to a
  tool"*; actual is *"permanent transferable record, no honouring of
  context decay"*.

**Realistic scenarios.**
- 2026: "ich habe AfD-Wahlerfolg satt". 2031: provider acquired,
  retention exported for security-vetting; user applies for Beamtenstatus.
- "tried microdosing for six months, no effect, stopped" → custody
  mediation four years later.
- New partner reads a year's worth of chat from a breakup period.

**apf taxonomy mapping.** Cuts across most `+cat` rows — H3, H4, P1,
P6, Su1, Su3, S6.

**Mitigation in apf.** Masking shrinks the verbatim surface but
not the categorical retention shape. §5.1 opaque tokens block the
cascade-leak; `/apf-reset` shortens what any one session carries.
Local-only routing (§5.6, deferred) is the clean fix for the most
temporally fragile categories.

---

### IPF-02 — Quasi-identifier triangulation

**Kernel.** Three to five innocuous fields, each individually
unidentifying, jointly resolve to one person.

**Description.** Sweeney (2002): 87 % of US residents identified by
*{ZIP, DOB, sex}*. The result generalises — postcode + employer +
child-school + commute = a household of fewer than 5 in most cities.
In LLM context the harm is twofold: (a) the provider, over many turns,
accumulates a profile that re-identifies across nominally separate
chats; (b) any breach or training scrape lets a third party do the
same. Danger lives in the *combination*, not the items.

**Maps to.** Solove → *Identification*, *Aggregation*. Lee 2024 →
*Identification*, *Aggregation*. Sweeney (2002) as theoretical anchor.

**Nissenbaum CI Worksheet.**
- Sender: user, across many turns / sessions.
- Recipient: provider as cumulative observer.
- Subject: user.
- Information type: each item low-sensitivity; the *set* high-sensitivity.
- Transmission principle: each turn appears bound by single-task
  appropriateness; actual flow concatenates all turns. CI violation =
  aggregation across contexts the user mentally kept separate.

**Realistic scenarios.**
- Three weeks of turns: weekly therapy scheduling (Wednesday 14:00),
  grocery list from a Rewe receipt in 10119, school-pickup logistics
  for *Sophie-Scholl-Grundschule*. No single turn is sensitive.
- "TC around 240 at the new place" + "Sansome Street office" +
  "Caltrain commute" → unique person in the FAANG recruiter index.
- First name + employer + month-of-birth crosses k=1.

**apf taxonomy mapping.** B1, B2, B3, B4, B8, F1, R5, most identity
rows. §3.3 (profile assembly) of the threat-model is the apf-side
acknowledgement.

**Mitigation in apf.** Per-value masking is necessary but
insufficient — the *structural* leak survives substitution. §5.4
diversity-weighted cumulative-profile warning is the direct
mitigation; `/apf-reset` the escape. Routing high-diversity sessions
to local models is the long-term fix.

---

### IPF-03 — Third-party data without consent

**Kernel.** The user discloses information about another person who has
no awareness and no opportunity to refuse.

**Description.** Assistant flows are saturated with third-party content:
emails to summarise, calendar invites to parse, notes about family,
drafts of messages to friends. The user consents *for themselves* but
cannot consent on behalf of mother, partner, child, colleague, friend —
each mentioned by name, often with sensitive context, sometimes inferred
without explicit naming ("my wife's chemo schedule").

**Maps to.** Solove → *Breach of Confidentiality* (when content was
under a confidence norm), *Disclosure*, *Aggregation*. Lee 2024 →
*Disclosure*, *Aggregation*, *Insecurity*.

**Nissenbaum CI Worksheet.**
- Sender: user.
- Recipient: provider.
- Subject: third party (Anna, Mum, Marc, daughter Lena, colleague).
- Information type: whatever the third party told the user under norms
  specific to *that* relationship.
- Transmission principle: third party expected "told a friend in
  confidence" / "told a co-parent privately"; actual = routed to a
  commercial LLM with retention. The third party has no recourse.

**Realistic scenarios.**
- "Anna hat mir erzählt, dass sie eine Abtreibung hatte — hilf mir,
  einfühlsam zu antworten."
- "Draft a response to my brother — he just got laid off and the
  family doesn't know yet."
- "Meine Mutter wurde gestern wegen Verdacht auf Pankreas-Ca in der
  Charité aufgenommen."

**apf taxonomy mapping.** Entire §2.10 (5 rows) plus all `A-3p`-tagged
rows (R1–R6, S3, S4, F7, H12, H13).

**Mitigation in apf.** §5.2: mask 3p spans as always-opaque
(`<PERSON_3p_1>`, never categorical), mark with `third_party=True`
attribute. Honest framing in README: filter minimises *leakage*, does
not solve the underlying consent problem. IPF-10 (bystander) is the
next-layer concern.

---

### IPF-04 — Cumulative provider profile

**Kernel.** A single provider, over years of daily use, accumulates a
larger and more coherent personal dataset about the user than anyone
in the user's life.

**Description.** Distinct from IPF-02 (joining fields). This IPF is
*temporal accumulation by one recipient*: five years of journal-style
chats, drafts, planning, medical questions, financial documents — all
in one commercial entity. No therapist, spouse, or doctor has this
breadth. Harm = the *existence* of that profile, regardless of how
each disclosure was justified at the time. Breaches, policy changes,
acquisitions have disproportionate blast radius compared to leaks at
conventional counterparties.

**Maps to.** Solove → *Aggregation*, *Secondary Use*. Lee 2024 →
*Aggregation*, *Surveillance*. Least-captured IPF in the academic
corpora, whose unit of analysis is "an AI incident", not "five years
of one user × one provider".

**Nissenbaum CI Worksheet.**
- Sender: user.
- Recipient: one provider, persistent.
- Subject: user.
- Information type: longitudinal, multi-context — blends domains
  (work, health, family, finance, beliefs) the user keeps separate.
- Transmission principle: implicit "this chat is a task" → actual
  "this chat is one cell of a long-running profile". Violation =
  blending of contexts the user would never blend in meatspace.

**Realistic scenarios.**
- User has used Claude as daily journal since 2024. 2027: a policy
  revision retroactively makes prior chats training-eligible.
- Acquisition: provider X bought by ad-tech Y; retention transfers
  under new TOS.
- A "memory" feature accidentally surfaces health-context content in
  a work-context turn.

**apf taxonomy mapping.** No single §2 row — backdrop that elevates
every row's risk. §3.3 sees the multi-field side; this IPF sees the
single-recipient side.

**Mitigation in apf.** `/apf-reset` and per-session placeholder
namespaces segment the *provider-visible* identity even though the
user's real identity stays stable. Multi-provider rotation (§5.8,
[[apf-ycu]]) is the stronger version.

---

### IPF-05 — Cross-platform identity stitching

**Kernel.** Identifiers leak across services the user actively kept
separate; the same person becomes a single record in adversary
infrastructure.

**Description.** A user has, by design, distinct identities: work email,
personal email, pseudonymous Reddit, Mastodon, dating burner. Each is
appropriate to its context. If the agent sees them in the same chat —
"draft a reply from my work email referencing this Reddit thread" —
the linkage is now legible to the provider, and a subsequent breach or
training scrape can publish the joined identity. Harm =
*de-pseudonymisation across contexts the user actively separated*.

**Maps to.** Solove → *Identification*, *Aggregation*, *Increased
Accessibility*. Lee 2024 → *Identification*, *Aggregation*.

**Nissenbaum CI Worksheet.**
- Sender: user.
- Recipient: provider (transitively any downstream reader).
- Subject: user under multiple personas.
- Information type: identifiers + the cross-walk between them.
- Transmission principle: each persona's home platform expects
  single-context visibility; the agent flow joins them. Violation =
  the joining itself, irrespective of content.

**Realistic scenarios.**
- "Reply to this LinkedIn DM, but use the tone from my Mastodon
  posts — here are the last 10 toots."
- "Sign the petition with my real email but find the Reddit post I
  wrote about this last year — same author handle."
- Subscription-unifier prompt: provider sees the full identity graph.

**apf taxonomy mapping.** B7, all of §2.7, plus R-rows when others'
cross-platform identities are disclosed.

**Mitigation in apf.** Per-session masking handles single-context
identifiers. Cross-context stitching needs *per-persona* token scoping
within a session — a deferred design hook. Today's vault is per-session,
not per-persona.

---

### IPF-06 — Inferential disclosure (cascade-leak via category-laden context)

**Kernel.** Even with the *value* masked, surrounding text lets a
reader recover the category — and often the value — by inference.

**Description.** Distinct from IPF-02 (joining identity fields). This IPF
is a *single masked span* whose context betrays what was redacted.
"Has `<MEDICATION_1>` made your sleep worse?" recovers "psychiatric
medication". "Termin bei Dr. `<PERSON_2>` in der `<ORG_1>` — Onkologie
14:00" recovers oncology. The adversary need not know the literal value;
the *category* alone is often the harm. Motivated the §5.1 decision to
keep tokens *opaque* — placeholder itself shouldn't surface category.
Context around the placeholder still can: a fundamental limit of
substitution-based filtering.

**Maps to.** Solove → *Disclosure*, *Aggregation*. Lee 2024 →
*Disclosure*, *Identification*; *Phrenology/Physiognomy* in the limit
case (model performs inference on multimodal cues).

**Nissenbaum CI Worksheet.**
- Sender: user.
- Recipient: provider; the inferring agent is the receiving model.
- Subject: user (or third party).
- Information type: masked value embedded in semantically rich
  surrounding text.
- Transmission principle: user believes "value hidden"; actual flow
  "category recoverable". Violation = gap between perceived and
  actual protection.

**Realistic scenarios.**
- "Can I drink wine with `<MEDICATION_1>` (10 mg, evening dose)?" —
  dosage and timing imply SSRI.
- "What time does `<ORG_2>`'s clinic open Fridays? Third infusion
  next week." — recovers oncology.
- "Mein `<PERSON_3p_1>` ist nach der Diagnose von `<DISEASE_1>` ins
  Hospiz gewechselt." — context recovers terminal illness.

**apf taxonomy mapping.** All `+cat` rows in §2 (44 of 74) —
especially H1, H3, H4, H7, H8, S2, S8, S9, P1, P5, L6, F3.

**Mitigation in apf.** Opaque tokens (§5.1) close one path. Remaining
context-leak cannot be fully closed without paraphrasing (lossy) or
local-only routing (§5.6 deferred). Cumulative-profile warning (§5.4)
helps users notice when they're stacking inferences. Docs must surface
this as an honest limit.

---

### IPF-07 — Power-asymmetry harms (state / corporate scale)

**Kernel.** Data the user volunteers casually flows to entities with
investigative, regulatory, or coercive power orders of magnitude
greater than the user's defensive capacity.

**Description.** User's natural threat model imagines an interpersonal
adversary (ex, colleague, phisher). Actual recipients include national
intelligence with compulsion over the provider, ICE-style enforcement,
employer investigative firms, future political shifts that weaponise
existing data. The user *cannot appeal the decision their data is used
to make about them* — the process is opaque, the data laundered through
a model, the user lacks resources for legal challenge.

**Maps to.** Solove → *Surveillance*, *Aggregation*, *Exclusion*. Lee
2024 → *Surveillance*, *Exclusion*, *Distortion*.

**Nissenbaum CI Worksheet.**
- Sender: user.
- Recipient: provider → state / large-corporate downstream via legal
  process, contract, or breach.
- Subject: user.
- Information type: especially L5, L6, P1, P7, R3.
- Transmission principle: user expects "tool processing my request",
  worst case commercial use; actual = "subpoena-eligible, possibly
  compelled under sealed gag order". Violation = the categorical
  mismatch in the recipient's *kind*.

**Realistic scenarios.**
- Asylum-seeker prepares §60 AsylG statement via the agent; provider
  served with an MLAT from country of origin.
- US Title VII organising drafts surface during employer subpoena.
- Activist in jurisdiction that later reclassifies the org as
  terrorist; data exists in years-old chats.

**apf taxonomy mapping.** L5, L6, P1, P3, P7, P8 most acutely; in the
limit any row if the downstream recipient is sufficiently powerful.

**Mitigation in apf.** Masking shrinks value-set; doesn't change
*that* the user used an LLM on these topics — metadata alone suffices
for the worst inferences. Honest mitigation is **local-only routing**
for the hardest categories (§5.6, deferred). Until then: explicit
warning that asylum / undocumented status / whistleblower drafts
should not go through the agent at all.

---

### IPF-08 — Lock-in via accumulated history

**Kernel.** The user becomes effectively unable to leave a provider
because the agent's utility is bound to its accumulated context.

**Description.** Over months the agent has learnt projects, preferences,
recurring people, shorthand. Switching providers means rebuilding that
context. Economic cost of switching becomes privacy cost: the user
accepts policy changes, TOS revisions, product degradation rather than
re-onboard. *Retention-as-leverage* failure mode. Solove's "Decisional
Interference" — privacy decisions constrained by sunk-cost accumulation
the provider designed in.

**Maps to.** Solove → *Decisional Interference*, *Exclusion*. Lee 2024
→ *Exclusion*, *Aggregation*. Like IPF-04, missed by product-incident
corpora.

**Nissenbaum CI Worksheet.**
- Sender: user, historic.
- Recipient: provider, with structural advantage from accumulated
  context.
- Subject: user.
- Information type: longitudinal context — preferences, relationships,
  recurring tasks.
- Transmission principle: user believes "I can leave anytime"; actual
  = "I can leave, at compounding utility cost". Violation = asymmetry
  between perceived and actual exit cost, plus chilling effect on
  privacy-protective decisions.

**Realistic scenarios.**
- Provider adds retroactive training-eligibility on prior chats; user
  has 3 years of context and cannot practically migrate.
- Price increase plus worse privacy: user pays anyway.
- "Memory" defaulted on in an update; opting out forfeits the feature
  the user relies on.

**apf taxonomy mapping.** Like IPF-04, no single §2 row.

**Mitigation in apf.** Session-scoped namespaces and `/apf-reset`
reduce *provider-visible* accumulation. Multi-provider rotation
(§5.8, deferred) is the structural fix. The filter must not itself
become a lock-in vector: the local vault must be portable/exportable.

---

### IPF-09 — Training-data residuality

**Kernel.** Content the user sent ends up extractable from a future
model via prompts the user cannot anticipate.

**Description.** Carlini et al. (USENIX 2021) demonstrated training-
data extraction; Copilot regurgitation confirmed at scale. Even when
the provider doesn't nominally train on consumer chats,
abuse-prevention copies, 30-day retention buffers, red-team sampling,
contractor-graded review, one-off fine-tune experiments all touch the
same bytes. Once ingested by *any* training-adjacent pipeline, future
model versions may emit content verbatim to other users.

**Maps to.** Solove → *Disclosure*, *Increased Accessibility*,
*Insecurity*. Lee 2024 → *Disclosure*, *Insecurity*.

**Nissenbaum CI Worksheet.**
- Sender: user.
- Recipient: provider; transitively, future users of any model trained
  on this data.
- Subject: user.
- Information type: anything sent.
- Transmission principle: user expects one-to-one processing; actual
  = potential one-to-many memorisation. Violation = the transition
  from bilateral to multilateral flow without sender awareness.

**Realistic scenarios.**
- User pastes Excel CSV with employee names; two years later another
  customer's chatbot emits the same row in a benchmark.
- Copyrighted draft regurgitated near-verbatim from a fine-tune.
- Sensitive medical narrative used in red-team eval; surfaced in a
  later eval-leakage paper.

**apf taxonomy mapping.** All §2 rows. Per threat-model §1 actor 5:
"the strongest argument for client-side filtering: it's the only
intervention that doesn't depend on the provider's continued
discipline."

**Mitigation in apf.** Masking eliminates value-level
extractability for substituted spans. Surrounding category-laden
context (cf. IPF-06) is residual; opaque tokens (§5.1) minimise it.
Hardest case is verbatim copy-paste of long structured documents —
filter must catch the full structure.

---

### IPF-10 — Bystander / secondary leak (data leaks via others)

**Kernel.** The user's privacy is compromised by other people's opsec —
chats forwarded, screenshots shared, exports posted on social media.

**Description.** User themselves takes care: masks, uses local
models for sensitive topics. Their counterparties — coworker, ex,
family member, clinician using their own AI — do not. Notes shared in
confidence get pasted into those people's LLM sessions, forwarded into
chat-summarisation plugins, screenshotted into Slack. User's data is
now spread across providers the user never directly engaged. Mirror
image of IPF-03: where IPF-03 is the user violating someone else's CI
norms, IPF-10 is the user being violated by others' CI breaches.

**Maps to.** Solove → *Breach of Confidentiality*, *Disclosure*,
*Increased Accessibility*. Lee 2024 → *Disclosure*, *Insecurity*.

**Nissenbaum CI Worksheet.**
- Sender: third party (user's counterparty).
- Recipient: that third party's LLM provider, then downstream.
- Subject: user.
- Information type: whatever the user told the third party under
  their bilateral norm (intimacy, professional confidence, medical /
  legal / spiritual).
- Transmission principle: user→3p governed by relationship norm;
  3p→LLM governed by TOS. Violation = the change in transmission
  principle without the user's knowledge.

**Realistic scenarios.**
- User sends drafts of personal news to a friend, who pastes them
  into ChatGPT to craft a reply. Provider now has both sides.
- Clinician uses Otter or a clinical-AI scribe to transcribe; the
  patient (user) never consented to that processor.
- Colleague summarises a candid 1:1 in their notes app, which
  silently uses an LLM backend.

**apf taxonomy mapping.** *Outside* the user's controllable surface —
filter can't enforce it. But the §2.10 / 3p-rows pattern is the
upstream "what others know about the user" set.

**Mitigation in apf.** Effectively none from the filter itself. Lives
in user education (assume anything you tell others may reach an LLM)
and ecosystem-level norms. **Named risk, not filter-enforceable.**

---

### IPF-11 — Phrenology / Physiognomy inference

**Kernel.** AI systems infer sensitive attributes (mood, ethnicity,
sexuality, health, "trustworthiness") from non-obvious signals — voice,
face, gait, typing rhythm, writing style — without the subject's
knowledge.

**Description.** Lee et al. (2024) identify Phrenology / Physiognomy as
the one category genuinely *new* relative to Solove. Applies whenever a
model derives protected-class or otherwise sensitive information from
inputs offered for a different purpose. Upload a voice memo for
transcription; the pipeline silently scores emotion, deception markers,
demographic likelihoods. Share a face for a profile crop; the system
infers ethnicity, age, "stress level". Inferences are often poorly
validated, frequently biased, and become durable labels in the
provider's profile. The user may never *type* the sensitive category,
yet it appears in their record as a model output.

**Maps to.** Solove → no direct map (the 2006 taxonomy did not
anticipate this); closest neighbours *Distortion* and *Identification*.
Lee 2024 → *Phrenology/Physiognomy* directly; also *Distortion*,
*Surveillance*.

**Nissenbaum CI Worksheet.**
- Sender: user, often for a different purpose than the inference.
- Recipient: provider, often through silent feature pipelines.
- Subject: user.
- Information type: derived inference from physical / behavioural
  signal.
- Transmission principle: user offered the signal for purpose X
  (transcribe my voice memo); actual processing X + Y + Z + W.
  Violation = unlabelled secondary inference outside the declared
  purpose.

**Realistic scenarios.**
- Voice-memo transcription pipeline also runs depression / emotion
  classifier; the score persists in the account profile.
- Profile-picture upload runs ethnicity-inference for ad targeting.
- Typing-cadence in an assistant client logged as a "stress" signal.

**apf taxonomy mapping.** B5 (biometric — voice / gait / typing) is
the only direct §2 row. Mostly *outside* apf's text-only surface —
names a gap rather than a covered row.

**Mitigation in apf.** Text-only filter has limited surface here. Honest
mitigation is **scope restraint**: filter inspects text; multimodal
sidechannels (audio, image, video, biometrics) need separate hooks,
currently out of scope. Docs must name this gap so users don't assume
text-masking extends to other modalities. Future: per-modality
routing in the endpoint trust map (§5.8).

---

## 2. Cross-cutting observations

### 2.1 Clusters by harm-shape, not by content category

The eleven IPFs sort into four shape-clusters that apf must address at
different layers:

| Cluster | IPFs | Filter layer |
|---|---|---|
| Temporal asymmetry | IPF-01, IPF-04, IPF-08, IPF-09 | Session boundaries, opaque tokens, endpoint rotation (future) |
| Joining / linkage | IPF-02, IPF-05 | Per-session namespaces, profile-aggregation warning, per-persona vault (future) |
| Inferential leak around tokens | IPF-06, IPF-11 | Opaque tokens (one path), local-only routing (rest, deferred), scope restraint for multimodal |
| Consent-of-others / asymmetry | IPF-03, IPF-07, IPF-10 | 3p-attribute masking, honest docs about limits, ecosystem advocacy |

This regrouping is more useful than the IPF list itself when asking
whether a proposed feature buys real protection — a change that only
addresses one cluster leaves the other three exposed.

### 2.2 What masking alone cannot fix

Five of eleven IPFs are *not* solvable by masking alone: IPF-04
(longitudinal volume isn't shrunk by substitution), IPF-06 (context
around the token leaks the category), IPF-07 (the *fact* the user
used an LLM on topic X is itself the signal), IPF-10 (happens on
someone else's machine), IPF-11 (happens outside the text channel).

Consistent with `THREAT-MODEL-PRIVATE.md` §3.1 — 60 % of taxonomy rows
have a categorical-leak component the three-tier mechanic doesn't fully
solve. Substitution is the *floor*, not the ceiling. Three of these
five (07, 10, 11) are explicitly *named-but-out-of-scope* for v1 rather
than promised solutions.

### 2.3 Connection to §5 decisions in THREAT-MODEL-PRIVATE.md

The resolved-decisions block already reflects several IPF-driven
choices, retroactively legible:

- §5.1 (opaque tokens) directly mitigates IPF-06.
- §5.2 (3p as orthogonal attribute) addresses IPF-03.
- §5.3 (eager default + opt-out) reflects IPF-01: users can't
  pre-anticipate which categories will age badly.
- §5.4 (diversity-weighted warning) responds to IPF-02 and IPF-04.
- §5.6 (deferred local-only routing) is the unbuilt mitigation for
  IPF-07's hardest form.

§5.5 (bystander on-screen — out of scope) corresponds to a physical
version of IPF-10. The two deferred design issues (§5.7 audit log, §5.8
endpoint trust map) both serve IPF-04 and IPF-08.

### 2.4 The cross-modal gap

IPF-11 and parts of IPF-05 / IPF-10 surface a clean limitation: apf is
*text-only*. Voice memos, profile images, screen-share streams,
behavioural-biometric sidechannels are all out of scope. The project
should *name* this perimeter in docs rather than letting users assume
text-masking extends to other modalities. Future architecture can
hook per-modality routing via the endpoint-trust map (§5.8), but v1
should make the gap explicit.

---

## 3. Coverage statement

### 3.1 Solove (2006) subtypes addressed

| Subtype | Addressed by |
|---|---|
| Surveillance | IPF-04, IPF-07 |
| Interrogation | — (not in assistant-agent flow) |
| Aggregation | IPF-02, IPF-03, IPF-04, IPF-05, IPF-06, IPF-08, IPF-10 |
| Identification | IPF-02, IPF-05, IPF-06, IPF-11 |
| Insecurity | IPF-03, IPF-09, IPF-10 |
| Secondary Use | IPF-01, IPF-04, IPF-09 |
| Exclusion | IPF-07, IPF-08 |
| Breach of Confidentiality | IPF-03, IPF-10 |
| Disclosure | IPF-01, IPF-03, IPF-06, IPF-09, IPF-10 |
| Exposure | IPF-01 |
| Increased Accessibility | IPF-05, IPF-09, IPF-10 |
| Blackmail | — (out of typical threat model) |
| Appropriation | — (commercial-use of likeness, out of scope) |
| Distortion | IPF-01, IPF-07, IPF-11 |
| Intrusion | — (physical-space; cf. §5.5 out-of-scope) |
| Decisional Interference | IPF-08 |

Twelve of sixteen Solove subtypes addressed; four (Interrogation,
Blackmail, Appropriation, Intrusion) are correctly out of the
assistant-agent threat space.

### 3.2 Lee et al. (2024) labels addressed

Of 12 Lee labels, 11 are addressed across the IPFs. Only *Intrusion*
remains unaddressed — for the same reason it's out of scope in Solove
(physical-space; §5.5 explicitly out of scope). The Lee net-new
category *Phrenology/Physiognomy* is captured by IPF-11.

### 3.3 Gaps — candidates for follow-up issues

1. **Local-only routing for asylum / abuse / whistleblower content** —
   IPF-07 hardest form. Tracked as §5.6.
2. **Multimodal coverage** — IPF-11 and parts of IPF-05. No issue yet;
   file as design-stub.
3. **Per-persona vault namespaces** — IPF-05 fully solved needs
   per-persona token scoping within a session. No issue yet.
4. **Provider rotation / endpoint-trust map** — IPF-04, IPF-08. Tracked
   as §5.8 / [[apf-ycu]].
5. **Bystander / ecosystem norms** — IPF-10. No filter-side solution;
   documentation placeholder needed.
6. **Audit / retention review** — IPF-04 in self-review form. §5.7
   deferred.

### 3.4 Next checks against THREAT-MODEL-PRIVATE.md §2 (for apf-1qh)

Concrete row-by-row pass:

1. **For every `+cat` row** — confirm an IPF-06 fixture exercises the
   inferential-context leak. File fixture gaps where missing.
2. **For every `A-3p` row** — confirm the filter emits `third_party=True`
   on the corresponding span (IPF-03 cross-check).
3. **For every row in §2.8 (profile-able behaviour)** — confirm it
   contributes to the §5.4 diversity counter (IPF-02 cross-check).
4. **For H6, S9, L6, P8, S10** — confirm flagged as candidates for §5.6
   local-only routing (IPF-07 cross-check).
5. **For B5 (biometric)** — confirm docs explicitly note text-only
   filtering does *not* cover voice / image / behaviour signals
   (IPF-11 cross-check).

Each is scoped small enough to dispatch as a sub-issue under
`apf-1qh`. Together they close the "do we actually cover the IPFs we
claim to cover" question.

---

## References

- Lee, H. P., Yang, Y. J., Von Davier, T. S., Forlizzi, J., & Das, S.
  (2024). *Deepfakes, Phrenology, Surveillance, and More! A Taxonomy
  of AI Privacy Risks.* CHI '24.
- Solove, D. J. (2006). *A Taxonomy of Privacy.* University of
  Pennsylvania Law Review, 154(3), 477–564.
- Nissenbaum, H. (2010). *Privacy in Context: Technology, Policy, and
  the Integrity of Social Life.* Stanford University Press.
- Sweeney, L. (2002). *k-anonymity: a model for protecting privacy.*
  International Journal of Uncertainty, Fuzziness and Knowledge-Based
  Systems, 10(5).
- Carlini, N. et al. (2021). *Extracting Training Data from Large
  Language Models.* USENIX Security 2021.
