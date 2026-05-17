"""Build the private-person fixture corpus (apf-baw).

Generates fixtures/private/private.jsonl from declarative definitions below.
The output directory is gitignored — these fixtures are synthetic but
category-charged (mental-health, asylum, addiction, sexual orientation),
and we keep them out of the public repo on principle.

Each fixture: id + lang + text + spans + notes.
Spans here are declared as (label, value-to-find-in-text, tier, third_party).
Offsets are computed by str.find() with uniqueness assertion — if a value
appears twice in the text and you want the second occurrence, split the
fixture or rename the value.

Run:
    python scripts/build_private_fixtures.py

Validates and writes to fixtures/private/private.jsonl.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SpanSpec:
    label: str
    value: str
    tier: str = "A"
    third_party: bool = False


@dataclass
class Fixture:
    id: str
    lang: str
    text: str
    spans: list[SpanSpec]
    notes: str
    bucket: str = "private"
    source: str = "synthetic"


# Category vocabulary used in spans. Reuses existing content.jsonl labels
# (PERSON, EMAIL, PHONE, ADDRESS, DATE, ORG, APPOINTMENT_HEALTH) and adds
# private-life labels per the THREAT-MODEL-PRIVATE.md taxonomy.
#
# Per Frage 5.1 decision: at runtime, all of these will be replaced by
# opaque <SENSITIVE_n>. The label here is for evaluation/audit, not for
# what the LLM sees.

FIXTURES: list[Fixture] = [

    # ── Health (mental + physical, mostly user's own) ──────────────────────

    Fixture(
        id="de-health-mental-01",
        lang="de",
        text=(
            "Liebe Frau Dr. Korte,\n\n"
            "ich wollte für unsere Sitzung am Donnerstag um 14:30 vorab kurz "
            "anmelden, dass es seit der Dosis-Erhöhung von Sertralin (jetzt "
            "100 mg) wieder mehr Schlafprobleme gibt und am Wochenende eine "
            "depressive Episode kam, ähnlich wie vor der letzten "
            "Klinikaufnahme in der Schön Klinik Roseneck. Können wir das "
            "Thema vorziehen?\n\n"
            "Viele Grüße\nMartina Hoffmann"
        ),
        spans=[
            SpanSpec("PERSON", "Frau Dr. Korte"),
            SpanSpec("DATE", "Donnerstag um 14:30"),
            SpanSpec("MEDICATION", "Sertralin"),
            SpanSpec("MEDICATION_DOSE", "100 mg"),
            SpanSpec("DIAGNOSIS_MENTAL", "depressive Episode"),
            SpanSpec("MEDICAL_FACILITY", "Schön Klinik Roseneck"),
            SpanSpec("PERSON", "Martina Hoffmann"),
        ],
        notes="user drafts msg to therapist, mental-health flare + medication + named clinic",
    ),

    Fixture(
        id="de-repro-01",
        lang="de",
        text=(
            "Hi Agent, fasse bitte den anhängenden Überweisungsbrief von "
            "Dr. Schreiber (Frauenarztpraxis am Stadtpark, Hamburg) "
            "zusammen, damit ich ihn an meinen Hausarzt Dr. Wegener "
            "weiterleiten kann. Wichtig ist: Befund Endometriose-Verdacht "
            "Stadium II, geplante Laparoskopie im Marienkrankenhaus "
            "voraussichtlich KW 24, Termin Ambulanz am 12.06."
        ),
        spans=[
            SpanSpec("PERSON", "Dr. Schreiber"),
            SpanSpec("MEDICAL_FACILITY", "Frauenarztpraxis am Stadtpark"),
            SpanSpec("ADDRESS", "Hamburg"),
            SpanSpec("PERSON", "Dr. Wegener"),
            SpanSpec("DIAGNOSIS", "Endometriose-Verdacht Stadium II"),
            SpanSpec("MEDICAL_PROCEDURE", "Laparoskopie"),
            SpanSpec("MEDICAL_FACILITY", "Marienkrankenhaus"),
            SpanSpec("DATE", "KW 24"),
            SpanSpec("DATE", "12.06."),
        ],
        notes="gynaecologist referral summary, reproductive health diagnosis + procedure + facility",
    ),

    Fixture(
        id="en-mental-substance-01",
        lang="en",
        text=(
            "Journal — Tuesday\n\n"
            "Relapsed on Sunday night, four glasses of wine after the call "
            "with mom. Tied to the depressive dip that started about a week "
            "ago — same pattern as last spring. AA meeting at St. Mary's "
            "tomorrow 7pm, told Dr. Patel I'd come back to weekly sessions "
            "instead of biweekly. Sertraline still at 50 mg, no change "
            "needed yet."
        ),
        spans=[
            SpanSpec("DATE", "Tuesday"),
            SpanSpec("SUBSTANCE_USE", "four glasses of wine"),
            SpanSpec("PERSON", "mom", third_party=True),
            SpanSpec("DIAGNOSIS_MENTAL", "depressive dip"),
            SpanSpec("RECOVERY_GROUP", "AA meeting"),
            SpanSpec("MEDICAL_FACILITY", "St. Mary's"),
            SpanSpec("DATE", "tomorrow 7pm"),
            SpanSpec("PERSON", "Dr. Patel"),
            SpanSpec("MEDICATION", "Sertraline"),
            SpanSpec("MEDICATION_DOSE", "50 mg"),
        ],
        notes="EN journal: relapse + depression + AA + therapist + medication; third-party mom",
    ),

    # ── Legal: asylum, custody, immigration ────────────────────────────────

    Fixture(
        id="de-asylum-01",
        lang="de",
        text=(
            "An: Bundesamt für Migration und Flüchtlinge\n"
            "Aktenzeichen: 8472193-475\n\n"
            "Ergänzende Stellungnahme zu meinem Antrag nach §60 AsylG.\n\n"
            "Mein Name ist Samira Hosseini, geboren am 03.04.1994 in Mashhad, "
            "Iran. Ich bin am 17.09.2023 über die Türkei nach Deutschland "
            "eingereist. Die Anhörung ist für den 21.05.2026 im Außenposten "
            "Heidelberg angesetzt. Gründe der Verfolgung: aktive Mitarbeit "
            "in der Frauenrechtsbewegung nach dem Tod von Mahsa Amini, "
            "namentliche Erwähnung in einer IRGC-Akte (Übersetzung im "
            "Anhang). Mein Anwalt ist Herr Rechtsanwalt Bastian Müller, "
            "Kanzlei Müller & Partner, München."
        ),
        spans=[
            SpanSpec("CASE_NUMBER", "8472193-475"),
            SpanSpec("PERSON", "Samira Hosseini"),
            SpanSpec("DATE", "03.04.1994"),
            SpanSpec("ADDRESS", "Mashhad, Iran"),
            SpanSpec("DATE", "17.09.2023"),
            SpanSpec("DATE", "21.05.2026"),
            SpanSpec("ADDRESS", "Außenposten Heidelberg"),
            SpanSpec("POLITICAL_ACTIVITY", "Frauenrechtsbewegung"),
            SpanSpec("PERSON", "Mahsa Amini", third_party=True),
            SpanSpec("ASYLUM_DETAIL", "IRGC-Akte"),
            SpanSpec("PERSON", "Bastian Müller"),
            SpanSpec("ORG", "Müller & Partner"),
            SpanSpec("ADDRESS", "München"),
        ],
        notes="§60 AsylG statement, high-risk category (asylum + political activity)",
    ),

    Fixture(
        id="en-custody-01",
        lang="en",
        text=(
            "Notes for mediation session Friday\n\n"
            "Re: custody arrangement for Mia (born 2018-07-11, currently "
            "in 2nd grade at Lincoln Elementary). Ex-partner Daniel Reyes "
            "is asking for Wednesday-overnight + alternating weekends; I "
            "want to push back on Wednesdays because of her piano "
            "lessons. Daniel's new address is 442 Oakwood Drive, "
            "Springfield. Attorney: Karen Whitfield (Whitfield & Park "
            "Family Law). Mediator: Dr. Helene Brooks."
        ),
        spans=[
            SpanSpec("DATE", "Friday"),
            SpanSpec("PERSON", "Mia", third_party=True),
            SpanSpec("DATE", "2018-07-11"),
            SpanSpec("ORG", "Lincoln Elementary"),
            SpanSpec("PERSON", "Daniel Reyes", third_party=True),
            SpanSpec("ADDRESS", "442 Oakwood Drive, Springfield"),
            SpanSpec("PERSON", "Karen Whitfield"),
            SpanSpec("ORG", "Whitfield & Park Family Law"),
            SpanSpec("PERSON", "Dr. Helene Brooks"),
        ],
        notes="custody mediation: minor child (3p), ex-partner (3p), attorney + mediator",
    ),

    Fixture(
        id="en-immigration-01",
        lang="en",
        text=(
            "Agent, summarise my I-485 status for my new tax preparer:\n\n"
            "I'm on a pending I-485 adjustment of status, filed 2024-03-12, "
            "priority date 2022-08-19, EB-2 category. Prior status: H-1B "
            "from 2019 (sponsor: Helix Diagnostics Inc.), before that F-1 "
            "at Carnegie Mellon. Receipt number MSC2490112847. EAD valid "
            "through 2026-09-30. Attorney is Rajiv Bhandari at Bhandari "
            "Immigration Law in Pittsburgh."
        ),
        spans=[
            SpanSpec("IMMIGRATION_STATUS", "I-485 adjustment of status"),
            SpanSpec("DATE", "2024-03-12"),
            SpanSpec("DATE", "2022-08-19"),
            SpanSpec("IMMIGRATION_STATUS", "EB-2"),
            SpanSpec("IMMIGRATION_STATUS", "H-1B"),
            SpanSpec("DATE", "2019"),
            SpanSpec("ORG", "Helix Diagnostics Inc."),
            SpanSpec("IMMIGRATION_STATUS", "F-1"),
            SpanSpec("ORG", "Carnegie Mellon"),
            SpanSpec("CASE_NUMBER", "MSC2490112847"),
            SpanSpec("DATE", "2026-09-30"),
            SpanSpec("PERSON", "Rajiv Bhandari"),
            SpanSpec("ORG", "Bhandari Immigration Law"),
            SpanSpec("ADDRESS", "Pittsburgh"),
        ],
        notes="I-485 timeline + visa history + attorney; high-risk immigration category",
    ),

    # ── Financial ──────────────────────────────────────────────────────────

    Fixture(
        id="de-finanz-insolvenz-01",
        lang="de",
        text=(
            "Sehr geehrte Damen und Herren,\n\n"
            "ich bitte um einen Termin in der Schuldnerberatung der Caritas "
            "Hannover. Stand: Gesamtverschuldung ca. 47.300 EUR (Sparkasse "
            "Hannover 22.000 EUR Dispo + KfW-Kredit 18.300 EUR + diverse "
            "Inkasso 7.000 EUR), Schufa-Score aktuell 78, drei laufende "
            "Mahnverfahren. Ziel: Privatinsolvenz, Antragsvorbereitung. "
            "Mein Arbeitgeber (Logistik Nord GmbH) weiß noch nichts. "
            "Erreichbar werktags ab 16 Uhr.\n\n"
            "Lukas Brettschneider"
        ),
        spans=[
            SpanSpec("ORG", "Caritas Hannover"),
            SpanSpec("FINANCIAL_AMOUNT", "47.300 EUR"),
            SpanSpec("ORG", "Sparkasse Hannover"),
            SpanSpec("FINANCIAL_AMOUNT", "22.000 EUR"),
            SpanSpec("FINANCIAL_AMOUNT", "18.300 EUR"),
            SpanSpec("FINANCIAL_AMOUNT", "7.000 EUR"),
            SpanSpec("FINANCIAL_STATUS", "Schufa-Score aktuell 78"),
            SpanSpec("FINANCIAL_STATUS", "Privatinsolvenz"),
            SpanSpec("ORG", "Logistik Nord GmbH"),
            SpanSpec("PERSON", "Lukas Brettschneider"),
        ],
        notes="Schuldnerberatung email: debts + Schufa + Privatinsolvenz + employer-not-aware",
    ),

    # ── Politics ───────────────────────────────────────────────────────────

    Fixture(
        id="de-politik-spende-01",
        lang="de",
        text=(
            "Agent, schreib mir bitte eine kurze E-Mail an die "
            "Bundesgeschäftsstelle der Linkspartei, ich brauche die "
            "Spendenbescheinigung für die Steuer 2024. Spende war "
            "240 EUR per Lastschrift am 14.11.2024, Mitgliedsnummer "
            "LP-DE-2019-44871. Empfänger der Bescheinigung: "
            "Hannelore Krüger, Goebenstraße 8, 48143 Münster."
        ),
        spans=[
            SpanSpec("POLITICAL_PARTY", "Linkspartei"),
            SpanSpec("FINANCIAL_AMOUNT", "240 EUR"),
            SpanSpec("DATE", "14.11.2024"),
            SpanSpec("MEMBERSHIP_ID", "LP-DE-2019-44871"),
            SpanSpec("PERSON", "Hannelore Krüger"),
            SpanSpec("ADDRESS", "Goebenstraße 8, 48143 Münster"),
        ],
        notes="political donation receipt request; party membership + donation amount",
    ),

    Fixture(
        id="en-political-activism-01",
        lang="en",
        text=(
            "Draft Twitter thread for me:\n\n"
            "Just back from the Stop Cop City protest in Atlanta GA. Marched "
            "with about 600 people; organised by Atlanta Community Press "
            "Collective and Defend the Atlanta Forest. Co-organiser Marisol "
            "Reyes spoke about the recent RICO indictments. I was at the "
            "Weelaunee gathering point at noon, left around 4pm."
        ),
        spans=[
            SpanSpec("POLITICAL_ACTIVITY", "Stop Cop City protest"),
            SpanSpec("ADDRESS", "Atlanta GA"),
            SpanSpec("ORG", "Atlanta Community Press Collective"),
            SpanSpec("ORG", "Defend the Atlanta Forest"),
            SpanSpec("PERSON", "Marisol Reyes", third_party=True),
            SpanSpec("LEGAL_DETAIL", "RICO indictments"),
            SpanSpec("ADDRESS", "Weelaunee gathering point"),
            SpanSpec("DATE", "noon"),
            SpanSpec("DATE", "4pm"),
        ],
        notes="political activism thread; high-risk org + named co-organiser (3p) + legal context",
    ),

    # ── Third-party PII ────────────────────────────────────────────────────

    Fixture(
        id="de-third-party-health-01",
        lang="de",
        text=(
            "Bitte recherchier mir, was \"primäres myelodysplastisches "
            "Syndrom\" konkret bedeutet — meine Mutter Elisabeth Lorenz "
            "(72) hat heute den Befund von der Onkologie der Uniklinik "
            "Tübingen bekommen, Dr. Hartmann. Therapieoptionen, übliche "
            "Prognose, was ich für sie organisieren sollte."
        ),
        spans=[
            SpanSpec("DIAGNOSIS", "primäres myelodysplastisches Syndrom"),
            SpanSpec("PERSON", "Elisabeth Lorenz", third_party=True),
            SpanSpec("AGE", "72", third_party=True),
            SpanSpec("MEDICAL_FACILITY", "Onkologie der Uniklinik Tübingen"),
            SpanSpec("PERSON", "Dr. Hartmann"),
        ],
        notes="third-party health: mother's diagnosis + age + treating physician",
    ),

    Fixture(
        id="en-third-party-confidence-01",
        lang="en",
        text=(
            "Journal — late.\n\n"
            "Aaron told me tonight he tested positive for HIV last month. "
            "He's on antiretrovirals now (Biktarvy), seeing Dr. Marlowe at "
            "the Castro clinic. He hasn't told his parents in Phoenix yet "
            "and asked me not to say anything to Jen or anyone in our "
            "Friday group. Felt heavy. Make sure I don't slip when texting "
            "her tomorrow."
        ),
        spans=[
            SpanSpec("PERSON", "Aaron", third_party=True),
            SpanSpec("DIAGNOSIS", "tested positive for HIV", third_party=True),
            SpanSpec("MEDICATION", "Biktarvy", third_party=True),
            SpanSpec("PERSON", "Dr. Marlowe", third_party=True),
            SpanSpec("MEDICAL_FACILITY", "Castro clinic", third_party=True),
            SpanSpec("ADDRESS", "Phoenix", third_party=True),
            SpanSpec("PERSON", "Jen", third_party=True),
        ],
        notes="third-party confidence: friend's HIV diagnosis, his treating doctor, his family location",
    ),

    # ── Sexuality / identity ───────────────────────────────────────────────

    Fixture(
        id="de-sex-orientation-01",
        lang="de",
        text=(
            "Hilf mir bitte beim Coming-out-Brief an meine Eltern Renate "
            "und Friedrich Westphal. Inhalt: ich bin seit zwei Jahren mit "
            "Tobias Albers zusammen, wir ziehen im August zusammen nach "
            "Köln, Heimfeldstraße 12. Ton: respektvoll, nicht entschuldigend. "
            "Erwähne, dass ich am 14.06. zu Besuch komme, wenn sie reden "
            "möchten."
        ),
        spans=[
            SpanSpec("PERSON", "Renate", third_party=True),
            SpanSpec("PERSON", "Friedrich Westphal", third_party=True),
            SpanSpec("SEXUAL_ORIENTATION", "seit zwei Jahren mit Tobias Albers zusammen"),
            SpanSpec("PERSON", "Tobias Albers", third_party=True),
            SpanSpec("DATE", "August"),
            SpanSpec("ADDRESS", "Köln, Heimfeldstraße 12"),
            SpanSpec("DATE", "14.06."),
        ],
        notes="coming-out letter; self-disclosure of orientation + named partner (3p) + parents (3p)",
    ),

    # ── Substance use, prescribed ──────────────────────────────────────────

    Fixture(
        id="de-substanz-rezept-01",
        lang="de",
        text=(
            "Hi, kann mir jemand das Rezept erklären? Verordnung von "
            "Dr. Wendelin (Praxis für Erwachsenen-ADHS, Berlin-Mitte): "
            "Ritalin Adult 20 mg, 1-0-1, Dauerverordnung 6 Monate, "
            "Diagnose F90.0 (ADHS adulter Typ). Apotheke: Hirsch-Apotheke "
            "Friedrichshain. Versichertennummer A123456789, AOK Nordost."
        ),
        spans=[
            SpanSpec("PERSON", "Dr. Wendelin"),
            SpanSpec("MEDICAL_FACILITY", "Praxis für Erwachsenen-ADHS"),
            SpanSpec("ADDRESS", "Berlin-Mitte"),
            SpanSpec("MEDICATION", "Ritalin Adult 20 mg"),
            SpanSpec("MEDICATION_DOSE", "1-0-1"),
            SpanSpec("DIAGNOSIS", "F90.0"),
            SpanSpec("DIAGNOSIS", "ADHS adulter Typ"),
            SpanSpec("ORG", "Hirsch-Apotheke Friedrichshain"),
            SpanSpec("INSURANCE_ID", "A123456789"),
            SpanSpec("ORG", "AOK Nordost"),
        ],
        notes="ADHS prescription + ICD code + insurance ID — DE-specific Krankenkasse",
    ),
]


def build_spans(text: str, specs: list[SpanSpec]) -> list[dict]:
    """Resolve (label, value) → (start, end, label, tier) with uniqueness check.

    If a value appears twice, raises — fixtures should disambiguate by editing
    text or splitting spans rather than guessing which occurrence is meant.
    """
    spans: list[dict] = []
    for spec in specs:
        first = text.find(spec.value)
        if first < 0:
            raise ValueError(f"value {spec.value!r} not found in fixture text")
        second = text.find(spec.value, first + 1)
        if second >= 0:
            raise ValueError(
                f"value {spec.value!r} appears more than once in fixture — "
                f"split or rephrase so each labelled value is unique"
            )
        span = {
            "start": first,
            "end": first + len(spec.value),
            "label": spec.label,
            "tier": spec.tier,
        }
        if spec.third_party:
            span["third_party"] = True
        spans.append(span)
    spans.sort(key=lambda s: s["start"])
    return spans


def to_jsonl_record(f: Fixture) -> dict:
    return {
        "id": f.id,
        "lang": f.lang,
        "bucket": f.bucket,
        "source": f.source,
        "text": f.text,
        "spans": build_spans(f.text, f.spans),
        "notes": f.notes,
    }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "fixtures" / "private"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "private.jsonl"

    records = []
    for f in FIXTURES:
        rec = to_jsonl_record(f)
        # quick self-check: every span's text matches the slice
        for sp in rec["spans"]:
            slice_ = rec["text"][sp["start"]:sp["end"]]
            assert slice_, f"empty span in {f.id}: {sp}"
        records.append(rec)

    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"wrote {len(records)} fixtures → {out_path}")
    by_lang = {"de": 0, "en": 0}
    label_counts: dict[str, int] = {}
    third_party_spans = 0
    for rec in records:
        by_lang[rec["lang"]] = by_lang.get(rec["lang"], 0) + 1
        for sp in rec["spans"]:
            label_counts[sp["label"]] = label_counts.get(sp["label"], 0) + 1
            if sp.get("third_party"):
                third_party_spans += 1
    print(f"  languages: {by_lang}")
    print(f"  total spans: {sum(label_counts.values())}")
    print(f"  third-party spans: {third_party_spans}")
    print(f"  labels seen: {sorted(label_counts)}")


if __name__ == "__main__":
    main()
