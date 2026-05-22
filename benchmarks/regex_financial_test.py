"""apf-6ql: crypto + financial regex coverage in RegexBaseline.

The ai4privacy fixtures carry ~55 financial false negatives the detector
ensemble missed: crypto addresses (Bitcoin base58, Ethereum 0x-hex), bare
13-19 digit card numbers, keyword-anchored account numbers, and amounts
(currency-prefixed, k/m/b-suffixed, or thousands-separated).

All of these are gold-labelled FINANCIAL (tier A) — the new patterns must
land at label FINANCIAL / tier A, and crypto must out-rank the existing
base64 CREDENTIAL catch-all so a 32+-char base58 address is not mislabelled.
"""
from __future__ import annotations

from benchmarks.adapters import RegexBaseline


def _detect(text: str) -> list[tuple[str, str, str]]:
    """Return (surface, label, tier) tuples for a detector run."""
    det = RegexBaseline()
    return [(text[s.start:s.end], s.label, s.tier) for s in det.detect(text)]


# ---- Bitcoin / crypto addresses ------------------------------------------

def test_bitcoin_p2pkh_address() -> None:
    text = "Send to 1Hdhe78mVPJmFMcZjGCs7ozkTSKm5 please."
    hits = _detect(text)
    assert ("1Hdhe78mVPJmFMcZjGCs7ozkTSKm5", "FINANCIAL", "A") in hits


def test_bitcoin_p2sh_address() -> None:
    text = "Wallet 3EoyajsVBXYD6r4rdoexYVtB4yfWSM7e is funded."
    hits = _detect(text)
    assert ("3EoyajsVBXYD6r4rdoexYVtB4yfWSM7e", "FINANCIAL", "A") in hits


def test_long_bitcoin_address_not_mislabelled_credential() -> None:
    """A 32+-char base58 address would match the base64 CREDENTIAL
    catch-all; the crypto pattern must win the overlap dedup."""
    text = "addr 1UdZzQ45snYxE2cH9RSf2jBtuGdgTRLWZhx31xX done"
    hits = _detect(text)
    labels = {label for surface, label, _ in hits
              if surface.startswith("1UdZzQ")}
    assert labels == {"FINANCIAL"}, hits


def test_ethereum_address() -> None:
    text = "ETH 0x085ec558a3b05187811d9f5cf38e182dcacaaead received."
    hits = _detect(text)
    assert ("0x085ec558a3b05187811d9f5cf38e182dcacaaead",
            "FINANCIAL", "A") in hits


def test_ethereum_address_case_insensitive_hex() -> None:
    text = "0xC9d3F887bA4efBAAa3aBABddb7DC3e5a5bc9BC3A"
    hits = _detect(text)
    assert any(label == "FINANCIAL" for _, label, _ in hits)


# ---- Card / account numbers ----------------------------------------------

def test_bare_16_digit_card_number() -> None:
    text = "Validate 7338684709509854 for the transaction."
    hits = _detect(text)
    assert ("7338684709509854", "FINANCIAL", "A") in hits


def test_13_digit_number_matches() -> None:
    text = "Card 4253172035722 on file."
    hits = _detect(text)
    assert ("4253172035722", "FINANCIAL", "A") in hits


def test_short_number_not_matched_as_card() -> None:
    """A 6-digit number is not a card — must not over-fire FINANCIAL."""
    text = "Order 123456 shipped."
    hits = _detect(text)
    assert not any(label == "FINANCIAL" and surface == "123456"
                   for surface, label, _ in hits)


def test_account_number_keyword_anchored() -> None:
    text = "Bitte auf das Konto 02817631 ueberweisen."
    hits = _detect(text)
    assert ("02817631", "FINANCIAL", "A") in hits


def test_account_number_english_keyword() -> None:
    text = "Payment through account 67212066 before noon."
    hits = _detect(text)
    assert ("67212066", "FINANCIAL", "A") in hits


def test_bare_8_digits_without_keyword_not_matched() -> None:
    """Bare 8-digit numbers with no account keyword stay unmatched —
    matching them standalone would be a precision disaster."""
    text = "Build 20260522 completed."
    hits = _detect(text)
    assert not any(surface == "20260522" for surface, _, _ in hits)


# ---- Amounts -------------------------------------------------------------

def test_amount_with_currency_symbol_prefix() -> None:
    text = "Die Kosten betragen лв245,251.49 insgesamt."
    hits = _detect(text)
    assert any(label == "FINANCIAL" and "245,251.49" in surface
               for surface, label, _ in hits)


def test_amount_with_magnitude_suffix() -> None:
    text = "Es sollte 554k gewesen sein."
    hits = _detect(text)
    assert any(label == "FINANCIAL" and "554k" in surface
               for surface, label, _ in hits)


def test_amount_decimal_magnitude_suffix() -> None:
    text = "A payment of 894.3k is due."
    hits = _detect(text)
    assert any(label == "FINANCIAL" and "894.3k" in surface
               for surface, label, _ in hits)


def test_amount_with_currency_code() -> None:
    text = "Transfer 19430.46 LAK from the account."
    hits = _detect(text)
    assert any(label == "FINANCIAL" and "19430.46" in surface
               for surface, label, _ in hits)


def test_plain_integer_not_matched_as_amount() -> None:
    """A bare integer with no currency context is not flagged AMOUNT."""
    text = "We saw 42 users today."
    hits = _detect(text)
    assert not any(surface == "42" for surface, _, _ in hits)


# ---- IBAN (unspaced) -----------------------------------------------------

def test_unspaced_iban() -> None:
    text = "IBAN AE670348204078003006255 confirmed."
    hits = _detect(text)
    assert any(label == "FINANCIAL" and "AE670348204078003006255" in surface
               for surface, label, _ in hits)
