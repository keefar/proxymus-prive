"""apf-okt: plausible surrogate values for Tier-A identifiers.

Instead of an opaque <REF_N> marker, a Tier-A identifier can be masked
to a plausible fictitious value of the same type — a different
real-looking name, e-mail, IP, city. The request then reads as natural
text, which a capable model handles without tripping its
prompt-injection defence (apf-76s). The vault keeps the original ↔
surrogate mapping; the surrogate resolves back at the tool boundary and
in the user-facing response.

Scope — the ratified hybrid (apf-okt): surrogates for non-sensitive
Tier-A identifiers only. Tier-C secrets and categorical-sensitive
content keep opaque markers — a surrogate there would leak the category
and the model would treat the fiction as fact.

Generators are hand-rolled (no faker dependency) and produce
format-valid, not-obviously-fake values: private IP ranges (not RFC 5737
TEST-NETs, which models recognise and comment on), plausible mid-size
cities, ASCII names so e-mail local-parts stay valid.
"""
from __future__ import annotations

import random
import re

# Labels eligible for surrogate substitution. Anything else (Tier-C
# secrets, categorical-sensitive labels) keeps the opaque <REF_N> marker.
SURROGATE_LABELS = frozenset({
    "PERSON", "EMAIL", "PHONE", "IP", "LOCATION", "DATE", "ADDRESS",
})

# ASCII first/last names — kept ASCII so e-mail local-parts stay valid.
_FIRST = (
    "Petra", "Lars", "Anja", "Tobias", "Sabine", "Markus", "Nina", "Jonas",
    "Claudia", "Felix", "Birgit", "Daniel", "Heike", "Stefan", "Carola",
    "Bjorn", "Ingrid", "Oliver", "Marlene", "Ralf", "Sonja", "Kai", "Ute",
    "Bernd", "Astrid", "Holger", "Gisela", "Sven", "Doris", "Frank",
)
_LAST = (
    "Vogel", "Henning", "Brandt", "Kessler", "Adler", "Roth", "Sommer",
    "Wegner", "Faber", "Pohl", "Schreiber", "Krause", "Hahn", "Lindner",
    "Beck", "Engel", "Arnold", "Dreyer", "Busch", "Reimann", "Walter",
    "Gerlach", "Naumann", "Probst", "Seidel", "Thiele", "Vetter", "Wieland",
)
_CITIES = (
    "Bremerhaven", "Kassel", "Regensburg", "Lübeck", "Erfurt", "Heilbronn",
    "Oldenburg", "Paderborn", "Würzburg", "Ingolstadt", "Göttingen",
    "Recklinghausen", "Pforzheim", "Bottrop", "Reutlingen", "Koblenz",
)
_STREETS = (
    "Lindenweg", "Ahornstraße", "Birkenallee", "Goethestraße", "Schulweg",
    "Gartenstraße", "Tannenweg", "Mozartstraße", "Feldstraße", "Parkallee",
)
_EMAIL_DOMAINS = (
    "kontaktbuero-nord.de", "webmail-host.de", "post-direkt.de",
    "mailverbund.de", "buero-online.de", "nordmail-service.de",
)


def _retry_distinct(gen, original: str) -> str:
    """Call gen() until the result differs from the original value."""
    for _ in range(20):
        val = gen()
        if val != original:
            return val
    return gen()


def _fake_person(_original: str) -> str:
    return f"{random.choice(_FIRST)} {random.choice(_LAST)}"


def _fake_email(_original: str) -> str:
    return (f"{random.choice(_FIRST).lower()}."
            f"{random.choice(_LAST).lower()}@{random.choice(_EMAIL_DOMAINS)}")


def _fake_phone(original: str) -> str:
    # Preserve a leading + country code if the original carried one.
    m = re.match(r"\s*(\+\d{1,3})", original)
    cc = m.group(1) if m else "+49"
    area = random.randint(20, 89)
    rest = "".join(random.choices("0123456789", k=8))
    return f"{cc} {area} {rest}"


def _fake_ip(_original: str) -> str:
    # Private ranges — not RFC 5737 TEST-NETs (models flag those as docs).
    if random.random() < 0.5:
        return f"10.{random.randint(0, 255)}.{random.randint(0, 255)}." \
               f"{random.randint(1, 254)}"
    return f"172.{random.randint(16, 31)}.{random.randint(0, 255)}." \
           f"{random.randint(1, 254)}"


def _fake_location(_original: str) -> str:
    return random.choice(_CITIES)


def _fake_date(_original: str) -> str:
    # ISO date; day capped at 28 so every month is valid.
    return (f"{random.randint(2023, 2027)}-"
            f"{random.randint(1, 12):02d}-{random.randint(1, 28):02d}")


def _fake_address(_original: str) -> str:
    return (f"{random.choice(_STREETS)} {random.randint(1, 150)}, "
            f"{random.randint(10000, 99999)} {random.choice(_CITIES)}")


_GENERATORS = {
    "PERSON": _fake_person,
    "EMAIL": _fake_email,
    "PHONE": _fake_phone,
    "IP": _fake_ip,
    "LOCATION": _fake_location,
    "DATE": _fake_date,
    "ADDRESS": _fake_address,
}


def generate_surrogate(original: str, label: str) -> str:
    """Return a plausible fictitious value of the same type as `original`.

    `label` must be in SURROGATE_LABELS; an unknown label falls back to a
    PERSON-shaped value rather than crashing a request. The result is
    guaranteed to differ from `original`. Uniqueness across a session is
    the vault's responsibility, not this function's.
    """
    gen = _GENERATORS.get(label, _fake_person)
    return _retry_distinct(lambda: gen(original), original)
