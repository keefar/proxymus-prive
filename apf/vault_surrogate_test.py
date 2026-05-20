"""apf-okt: vault dual-mapping — a surrogate surface form alongside the
opaque token, reverse-indexed and deduplicated.

The opaque path (no surrogate_gen) must be wholly unaffected.
"""
from __future__ import annotations

import itertools

from apf.vault import Vault


def _counter_gen(prefix: str = "Fake Person"):
    """A surrogate generator that always yields a fresh unique value."""
    c = itertools.count(1)
    return lambda: f"{prefix} {next(c)}"


def test_opaque_path_unchanged_without_surrogate_gen() -> None:
    v = Vault()
    e = v.get_or_mint("Anna Müller", "PERSON", "A")
    assert e.surrogate is None
    assert e.surface == e.token == "<REF_1>"


def test_surrogate_becomes_the_surface_form() -> None:
    v = Vault()
    e = v.get_or_mint("Anna Müller", "PERSON", "A",
                      surrogate_gen=_counter_gen())
    assert e.surrogate == "Fake Person 1"
    assert e.surface == "Fake Person 1"
    assert e.token == "<REF_1>"          # opaque token still minted
    assert e.surface != e.token


def test_get_original_reverses_the_surrogate() -> None:
    v = Vault()
    e = v.get_or_mint("Anna Müller", "PERSON", "A",
                      surrogate_gen=_counter_gen())
    assert v.get_original(e.surface) == "Anna Müller"


def test_get_original_still_reverses_opaque_tokens() -> None:
    v = Vault()
    e = v.get_or_mint("Anna Müller", "PERSON", "A")
    assert v.get_original("<REF_1>") == "Anna Müller"
    assert v.get_original(e.surface) == "Anna Müller"


def test_same_original_dedups_surrogate_not_regenerated() -> None:
    v = Vault()
    gen = _counter_gen()
    first = v.get_or_mint("Anna Müller", "PERSON", "A", surrogate_gen=gen)
    again = v.get_or_mint("Anna Müller", "PERSON", "A", surrogate_gen=gen)
    assert again.surrogate == first.surrogate


def test_distinct_originals_get_distinct_surrogates() -> None:
    v = Vault()
    gen = _counter_gen()
    surrogates = {
        v.get_or_mint(name, "PERSON", "A", surrogate_gen=gen).surrogate
        for name in ("Anna", "Bert", "Cara", "Dirk")
    }
    assert len(surrogates) == 4


def test_surrogate_never_equals_the_original() -> None:
    v = Vault()
    # generator hands back the original first, then a usable value
    seq = iter(["Anna Müller", "Petra Vogel"])
    e = v.get_or_mint("Anna Müller", "PERSON", "A",
                      surrogate_gen=lambda: next(seq))
    assert e.surrogate == "Petra Vogel"


def test_tier_c_keeps_opaque_marker() -> None:
    v = Vault()
    e = v.get_or_mint("xk-live-secret", "API_KEY", "C")
    assert e.surface == e.token == "<REF>"
    assert e.surrogate is None


def test_confidence_refresh_preserves_surrogate() -> None:
    v = Vault()
    gen = _counter_gen()
    e1 = v.get_or_mint("Anna", "PERSON", "A", confidence=0.9,
                       surrogate_gen=gen)
    e2 = v.get_or_mint("Anna", "PERSON", "A", confidence=0.4,
                       surrogate_gen=gen)
    assert e2.confidence == 0.4
    assert e2.surrogate == e1.surrogate
    assert v.get_original(e2.surface) == "Anna"
