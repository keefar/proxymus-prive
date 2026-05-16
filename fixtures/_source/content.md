# Content fixtures — Tier A PII

Source for `fixtures/content.jsonl`. Run `python tools/build_fixtures.py` to regenerate.
All data synthetic; see `docs/MODELS.md` § "Synthetic-data rules".

Inline marker: `⟦LABEL|text⟧` — see `tools/build_fixtures.py` for the label inventory.

---

## id: de-mail-01 lang=de bucket=content notes="basic colleague mail"

Hallo ⟦PERSON|Anna⟧, schick mir bitte das Protokoll der Lenkungsausschuss-Sitzung an ⟦EMAIL|thomas.weber@example.de⟧ bis ⟦DATE|Freitag⟧. Danke!

Gruß, ⟦PERSON|Thomas⟧

## id: de-mail-02 lang=de bucket=content notes="health context in workplace mail"

Lieber ⟦PERSON|Sebastian⟧,

ich bin nächste Woche von ⟦DATE|Montag⟧ bis ⟦DATE|Mittwoch⟧ wegen eines ⟦APPOINTMENT_HEALTH|Termins bei Dr. Bauer in der Kardiologie⟧ nicht im Büro. Bei dringenden Themen erreichst du mich auf dem Handy (⟦PHONE|+49 30 9900 4471⟧).

Viele Grüße
⟦PERSON|Aylin Demir⟧

## id: de-mail-03 lang=de bucket=content notes="multi-recipient + address"

Hallo zusammen,

zur Erinnerung: Workshop bei ⟦ORG|Nordlicht GmbH⟧, ⟦ADDRESS|Marienstraße 14, 10117 Berlin⟧, am ⟦DATE|14. Juni⟧ um 09:30. Bitte direkt an ⟦PERSON|Maria Engel⟧ wenden falls ihr Allergien für das Catering durchgeben wollt.

Gruß, ⟦PERSON|Julian⟧

## id: de-mail-04 lang=de bucket=content notes="financial detail in invoice mail"

Sehr geehrte Damen und Herren,

anbei die Rechnung Nr. 2026-0117 über ⟦FINANCIAL|3.480,00 EUR netto⟧. Bitte überweisen Sie auf ⟦FINANCIAL|IBAN DE89 3704 0044 0532 0130 00⟧, Verwendungszweck "Beratung Q1". Bei Rückfragen ⟦PHONE|+49 30 9900 1108⟧.

Mit freundlichen Grüßen
⟦PERSON|Beatrice Pfeiffer⟧
⟦ORG|KMU Beratungshaus⟧

## id: en-mail-01 lang=en bucket=content notes="basic colleague mail"

Hi ⟦PERSON|Sarah⟧, can you forward the Q2 review deck to ⟦EMAIL|d.reyes@example.com⟧ by ⟦DATE|Thursday EOD⟧? I'm out tomorrow.

Thanks, ⟦PERSON|James⟧

## id: en-mail-02 lang=en bucket=content notes="health excuse + phone"

Hi team,

I'll be offline ⟦DATE|Tuesday morning⟧ for an ⟦APPOINTMENT_HEALTH|MRI follow-up at Dr. Vance's clinic⟧. Back online by lunch. Mobile is ⟦PHONE|+1-555-0179⟧ if it's urgent.

— ⟦PERSON|Alice Carter⟧

## id: en-mail-03 lang=en bucket=content notes="address + dates + colleagues"

Hi all,

The off-site is confirmed: ⟦ORG|Stellaris Inc.⟧, ⟦ADDRESS|2200 Foothill Drive, Suite 410, Boulder, CO 80302⟧, ⟦DATE|June 18-20⟧. Hotel block under ⟦PERSON|Olivia Chen⟧'s name. Flights to ⟦LOCATION|Denver⟧ ideally before 6pm local.

Cheers, ⟦PERSON|Bob⟧

## id: en-mail-04 lang=en bucket=content notes="implicit identifier via project + role"

Hi ⟦PERSON|Emily⟧,

The new lead engineer on the migration project — the one who joined from ⟦ORG|Brightline Labs⟧ last quarter ⟦IMPLICIT_PII|, the woman with the toddler in daycare on Pine St⟧ — would be great to include in Friday's review. Could you forward her the agenda?

— ⟦PERSON|Daniel⟧

---

## id: de-cal-01 lang=de bucket=content notes="doctor appointment"

⟦DATE|Mittwoch 14:30⟧ — ⟦APPOINTMENT_HEALTH|Dr. Bauer Kardiologie, Belastungs-EKG⟧, ⟦ADDRESS|Lessingstraße 8, 10555 Berlin⟧.

## id: de-cal-02 lang=de bucket=content notes="personal-life calendar"

⟦DATE|Sa 17:00⟧ ⟦PERSON|Mama⟧s ⟦APPOINTMENT|Geburtstag⟧ bei ⟦RELATIONSHIP|Tante Petra⟧, mitbringen: Wein + Karte. ⟦LOCATION|Bergstraße⟧.

## id: de-cal-03 lang=de bucket=content notes="recurring health appointment"

⟦APPOINTMENT_HEALTH|Physiotherapie wegen Bandscheibenvorfall L4/L5⟧ — jeden ⟦DATE|Donnerstag 08:00⟧, Praxis ⟦PERSON|Reinhard⟧, ⟦ADDRESS|Hauptplatz 3⟧. 8 Sitzungen, läuft bis ⟦DATE|Ende Juli⟧.

## id: en-cal-01 lang=en bucket=content notes="doctor + medication note"

⟦DATE|Fri 09:15⟧ ⟦APPOINTMENT_HEALTH|Dr. Vance — review Levothyroxin dosage⟧, fasting since midnight. Reschedule gym.

## id: en-cal-02 lang=en bucket=content notes="personal + relationship"

⟦DATE|Sat 19:30⟧ dinner with ⟦RELATIONSHIP|my sister-in-law⟧ and ⟦PERSON|Yuki⟧ at ⟦LOCATION|the place on Mission St.⟧ — bring the photo album.

---

## id: de-note-01 lang=de bucket=content notes="health diary entry"

⟦DATE|12. Mai⟧: Migräne wieder schlimm, mit ⟦HEALTH|Sumatriptan 50mg⟧ unter Kontrolle gekriegt. ⟦HEALTH|Dr. Schmitt⟧ meinte, wenn's diesen Monat nochmal vorkommt, soll ich's bei ihm melden. Schlafqualität laut Tracker mies (4h Tiefschlaf).

## id: de-note-02 lang=de bucket=content notes="financial worry"

⟦FINANCIAL|Kreditrate bei der Sparkasse läuft jetzt seit 14 Monaten⟧, noch ⟦FINANCIAL|22.300 EUR offen⟧. Wenn der Bonus bei ⟦ORG|Stahlwerk Süd⟧ wirklich kommt, könnte ich's ⟦DATE|im November⟧ ablösen. ⟦PERSON|Petra⟧ noch nicht eingeweiht.

## id: de-note-03 lang=de bucket=content notes="relationship-heavy note"

Gespräch mit ⟦RELATIONSHIP|M.⟧ war angespannt. ⟦RELATIONSHIP|Mein Vater⟧ macht weiter Druck wegen der ⟦APPOINTMENT|Hochzeit im September⟧. ⟦PERSON|Lukas⟧ schlägt vor, einfach hinzufahren, ⟦LOCATION|Wien⟧, und Schluss. Vielleicht hat er recht.

## id: de-note-04 lang=de bucket=content notes="diagnosis + treatment"

Befund ⟦DATE|von gestern⟧: ⟦HEALTH|Schilddrüsenüberfunktion, TSH < 0.01⟧. ⟦HEALTH|Dr. Bauer⟧ überweist an ⟦ORG|Endokrinologie Charité⟧. ⟦APPOINTMENT_HEALTH|Erstgespräch in 3 Wochen⟧, bis dahin ⟦HEALTH|Carbimazol 10mg morgens⟧.

## id: de-note-05 lang=de bucket=content notes="mixed personal log"

Habe ⟦PERSON|Mehmet⟧ nach den Unterlagen für die ⟦APPOINTMENT|Steuererklärung⟧ gefragt — kommt ⟦DATE|nächste Woche⟧. Außerdem: ⟦RELATIONSHIP|Nachbar⟧ aus ⟦ADDRESS|Wohnung 3B⟧ hat sich beschwert wegen Klavier nach 22:00. Mit ⟦PERSON|Beatrice⟧ besprochen, ab jetzt früher.

## id: en-note-01 lang=en bucket=content notes="medical log"

⟦DATE|May 10⟧: started ⟦HEALTH|CPAP for the sleep apnea⟧, ⟦HEALTH|pressure 9 cmH2O⟧. First night was rough — mask leaks. ⟦HEALTH|Dr. Vance's⟧ nurse said give it two weeks. Notes for follow-up ⟦DATE|on the 24th⟧.

## id: en-note-02 lang=en bucket=content notes="financial detail"

Mortgage refinance offer from ⟦ORG|Foothill Partners⟧ — ⟦FINANCIAL|5.85% on the remaining $312k⟧, 25-year. Worth running against current 6.4%. Need to pull statements from ⟦PERSON|Olivia⟧'s file by ⟦DATE|end of month⟧.

## id: en-note-03 lang=en bucket=content notes="relationship + implicit"

⟦RELATIONSHIP|Ex⟧ texted about pickup logistics for ⟦RELATIONSHIP|the kids⟧ ⟦DATE|next weekend⟧. Need to be at the airport early — ⟦LOCATION|SFO⟧ Terminal 2, ⟦DATE|Saturday 6am⟧. ⟦PERSON|Sarah⟧ said she can take ⟦RELATIONSHIP|Ben⟧ to soccer if it slips.

---

## id: de-prose-01 lang=de bucket=content notes="implicit PII via role + context"

Der ⟦IMPLICIT_PII|Kollege aus dem Controlling, der nächste Woche heiratet⟧, hat mich gefragt ob ich beim Umzug helfe. Ich glaub er zieht ⟦LOCATION|nach Potsdam⟧, irgendwo Richtung Babelsberg. ⟦PERSON|Sebastian⟧ kommt auch.

## id: de-prose-02 lang=de bucket=content notes="paraphrased identity"

⟦IMPLICIT_PII|Die einzige Mitarbeiterin im Team mit zwei Kindern und einer Diabetes-Diagnose⟧ braucht für die ⟦APPOINTMENT|Konferenz im Oktober⟧ ein eigenes Zimmer. Ist mit ⟦PERSON|Maria⟧ aus HR geklärt.

## id: de-prose-03 lang=de bucket=content notes="adversarial — implicit location"

Treffpunkt war ⟦IMPLICIT_PII|das Café gegenüber von Lukas' alter Schule, wo wir uns zur Abi-Vorbereitung getroffen haben⟧. ⟦PERSON|Jonas⟧ kam zu spät, wie immer.

## id: de-prose-04 lang=de bucket=content notes="adversarial — sensitive without keywords"

⟦IMPLICIT_PII|Das was mir damals Anfang März passiert ist⟧ — ich hab's nie ⟦RELATIONSHIP|den Eltern⟧ erzählt. Manchmal denk ich, ich sollte mal mit ⟦HEALTH|jemandem reden, professionell⟧. ⟦PERSON|Pia⟧ hat eine Therapeutin empfohlen.

## id: en-prose-01 lang=en bucket=content notes="implicit identifier"

The ⟦IMPLICIT_PII|guy who ran the all-hands last week — the one who used to work at Brightline⟧ — is now leading the new privacy initiative. ⟦PERSON|James⟧ says he's solid. Need to set up a 1:1 ⟦DATE|next week⟧.

## id: en-prose-02 lang=en bucket=content notes="adversarial — narrative health"

⟦IMPLICIT_PII|Got the call from the lab on Tuesday⟧. Not what I was hoping for but ⟦HEALTH|the oncologist⟧ said early enough that the prognosis is good. Started ⟦HEALTH|treatment this week⟧. Only told ⟦RELATIONSHIP|Mom⟧ and ⟦PERSON|Alice⟧ so far.

## id: en-prose-03 lang=en bucket=content notes="adversarial — implicit org"

⟦IMPLICIT_PII|The startup I joined right after grad school, the one acquired by the search giant in 2018⟧ — they're paying out the final earnout this quarter. Talking to ⟦PERSON|Bob⟧ about reinvesting it.

---

## id: de-adv-01 lang=de bucket=content notes="adversarial — name-shaped non-name"

Die ⟦ORG|Müller AG⟧ ist nicht zu verwechseln mit der ⟦PERSON|Anna Müller⟧ aus dem Vertrieb. Standort der AG ist ⟦LOCATION|Frankfurt⟧, Anna sitzt in ⟦LOCATION|Hannover⟧.

## id: en-adv-01 lang=en bucket=content notes="adversarial — distractor numbers"

Order #4471 shipped from warehouse 8 at 14:00 PT. The customer's phone is ⟦PHONE|+1-555-0142⟧, ref number is 2026-Q2-0883. ETA is ⟦DATE|Friday⟧.
