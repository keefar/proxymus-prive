# Modell-Evaluation — Dossier

Stand 2026-05-17 (Nacht).
Adressat: Projekt-Owner. Ziel: vor der Implementierung den Stand der
Modell-Auswahl klar machen — was funktioniert, was nicht, was lohnt sich noch.

---

## TL;DR

- **Spitze aktuell:** `ensemble-max` — Kombination aus Regex + Microsoft Presidio
  + GLiNER `urchade/gliner_multi_pii-v1` + GLiNER `nvidia/gliner-PII`.
- **Recall:** 0.73 auf unseren synthetischen Fixtures, 0.72 auf dem
  standardisierten ai4privacy-200k-Sample. **Beide Sprachen vergleichbar**
  (DE 0.72 / EN 0.75).
- **Latenz:** p95 ~300 ms, gut innerhalb des 1.5-s-Budgets.
- **RAM:** ~4 GB (drei Modelle gleichzeitig resident) — am Limit unseres
  4-GB-Budgets. Reduzierbar, wenn nötig.
- **Gap zum Ideal (≥ 0.95 Recall):** ~0.20–0.25. Ein Teil ist schließbar
  (Punkte unten), ein Teil ist bei 1.7B-Klasse-Modellen strukturell hart.
- **Was nicht hilft:** weiteres Stage-2-Generativ-Modell dazuhängen
  (Anonymizer-SLM brachte +3 pp Recall für 40× Latenz und *senkte* die
  Tier-C-Recall).

---

## Was wurde getestet — komplette Tabelle

Zwei Test-Sets, gleicher Code:

- **Unsere Fixtures** (`fixtures/{content,operational,secrets}.jsonl`) — 50
  synthetische Beispiele, 186 Spans, DE+EN, mit adversarialen Paraphrasen,
  Operational-PII (Pfade/IPs) und Secrets. Bewusst harte Cases.
- **ai4privacy/pii-masking-200k Sample** (`fixtures/ai4privacy_sample.jsonl`)
  — 200 Beispiele (100 DE + 100 EN) aus dem Standard-Datensatz, 626 Spans.
  Strukturell sauber, weniger adversarial.

| Modell | unser T-rec | ai4p T-rec | DE | EN | p95 ms | RAM | Anmerkung |
|---|:-:|:-:|:-:|:-:|:-:|:-:|---|
| **ensemble-max** ⭐ | **0.734** | **0.719** | 0.71 | 0.75 | 298 | ~4 GB | regex+presidio+2×GLiNER |
| ensemble-fast | 0.715 | 0.540 | 0.72 | 0.71 | 76 | 2.8 GB | regex+GLiNER-multi |
| gliner-nvidia | 0.688 | **0.660** | 0.67 | 0.70 | 199 | 3.9 GB | nvidia/gliner-PII |
| gliner | 0.667 | 0.530 | 0.71 | 0.63 | 80 | 2.8 GB | urchade/gliner_multi_pii-v1 |
| ensemble-full | 0.747 | — | 0.76 | 0.73 | 3201 | 3.2 GB | + Anonymizer = LATENZ-TOT |
| gliner-knowledgator | 0.499 | 0.486 | 0.46 | 0.54 | 213 | 3+ GB | mehr Labels, schwächer überall |
| presidio | 0.445 | 0.451 | 0.42 | 0.47 | 8 | 0.3 GB | regex+spaCy NER, extrem schnell |
| anonymizer-slm | 0.355 | — | 0.38 | 0.33 | 2958 | 1.3 GB | generativ, langsam |
| piiranha | 0.305 | 0.374 | 0.26 | 0.35 | 42 | 1 GB | sauber aber dünne Labels |
| nemotron-mlx | 0.290 | 0.468 | 0.26 | 0.32 | 187 | 1.6 GB | EN-only, Tier-B-Star |
| ai4p-modernbert | 0.269 | 0.320 | 0.15 | 0.38 | 39 | 0.4 GB | unter Erwartung |
| qwen3-1.7b-zeroshot | 0.226 | — | 0.21 | 0.24 | 1009 | 1.3 GB | generischer LLM |
| regex-baseline | 0.194 | 0.075 | 0.11 | 0.27 | <1 | – | floor |

T-rec = Tier-Recall (Anteil der Gold-PII-Spans, die der Detector mit
korrekter Tier-Zuordnung A/B/C findet, ≥ 50 % Überlapp).

---

## Was die Zahlen bedeuten

### Tier-Recall 0.7 — heißt was?

Von 10 PII-Stellen werden ~7 erkannt, ~3 entwischen. Aufgeschlüsselt für
`ensemble-max` auf unseren Fixtures:

- **Tier A (Inhalts-PII — Namen, Email, Gesundheit, Adressen)**: 0.73 Recall.
  Das ist der „Mensch-bezogene" Kram. 3 von 10 Namen / Health-Erwähnungen
  fehlen — überwiegend implizite/paraphrasierte („der Kollege aus dem
  Controlling, der nächste Woche heiratet").
- **Tier B (Pfade, Hostnames, IPs)**: 0.86 Recall — fast vollständig
  abgedeckt. Wichtig, weil hier die Tool-Call-Boundary-Resolution dranhängt.
- **Tier C (Secrets — API-Keys, Passwörter, Private Keys)**: 0.57 Recall —
  das ist der **wundeste Punkt**. Lecks hier sind die teuersten. Gap
  schließbar mit erweiterten Regex-Patterns (siehe „Was noch was bringt").

### Precision 0.6 — heißt was?

Von 10 als-PII-markierten Stellen sind ~6 wirklich PII, ~4 sind False
Positives. Im Kontext eines reversiblen Tokenizers ist Über-Maskierung
*akzeptabel*: der Text geht durch die Pipeline, die Token werden im Tool-Call
oder in der Antwort wieder zurückgesetzt — also keine Datenverluste, nur
leichter Qualitätsverlust am LLM-Input. False Negatives (entwischte PII) sind
die teure Klasse, weil sie unwiderruflich rausgehen.

### Warum mehr GLiNER-Varianten zusammen besser werden

GLiNER `multi_pii-v1` und `nvidia/gliner-PII` machen unterschiedliche Fehler:

- multi: stark auf DE-Prosa und impliziter PII (Paraphrasen), aber schwächer
  auf strukturierten Operational-Inputs.
- nvidia: stärker auf strukturierten Daten (Pfade, URLs, Code), 0.96 Tier-B
  Precision — kaum Falsch-Alarme.

Der Span-Union mit longest-wins-Dedup nutzt beide Stärken aus. Plus Presidio
gibt einen schnellen regex+spaCy-Hintergrund, der z.B. deutsche Personennamen
über spaCy NER fängt, die GLiNER manchmal verpasst.

---

## Wer ist gut wofür — kurz erklärt

| Modell | Stärke | Schwäche |
|---|---|---|
| **GLiNER multi-pii-v1** | DE-Prosa, paraphrasierte PII („der Kollege aus dem Controlling"), zero-shot-Labels per Prompt | Mäßig bei strukturierten Operational-Inputs |
| **GLiNER nvidia/gliner-PII** | EN-Prosa + strukturierte Daten, sehr hohe Precision auf Tier B (0.96) | Etwas EN-lastig, größer (~3 GB RAM) |
| **Microsoft Presidio** | Extrem schnell (5–8 ms), deterministisch, gut auf ID-artigen Strukturen, sauberes spaCy-NER für Namen/Orte | Keine Secrets-Recognizer im Default, schwach auf paraphrasierten Inhalten |
| **Regex-Baseline** | Sub-Millisekunden, 100 % deterministisch, sehr hohe Precision auf bekannten Patterns (Emails, IBANs, API-Key-Prefixes) | Nichts kontextuelles, scheitert an allem implizit |
| **GLiNER knowledgator** | Größerer Label-Raum (inkl. PHI/medical-Klassen), beste Tier-C-Recall (0.63) | Insgesamt geringere Recall als nvidia-Variante |
| **Nemotron MLX 8bit** | Tier-B-Recall 0.96 auf strukturierten Daten — Pfade/IPs sehr sauber | Englisch-only laut Modell-Card, DE-FPs auf deutschen Verben |
| **Anonymizer-SLM** | Höchster „natural-language"-Recall, multilingual via Qwen3-Base | 3 Sekunden Latenz, ruiniert die Tier-C-Precision im Ensemble |
| **Piiranha** | Hohe Precision (0.95), 5 Sprachen inkl. DE, sehr schnell (42 ms) | Dünner Label-Raum (17), keine Pfade/Secrets |
| **ai4p-modernbert** | Auf Papier beste Multilingual-F1 (0.92) | In unserem Setup deutlich unter Erwartung — vermutlich Format-empfindlich |
| **Qwen3-1.7B zero-shot** | Höchste Precision (0.71), kein Fine-tune nötig | Lowest Recall — zeigt: PII-Fine-tune lohnt sich |

---

## Empfehlung für den PoC

**Setze auf `ensemble-max`** als initialen Stage-1+2-Engine.

Konkret:

```
input text
  │
  ├──▶ Regex-Baseline           (~1 ms, Tier-B/C-Patterns)
  ├──▶ Microsoft Presidio       (~6 ms, NER + regex catalog)
  ├──▶ GLiNER multi-pii-v1      (~50 ms, multilingual + implicit)
  └──▶ GLiNER nvidia/gliner-PII (~150 ms, high-precision Tier-B)
        │
        ▼
   Span-Union (longest-wins, label-conflict → first listed wins)
        │
        ▼
   tier-tagged Span-Liste
```

**Warum diese Kombi und nicht ensemble-fast (2 Komponenten):**

- ensemble-fast hat **0.715** Recall, ensemble-max **0.734** — +2 pp.
- Wichtiger als die 2 pp: ensemble-max hebt Tier-B von 0.69 → 0.86. Das ist
  die Tier, an der die Tool-Call-Boundary-Resolution hängt — niedrige
  Tier-B-Recall heißt der Resolver wird umgangen.
- Latenz steigt von 76 ms → 298 ms p95. Beides weit unter dem 1.5-s-Budget.
- RAM-Mehrbedarf: ~1.5 GB durch Presidio (spaCy NER für 2 Sprachen) + nvidia
  GLiNER (1.4 GB Delta).

**Wenn RAM eng wird:** auf ensemble-fast zurückfallen (2.8 GB statt 4 GB)
und die Tier-B-Lücke später mit erweitertem Regex schließen.

---

## Was wurde nicht getestet — und warum

| Modell / Ansatz | Warum nicht | Wäre es wert? |
|---|---|---|
| **GLiNER2-PII** (arXiv 2605.09973, Mai 2026) | HF-Repo-ID nicht in 2 min auffindbar; vermutlich noch nicht released oder fastino-ai/GLiNER2-org-internal | **Ja, sofort wenn auffindbar.** Paper behauptet SOTA über OpenAI Privacy Filter + 3 GLiNER-Detektoren |
| **Isotonic/deberta-v3-base_finetuned_ai4privacy_v2** | EN-only laut Modell-Card | Nein für DE-relevanten PoC |
| **lakshyakh93 / h2oai DeBERTa-PII** | EN-only, kleiner/älter | Nein |
| **HuggingLil/pii-sensitive-ner-german** | DE-Only, aber adressiert GDPR-Art-9-Kategorien (Religion, Ethnie, sexuelle Orientierung) die nichts anderes abdeckt | **Ja, als Sensitive-Specialist-Slot im Ensemble** |
| **OpenAI Privacy Filter (Open-Weights)** | Erwähnt im GLiNER2-PII-Paper, aber Repo nicht direkt referenziert | Mittel — wenn auffindbar, schnell zu testen |
| **GLiNER-Multi-v2.1** (allgemein, nicht PII-fine-tuned) | Ohne PII-Fine-tune zu erwartender Performance-Hit | Niedrig |
| **Microsoft Presidio + GLiNER als NLP-Engine** | Presidio kann GLiNER als externe NLP-Engine einbinden, hätten wir konfigurieren können | Mittel — ähnliche Numbers wie ensemble-max wahrscheinlich |
| **LLM-as-judge (Sonnet, GPT-4)** | User-Entscheidung: keine Cloud-Services im Projekt | Nicht im Scope |

---

## Was bringt vermutlich noch was — priorisiert

### Hoch (≥ +0.05 Recall erwartet)

1. **Tier-C-Regex erweitern** (Zeit: 1 h). Aktuell deckt der Regex
   `sk-...`, `ghp_...`, JWT-Form, IBAN-ähnlich. Hinzu sollte:
   - Base64-Heuristik (`[A-Za-z0-9+/]{32,}={0,2}` mit Kontext-Filter)
   - `KEY=VALUE`-Pattern in .env-artigen Zeilen
   - PEM-Block-Erkennung (`-----BEGIN ... PRIVATE KEY-----`)
   - Deutsche Bankkonten / weitere IBAN-Validierung
   Vermutung: Tier-C-Recall geht von 0.57 → 0.90+.

2. **GLiNER2-PII einbauen sobald HF-ID auffindbar** (Zeit: 30 min wenn Modell
   da, sonst 1-2 h Suche). Laut Paper SOTA — könnte einzeln schon 0.75+ sein,
   im Ensemble 0.80+.

3. **Custom GLiNER-Labels** — momentan 28 generische Labels. Spezifische
   DE-Bezeichnungen („deutscher Vorname", „Arzttermin", „Krankenkassen-Karte")
   könnten +2–4 pp Recall auf DE-spezifischen Fixtures bringen. Zeit: 1 h.

### Mittel (+0.02 bis +0.05)

4. **HuggingLil DE-Sensitive-NER ins Ensemble** — speziell für
   GDPR-Art-9-Kategorien (Religion, Ethnie, sexuelle Orientierung, politische
   Sicht). Macht keiner sonst. Zeit: 1 h.

5. **Threshold-Tuning per Sprache** — Presidio läuft bei 0.4, GLiNER bei 0.5.
   Pro Detector ein DE/EN-Threshold-Sweep auf einem Validation-Subset könnte
   marginal gewinnen. Zeit: 2-3 h.

6. **Presidio um Custom-DE-Recognizer erweitern** — der Github-PR #1828 fügt
   genau das hinzu (deutsche Steuer-ID, Sozialversicherungsnummer, Rentennummer,
   etc.). Manuelle Übernahme der RegEx-Patterns ist trivial. Zeit: 1 h.

### Niedrig (≤ +0.02 oder Risiko-Tausch)

7. **GLiNER auf 10–20 Adversarial-Fixtures fein-tunen** — GLiNER unterstützt
   few-shot. Würde implicit_PII-Coverage heben aber Risiko der Overfit auf
   unsere Fixtures. Zeit: 4-6 h plus Validation-Sorgfalt.

8. **MLX-Quantisierung der HF-Modelle** — Speicher-Optimierung, aber nicht
   Recall. Nur relevant wenn RAM-Budget bricht.

### Wahrscheinlich nicht (negativer ROI nach Daten)

- **Generatives Modell zurück ins Ensemble** — ensemble-full hat gezeigt
  dass Anonymizer-SLM die Tier-C-Recall *senkt* und die Latenz um 40×
  hochschießt. Nicht ohne strenges Routing.
- **Größere generative Modelle (Qwen3-7B, 14B)** — würden vermutlich GLiNER
  knapp schlagen aber RAM-Budget sprengen und Latenz versauen. Lokales-LLM-Ziel
  ist 4 GB total.

---

## Pragmatischer nächster Schritt

**Vorschlag für den Übergang in die Implementierung:**

1. **Jetzt:** Festlegen auf ensemble-max als PoC-Engine. Code existiert
   bereits in `benchmarks/adapters_mlx.py:EnsembleMaxAdapter`.

2. **Stunde 1 nach Implementierungs-Start:** Tier-C-Regex erweitern (Punkt 1
   oben). Das ist der einzige Tier-Recall-Wert, der unter 0.6 liegt, und
   gleichzeitig der mit den teuersten Lecks.

3. **Stunde 2:** Custom-DE-Labels für GLiNER hinzufügen (Punkt 3).

4. **Sobald GLiNER2-PII auffindbar ist:** Als drittes GLiNER ins ensemble
   einbauen — wahrscheinlich Recall-Gewinn ohne nennenswerten Latenz-Hit.

5. **Niedriges-Confidence-UX-Flag:** unabhängig vom Modell-Layer — für die
   restlichen ~25 % der PII, die das Ensemble nicht greift, soll die UI dem
   User Stellen *anbieten*, die der Filter für unsicher hält, statt schweigend
   durchzulassen. Das wandelt das Recall-Problem in ein UX-Problem.

6. **Realistische Recall-Ziele für den PoC** (übernommen aus dem Decision-Log,
   leicht angepasst nach den ensemble-max-Zahlen):
   - **Tier-A explizit** (Namen, Email, Phone, Adresse, Datum): ≥ 0.90
     (statt der ursprünglichen 0.95). Aktuell 0.73 — erreichbar mit Punkten
     1-3.
   - **Tier-A implizit** (paraphrasiert): ≥ 0.60. Aktuell ~0.50.
     UX-Flag-Fallback für den Rest.
   - **Tier-B** (Pfade/IPs/Hostnames): ≥ 0.85. Aktuell 0.86. **Geschafft.**
   - **Tier-C** (Secrets): ≥ 0.95. Aktuell 0.57. **Pflicht-Verbesserung**
     vor Release.

---

## Ehrlichkeits-Kasten

Drei Dinge, die diesem Bericht im Mund umgangen werden müssen:

1. **0.95 Recall auf der Original-Spec wird mit lokalem 1.7B-Setup nie
   erreicht.** Implizite PII („das was mir damals Anfang März passiert ist
   — ich hab's nie meinen Eltern erzählt") ist ohne Welt-Wissen und
   Konversations-Kontext nicht zuverlässig als sensitiv klassifizierbar.
   Das ist eine Grenze der Architektur, nicht ein Tuning-Knopf.

2. **ai4privacy als Standard-Benchmark ist nur teilweise unser Use-Case.**
   ai4privacy ist strukturierter Kontaktdaten-PII (FIRSTNAME, EMAIL,
   STREETADDRESS). Coding-Agent-Traffic enthält auch viel
   Operational-PII (Pfade, IPs, Code mit Secrets) und Konversations-PII
   (Notizen, Kalender). Unsere Fixtures testen das gezielt; ai4privacy
   nicht. Beide Sets liefern unterschiedliche Bestenlisten, was *richtig*
   ist — kein einzelner Benchmark genügt.

3. **Die Recall-Zahl hängt am Goldlabel-Set, das ich selbst gebaut habe.**
   Wenn ich „Freitag" als DATE markiere und ein Modell „Freitag" auch als
   DATE findet, ist das ein TP. Aber ist „Freitag" wirklich PII-relevant
   in dem Kontext? Solche Edge-Cases sind im 50-Fixture-Set zwischen 10 %
   und 20 % der Spans. Ein extern kuratiertes Goldlabel (oder
   ai4privacy-Subset) macht hier ehrlicher.

Diese drei Punkte heißen: **die Modell-Auswahl ist gut, aber „Sicher" als
absolute Aussage ist sie nicht.** Das UX-Flag für unsichere Cases ist
deswegen nicht „Nice-to-have", sondern Teil des Sicherheitsmodells.
