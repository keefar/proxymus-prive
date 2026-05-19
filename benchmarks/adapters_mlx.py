"""MLX-backed detector adapters.

Each adapter wraps a different model and maps its native label space to
the project's `docs/MODELS.md` label inventory. Tier-equality (our primary
metric) tolerates imperfect label mappings as long as the *tier* survives.

Adapters lazy-load weights in `warmup()` so harness latency measurements
on `detect()` reflect steady-state behaviour, not first-call cold-start.
"""
from __future__ import annotations

import os
import time
from typing import Iterable

from .adapters import LABEL_TIER, Span


# ---- Nemotron Privacy Filter MLX -----------------------------------------

# Nemotron emits 55 PII span classes; our inventory has ~25. This maps each
# Nemotron entity_group to the most defensible label in our inventory.
# Tier-equality scoring is the primary metric, so the *tier* assignment is
# what matters most — label-equality is a stricter diagnostic.
NEMOTRON_LABEL_MAP: dict[str, str] = {
    # Personal identifiers
    "first_name": "PERSON",
    "last_name": "PERSON",
    "user_name": "PERSON",
    "gender": "NOTE_SENSITIVE",
    "age": "NOTE_SENSITIVE",
    "date_of_birth": "DATE",
    # Contact
    "email": "EMAIL",
    "phone_number": "PHONE",
    "fax_number": "PHONE",
    "street_address": "ADDRESS",
    "city": "LOCATION",
    "state": "LOCATION",
    "country": "LOCATION",
    "county": "LOCATION",
    "postcode": "ADDRESS",
    "coordinate": "LOCATION",
    # Gov/Legal IDs → Tier A sensitive identifier
    "ssn": "NOTE_SENSITIVE",
    "national_id": "NOTE_SENSITIVE",
    "tax_id": "NOTE_SENSITIVE",
    "certificate_license_number": "NOTE_SENSITIVE",
    # Financial
    "account_number": "FINANCIAL",
    "bank_routing_number": "FINANCIAL",
    "credit_debit_card": "FINANCIAL",
    "cvv": "PASSWORD",  # access control → Tier C
    "pin": "PASSWORD",
    "swift_bic": "FINANCIAL",
    # Medical
    "medical_record_number": "HEALTH",
    "health_plan_beneficiary_number": "HEALTH",
    "blood_type": "HEALTH",
    # Workplace
    "company_name": "ORG",
    "occupation": "NOTE_SENSITIVE",
    "employee_id": "NOTE_SENSITIVE",
    "customer_id": "NOTE_SENSITIVE",
    "employment_status": "NOTE_SENSITIVE",
    "education_level": "NOTE_SENSITIVE",
    # Online
    "url": "URL_LOCAL",
    "ipv4": "IP",
    "ipv6": "IP",
    "mac_address": "IP",
    "http_cookie": "TOKEN",
    "api_key": "API_KEY",
    "password": "PASSWORD",
    "device_identifier": "HOSTNAME",
    # Demographic — Tier A sensitive
    "race_ethnicity": "NOTE_SENSITIVE",
    "religious_belief": "NOTE_SENSITIVE",
    "political_view": "NOTE_SENSITIVE",
    "sexuality": "NOTE_SENSITIVE",
    "language": "NOTE_SENSITIVE",
    # Vehicles
    "license_plate": "NOTE_SENSITIVE",
    "vehicle_identifier": "NOTE_SENSITIVE",
    # Time
    "date": "DATE",
    "date_time": "DATE",
    "time": "DATE",
    # Misc
    "biometric_identifier": "HEALTH",
    "unique_id": "NOTE_SENSITIVE",
}


class NemotronAdapter:
    name = "nemotron-mlx-8bit"
    hf_id = "OpenMed/privacy-filter-nemotron-mlx-8bit"

    def __init__(self, min_score: float = 0.6) -> None:
        self.min_score = min_score
        self._pipe = None

    def warmup(self) -> None:
        from huggingface_hub import snapshot_download
        from openmed.mlx.inference import PrivacyFilterMLXPipeline
        path = snapshot_download(self.hf_id)
        self._pipe = PrivacyFilterMLXPipeline(path)
        # Prime caches by running on a tiny string — first call is slower.
        self._pipe("Hi.")

    def detect(self, text: str) -> list[Span]:
        assert self._pipe is not None, "call warmup() before detect()"
        raw = self._pipe(text)
        spans: list[Span] = []
        for ent in raw:
            score = float(ent.get("score", 0.0))
            if score < self.min_score:
                continue
            group = ent.get("entity_group", "")
            label = NEMOTRON_LABEL_MAP.get(group)
            if label is None:
                continue
            tier = LABEL_TIER.get(label)
            if tier is None:
                continue
            start = int(ent["start"])
            end = int(ent["end"])
            if end <= start:
                continue
            spans.append(Span(start=start, end=end, label=label, tier=tier,
                              confidence=score))
        return spans


# ---- Anonymizer-SLM (eternisai/Anonymizer-1.7B, MLX-converted) -----------

# Anonymizer-SLM is generative: it returns {original, replacement} pairs with
# no offsets and no explicit category. We:
#   1. Find each `original` in the input text (first occurrence) → span offsets.
#   2. Infer a label from the original's surface form using regex patterns
#      (re-used from the RegexBaseline). Anything that matches no pattern
#      falls back to NOTE_SENSITIVE — Tier-A catch-all.
# This means label-equality recall will be limited, but tier-equality is fair
# game (Anonymizer is explicitly a Tier-A content-PII tool).

ANONYMIZER_TASK = (
    "You are an anonymizer. Identify all personally identifiable information "
    "(PII) in the user message and replace each occurrence with a fictitious but "
    "plausible substitute. Use the replace_entities tool to return your "
    "replacements. If a value is PII but should be kept verbatim, still include "
    "it with original == replacement."
)

ANONYMIZER_TOOLS = [{
    "type": "function",
    "function": {
        "name": "replace_entities",
        "description": "Replace PII entities with anonymized versions",
        "parameters": {
            "type": "object",
            "properties": {
                "replacements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "original": {"type": "string"},
                            "replacement": {"type": "string"},
                        },
                        "required": ["original", "replacement"],
                    },
                }
            },
            "required": ["replacements"],
        },
    },
}]


def _infer_label(text: str) -> str:
    """Heuristic label inference from the surface form of a flagged original."""
    from .adapters import RegexBaseline
    for label, rx in RegexBaseline.PATTERNS:
        if rx.search(text):
            return label
    return "NOTE_SENSITIVE"


def _parse_tool_call(raw: str) -> list[dict]:
    """Pull the JSON arg list out of a <tool_call> or <|tool_call|> envelope."""
    import json
    import re
    m = re.search(r"<\|?tool_call\|?>\s*(\{.*?\})\s*</?\|?tool_call\|?>",
                  raw, re.DOTALL)
    if not m:
        # Try a looser match — sometimes the model emits a bare JSON object.
        m = re.search(r'\{\s*"name"\s*:\s*"replace_entities".*\}', raw, re.DOTALL)
        if not m:
            return []
        payload = m.group(0)
    else:
        payload = m.group(1)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    return data.get("arguments", {}).get("replacements", []) or []


class AnonymizerSLMAdapter:
    name = "anonymizer-slm-1.7b-4bit"
    mlx_path = "/Users/chris/.cache/huggingface/mlx-models/Anonymizer-1.7B-4bit"

    def __init__(self, max_tokens: int = 400) -> None:
        self.max_tokens = max_tokens
        self._model = None
        self._tok = None

    def warmup(self) -> None:
        from mlx_lm import load, generate
        self._model, self._tok = load(self.mlx_path)
        self._generate = generate
        # Prime the model with a tiny call so detect() latency is warm.
        self._run("Hi.")

    def _run(self, text: str) -> str:
        prompt = self._tok.apply_chat_template(
            [
                {"role": "system", "content": ANONYMIZER_TASK},
                {"role": "user", "content": text + "\n/no_think"},
            ],
            tools=ANONYMIZER_TOOLS,
            tokenize=False,
            add_generation_prompt=True,
        )
        return self._generate(self._model, self._tok,
                              prompt=prompt, max_tokens=self.max_tokens, verbose=False)

    def detect(self, text: str) -> list[Span]:
        raw = self._run(text)
        replacements = _parse_tool_call(raw)
        spans: list[Span] = []
        used: list[tuple[int, int]] = []
        for r in replacements:
            original = r.get("original", "")
            if not original:
                continue
            # First occurrence of the original in text. Skip ranges already used.
            search_from = 0
            while True:
                idx = text.find(original, search_from)
                if idx < 0:
                    break
                end = idx + len(original)
                if not any(s < end and e > idx for s, e in used):
                    break
                search_from = idx + 1
            if idx < 0:
                continue
            label = _infer_label(original)
            tier = LABEL_TIER.get(label, "A")
            spans.append(Span(start=idx, end=end, label=label, tier=tier))
            used.append((idx, end))
        spans.sort(key=lambda s: s.start)
        return spans


# ---- Qwen3-1.7B-4bit (generic generative fallback, mlx-community) --------

# Qwen3 has no PII fine-tune; we prompt it to emit a JSON span list and parse.
# Same offset-recovery + label inference trick as AnonymizerSLM.

QWEN_TASK = (
    "You detect personally identifiable information (PII) in text. Output ONLY "
    "a JSON object on a single line with the schema:\n"
    '{"pii":[{"text":"<exact substring>","type":"<one of: PERSON, EMAIL, '
    "PHONE, ADDRESS, LOCATION, ORG, DATE, APPOINTMENT, HEALTH, RELATIONSHIP, "
    "FINANCIAL, NOTE_SENSITIVE, IMPLICIT_PII, PATH, FILENAME, HOSTNAME, IP, "
    "URL_LOCAL, CREDENTIAL, API_KEY, PRIVATE_KEY, PASSWORD, TOKEN, "
    'CONNECTION_STRING>"}]}\n'
    'Use the exact original substring from the input. Output {"pii":[]} if none.'
)


def _parse_qwen_json(raw: str) -> list[dict]:
    import json
    import re
    # Strip <think> blocks; pick the first JSON object containing "pii".
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    # Find balanced JSON object — search forward from the first '{'.
    for m in re.finditer(r"\{[^{}]*\"pii\"\s*:\s*\[(?:[^][]|\[[^]]*\])*\][^{}]*\}",
                         raw, re.DOTALL):
        try:
            data = json.loads(m.group(0))
            return data.get("pii", []) or []
        except json.JSONDecodeError:
            continue
    return []


class Qwen3Adapter:
    name = "qwen3-1.7b-4bit"
    hf_id = "mlx-community/Qwen3-1.7B-4bit"

    def __init__(self, max_tokens: int = 512) -> None:
        self.max_tokens = max_tokens
        self._model = None
        self._tok = None
        self._generate = None

    def warmup(self) -> None:
        from huggingface_hub import snapshot_download
        from mlx_lm import load, generate
        path = snapshot_download(self.hf_id)
        self._model, self._tok = load(path)
        self._generate = generate
        self._run("Hi.")

    def _run(self, text: str) -> str:
        prompt = self._tok.apply_chat_template(
            [
                {"role": "system", "content": QWEN_TASK},
                {"role": "user", "content": text + "\n/no_think"},
            ],
            tokenize=False,
            add_generation_prompt=True,
        )
        return self._generate(self._model, self._tok,
                              prompt=prompt, max_tokens=self.max_tokens, verbose=False)

    def detect(self, text: str) -> list[Span]:
        raw = self._run(text)
        items = _parse_qwen_json(raw)
        spans: list[Span] = []
        used: list[tuple[int, int]] = []
        for it in items:
            original = it.get("text", "")
            if not original:
                continue
            search_from = 0
            idx = -1
            while True:
                idx = text.find(original, search_from)
                if idx < 0:
                    break
                end = idx + len(original)
                if not any(s < end and e > idx for s, e in used):
                    break
                search_from = idx + 1
            if idx < 0:
                continue
            type_ = (it.get("type") or "").strip().upper()
            label = type_ if type_ in LABEL_TIER else _infer_label(original)
            tier = LABEL_TIER.get(label, "A")
            spans.append(Span(start=idx, end=end, label=label, tier=tier))
            used.append((idx, end))
        spans.sort(key=lambda s: s.start)
        return spans


# ---- GLiNER multilingual PII (urchade/gliner_multi_pii-v1) ---------------

# GLiNER is a BERT-encoder NER with zero-shot label support: you pass a list
# of natural-language labels at call time and it returns spans for each. The
# multi_pii-v1 variant is fine-tuned on a synthetic PII NER dataset and
# explicitly supports DE/EN/FR/ES/IT/PT.
#
# Strategy: hand GLiNER descriptive natural-language labels (its strength)
# and map back to our inventory.

GLINER_LABELS = [
    # English descriptive labels
    "person",
    "email",
    "phone number",
    "street address",
    "city",
    "country",
    "organization",
    "date",
    "appointment",
    "medical condition",
    "medication",
    "doctor",
    "family relationship",
    "iban",
    "credit card",
    "bank account",
    "implicit person identifier",
    "implicit health identifier",
    "file path",
    "filename",
    "hostname",
    "ip address",
    "url",
    "api key",
    "private key",
    "password",
    "token",
    "database connection string",
    # German-localized labels — GLiNER's multilingual base benefits from
    # parallel labels in the target language (apf-73d).
    "deutscher Vorname",
    "deutscher Nachname",
    "deutsche Adresse",
    "deutsche Telefonnummer",
    "Arzttermin",
    "Diagnose",
    "Medikament",
    "Krankenkasse",
    "Familienmitglied",
    "Geburtsdatum",
    "Arbeitgeber",
    "Beruf",
    "deutsche Stadt",
    "Bundesland",
    "Postleitzahl",
]

GLINER_LABEL_MAP: dict[str, str] = {
    # English
    "person": "PERSON",
    "email": "EMAIL",
    "phone number": "PHONE",
    "street address": "ADDRESS",
    "city": "LOCATION",
    "country": "LOCATION",
    "organization": "ORG",
    "date": "DATE",
    "appointment": "APPOINTMENT",
    "medical condition": "HEALTH",
    "medication": "HEALTH",
    "doctor": "HEALTH",
    "family relationship": "RELATIONSHIP",
    "iban": "FINANCIAL",
    "credit card": "FINANCIAL",
    "bank account": "FINANCIAL",
    "implicit person identifier": "IMPLICIT_PII",
    "implicit health identifier": "HEALTH",
    "file path": "PATH",
    "filename": "FILENAME",
    "hostname": "HOSTNAME",
    "ip address": "IP",
    "url": "URL_LOCAL",
    "api key": "API_KEY",
    "private key": "PRIVATE_KEY",
    "password": "PASSWORD",
    "token": "TOKEN",
    "database connection string": "CONNECTION_STRING",
    # German parallel labels
    "deutscher vorname": "PERSON",
    "deutscher nachname": "PERSON",
    "deutsche adresse": "ADDRESS",
    "deutsche telefonnummer": "PHONE",
    "arzttermin": "APPOINTMENT",
    "diagnose": "HEALTH",
    "medikament": "HEALTH",
    "krankenkasse": "HEALTH",
    "familienmitglied": "RELATIONSHIP",
    "geburtsdatum": "DATE",
    "arbeitgeber": "ORG",
    "beruf": "NOTE_SENSITIVE",
    "deutsche stadt": "LOCATION",
    "bundesland": "LOCATION",
    "postleitzahl": "ADDRESS",
}


# Salutation prefixes that GLiNER sometimes glues onto a PERSON span. Stripped
# from the start of PERSON spans during post-processing.
_PERSON_SALUTATION_PREFIXES = (
    # German
    "Lieber ", "Liebe ", "Liebes ", "Sehr geehrter Herr ", "Sehr geehrte Frau ",
    "Hallo ", "Hi ", "Hey ", "Servus ", "Moin ", "Guten Tag ", "Hallo zusammen,",
    "Hallo zusammen", "Guten Morgen ", "Guten Abend ",
    # English
    "Dear ", "Hi ", "Hey ", "Hello ", "Greetings ", "Mr. ", "Mrs. ", "Ms. ", "Dr. ",
    # Common French/IT that creep in via the multilingual base
    "Cher ", "Chère ", "Caro ", "Cara ",
)

# Punctuation that sometimes leaks into the start/end of a span and should be
# trimmed before tokenisation.
_TRIM_LEADING_CHARS = "([{<\"'`,.;: \t\n"
_TRIM_TRAILING_CHARS = ")]}>\"'`,.;: \t\n"


def _clean_span(text: str, span: Span) -> Span | None:
    """Strip salutation prefixes and stray punctuation from a span.
    Returns None if the cleaned span becomes empty."""
    start, end = span.start, span.end
    fragment = text[start:end]

    # Trim trailing/leading punctuation (but keep matched pairs intact).
    while fragment and fragment[0] in _TRIM_LEADING_CHARS:
        fragment = fragment[1:]
        start += 1
    while fragment and fragment[-1] in _TRIM_TRAILING_CHARS:
        fragment = fragment[:-1]
        end -= 1

    # PERSON-specific: strip salutation prefixes (case-insensitive).
    if span.label == "PERSON":
        lower = fragment.lower()
        for prefix in _PERSON_SALUTATION_PREFIXES:
            if lower.startswith(prefix.lower()):
                offset = len(prefix)
                fragment = fragment[offset:]
                start += offset
                lower = fragment.lower()
                break  # one salutation strip per pass

    if not fragment.strip():
        return None
    return Span(start=start, end=end, label=span.label, tier=span.tier,
                confidence=span.confidence)


class _GlinerBase:
    hf_id: str = ""
    name: str = ""

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self._model = None

    def warmup(self) -> None:
        from gliner import GLiNER
        self._model = GLiNER.from_pretrained(self.hf_id)
        # Prime kernels.
        self._model.predict_entities("Hi.", ["person"], threshold=self.threshold)

    def detect(self, text: str) -> list[Span]:
        assert self._model is not None, "call warmup() before detect()"
        raw = self._model.predict_entities(text, GLINER_LABELS,
                                           threshold=self.threshold)
        spans: list[Span] = []
        for ent in raw:
            label_in = ent.get("label", "").lower()
            label = GLINER_LABEL_MAP.get(label_in)
            if label is None:
                continue
            tier = LABEL_TIER.get(label)
            if tier is None:
                continue
            start = int(ent["start"])
            end = int(ent["end"])
            if end <= start:
                continue
            score = float(ent.get("score", 0.5))
            raw_span = Span(start=start, end=end, label=label, tier=tier,
                            confidence=score)
            cleaned = _clean_span(text, raw_span)
            if cleaned is not None:
                spans.append(cleaned)
        spans.sort(key=lambda s: (s.start, -s.end))
        # GLiNER can emit overlapping spans for different labels — dedupe by
        # keeping the longest span at each start position.
        deduped: list[Span] = []
        seen_ranges: list[tuple[int, int]] = []
        for s in spans:
            if any(rs <= s.start and s.end <= re for rs, re in seen_ranges):
                continue
            deduped.append(s)
            seen_ranges.append((s.start, s.end))
        return deduped


class GlinerMultiPiiAdapter(_GlinerBase):
    name = "gliner-multi-pii-v1"
    hf_id = "urchade/gliner_multi_pii-v1"


class GlinerNvidiaAdapter(_GlinerBase):
    name = "gliner-pii-nvidia"
    hf_id = "nvidia/gliner-PII"


class GlinerKnowledgatorAdapter(_GlinerBase):
    name = "gliner-pii-knowledgator-large"
    hf_id = "knowledgator/gliner-pii-large-v1.0"


# ---- Generic HuggingFace token-classification adapter --------------------

# Uses transformers' `pipeline("token-classification", ...)`. The pipeline
# returns dicts with entity_group/word/score/start/end. Subclasses provide
# the HF id and a native-to-ours label map.

class _HFTokenClassifierBase:
    hf_id: str = ""
    name: str = ""
    label_map: dict[str, str] = {}
    # Some models emit BIO/BIOES prefixes — strip "B-", "I-", "E-", "S-".

    def __init__(self, min_score: float = 0.5) -> None:
        self.min_score = min_score
        self._pipe = None

    def warmup(self) -> None:
        from transformers import pipeline
        self._pipe = pipeline(
            "token-classification",
            model=self.hf_id,
            aggregation_strategy="simple",
            device=-1,  # CPU; MPS via torch is set per-tensor when supported
        )
        self._pipe("Hi.")

    def _normalize_label(self, raw: str) -> str:
        for prefix in ("B-", "I-", "E-", "S-", "L-", "U-"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
                break
        return raw.upper()

    def detect(self, text: str) -> list[Span]:
        assert self._pipe is not None
        raw = self._pipe(text)
        spans: list[Span] = []
        for ent in raw:
            score = float(ent.get("score", 0.0))
            if score < self.min_score:
                continue
            native = self._normalize_label(ent.get("entity_group", ent.get("entity", "")))
            label = self.label_map.get(native)
            if label is None:
                continue
            tier = LABEL_TIER.get(label)
            if tier is None:
                continue
            start = int(ent["start"])
            end = int(ent["end"])
            if end <= start:
                continue
            spans.append(Span(start=start, end=end, label=label, tier=tier))
        return spans


# Piiranha labels (from model card, 17 labels):
PIIRANHA_MAP = {
    "GIVENNAME": "PERSON", "SURNAME": "PERSON", "USERNAME": "PERSON",
    "EMAIL": "EMAIL", "TELEPHONENUM": "PHONE",
    "STREET": "ADDRESS", "CITY": "LOCATION", "ZIPCODE": "ADDRESS",
    "BUILDINGNUM": "ADDRESS", "DATEOFBIRTH": "DATE",
    "ACCOUNTNUM": "FINANCIAL", "CREDITCARDNUMBER": "FINANCIAL",
    "IDCARDNUM": "NOTE_SENSITIVE", "TAXNUM": "NOTE_SENSITIVE",
    "SOCIALNUM": "NOTE_SENSITIVE", "DRIVERLICENSENUM": "NOTE_SENSITIVE",
    "PASSWORD": "PASSWORD",
}


class PiiranhaAdapter(_HFTokenClassifierBase):
    name = "piiranha-v1"
    hf_id = "iiiorg/piiranha-v1-detect-personal-information"
    label_map = PIIRANHA_MAP


# ai4privacy ModernBERT openpii labels (≈20 categories per model card)
AI4P_MODERN_MAP = {
    "GIVENNAME": "PERSON", "SURNAME": "PERSON", "FULLNAME": "PERSON",
    "USERNAME": "PERSON", "PERSON": "PERSON",
    "EMAIL": "EMAIL", "TELEPHONENUM": "PHONE", "PHONENUMBER": "PHONE",
    "PHONE": "PHONE",
    "STREET": "ADDRESS", "BUILDINGNUM": "ADDRESS", "ZIPCODE": "ADDRESS",
    "CITY": "LOCATION", "STATE": "LOCATION", "COUNTRY": "LOCATION",
    "DATEOFBIRTH": "DATE", "DOB": "DATE", "DATE": "DATE", "TIME": "DATE",
    "ACCOUNTNUM": "FINANCIAL", "ACCOUNTNUMBER": "FINANCIAL",
    "CREDITCARDNUMBER": "FINANCIAL", "IBAN": "FINANCIAL",
    "IDCARDNUM": "NOTE_SENSITIVE", "TAXNUM": "NOTE_SENSITIVE",
    "SOCIALNUM": "NOTE_SENSITIVE", "GENDER": "NOTE_SENSITIVE",
    "SEX": "NOTE_SENSITIVE", "AGE": "NOTE_SENSITIVE",
    "URL": "URL_LOCAL",
}


class Ai4PrivacyModernBertAdapter(_HFTokenClassifierBase):
    name = "ai4privacy-modernbert-openpii"
    hf_id = "ai4privacy/llama-ai4privacy-multilingual-categorical-anonymiser-openpii"
    label_map = AI4P_MODERN_MAP


# ---- Ensemble meta-adapters ----------------------------------------------

# Runs multiple detectors and merges their spans:
#   - Union by character range; overlapping spans are deduped, keeping the
#     LONGEST span at each start (GLiNER tends to find broader, more
#     contextually-aware spans than regex, which is usually what we want).
#   - Label-conflict resolution: spans from earlier-listed detectors win on
#     label when their range is a strict subset of a later-listed detector's
#     range — this lets us seed precise structural labels (regex EMAIL) and
#     have GLiNER's broader-context predictions fill the gaps.
#
# The cost knob is which detectors are included. We register two variants:
#   - ensemble-fast: RegexBaseline + GLiNER multi_pii-v1
#       Cheap (p95 < 100ms target), no SLM, no DE-fragile components.
#   - ensemble-full: above + AnonymizerSLM
#       Adds the slow generative pass for the long tail (implicit PII,
#       free-form prose). Latency dominated by Anonymizer (~1.5s/call mean).

from typing import Sequence


# apf-t7t FP-2: GLiNER PII models conflate general science / biology /
# education vocabulary with personal HEALTH information ('Photosynthese'
# scored HEALTH @ 0.79 from nvidia/gliner-PII). This stoplist drops HEALTH
# spans whose surface is a common non-personal science term. Recall-safe
# by construction — it only ever contains terms that are NOT personal
# health info, so it cannot suppress a real health detection. Narrow v0;
# extend as the over-filter eval surfaces more. The principled long-term
# fix is detector retuning, tracked in apf-t7t.
HEALTH_TERM_STOPLIST = frozenset(s.lower() for s in {
    "photosynthesis", "photosynthese", "mitosis", "mitose", "meiosis",
    "meiose", "osmosis", "osmose", "evolution", "gravitation", "gravity",
    "thermodynamics", "thermodynamik", "algebra", "geometry", "geometrie",
    "calculus", "biology", "biologie", "chemistry", "chemie", "physics",
    "physik", "ecology", "ökologie", "photosynthesis.", "metabolism",
    "metabolismus", "respiration", "zellatmung", "ecosystem", "ökosystem",
})


def _drop_health_stoplist(spans: list[Span], text: str) -> list[Span]:
    """Drop HEALTH spans whose surface text is a known non-personal
    science / education term (apf-t7t FP-2)."""
    out: list[Span] = []
    for s in spans:
        if s.label == "HEALTH":
            surface = text[s.start:s.end].strip().lower()
            if surface in HEALTH_TERM_STOPLIST:
                continue
        out.append(s)
    return out


def _merge_spans(span_groups: Sequence[list[Span]],
                 text: str | None = None) -> list[Span]:
    """Union, dedupe, longest-wins. Earlier groups win on label when nested.

    Exception (apf-eg3): locked-category labels are always kept even when
    contained inside a larger generic-PII span. The locked-cat scan
    triggers a hard refusal (apf-enr), so a generic PERSON span swallowing
    an inner ASYLUM_STATUS span would silently disable the refusal — which
    is the precise outcome the refusal pathway exists to prevent.

    When `text` is supplied, the HEALTH science-term stoplist (apf-t7t
    FP-2) is applied to the merged result.
    """
    # Late import to avoid module-load cycle (apf.local_only imports
    # nothing from benchmarks, but keeping this lazy is cheap insurance).
    try:
        from apf.local_only import DEFAULT_LOCKED_LABELS as _LOCKED
    except ImportError:
        _LOCKED = frozenset()

    flat: list[tuple[int, Span]] = []  # (group_idx, span)
    for gi, group in enumerate(span_groups):
        for s in group:
            flat.append((gi, s))
    # Sort: by start, then by length descending so the longest span comes first
    # at each start position.
    flat.sort(key=lambda t: (t[1].start, -(t[1].end - t[1].start)))
    kept: list[tuple[int, Span]] = []
    for gi, s in flat:
        # Skip if a previously-kept span fully covers this one — UNLESS
        # this span carries a locked-category label, in which case it must
        # survive (the refusal scan depends on seeing it).
        contained = False
        if s.label not in _LOCKED:
            for kgi, ks in kept:
                if ks.start <= s.start and s.end <= ks.end:
                    contained = True
                    break
        if contained:
            continue
        # If this span fully covers a previously-kept smaller span, replace
        # the smaller one ONLY if the smaller is from a later (less trusted)
        # group; otherwise keep both since they don't strictly nest.
        new_kept: list[tuple[int, Span]] = []
        replaced = False
        for kgi, ks in kept:
            if s.start <= ks.start and ks.end <= s.end and ks != s:
                # Outer span — prefer the *more specific* (smaller, earlier-group)
                # span's label by retaining ks if it came from an earlier group.
                if kgi <= gi:
                    # Smaller earlier-group span keeps its position; absorb the
                    # outer span only if it adds tier info the inner one didn't
                    # have (rare). For simplicity: keep the smaller span.
                    new_kept.append((kgi, ks))
                    replaced = True
                else:
                    # Smaller span came from a less-trusted group — replace.
                    pass
            else:
                new_kept.append((kgi, ks))
        if not replaced:
            new_kept.append((gi, s))
        kept = new_kept
    kept.sort(key=lambda t: t[1].start)
    result = [s for _, s in kept]
    if text is not None:
        result = _drop_health_stoplist(result, text)
    return result


class EnsembleFastAdapter:
    name = "ensemble-fast"

    def __init__(self) -> None:
        self._detectors: list = []

    def warmup(self) -> None:
        from .adapters import RegexBaseline
        regex = RegexBaseline()
        gliner = GlinerMultiPiiAdapter()
        regex.warmup()
        gliner.warmup()
        self._detectors = [regex, gliner]

    def detect(self, text: str) -> list[Span]:
        groups = [d.detect(text) for d in self._detectors]
        return _merge_spans(groups, text)


class EnsembleMaxAdapter:
    """Wide net: regex (Tier B/C) + Presidio (fast NER + recognizers) +
    GLiNER multi-pii-v1 (multilingual + implicit) +
    GLiNER nvidia (high Tier-B/C precision) +
    locked-category regex (apf-eg3 v0: asylum/abuse/whistleblower/
    undocumented; emits labels the apf-enr refusal pathway gates on).
    Each component contributes a different blind-spot patch. Slower than
    ensemble-fast but should hit higher recall."""
    name = "ensemble-max"

    def __init__(self) -> None:
        self._detectors: list = []

    def warmup(self) -> None:
        from .adapters import RegexBaseline
        from .adapters_locked import LockedCategoryRegexAdapter
        regex = RegexBaseline()
        presidio = PresidioAdapter()
        gliner_multi = GlinerMultiPiiAdapter()
        gliner_nvidia = GlinerNvidiaAdapter()
        locked = LockedCategoryRegexAdapter()
        regex.warmup()
        presidio.warmup()
        gliner_multi.warmup()
        gliner_nvidia.warmup()
        locked.warmup()
        self._detectors = [regex, presidio, gliner_multi, gliner_nvidia, locked]

    def detect(self, text: str) -> list[Span]:
        groups = [d.detect(text) for d in self._detectors]
        return _merge_spans(groups, text)


class EnsembleMaxPlusAdapter:
    """ensemble-max plus the vendored DontFeedTheAI regex catalog (181 extra
    patterns). Useful where pentest-shaped data (NTLM hashes, AD usernames,
    additional vendor API-key prefixes) appears in input. Marginal cost
    (~1 ms per call) over ensemble-max."""
    name = "ensemble-max-plus"

    def __init__(self) -> None:
        self._detectors: list = []

    def warmup(self) -> None:
        from .adapters import RegexBaseline
        regex = RegexBaseline()
        presidio = PresidioAdapter()
        gliner_multi = GlinerMultiPiiAdapter()
        gliner_nvidia = GlinerNvidiaAdapter()
        regex.warmup()
        presidio.warmup()
        gliner_multi.warmup()
        gliner_nvidia.warmup()
        self._detectors = [regex, presidio, gliner_multi, gliner_nvidia]
        # Try to add vendored DFTA regex if submodule present.
        try:
            from . import adapters_dfta
            if adapters_dfta._DFTA_AVAILABLE:
                dfta = adapters_dfta.DftaRegexAdapter()
                dfta.warmup()
                self._detectors.append(dfta)
        except ImportError:
            pass

    def detect(self, text: str) -> list[Span]:
        groups = [d.detect(text) for d in self._detectors]
        return _merge_spans(groups, text)


class GlinerMultiPiiLowThresholdAdapter(_GlinerBase):
    """Same model, threshold 0.3 instead of 0.5 — buys recall, pays precision."""
    name = "gliner-multi-pii-v1-lo"
    hf_id = "urchade/gliner_multi_pii-v1"

    def __init__(self, threshold: float = 0.3) -> None:
        super().__init__(threshold=threshold)


class EnsembleFullAdapter:
    name = "ensemble-full"

    def __init__(self) -> None:
        self._detectors: list = []

    def warmup(self) -> None:
        from .adapters import RegexBaseline
        regex = RegexBaseline()
        gliner = GlinerMultiPiiAdapter()
        anon = AnonymizerSLMAdapter()
        regex.warmup()
        gliner.warmup()
        anon.warmup()
        self._detectors = [regex, gliner, anon]

    def detect(self, text: str) -> list[Span]:
        groups = [d.detect(text) for d in self._detectors]
        return _merge_spans(groups, text)


# Register on import for run.py.
# ---- Microsoft Presidio (analyzer with regex + spaCy NER) ----------------

# apf-t7t mitigation: Presidio's NRP recognizer is over-broad — it fires
# on any language or nationality name regardless of context. In benign
# patterns ('translate to German', 'a Spanish word for...') this produces
# false-positive NOTE_SENSITIVE vault entries that aren't actually PII.
# The privacy value of flagging widely-spoken language names is ~zero;
# the wider apf taxonomy (ASYLUM_STATUS, etc.) catches the truly
# sensitive nationality / origin declarations via dedicated labels.
#
# This stop-list filters single-word NRP matches that are common
# language or nationality names. Multi-word matches and uncommon names
# still pass through (where the privacy concern is more plausible).
PRESIDIO_NRP_STOPLIST = frozenset(s.lower() for s in {
    # Common languages (EN + native names)
    "english", "german", "deutsch", "spanish", "french", "italian",
    "portuguese", "dutch", "swedish", "norwegian", "danish", "finnish",
    "polish", "russian", "ukrainian", "czech", "slovak", "hungarian",
    "romanian", "bulgarian", "greek", "turkish", "arabic", "hebrew",
    "persian", "farsi", "hindi", "urdu", "bengali", "tamil", "telugu",
    "chinese", "mandarin", "cantonese", "japanese", "korean", "vietnamese",
    "thai", "indonesian", "malay", "tagalog", "filipino", "swahili",
    "latin", "esperanto",
    # Common nationality / demonym forms (matching the above)
    "english", "germans", "americans", "british", "french", "spaniards",
    "italians", "europeans", "asians", "africans",
})


PRESIDIO_MAP = {
    "PERSON": "PERSON",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "IBAN_CODE": "FINANCIAL",
    "CREDIT_CARD": "FINANCIAL",
    "US_BANK_NUMBER": "FINANCIAL",
    "IP_ADDRESS": "IP",
    "URL": "URL_LOCAL",
    "DATE_TIME": "DATE",
    "LOCATION": "LOCATION",
    "NRP": "NOTE_SENSITIVE",
    "US_SSN": "NOTE_SENSITIVE",
    "US_DRIVER_LICENSE": "NOTE_SENSITIVE",
    "US_PASSPORT": "NOTE_SENSITIVE",
    "CRYPTO": "FINANCIAL",
    "MEDICAL_LICENSE": "HEALTH",
    "IT_PASSPORT": "NOTE_SENSITIVE",
    "AU_TFN": "NOTE_SENSITIVE",
    "UK_NHS": "HEALTH",
    "SG_NRIC_FIN": "NOTE_SENSITIVE",
}


class PresidioAdapter:
    name = "presidio"

    def __init__(self, min_score: float = 0.4) -> None:
        self.min_score = min_score
        self._analyzers: dict[str, object] = {}

    def warmup(self) -> None:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        # English (default), then German alongside.
        for lang, spacy_model in [("en", "en_core_web_sm"), ("de", "de_core_news_sm")]:
            config = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": lang, "model_name": spacy_model}],
            }
            engine = NlpEngineProvider(nlp_configuration=config).create_engine()
            self._analyzers[lang] = AnalyzerEngine(nlp_engine=engine,
                                                  supported_languages=[lang])
        # Prime
        self._analyzers["en"].analyze("Hi.", language="en")

    def detect(self, text: str) -> list[Span]:
        # Cheap language guess: presence of ä/ö/ü/ß or common DE stop words → de
        lower = text.lower()
        is_de = any(c in lower for c in "äöüß") or any(
            w in lower for w in (" der ", " die ", " das ", " und ", " ich ", " ist "))
        analyzer = self._analyzers["de" if is_de else "en"]
        results = analyzer.analyze(text=text, language="de" if is_de else "en")
        spans: list[Span] = []
        for r in results:
            if r.score < self.min_score:
                continue
            label = PRESIDIO_MAP.get(r.entity_type)
            if label is None:
                continue
            tier = LABEL_TIER.get(label)
            if tier is None:
                continue
            # apf-t7t: drop NRP-derived NOTE_SENSITIVE spans whose surface
            # is a single common language / nationality. See
            # PRESIDIO_NRP_STOPLIST above for the rationale.
            if r.entity_type == "NRP":
                surface = text[r.start:r.end].strip().lower()
                if surface in PRESIDIO_NRP_STOPLIST:
                    continue
            raw = Span(start=r.start, end=r.end, label=label, tier=tier,
                       confidence=float(r.score))
            cleaned = _clean_span(text, raw)
            if cleaned is not None:
                spans.append(cleaned)
        return spans


def register(adapters: dict) -> None:
    adapters["nemotron"] = NemotronAdapter
    adapters["anonymizer"] = AnonymizerSLMAdapter
    adapters["qwen3"] = Qwen3Adapter
    adapters["gliner"] = GlinerMultiPiiAdapter
    adapters["gliner-nvidia"] = GlinerNvidiaAdapter
    adapters["gliner-knowledgator"] = GlinerKnowledgatorAdapter
    adapters["piiranha"] = PiiranhaAdapter
    adapters["ai4p-modernbert"] = Ai4PrivacyModernBertAdapter
    adapters["presidio"] = PresidioAdapter
    adapters["ensemble-fast"] = EnsembleFastAdapter
    adapters["ensemble-full"] = EnsembleFullAdapter
    adapters["ensemble-max"] = EnsembleMaxAdapter
    adapters["ensemble-max-plus"] = EnsembleMaxPlusAdapter
    adapters["gliner-lo"] = GlinerMultiPiiLowThresholdAdapter
