"""apf-okt: surrogate generator — plausible, format-valid, type-correct.

Surrogates must look real (a model must not flag them as fake) and be
format-valid (a malformed e-mail / IP would break a tool call).
"""
from __future__ import annotations

import datetime
import re

from apf.surrogates import SURROGATE_LABELS, generate_surrogate


def test_surrogate_labels_are_the_ratified_set() -> None:
    assert SURROGATE_LABELS == {
        "PERSON", "EMAIL", "PHONE", "IP", "LOCATION", "DATE", "ADDRESS"}


def test_every_label_yields_nonempty_distinct_value() -> None:
    for label in SURROGATE_LABELS:
        out = generate_surrogate("original-value", label)
        assert out and out != "original-value"


def test_person_is_two_words() -> None:
    assert len(generate_surrogate("Anna Müller", "PERSON").split()) == 2


def test_email_is_format_valid() -> None:
    for _ in range(20):
        out = generate_surrogate("anna@example.de", "EMAIL")
        assert re.fullmatch(r"[a-z]+\.[a-z]+@[a-z0-9.-]+\.[a-z]+", out), out


def test_ip_is_a_valid_address() -> None:
    for _ in range(20):
        octets = generate_surrogate("8.8.8.8", "IP").split(".")
        assert len(octets) == 4
        assert all(0 <= int(o) <= 255 for o in octets)


def test_ip_avoids_rfc5737_test_nets() -> None:
    # models recognise 192.0.2/198.51.100/203.0.113 as documentation ranges
    for _ in range(30):
        ip = generate_surrogate("8.8.8.8", "IP")
        assert not ip.startswith(("192.0.2.", "198.51.100.", "203.0.113."))


def test_phone_preserves_country_code() -> None:
    assert generate_surrogate("+1 202 5550199", "PHONE").startswith("+1 ")
    assert generate_surrogate("+49 30 12345678", "PHONE").startswith("+49 ")
    # no country code in the original -> a default one is supplied
    assert generate_surrogate("030 12345678", "PHONE").startswith("+")


def test_date_is_a_valid_iso_date() -> None:
    for _ in range(20):
        out = generate_surrogate("2026-06-15", "DATE")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", out), out
        y, m, d = (int(x) for x in out.split("-"))
        datetime.date(y, m, d)  # raises if invalid


def test_address_has_postcode_and_comma() -> None:
    out = generate_surrogate("Hauptstraße 1, 10115 Berlin", "ADDRESS")
    assert "," in out
    assert re.search(r"\b\d{5}\b", out)


def test_generator_is_varied() -> None:
    seen = {generate_surrogate("x", "PERSON") for _ in range(30)}
    assert len(seen) > 1


def test_unknown_label_falls_back_without_crashing() -> None:
    out = generate_surrogate("something", "NOT_A_LABEL")
    assert out and out != "something"
