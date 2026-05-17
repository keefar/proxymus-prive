# Threat model — private individual using a personal AI agent

Companion to `docs/ARCHITECTURE.md`. Where `ARCHITECTURE.md` defines the three
mechanical tiers (A = content PII, B = operational identifiers, C = secrets),
this document is the *substance* side: what concrete categories of personal
information cross the boundary, what harm each class can cause, and what
implications that has for the filter design.

The motivating user is **not** a pentester, not a compliance officer, not a
corporate employee with a DPO. The user is a private person who uses Claude
Code, ChatGPT desktop, future personal-assistant agents the way a normal
human would: drafting messages, asking medical questions, planning
appointments, processing notes, journaling, getting help with admin and
finances. The threat model below is built for that user.

## 0. Scope (decided 2026-05-17)

**In scope.** Assistant-agent processing of the user's own data and
correspondence: calendar parsing, email categorisation, reminder management,
document drafting, file search, note summarisation. The sensitive content is
data the agent *handles*, not the topic of the conversation.

**Out of scope.** Chat-as-confidant scenarios where the sensitive content
*is* the conversation topic (therapy sparring, medication chat, coming-out
reflection). These deserve providers that don't need a filter — local
models, DuckDuckGo AI, future audited no-log endpoints. Trying to serve
both use cases makes both worse. Users in the chat-use-case are directed
elsewhere in the README.

**Also out of scope.** Bystander / shoulder-surfing threats (screen
mitlesen by physical co-present people). The filter protects against
network-side leakage to the LLM provider; physical-environment risk is
user-side risk management (privacy filter foil, room layout, screen lock).
A best-effort metadata hook for client-side blur-on-render is deferred —
not antizipativ added.

---

## 1. Threat model statement

### Who we're protecting against

The "LLM provider" is a useful shorthand but flattens five distinct actors.
The filter design has to remain sane against *all* of them:

1. **The provider itself, as an institution.** Anthropic, OpenAI, Google all
   publish privacy commitments. These are policy artifacts, not technical
   guarantees. Policies change, products get sold (cf. Inflection → Microsoft
   in 2024), retention windows extend after incidents, "consumer" surfaces
   silently route training-eligible. The filter assumes the provider's
   *current* policy is the best case and that the *future* policy is worse.

2. **Data breaches at the provider or its sub-processors.** Both OpenAI
   (March 2023 Redis bug exposed chat titles + partial payment data) and
   Anthropic (May 2024 contractor mistake exposed customer names + balances)
   have had real incidents. Anything the provider holds, the breach holds.
   Filtering at the client is the only way to ensure the breach surface is
   smaller than the conversation surface.

3. **Third-party training pipelines and retention.** Even when a consumer
   product nominally doesn't train on user data, abuse-prevention copies,
   30-day retention buffers, red-team sampling, internal eval sets and
   contractor-graded fine-tune runs all touch the same bytes. The filter
   has to be safe against the assumption that *anything sent will be read
   by humans we don't know, on hardware we don't control, for purposes we
   can't audit*.

4. **Bystanders, screen-sharers, partners with shared devices.** The agent's
   *rendered output* often appears unredacted on the user's screen during
   meetings, screen-shares, or simply when a partner walks past. The
   filter's restore step is not a privacy win against this attacker —
   restored output on screen is exactly as leaky as unredacted output. A
   private-mode response renderer (blurred, type-tagged, click-to-reveal)
   is a real design question, not a UI nice-to-have.

5. **Future model failures and emergent retention.** Foundation models
   trained on web-scale corpora have demonstrably memorised training
   examples (Carlini et al., USENIX 2021; the GitHub Copilot regurgitation
   suits). A reasonable assumption is that *any text the provider holds
   long enough* may become extractable from a future model via prompts the
   user can't anticipate. This is the strongest argument for client-side
   filtering: it's the only intervention that doesn't depend on the
   provider's continued discipline.

### Concrete harm model

Privacy harms are not abstractions. The fixture corpus and the filter's
behaviour have to be tuned against *specific* downstream consequences:

- **Insurance discrimination** — Krankenversicherung, Berufsunfähigkeits-,
  Lebens-, KFZ-Versicherung. A future "AI-assisted underwriting" surface
  that ingests a leaked diagnosis, a gambling-debt note, or a depression
  Therapie-Erwähnung can result in higher premiums or refused coverage,
  and the user has no recourse because the discrimination is laundered
  through a model.
- **Employment / background-check exposure.** German Schufa-Eintrag,
  US background-check vendors (HireRight, Checkr) increasingly ingest
  unstructured data. A leaked Vorstrafe, Insolvenzantrag, or even a
  candid political opinion in a chat log can disqualify silently.
- **Custody and family-court disclosure.** Notes about parenting
  decisions, ex-partner conflicts, mental-health treatment, or substance
  use written *to an AI* can be subpoenaed (US) or discovered via
  Auskunftsersuchen (DE) in a family-law dispute. The fact that the user
  was talking to an AI doesn't grant privilege.
- **Social engineering of the user.** A leaked combination of pet name +
  birth date + bank + employer + commute pattern is sufficient seed
  material for phishing that bypasses normal scepticism. The filter's
  job is not just regulatory compliance — it's reducing the *attack
  surface* the user presents to anyone with an LLM and a vendetta.
- **Relationship damage.** Drafts of letters to estranged family, candid
  notes about a partner, mental-health context entrusted to the agent —
  all of these have asymmetric blast radius. A small leak to the wrong
  reader is a relationship-ending event in a way that a leaked password
  isn't.
- **Stigma and social cost.** HIV status, abortion history, addiction
  recovery, neurodivergence, gender identity in a non-supportive
  community — these don't necessarily produce legal or financial harm
  but produce social harm that the user cannot un-do. The filter has to
  treat these as first-class even though they don't show up in a
  standard PII taxonomy.
- **Legal exposure of third parties.** When the user writes about a
  *friend's* drug use, a *colleague's* affair, a *child's* mental-health
  appointment, the privacy stake is not the user's — it's the other
  person's, who never consented to be in the dataset.

The taxonomy below is built around these six harm shapes, not around
regulatory categories alone. Regulatory categories (GDPR Art. 9, AGG §1,
EEOC/ADA) are mapped in the rightmost column as legal anchors, but they
are necessary, not sufficient — the user's harm model is broader than
any single jurisdiction's special-category list.

---

## 2. Taxonomy

### How to read this table

- **Surface forms**: short realistic examples of how this kind of
  content actually appears in private text — chat drafts, calendar
  entries, journal lines, agent prompts. DE and EN are mixed
  deliberately because the user writes in both.
- **Harm vector**: the concrete downstream consequence if this leaks,
  not a generic "privacy violation". One per row.
- **Filter difficulty**: where in the detector stack this lives.
  - `easy` — deterministic regex catches it (IBAN, email, API key
    prefix, specific medication names from a list).
  - `medium` — NER / GLiNER catches it (named entity, structured
    span with anchor word).
  - `hard` — needs semantic understanding (paraphrase, implicit
    reference, context-dependent meaning).
  - `categorical-only` — the *value* can be tokenised, but the *fact
    that the topic appeared in this category at all* is itself the
    leak. Tokenising "Lexapro" to `<MEDICATION_1>` still tells the
    cloud LLM the user is on medication. These cases need a
    different mechanic than reversible substitution — see §3 and §5.
- **Tier mapping**: A (content, reversible), B (operational, tool-
  call boundary), C (secret, opaque). `A+cat` = Tier A
  reversible substitution PLUS a recommended new "categorical-only"
  handling (see §3). `A-3p` = Tier A but the data subject is a
  third party, not the user.

### 2.1 Health

| # | Subcategory | Surface forms (DE+EN) | Harm vector | Filter difficulty | Tier |
|---|---|---|---|---|---|
| H1 | Physical diagnosis (chronic) | "seit der Diabetes-Diagnose 2022…", "my MS flare last winter" | Insurance refuses Berufsunfähigkeits-, life, or US individual-market policy | medium (anchor word) → hard (paraphrase) | A+cat |
| H2 | Physical diagnosis (acute / infectious) | "Borreliose nach dem Wandern", "tested positive for COVID Tuesday" | Less stigma; still a profiling signal — combined with other data forms a health trajectory | medium | A |
| H3 | Mental-health diagnosis | "ADHS-Diagnose endlich da", "since the depression diagnosis", "Borderline-Verdacht" | Custody disputes; insurance; Verbeamtung gesundheitliche Eignung; social stigma | medium → hard | A+cat |
| H4 | Psychotherapy / Therapie-Erwähnung | "war heute bei meiner Therapeutin", "EMDR session yesterday was rough" | Same as H3; the *act of being in therapy* leaks even without the diagnosis | hard (no anchor needed) | A+cat |
| H5 | Reproductive health | "war heute beim Frauenarzt", "we're trying since March", "post-abortion follow-up" | Discrimination at work (DE Mutterschutz pre-disclosure leak); criminalisation risk (US post-Dobbs travel); intra-family conflict | hard | A+cat |
| H6 | Sexual health / STI | "HIV-Status weiter negativ", "PrEP refill needed", "Chlamydientest negativ" | Stigma, partner-network discovery, immigration impact in some jurisdictions | medium (named conditions) → hard | A+cat |
| H7 | Specialist mentions + Fachrichtung | "Termin bei Dr. Bauer in der Onkologie", "appointment at the gender clinic" | Reveals diagnosis category by inference — onco/psych/gender/repro specialists are sticky labels | medium (anchor: Dr./MD/clinic) | A+cat |
| H8 | Medication names | "Lexapro 10mg seit Mai", "habe Concerta abgesetzt" | Reveals diagnosis category (SSRI→depression, methylphenidate→ADHD, PrEP→HIV-risk-management) | easy (list-based) | A+cat |
| H9 | Lab values / vital signs | "Cholesterin 280", "HbA1c 8.2", "BP 160/95 again" | Insurance underwriting; profiling | easy (numeric+unit) → medium | A |
| H10 | Hospital / clinic stays | "drei Tage Charité Station 14", "discharged from psych unit last week" | Same as diagnosis; psych unit especially stigmatising | medium | A+cat |
| H11 | Lab + paramedic / Rettungsdienst notes | "RTW-Einsatz mit Verdacht auf TIA", "ED triage note attached" | Reveals medical emergency history; insurance | hard (clinical jargon) | A+cat |
| H12 | Genetic / hereditary info | "BRCA1-Träger", "Huntington in der Familie" | Discrimination at insurance and employment; affects blood relatives who never consented (see R3) | medium | A+cat, A-3p |
| H13 | Family medical history | "meine Mutter hatte Brustkrebs mit 45", "father's Alzheimer's started early" | Same as H12; blast radius across family tree | hard | A-3p, A+cat |
| H14 | Disability status | "mit GdB 50 anerkannt", "filing for SSDI", "Schwerbehindertenausweis" | Discrimination (AGG §1 protects but doesn't prevent); insurance | medium | A+cat |
| H15 | Neurodivergence (Autism, ADHD, dyslexia) | "auf dem Autismus-Spektrum", "since my ADHD diagnosis at 38" | Stigma; employer perception; rarely formal discrimination but real social cost | medium → hard | A+cat |

### 2.2 Sexuality, gender, relationships

| # | Subcategory | Surface forms (DE+EN) | Harm vector | Filter difficulty | Tier |
|---|---|---|---|---|---|
| S1 | Sexual orientation | "mein Freund und ich", "out to my parents now", "schwul" | Family conflict; immigration risk in non-EU travel; rare formal employment cost in EU but real in US private sector | hard (often implicit from pronouns + context) | A+cat |
| S2 | Gender identity | "since starting HRT", "Vornamensänderung im Personenstand", "they/them now at work" | Workplace; family; medical-care access; physical safety in some contexts | hard | A+cat |
| S3 | Partner / spouse name | "Sebastian und ich fahren", "my wife Hannah" | Profile-builder; partner becomes searchable through user | medium (NER) | A, A-3p |
| S4 | Ex-partner / divorce | "seit der Trennung von Marc", "in mediation with my ex" | Custody / Unterhalt evidence; emotional content valuable for social engineering | hard | A, A-3p |
| S5 | Dating-app usage | "Hinge messages getting weird", "drei Tinder-Dates diese Woche" | Stigma in conservative environments; profile-builder | hard | A+cat |
| S6 | Affair / infidelity | "Affäre seit Februar", "the thing with my coworker last summer" | Marriage-ending; in some jurisdictions (US fault-divorce states) financial impact | hard | A+cat |
| S7 | Sexual practices / kinks | "kink-aware therapist suchen", "we're in a poly arrangement" | Stigma; some jurisdictions (Saudi travel etc.) legal risk; employment in conservative fields | hard | A+cat |
| S8 | Fertility / pregnancy | "in Woche 9", "IVF cycle 3 didn't take" | Workplace timing pre-Mutterschutz-Mitteilung; insurance; emotional sensitivity if outcome bad | medium → hard | A+cat |
| S9 | Abortion | "Abbruch in der 8. SSW", "the abortion last fall" | Stigma; legal risk in restrictive US states; intra-family | medium (anchor) → hard | A+cat |
| S10 | Domestic abuse / violence | "wenn er wieder so wird", "Frauenhaus-Nummer rausgesucht", "restraining order in progress" | Safety (perpetrator-access risk); custody; mental-health profile leak | hard | A+cat |

### 2.3 Politics, beliefs, activism

| # | Subcategory | Surface forms (DE+EN) | Harm vector | Filter difficulty | Tier |
|---|---|---|---|---|---|
| P1 | Party affiliation / membership | "auf der Linken-Versammlung", "since I joined the DSA chapter" | Border-crossing scrutiny; some employers; surveillance lists in non-democratic destinations | medium (named entities) → hard | A+cat |
| P2 | Voting history / preferences | "habe Grün gewählt", "voted third-party again" | Lower direct harm in EU; higher in US-style targeted disinformation; profile-builder | hard | A+cat |
| P3 | Political donations | "100 € an Sea-Watch gespendet", "ActBlue receipts" | Same as P1 plus financial trail; US FEC data already public but linkage to private notes amplifies | easy (amount+org) → hard | A+cat |
| P4 | Religion / belief | "nach dem Schabbat", "Ramadan-Pause heute", "Austritt aus der Kirche eingereicht" | Workplace bias (especially Austritt sensitive in DE due to Kirchensteuer-trail); immigration in some destinations | medium | A+cat (AGG §1, GDPR 9) |
| P5 | Apostasy / belief change | "since I left the Jehovah's Witnesses", "Austritt aus Scientology" | Family / community shunning; in some jurisdictions physical risk | hard | A+cat |
| P6 | Controversial opinions | "AfD-Wahlerfolg ist mir egal", "Israel-Hamas take that I won't say out loud" | Social cost asymmetric — easy to be cancelled, hard to be re-employed | hard | A+cat |
| P7 | Activism / protest participation | "war auf der Lützerath-Demo", "got kettled at the Gaza protest" | Border-crossing in some jurisdictions; surveillance; employer disqualification in sensitive fields | hard | A+cat |
| P8 | Whistleblowing / leak intent | "drafting the disclosure for the press", "thinking about reporting my manager to BaFin" | Career-ending if employer learns first; legal exposure | hard | A+cat (treat as Tier-C-adjacent — see §5) |

### 2.4 Legal & criminal

| # | Subcategory | Surface forms (DE+EN) | Harm vector | Filter difficulty | Tier |
|---|---|---|---|---|---|
| L1 | Arrest / charges (not convicted) | "Anzeige wegen Trunkenheit am Steuer", "got arrested at the protest" | Background-check exposure; employer; immigration | hard | A+cat |
| L2 | Conviction / Vorstrafe | "Eintrag wegen §316 StGB", "felony record from 2014" | Same as L1 with stronger effect; housing in some markets | hard | A+cat |
| L3 | Fines / Bußgeld | "Punkte in Flensburg sind voll", "speeding ticket lawyer fee" | Lower stakes alone; profile-builder | easy (anchor: Bußgeld, fine) → medium | A |
| L4 | Civil suits | "Klage gegen den Vermieter", "in litigation with the contractor" | Tenant blacklists (DE Schufa-Eintrag for Mietnomaden); profile | medium | A |
| L5 | Immigration / visa status | "Niederlassungserlaubnis verlängern", "OPT runs out in March", "Duldung läuft" | Employer leverage; deportation risk if status irregular; family-reunion impact | medium | A+cat |
| L6 | Asylum / refugee status | "mein Asylverfahren in der Anhörungsphase", "asylum interview scheduled" | Persecution risk if leaked back to origin country; community implications | hard | A+cat (highest sensitivity tier) |
| L7 | Custody / Sorgerecht disputes | "vor dem Familiengericht im Mai", "supervised visitation order" | Material for the *other* side; child welfare authorities | hard | A, A-3p |
| L8 | Restraining / protection orders | "Gewaltschutzanordnung gegen meinen Ex", "DV restraining order" | Safety (perpetrator access); also stigma if user is the *subject* | hard | A+cat |

### 2.5 Financial

| # | Subcategory | Surface forms (DE+EN) | Harm vector | Filter difficulty | Tier |
|---|---|---|---|---|---|
| F1 | Salary / income | "verdiene 78k brutto", "TC around 240 at the new place" | Negotiation leverage if leaked to employer; relationship friction | medium (amount + anchor) | A |
| F2 | Savings / net worth | "150k auf dem Tagesgeld", "down payment of 60k saved" | Social engineering; profile | medium | A |
| F3 | Debts / Insolvenz | "Privatinsolvenz seit März läuft", "filed Chapter 13" | Schufa stays 3 years post-Restschuldbefreiung; housing, credit, employment in finance/security clearances | medium | A+cat |
| F4 | Credit score / Schufa-Score | "Score auf 91 gefallen", "FICO dropped after the dispute" | Discrimination by lenders; some employers; combined with F3 a profile | easy → medium | A+cat |
| F5 | Tax issues | "Steuerprüfung läuft seit Mai", "IRS audit notice arrived" | Stigma; potential employer concern in finance/clearance roles | hard | A+cat |
| F6 | Gambling spend | "wieder 800 auf Tipico verloren", "$2k on DraftKings last month" | Addiction signal — insurance, custody, employer in financial roles | medium (anchor: site name + amount) | A+cat |
| F7 | Inheritance / Erbschaft | "Erbe von Tante Helga 45k", "Mom's estate finally closing" | Social engineering; family conflict if siblings find out terms | medium | A, A-3p |

### 2.6 Substance use, addiction, recovery

| # | Subcategory | Surface forms (DE+EN) | Harm vector | Filter difficulty | Tier |
|---|---|---|---|---|---|
| Su1 | Alcohol use (problematic) | "trocken seit 47 Tagen", "third drink before noon again" | Custody; employer; insurance | hard | A+cat |
| Su2 | Recovery / Selbsthilfe | "war heute auf dem AA-Meeting", "year sober next week" | Implies prior addiction; same harm as Su1 with added recovery-narrative leak | hard | A+cat |
| Su3 | Recreational drugs | "Pilze am Wochenende", "microdosing for 6 months now" | Legal exposure (DE BtMG, US federal law); employer drug testing | hard | A+cat |
| Su4 | Prescribed controlled substances | "Ritalin-Rezept abgeholt", "my Adderall scripts" | Implies diagnosis (often ADHD); workplace stigma; border-crossing | easy (name) → medium | A+cat |
| Su5 | Smoking / nicotine | "Vape seit Januar nicht mehr", "rauchen wieder seit der Trennung" | Insurance underwriting; lower stigma but real cost | hard | A |
| Su6 | Eating-disorder context | "Rückfall in alte Essmuster", "ED therapist appointment" | Stigma; insurance; minor-custody concerns | hard | A+cat |
| Su7 | Gambling-addiction recovery | "OASIS-Sperre verlängert", "GA meeting Tuesday" | Same as F6 plus addiction-history label | hard | A+cat |

### 2.7 Identity vectors

| # | Subcategory | Surface forms (DE+EN) | Harm vector | Filter difficulty | Tier |
|---|---|---|---|---|---|
| I1 | Ethnicity / Hautfarbe | "als Schwarze Frau im Tech", "growing up Turkish-German" | Discrimination (AGG §1, GDPR 9, EEOC Title VII); often inferable from other data anyway | hard | A+cat |
| I2 | National origin | "in Aleppo geboren", "naturalized US citizen since 2019" | Same as I1; immigration-status adjacent (L5) | medium | A+cat |
| I3 | Refugee / migration history | "nach 2015 nach Deutschland", "fled Iran in 2009" | Same as I1 plus persecution-risk depending on origin | hard | A+cat |
| I4 | Native language / accent disclosure | "as a non-native speaker", "Muttersprache Farsi" | Profile-builder; combined with I2 sharpens identification | hard | A |
| I5 | Disability (non-medical framing) | "im Rollstuhl seit dem Unfall", "as a Deaf user" | Discrimination at work / housing / services | medium | A+cat (overlap with H14) |

### 2.8 Profile-able behaviour

These are the categories where each *individual* value is innocuous but
the *combination* is identifying. Filtering one without filtering the
others is theatre — see §3 cross-cutting.

| # | Subcategory | Surface forms (DE+EN) | Harm vector | Filter difficulty | Tier |
|---|---|---|---|---|---|
| B1 | Home address / postcode | "wohne in 10119, gegenüber vom Café Einstein" | Stalking; doxxing; ID theft | easy (regex/NER) | A |
| B2 | Workplace address / Büro | "im Büro am Potsdamer Platz", "office on Sansome Street" | Triangulates with B1 to identify user | medium | A |
| B3 | Commute / routine pattern | "jeden Dienstag zum Yoga in Mitte", "M2 train at 7:48 every weekday" | Stalker can find user without ever knowing address | hard | A+cat |
| B4 | Frequent locations | "mein Stammcafé Bonanza", "the gym on 14th" | Same as B3 | medium | A |
| B5 | Biometric — voice / gait / typing | "voice memo attached", "fingerprint scan failed three times" | Re-identification across services; the metadata is the leak, not the content | hard (not text-level usually) | A or new |
| B6 | Purchase patterns / shopping | "Rewe gestern 87 €, Amazon zwei Pakete heute" | Profile-builder; spending behaviour leaks lifestyle | medium | A |
| B7 | Device / browser / IP fingerprint | "from my home IP 84.137.x.x", "Safari Mac M5" | Cross-session linkability outside the LLM context | easy | B |
| B8 | Calendar regularity | "Mittwoch immer 14:00 Therapeutin" | Combines B3 and a Tier-A category — *structural* leak even if each cell tokenised | hard | A+cat |

### 2.9 Relationship-network info

| # | Subcategory | Surface forms (DE+EN) | Harm vector | Filter difficulty | Tier |
|---|---|---|---|---|---|
| R1 | Family member name + role | "meine Mutter Helene wohnt in Erfurt" | Security-question fodder; mother's maiden name still in active use as a "secret" by banks | medium | A, A-3p |
| R2 | Employer of relative / partner | "mein Mann arbeitet bei BMW Treasury" | Employer-side profile; insider-trading suspicion vector if relevant | medium | A, A-3p |
| R3 | Health info of family member | "mein Sohn hat ein Asperger-Verdachtsgutachten", "Dad's chemo schedule" | Third-party data; the *child* / parent never consented; GDPR-relevant if the user is treated as a "controller" of that data | hard | A-3p (+cat) |
| R4 | Friends' confidences entrusted | "Anna hat mir erzählt, dass sie eine Abtreibung hatte" | Most severe third-party case; Anna trusted *user*, not the LLM provider | hard | A-3p (+cat) |
| R5 | Child / minor info | "meine Tochter Lena, 7, in der 2. Klasse Sophie-Scholl-Schule" | Targeting of minors; school identification is high-value | medium | A-3p |
| R6 | Caregiving relationships | "pflege meinen Vater seit dem Schlaganfall" | Profile + reveals parent's health status | hard | A, A-3p (+cat) |

### 2.10 Third-party PII (cross-cutting category)

This is not a separate "kind" of data but a *modifier* on every row
above. Whenever the data subject is someone other than the user
(rows tagged `A-3p` above), the harm calculus shifts in two ways:
(a) the user cannot give consent on the third party's behalf, and
(b) the third party has no awareness their data is in the agent
context. Substance categories that recur as third-party data:

| # | Pattern | Example | Tier |
|---|---|---|---|
| 3p1 | Health of named relative | "meine Mutter Helene wurde gestern wegen Verdacht auf Pankreas-Ca eingeliefert" | A-3p+cat |
| 3p2 | Relationship problem disclosed about partner | "Marc hat seit Monaten Affäre mit einer Kollegin" | A-3p+cat |
| 3p3 | Friend's confidence | "Anna hat mir erzählt, dass sie HIV+ ist" | A-3p+cat |
| 3p4 | Minor's school / health | "Lenas Schulpsychologin meinte, dass…" | A-3p+cat |
| 3p5 | Employer / colleague confidential info | "mein Chef hat mir gestern gesagt, sie planen 30 Entlassungen" | A-3p+cat (also potential confidentiality breach) |

**Row count for §2 (taxonomy proper): 74 substance rows**
(H 15 + S 10 + P 8 + L 8 + F 7 + Su 7 + I 5 + B 8 + R 6),
plus 5 third-party pattern rows in §2.10 as cross-cutting tags
(total 79 rows).

---

## 3. Cross-cutting observations

### 3.1 Categorical-only leakage is the design problem this taxonomy reveals

The three-tier model (A/B/C) is built around the question *"what
happens to the value?"* — reversibly tokenise (A), tokenise with
boundary resolution (B), or opaquely redact (C). What the taxonomy
makes visible is a fourth question the current tier model does not
answer: *"what happens to the **category**?"*

Consider the phrase:

> "Ich habe eine Frage zu meiner <DIAGNOSIS_1>-Therapie."

After Tier-A substitution, the cloud LLM no longer knows *which*
diagnosis. It still knows the user *has a diagnosis* and *is in
therapy for it*. For 44 of the 74 substance rows above (everything
marked `+cat`), this kind of structural leak is the actual privacy
story — the specific value is almost incidental.

Concretely, **categorical-only leaks happen for**:

- All of §2.1 Health except H2 (acute infectious — low stigma) and H9
  (lab values — quantitative).
- All of §2.2 Sexuality / relationships except the bare name cases
  (S3 partner name in a benign context).
- All of §2.3 Politics / beliefs.
- The conviction / asylum / custody / restraining-order rows of §2.4
  (L2, L6, L7, L8).
- The debt / score / gambling / tax rows of §2.5 (F3, F4, F5, F6).
- All of §2.6 Substance.
- Most of §2.7 Identity.
- B3, B8 in §2.8 (routine + temporal patterns).
- R3, R4, R6 in §2.9 (third-party sensitive contexts).

That's 44 of 74 rows (~60 %) where pure value-substitution does
not produce a privacy-preserving prompt. **The current three-tier
mechanic is insufficient for these.** The design options for handling
them, in increasing order of intrusiveness:

1. **Topic-tagged placeholder** — replace `<MEDICATION_1>` with a
   semantically uninformative `<SENSITIVE_1>`. The LLM loses topical
   context entirely; user gets generic answers. Strong privacy, weak
   utility.
2. **Topic-tagged placeholder, with category visible** —
   `<MEDICAL_1>`. The LLM can still produce on-topic help ("for
   medications like this, common questions are…") but the *category*
   is leaked. Same privacy as today's tokenisation; honest about it.
3. **Rewrite-and-summarise** — instead of substitution, the local
   filter sends a paraphrase: "User has a question about long-term
   medication management." Significant utility loss; complete category
   protection. Probably too lossy for daily use.
4. **Local-only handling** — for the most sensitive subset (asylum,
   custody, abuse), refuse to forward at all and have the local agent
   answer with its smaller-but-resident model, no cloud round-trip.
   Strongest, requires UX to communicate "this question stays local".

The taxonomy strongly suggests **a fourth tier or a "category
sensitivity" attribute orthogonal to the existing tiers**, with a
user-configurable default policy per category. See §5 open
questions.

### 3.2 Utility loss is uneven across categories

Reversible round-trip works *cleanly* (no utility loss after restore)
for rows where the value is the privacy concern: names, emails,
phones, addresses, IBANs, IPs, paths, secrets. The LLM can reason
abstractly about `<PERSON_1>` and the user gets the restored output
without losing meaning.

It works *poorly* for rows where the value carries semantic weight
the LLM needs to reason correctly. Examples where tokenising
*degrades the answer*, not just hides the value:

- Medication-specific advice: "Can I drink wine with `<MEDICATION_1>`?"
  is unanswerable. The LLM has to know the drug.
- Diagnosis-specific advice: same.
- Legal-status-specific advice: visa rules differ per status type.
- Drug-interaction questions.
- Religious-practice-specific scheduling: "When can I take my dog out
  during `<RELIGIOUS_OBSERVANCE_1>`?"

These rows force a real trade-off. The user has to either accept
weaker advice or accept the value leaving the machine. The filter
cannot make this trade-off transparent without UX — which is why §5
asks the user to decide defaults.

### 3.3 Profile assembly: filtered values, leaked person

The taxonomy contains several rows that are individually weak signals
but combine to a uniquely identifying profile even after every value
is tokenised. The canonical examples:

- B1 home postcode + B2 work postcode + B3 commute pattern + R5
  child-school = a profile of <50 people in a large city; <5 in a
  small one. Even with all four tokenised, the *pattern of having
  exactly those four things* leaks.
- H4 (therapy regularity) + B8 (weekly calendar entry) + H7
  (specialist Fachrichtung) = "user has weekly psychotherapy at the
  same clinic" — survives tokenisation as a structural signal.
- F1 salary + B1 postcode + I2 national origin = census-grade
  identifier across many cities.

This is a known result from the de-identification literature
(Sweeney 2002 on quasi-identifiers; the Netflix Prize re-id) but
the new wrinkle for an LLM-context threat model is that the LLM
*reasons across multiple turns*. Even if each individual turn is
filtered well, the cumulative context that builds up in a long
conversation is profile-grade. The filter has to think in
*conversation*, not just per-request.

**Implication for design**: the session vault is not only a
"placeholder ↔ value" map; it should also surface a *cumulative
sensitivity score* per conversation. If the user is on turn 30 of a
chat that has touched three Tier-A+cat categories, the filter UX
should say something. This is the "low-confidence flag" idea from the
MODEL-EVALUATION doc, extended to "cumulative profile flag".

### 3.4 Where DE and EN diverge in surface form

Most categories have parallel surface forms in DE and EN, but some
are jurisdiction-specific and the detector will need separate
treatment:

| Category | DE-specific form | EN-specific form |
|---|---|---|
| Insurance ID (B / health) | "KV-Nr.", "Krankenversichertennummer", AOK/TK/Barmer numbers | SSN-last-4, MBI, Aetna/UHC member-ID format |
| Tax ID | Steuerliche Identifikationsnummer (11 Ziffern, IdNr.) | SSN (9 digits, US), NI number (UK) |
| Civil-status registry | "Personenstandsregister", "Vornamensänderung" | court order JD #, US state-by-state |
| Financial blacklist | "Schufa-Eintrag", "Bonität", "BoniCheck" | "FICO", "Experian dispute" |
| Driving-points | "Punkte in Flensburg", "Bußgeldbescheid" | "points on license", "DMV record" |
| Healthcare facility types | "Charité", "Vivantes", "Asklepios" → big-three Berlin chains | "Kaiser", "Mount Sinai", "VA hospital" |
| Insolvency | "Privatinsolvenz", "Restschuldbefreiung" | "Chapter 7/13", "bankruptcy filing" |
| Disability admin | "GdB 50", "Schwerbehindertenausweis" | "SSDI", "ADA reasonable accommodation" |
| Reproductive law context | "§218 StGB", "Beratungsschein" | "Roe", "trigger law", "Dobbs" |
| Asylum / refugee | "Aufenthaltsgestattung", "Duldung", "Anhörung" | "credible-fear interview", "EAD" |
| Religious context | "Kirchensteuer", "Austritt aus der Kirche", "Konfession" | "tithe", "non-denominational" |

GLiNER multilingual catches *names* across languages fine
(`gliner_multi_pii-v1` actually scores higher on DE than EN in this
project's benchmark). The gap is on *institutional vocabulary* like
the rows above — these are mostly easy regex/keyword catches, but
they need *parallel keyword lists*, not just a translated one.

### 3.5 Legal anchors and what they map to

Three legal frameworks are useful for naming categories with
authority. They overlap but don't coincide.

- **GDPR Art. 9(1)** [Regulation (EU) 2016/679, Art. 9(1)] — eight
  special categories: racial/ethnic origin, political opinions,
  religious/philosophical beliefs, trade-union membership, genetic
  data, biometric data for unique identification, health data, sex
  life or sexual orientation. Maps to: §2.1, §2.2 (S1, S2, S7, S8,
  S9), §2.3 (P1 trade-union membership, P4, P5), §2.7 (I1, I3), §2.8
  (B5).
- **AGG §1** [Allgemeines Gleichbehandlungsgesetz § 1] — German
  workplace and civil-transactions anti-discrimination: race or
  ethnic origin, sex, religion or belief, disability, age, sexual
  identity. Narrower scope than GDPR-9 but with *enforcement teeth*
  for discrimination. Maps to: §2.7 (I1, I2), §2.2 (S1, S2), §2.3
  (P4, P5), §2.1 (H14, H15 partially).
- **US Title VII + ADA + ADEA + GINA** [42 U.S.C. § 2000e et seq.;
  42 U.S.C. § 12101 et seq.; 29 U.S.C. § 621 et seq.; 42 U.S.C. §
  2000ff] — race, color, religion, sex (incl. orientation and gender
  identity post-Bostock 2020), national origin, disability, age 40+,
  genetic information. Maps similarly to AGG but with
  disability covered explicitly under ADA and genetic info under
  GINA.

Two categories *no jurisdiction's discrimination law touches*
which the threat model still has to handle:

- **Financial-status discrimination** (F1–F7) — not protected at
  workplace level in either DE or US, but real harm via lending,
  housing, insurance. AGG explicitly *excludes* "financial
  circumstances" from §1 (per Antidiskriminierungsstelle
  guidance).
- **Substance-use history** when not framed as disability (Su1–Su7).
  Recovery status often *is* ADA-protected in US ("history of"
  addiction); active use generally is not. DE: no specific
  protection beyond general data-protection.

These two clusters are *not* in any special-category list but rank
high on the user-harm dimension. The taxonomy includes them not for
legal compliance but because they're materially harmful if leaked.

**German constitutional anchor**: the
*informationelle Selbstbestimmung* derived from BVerfG
Volkszählungsurteil (1983) — the constitutional right that the
*aggregation* of innocuous data into a profile is itself a Grundrecht
intrusion. This is the constitutional grounding for §3.3 (profile
assembly) above; the filter's "cumulative profile flag" can be
framed as a direct technical implementation of that doctrine.

---

## 4. Fixture-corpus recommendations

The current `fixtures/content.jsonl` (30 rows) covers explicit Tier-A
spans well (names, emails, phones, addresses, dates, a few health
anchors). It does not stress-test the taxonomy above — specifically
nothing for politics / sexuality / asylum / substance / third-party
data. The following 14 scenarios would cover the gaps without
re-doing the whole corpus.

Naming convention: `de-` / `en-` prefix, taxonomy-section identifier,
two-digit suffix. All scenarios use synthetic data only.

| Fixture ID | One-sentence scenario |
|---|---|
| `de-health-mental-01` | User drafts a chat to a therapist suggesting a session topic, mentioning an SSRI medication and a recent flare. |
| `de-repro-01` | User asks the agent to summarise their gynaecologist's referral letter (named clinic, named Befund) for forwarding. |
| `en-mental-substance-01` | User journals a relapse note: alcohol use after a depressive episode, mentions AA meeting and therapist name. |
| `de-asylum-01` | User has the agent help draft a §60 AsylG statement, with origin country, dates, and hearing date. |
| `en-custody-01` | User drafts notes for a custody-mediation session, referencing child's name, ex-partner, and the child's school. |
| `de-finanz-insolvenz-01` | User drafts an email to a Schuldnerberatung describing debts, Schufa score, and Privatinsolvenz status. |
| `de-politik-spende-01` | User asks the agent to draft a tax-deduction letter for political donations to a named party. |
| `en-political-activism-01` | User drafts a Twitter thread about a protest they attended, mentioning the org and a co-organiser. |
| `de-third-party-health-01` | User asks the agent to research a rare condition their mother was diagnosed with, naming the mother and the Klinik. |
| `en-third-party-confidence-01` | User reflects in a journal entry on a friend's HIV disclosure, named friend. |
| `de-sex-orientation-01` | User drafts a coming-out letter to their parents, names self + partner + parents. |
| `en-immigration-01` | User asks the agent to summarise their I-485 status and timeline, mentioning prior visas and an attorney name. |
| `de-substanz-rezept-01` | User asks for help interpreting their Ritalin prescription dosage, naming the prescribing Facharzt. |
| `de-profile-aggregation-01` | A single chat across 5 turns that accumulates: postcode, employer, child's school, weekly therapy time, partner name — designed to test §3.3 cumulative-profile detection. |

The 14th fixture (`de-profile-aggregation-01`) is structurally
different from the others — it's a *conversation*, not a single
text. It's deliberately listed because §3.3 cumulative-profile
leakage cannot be tested against single-turn fixtures. If the
fixture-builder format only supports single turns, this scenario
needs format extension (turn array) and is the trigger to do it.

---

## 5. Decisions (resolved 2026-05-17)

The seven open questions originally raised in this section. Five were
decided in conversation; two are deferred to dedicated issues so they
get the attention they need without blocking the fixture-corpus work
(apf-baw).

### 5.1 — Categorical handling [DECIDED: opaque]

Default tokenisation is **opaque** (`<SENSITIVE_1>`, `<SENSITIVE_2>` …),
not categorical. The supposed utility benefit of `<MEDICATION_1>` is
moot once chat-as-confidant is out of scope (§0): in assistant-agent
flows the LLM doesn't need to reason about the value semantically, it
just shuffles tokens. The cost is real: a categorical placeholder
cascade-leaks the actual value — an LLM that infers `<MEDICATION_1>`
is "an SSRI" from surrounding context has factually surfaced both
medication class and the matching diagnosis.

**Future hook**: operations that need category-level info (sort
appointments by importance, summarise types of items) get it
**out-of-band** via tool metadata, not embedded in the placeholder
itself. Tracked separately.

### 5.2 — Third-party PII [DECIDED: filter on user's behalf, mark as 3p]

Refusing to forward messages containing third-party identifiers would
break the assistant use case (every email mentions someone). The
filter treats third-party data as the user's for the purpose of
tokenisation, **with two clarifications**:

1. **Third-party identifiers are always opaque** (Tier-A with
   orthogonal `third_party=True` attribute on the Span), never
   categorical — `<PERSON_3p_1>` not `<COLLEAGUE_1>`.
2. **Honest framing in README/onboarding**: the filter minimises the
   leak to the LLM provider; it does *not* solve the consent problem
   inherent in processing other people's data. The user remains a
   de-facto data controller of third-party content they choose to
   process with AI.

`3p` becomes an orthogonal attribute, not a new tier.

### 5.3 — Controversial-but-legal categories [DECIDED: eager default + opt-out]

All sensitive categories from the taxonomy are filter-enabled by
default. Users opt **out** per category via `~/.config/apf/filter.toml`
(or env). Common opt-out patterns documented:

- "Public activist" — politics / religion off
- "Out and proud" — sexual orientation off
- "Open salary" — salary off

Privacy-by-default is the project premise; opt-in defaults would
require the user to have the threat-awareness the filter is meant
to relieve them of. A `log-only` per-category mode (detect, don't
filter) supports apf-00s evaluation work without burdening the user.

### 5.4 — Profile-aggregation warning [DECIDED: diversity-weighted, multi-stage; thresholds empirical]

Cumulative-profile warning fires on category **diversity**, not raw
span volume — Gesundheit + Sexuelles + Standort + Politik in one
session is qualitatively different from 100 calendar names.

| Stage | Trigger (initial estimates) | UX action |
|---|---|---|
| Notice | 3+ orthogonal sensitive categories | Statusline counter, silent |
| Warning | 5+ orthogonal categories, or 25 %+ Tier-A-sensitive spans | Inline annotation in next agent reply |
| Alarm | User-configured hard limit (default: 8 categories or 100 spans) | Tool-result annotation: "Session profile broad. /apf-reset to start fresh" |

Concrete thresholds are first estimates; final values pinned
empirically once apf-baw (private fixture corpus) and apf-00s
(over-filter eval) yield real distributions.

Corresponding user action: `/apf-reset` (or header / marker) flushes
the vault — same originals get new pseudonyms for the LLM provider,
profile assembly resets. Tracked under [[apf-80c]] / [[apf-qzc]] for
the actual UI work.

### 5.5 — Restore-on-screen / bystander mode [DECIDED: out of scope]

Bystander threats are user-side risk management (privacy filter foil,
room layout, attention). The proxy protects against network-side
leakage to the LLM provider, not against humans physically reading
the screen. Restore-on-screen stays unmasked. Documentation states
the limitation explicitly.

A best-effort metadata hook (proxy emits `apf-metadata` SSE event or
`X-APF-Restored` header carrying `[(start, end, category, tier)]` for
client-side blur-on-render) is **deferred** — added only when a real
client wants to consume it, not antizipativ.

### 5.6 — Local-only categories [OPEN — tracked separately]

Whether categories like asylum status (L6), domestic abuse (S10),
whistleblower intent (P8), undocumented-immigration status (L5) should
**never** leave the machine, regardless of tokenisation. Implies a
local-fallback model pathway and routing logic that the proxy
currently lacks. Deferred to its own design issue; needs concrete
scenario evaluation, not a quick decision.

### 5.7 — Audit log [OPEN — tracked separately]

Whether the filter keeps a local history of what categories were
detected/forwarded per session. Self-review value vs. attack-surface
trade-off; encryption + retention + UI all need design. Deferred to
its own issue.

### 5.8 — Endpoint trust map [OPEN — tracked separately]

Raised in conversation rather than in the original list: per-endpoint
filter policy (filter / categorical-only / off), so trusted endpoints
(local models, audited no-log providers, Apple Private Compute) can
be relaxed once they exist. v1 stays uniform-filter; v2 question
captured under [[apf-ycu]].

---

## References

- Regulation (EU) 2016/679, Art. 9(1) — "Processing of special
  categories of personal data". <https://gdpr-info.eu/art-9-gdpr/>
- Allgemeines Gleichbehandlungsgesetz (AGG), § 1 —
  Antidiskriminierungsstelle des Bundes guidance.
  <https://www.antidiskriminierungsstelle.de/DE/ueber-diskriminierung/recht-und-gesetz/allgemeines-gleichbehandlungsgesetz/allgemeines-gleichbehandlungsgesetz-node.html>
- US EEOC, Title VII / ADA / ADEA / GINA — protected categories,
  including the post-Bostock (2020) extension of "sex" to sexual
  orientation and gender identity.
  <https://www.eeoc.gov/publications/ada-your-employment-rights-individual-disability>
- BVerfG, Volkszählungsurteil, 15.12.1983 (BVerfGE 65, 1) —
  Recht auf informationelle Selbstbestimmung (constitutional
  anchor for §3.3 profile aggregation).
- Sweeney, L. (2002), "k-anonymity: a model for protecting privacy",
  IJUFKS 10(5) — quasi-identifier theory underlying §3.3.
- Carlini et al. (2021), "Extracting Training Data from Large
  Language Models", USENIX Security — empirical anchor for
  §1 actor 5 (future model memorisation).
