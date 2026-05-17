# Coverage audit — anchor frameworks vs. apf taxonomy

Untracked working document. Cross-checks the substance taxonomy in
`docs/THREAT-MODEL-PRIVATE.md` §2 (79 rows across 9 sections + 5 third-party
patterns) and the 11 entries in `docs/INDIVIDUAL-PRIVACY-FAILURES.md` against
six external frameworks. Goal: a checkable completeness statement —
*for each external framework category, is there a row that covers it, a row
that partly covers it, an explicit gap, or an out-of-scope exclusion?*

---

## §1 Intro and methodology

The §2 taxonomy was built bottom-up from realistic user content. The
construction risks *coverage drift* — categories that loom large in legal
or academic frameworks could be silently missing. This audit reverses the
direction: every category from each anchor framework is queried against
the existing rows.

**Frameworks audited.**

1. **GDPR Art. 9(1)** — Reg. (EU) 2016/679 Art. 9(1). <https://gdpr-info.eu/art-9-gdpr/>.
2. **AGG §1** — Allgemeines Gleichbehandlungsgesetz §1
   (Antidiskriminierungsstelle des Bundes).
3. **HIPAA — 18 PHI identifier types** — 45 CFR 164.514(b)(2).
   *US-specific overlay applicable when the user discusses US healthcare;
   not a primary spine.*
4. **Solove (2006)** — 154 U. Pa. L. Rev. 477. 16 subtypes in 4 groups.
5. **Lee et al. CHI 2024** — 12 AI privacy risk labels; one net-new
   vs. Solove (Phrenology/Physiognomy).
6. **OWASP LLM Top 10 (2025)** — LLM01–LLM10. Application-/developer-frame;
   for each, the audit checks whether a *user-side privacy angle* exists
   in the apf scope.

**Status legend.** **✓ covered** — explicit row(s) match. **~ partial** —
row exists but narrower than the framework's intent. **✗ gap** — no
matching row; candidate row addition if in scope. **n/a** — outside
apf's chosen scope (decisions in `THREAT-MODEL-PRIVATE.md` §0 / §5).

**Out of scope, for honesty.** Chat-as-confidant (§0); bystander /
shoulder-surfing (§0, §5.5); multimodal sidechannels (IPF-11); third-party
op-sec leaks (IPF-10); AI-system supply-chain (model poisoning, vector-store
integrity, prompt injection, system-prompt leakage — handled at
proxy/architecture, not content detection).

---

## §2 Mapping tables

### §2.1 GDPR Art. 9(1) — 8 special categories (all in scope)

| Framework category | Our taxonomy row(s) | Coverage status |
|---|---|---|
| Racial / ethnic origin | I1 (Ethnicity), I2 (National origin), I3 (Refugee / migration history) | ✓ covered |
| Political opinions | P2 (voting), P6 (controversial opinions), P7 (activism/protest) | ✓ covered |
| Religious / philosophical beliefs | P4 (Religion), P5 (Apostasy / belief change) | ✓ covered |
| Trade-union membership | — (no dedicated row; closest: P1 party affiliation / membership pattern) | ✗ gap |
| Genetic data | H12 (Genetic / hereditary), H13 (Family medical history) | ✓ covered |
| Biometric data (for unique identification) | B5 (voice / gait / typing) | ~ partial — B5 lists the patterns but the row's filter difficulty is `hard (not text-level usually)`; doc-side IPF-11 names this gap explicitly |
| Health data | All of §2.1 (H1–H15) | ✓ covered |
| Sex life / sexual orientation | S1 (orientation), S2 (gender identity), S5–S9 (dating / kinks / fertility / abortion) | ✓ covered |

### §2.2 AGG §1 — 6 protected categories

Anti-discrimination anchor for DE workplace + civil transactions.

| Framework category | Our taxonomy row(s) | Coverage status |
|---|---|---|
| Race / ethnic origin | I1, I2, I3 | ✓ covered |
| Sex | S2 (gender identity); implicit user-gender via S1/S3 etc. | ~ partial — gender-as-such (legal sex marker) is not a dedicated row; usually a side-effect of other rows |
| Religion / worldview | P4, P5 | ✓ covered |
| Disability | H14 (admin/legal: GdB / SSDI), I5 (non-medical framing) | ✓ covered |
| Age | — (no dedicated row; date-of-birth implicit in B1/B7-style identifiers but not flagged as a discrimination category) | ✗ gap |
| Sexual identity | S1, S2 | ✓ covered |

### §2.3 HIPAA — 18 PHI identifier types

US-specific overlay; applies when the user discusses US healthcare.
Several entries overlap with rows the taxonomy already has for
non-healthcare reasons.

| Framework category | Our taxonomy row(s) | Coverage status |
|---|---|---|
| Names | Tier A pre-existing (PERSON spans) + S3, R1, R5 | ✓ covered |
| Geographic subdivisions smaller than state (street, city, ZIP, etc.) | B1 (home), B2 (work), B4 (frequent locations) | ✓ covered |
| All elements of dates (except year) related to an individual | Tier A pre-existing (DATE spans); calendar regularity B8 | ✓ covered |
| Telephone numbers | Tier A pre-existing (PHONE) | ✓ covered |
| Fax numbers | Tier A PHONE regex (not separately enumerated) | ~ partial — harm-equivalent |
| Email addresses | Tier A EMAIL | ✓ covered |
| SSN (and DE: Steuer-ID, RV-Nummer) | Tier A regex; §3.4 lists DE equivalents | ~ partial — cross-cut only |
| Medical record numbers | — | ✗ gap |
| Health-plan beneficiary numbers (KV-Nr., MBI, etc.) | §3.4 mention only | ~ partial |
| Account numbers (IBAN, US bank #) | Tier A IBAN/account regex | ✓ covered |
| Certificate / license numbers | — | ✗ gap |
| Vehicle identifiers + license plate | — | ✗ gap |
| Device identifiers + serial numbers | B7 | ~ partial — category yes, MAC/serial/IMEI breadth no |
| URLs (uniquely identifying) | B7 | ~ partial |
| IP addresses | B7 | ✓ covered |
| Biometric identifiers | B5 | ~ partial — IPF-11 limitation |
| Full-face photos & comparable images | B5 catch-all | n/a (multimodal) |
| Any other unique identifying number / characteristic / code | Tier A | ~ partial — open-ended |

### §2.4 Solove (2006) — 16 subtypes

Mapped at the threat-pattern level. The §2 taxonomy is a *content*
catalogue; Solove subtypes describe *what happens to the content*. The
IPF document is where Solove subtypes get a first-class mapping. Audit
question: does the taxonomy include rows whose harm vectors invoke this
subtype?

| Framework category | Our taxonomy row(s) / IPF | Coverage status |
|---|---|---|
| Surveillance (Information Collection) | IPF-04 (cumulative provider profile), IPF-07 (power asymmetry); §2 rows that *enable* surveillance: all profile-able B-rows | ✓ covered |
| Interrogation (Information Collection) | — (assistant-agent doesn't interrogate the user; chat-as-confidant excluded) | n/a |
| Aggregation (Processing) | IPF-02, IPF-03, IPF-04, IPF-05, IPF-06, IPF-08, IPF-10; §3.3 (profile assembly) | ✓ covered |
| Identification (Processing) | IPF-02, IPF-05, IPF-06, IPF-11; B-rows | ✓ covered |
| Insecurity (Processing) | IPF-03, IPF-09, IPF-10; Tier C secrets (architecture) | ✓ covered |
| Secondary Use (Processing) | IPF-01, IPF-04, IPF-09 | ✓ covered |
| Exclusion (Processing) | IPF-07, IPF-08 | ✓ covered |
| Breach of Confidentiality (Dissemination) | IPF-03, IPF-10; R4 (friends' confidences), 3p3 | ✓ covered |
| Disclosure (Dissemination) | IPF-01, IPF-03, IPF-06, IPF-09, IPF-10 | ✓ covered |
| Exposure (Dissemination — bodily/embarrassing) | IPF-01; H4, H10 (psych unit), S9 (abortion) | ✓ covered |
| Increased Accessibility (Dissemination) | IPF-05, IPF-09, IPF-10 | ✓ covered |
| Blackmail (Dissemination) | — (not in apf threat model — user has no adversary "demanding" the data) | n/a |
| Appropriation (Dissemination — commercial use of likeness) | — | n/a |
| Distortion (Dissemination) | IPF-01, IPF-07, IPF-11 | ✓ covered |
| Intrusion (Invasion) | — (physical-space; §5.5 out of scope) | n/a |
| Decisional Interference (Invasion) | IPF-08 (lock-in chills privacy decisions) | ✓ covered |

Twelve of sixteen Solove subtypes mapped; four (Interrogation, Blackmail,
Appropriation, Intrusion) are explicit n/a with rationale in
`THREAT-MODEL-PRIVATE.md` §0 / §5.

### §2.5 Lee et al. (CHI 2024) — 12 AI privacy risk labels

Per `INDIVIDUAL-PRIVACY-FRAMEWORKS.md` and the IPF cross-walk.

| Lee 2024 label | Our taxonomy row(s) / IPF | Coverage status |
|---|---|---|
| Surveillance | IPF-04, IPF-07; B-rows | ✓ covered |
| Identification | IPF-02, IPF-05, IPF-06, IPF-11; B-rows | ✓ covered |
| Aggregation | IPF-02, IPF-03, IPF-04, IPF-05, IPF-06, IPF-08, IPF-10; §3.3 | ✓ covered |
| Phrenology / Physiognomy (Lee net-new) | IPF-11; B5 | ~ partial — named, scope-limited to text-only; IPF-11 acknowledges the gap |
| Secondary Use | IPF-01, IPF-04, IPF-09 | ✓ covered |
| Exclusion | IPF-07, IPF-08 | ✓ covered |
| Insecurity | IPF-03, IPF-09, IPF-10 | ✓ covered |
| Exposure | IPF-01; H4, H10, S9, S10 | ✓ covered |
| Distortion | IPF-01, IPF-07, IPF-11 | ✓ covered |
| Disclosure | IPF-01, IPF-03, IPF-06, IPF-09, IPF-10 | ✓ covered |
| Increased Accessibility | IPF-05, IPF-09, IPF-10 | ✓ covered |
| Intrusion | — (physical-space; §5.5 out of scope) | n/a |

Eleven of twelve Lee labels mapped; the one n/a (Intrusion) is the same
out-of-scope exclusion as Solove's.

### §2.6 OWASP Top 10 for LLM Applications (2025)

Most OWASP-LLM entries are not user-side privacy risks — they describe
attacker capabilities the *application owner* must defend against. For
each, the audit asks: *does this have a privacy angle in the apf scope,
and where is it addressed?*

| OWASP-LLM entry | Privacy angle in apf scope? | Addressed by | Status |
|---|---|---|---|
| LLM01 Prompt Injection | Indirect-injection in user content can exfiltrate vault | Proxy/architecture layer; Tier-C secret handling | n/a (architecture) |
| LLM02 Sensitive Information Disclosure | Yes — apf's core thesis | Entire §2; all IPFs; esp. IPF-01, IPF-06, IPF-09 | ✓ covered |
| LLM03 Supply Chain | Marginal — model provenance | §5.8 endpoint-trust map (deferred) | n/a (architecture) |
| LLM04 Data and Model Poisoning | None (we send, we don't train) | — | n/a |
| LLM05 Improper Output Handling | Restored output into tools (`grep <EMAIL_3>`) | Tier-B boundary resolution | n/a (architecture) |
| LLM06 Excessive Agency | Tool permissions affect vault exfil surface | Architecture | n/a (architecture) |
| LLM07 System Prompt Leakage | None (user isn't the system-prompt author) | — | n/a |
| LLM08 Vector and Embedding Weaknesses | Yes when session memory persists user data in an embedding store; relates to IPF-04 | IPF-04; §5.8 endpoint-trust map | ~ partial — IPF-level only |
| LLM09 Misinformation | None | — | n/a |
| LLM10 Unbounded Consumption | None (cost / DoS) | — | n/a |

LLM02 is the only entry directly mapped to detection content; LLM01,
LLM05, LLM06, LLM08 have privacy implications addressed at the
proxy/architecture layer. The remaining five are correctly not part of
the detection model.

---

## §3 Gap summary (✗)

Rows to add to `THREAT-MODEL-PRIVATE.md` §2.

1. **Trade-union membership** (GDPR Art. 9). Closest existing is P1
   (party affiliation), but unions are distinct, with DE workplace-law
   relevance (Betriebsrats-Schutz, IG-Metall, Verdi). **Proposal: row
   P9** in §2.3, tier `A+cat`, filter difficulty `medium`.
2. **Age / date-of-birth as discrimination signal** (AGG §1, US ADEA).
   DOB is detected as Tier-A but not flagged as protected. **Proposal:
   row I6** in §2.7, tier `A` with `+cat` flag in employment / insurance
   contexts.
3. **Medical record / health-plan beneficiary numbers** (HIPAA; DE:
   KV-Nummer, RV-Versichertennummer). §3.4 mentions surface forms but
   there is no substance row. **Proposal: row H16** in §2.1, tier `A`,
   `easy`.
4. **Certificate / professional-credential numbers** (HIPAA 11+12;
   Approbations-Nr., BAR-Nr., DEA #). **Proposal: row L9** in §2.4,
   tier `A`, `easy`.
5. **Vehicle identifiers** (HIPAA 12; Kennzeichen, VIN). **Proposal: row
   B9** in §2.8, tier `A`, `easy`.
6. **Device serial / MAC / IMEI** (HIPAA 13). B7 covers the category but
   not the breadth. **Proposal: widen B7 examples**; no new row.

The other ✗-side OWASP-LLM entries (LLM01, LLM03–LLM07, LLM09, LLM10) are
deliberately *not* in §2 — they belong in `ARCHITECTURE.md`. Scope
discipline, not row addition.

**Total proposed additions: 5 rows** (P9, I6, H16, L9, B9) + one B7
refinement. No structural changes to §2.

---

## §4 Partial-coverage summary (~)

Existing rows to tighten; no structural changes.

1. **B5 (biometric).** GDPR Art. 9 names "biometric data for unique
   identification". B5 currently lists examples but its filter difficulty
   is `hard (not text-level usually)`. Split the row's intent:
   (a) text-level mentions ("voice memo attached", "fingerprint scan
   failed three times") — in scope, tier `A`, difficulty `easy → medium`;
   (b) biometric features in non-text modalities — out-of-scope per
   IPF-11.
2. **AGG §1 "Sex".** S2 covers gender identity; the bare legal sex
   marker ("männlich / weiblich / divers", "F" / "M" / "X") is captured
   at Tier-A regex level along with other PA-Felder. No new row, just a
   one-line note in §2.2.
3. **HIPAA fax / phone.** Same PHONE regex covers both; harm-equivalent.
   Non-issue.
4. **HIPAA "any other unique identifying number / characteristic /
   code".** Open-ended catch-all; depends on a "looks-like-an-ID"
   heuristic in the detector. Detector-spec question, not taxonomy.
5. **Lee 2024 Phrenology / Physiognomy.** Scope-restricted to text-only
   per IPF-11. Honest limitation, not a row gap — document the limit in
   user-facing docs.
6. **OWASP LLM08 (Vector/Embedding Weaknesses).** Embedding-side
   reflection of IPF-04. Architecture-side issue, not a row.

---

## §5 IPF cross-check (reverse direction)

For each of the 11 IPFs, which external-framework categories does it span?
Reverse of §2 — "does IPF-01 span Solove's Secondary Use *and* GDPR Art. 9
*and* Lee's Distortion?".

| IPF | Solove | Lee 2024 | GDPR-9 / AGG | OWASP-LLM | HIPAA |
|---|---|---|---|---|---|
| IPF-01 Future-self damage | Secondary Use, Exposure, Distortion | Secondary Use, Disclosure, Distortion | All Art. 9 aged badly | LLM02 (indirect) | health context retained |
| IPF-02 Quasi-identifier triangulation | Identification, Aggregation | Identification, Aggregation | Indirect via profile | — | most types contribute |
| IPF-03 Third-party data | Breach of Confidentiality, Disclosure, Aggregation | Disclosure, Aggregation, Insecurity | All Art. 9 of third parties | — | all types when 3p is patient |
| IPF-04 Cumulative provider profile | Aggregation, Secondary Use | Aggregation, Surveillance | Cumulative Art. 9 | LLM08 | longitudinal |
| IPF-05 Cross-platform identity stitching | Identification, Aggregation, Increased Accessibility | Identification, Aggregation | Indirect | LLM05 | URLs, email, account # |
| IPF-06 Inferential disclosure | Disclosure, Aggregation | Disclosure, Identification, Phrenology limit | Health, sex, religion, politics | LLM02 (residual) | health most acute |
| IPF-07 Power-asymmetry harms | Surveillance, Aggregation, Exclusion | Surveillance, Exclusion, Distortion | Political, religion, race, sex orient. | LLM01 (state-actor) | targeted patient |
| IPF-08 Lock-in | Decisional Interference, Exclusion | Exclusion, Aggregation | All (chilling effect) | LLM08 | longitudinal |
| IPF-09 Training-data residuality | Disclosure, Increased Accessibility, Insecurity | Disclosure, Insecurity | All Art. 9 retained | LLM04 inverse, LLM02 | all types |
| IPF-10 Bystander / secondary leak | Breach of Confidentiality, Disclosure, Increased Accessibility | Disclosure, Insecurity | Indirect via third party | LLM01 (3p prompt-inj.) | patient relays |
| IPF-11 Phrenology / Physiognomy | Distortion, Identification | Phrenology, Distortion, Surveillance | Race, health, sex orient. by inference | LLM02 (silent) | biometric, photos |

**Observations.** IPF-09 and IPF-01 span *every* Art. 9 category —
category-agnostic harm amplifiers; no new rows needed but a §2 preface
note. IPF-03 and IPF-07 have the broadest external-framework spans and
are the IPFs whose mitigation is *least* served by detection alone
(§5.6 deferred for IPF-07; honest framing for IPF-03).

---

## §6 Recommended actions

No code changes; all action items are taxonomy / doc edits.

**P1 — substance-row additions to `THREAT-MODEL-PRIVATE.md` §2.**

1. **P9** in §2.3 — *Trade-union membership / Gewerkschaftszugehörigkeit*.
   Examples: "ver.di-Mitglied", "joined the union last quarter",
   "Betriebsrats-Wahl". Harm: workplace bias; GDPR Art. 9 anchor.
   Tier `A+cat`, filter difficulty `medium`.
2. **I6** in §2.7 — *Age / date-of-birth as protected category*. Examples
   with explicit numerical age in employment / insurance contexts. Tier
   `A`, `+cat` when frame is employment / insurance / medical rationing.
3. **H16** in §2.1 — *Healthcare administrative identifiers* (KV-Nr.,
   MBI, US MRN, beneficiary IDs). Promotes §3.4 cross-cutting note to a
   first-class row. Tier `A`, `easy`.
4. **L9** in §2.4 — *Professional licence / credential identifiers*
   (Approbations-Nr., BAR-Nr., DEA #). Tier `A`, `easy`.
5. **B9** in §2.8 — *Vehicle identifiers* (Kennzeichen, VIN). Tier `A`,
   `easy`.

**P2 — refinements to existing rows.**

6. **B5** — split intent: text-level mention (in scope, Tier `A`) vs.
   biometric features in non-text modalities (out-of-scope per IPF-11).
   Copy change only.
7. **B7** — widen examples to MAC, IMEI, device / USB / Bluetooth serial.
8. **§2.2 note** — bare legal sex marker ("männlich / weiblich / divers",
   "F" / "M" / "X") is captured at Tier-A regex level along with other PA
   fields; AGG §1 "Sex" covered without new row.

**P3 — documentation only.**

9. Add a preface to `THREAT-MODEL-PRIVATE.md` §2 naming IPF-01 and IPF-09
   as *category-agnostic temporal amplifiers* — every row's harm vector
   compounds under retention. Avoids repeating the caveat per row.
10. Consolidate "Out of scope, intentionally" in one README /
    `ARCHITECTURE.md` section: OWASP LLM01, LLM03–LLM07, LLM09–LLM10
    (architecture-side); multimodal (IPF-11); bystander (§5.5);
    chat-as-confidant (§0). Currently spread across §0, §5, IPFs.
11. Name HIPAA in §3.5 (Legal anchors) as a US-specific overlay alongside
    GDPR-9 / AGG / Title VII; currently absent.

**P4 — no action.** Solove Interrogation / Blackmail / Appropriation /
Intrusion; Lee Intrusion; OWASP LLM03 / LLM04 / LLM07 / LLM09 / LLM10 —
all correctly excluded.

---

## §7 Honest assessment

The taxonomy is **mostly aligned with the external frameworks, with a
small number of well-defined refinements**. Five row additions (P9, I6,
H16, L9, B9) plus two row clarifications (B5, B7) close every ✗ found.
None are structural — the nine §2 sections accommodate the additions
cleanly. The four Solove subtypes and one Lee label currently unaddressed
are *correctly* out of scope per the already-decided §0 / §5 boundaries
(chat-as-confidant, bystander, multimodal, AI-system supply chain).

The biggest intellectual gap surfaced by the audit is at the OWASP-LLM
layer: only LLM02 lands in content detection; the remaining nine are
architecture-side or explicitly out of scope. This isn't a coverage
failure but a *frame boundary*; it deserves to be stated visibly so a
reader looking for "is OWASP covered?" gets a clean answer instead of
having to infer it from absence. Action item 10 proposes the fix.

---

## References

- Regulation (EU) 2016/679 (GDPR), Art. 9(1). <https://gdpr-info.eu/art-9-gdpr/>
- Allgemeines Gleichbehandlungsgesetz (AGG), § 1. Antidiskriminierungsstelle
  des Bundes.
- 45 CFR § 164.514(b)(2) — HIPAA Privacy Rule, 18 identifier types
  ("Safe Harbor" method).
- Solove, D. J. (2006). *A Taxonomy of Privacy.* 154 U. Pa. L. Rev. 477.
- Lee, H. P., Yang, Y. J., Von Davier, T. S., Forlizzi, J., & Das, S.
  (2024). *Deepfakes, Phrenology, Surveillance, and More! A Taxonomy of
  AI Privacy Risks.* CHI '24.
- OWASP. (2025). *Top 10 for LLM Applications.*
  <https://genai.owasp.org/llm-top-10/>
- Nissenbaum, H. (2010). *Privacy in Context.* Stanford UP.
- Sweeney, L. (2002). *k-anonymity.* IJUFKS 10(5).
- Carlini, N. et al. (2021). *Extracting Training Data from Large
  Language Models.* USENIX Security 2021.
