"""apf-8pz: OpenAI-shape reasoning_content masking round-trip.

Reasoning models return their trace in message.reasoning_content. apf
must unmask it for display (the user sees originals, like in content)
AND re-mask it on the way back, so a replayed trace cannot leak
originals to the upstream. The two halves must be symmetric — unmasking
without the matching mask would turn a display convenience into a leak.
"""
from __future__ import annotations

from apf.openai_shape import mask_request, unmask_response
from apf.vault import Vault

_PII = {"Anna Müller": "PERSON", "anna@example.de": "EMAIL"}


def _masker(text: str, vault: Vault) -> str:
    """Minimal masker_fn stand-in: mints a vault entry for known PII."""
    for original, label in _PII.items():
        if original in text:
            entry = vault.get_or_mint(original, label, "A")
            text = text.replace(original, entry.token)
    return text


def test_unmask_response_restores_reasoning_content() -> None:
    vault = Vault()
    token = vault.get_or_mint("Anna Müller", "PERSON", "A").token
    body = {"choices": [{"index": 0, "message": {
        "role": "assistant",
        "reasoning_content": f"The user wants to contact {token}.",
        "content": f"Done — messaged {token}.",
    }}]}

    out = unmask_response(body, vault, secret_resolver=None)
    msg = out["choices"][0]["message"]

    assert msg["reasoning_content"] == "The user wants to contact Anna Müller."
    assert msg["content"] == "Done — messaged Anna Müller."


def test_mask_request_masks_reasoning_content() -> None:
    vault = Vault()
    body = {"messages": [{
        "role": "assistant",
        "reasoning_content": "Plan: email Anna Müller at anna@example.de.",
        "content": "On it.",
    }]}

    out = mask_request(body, vault, _masker)
    reasoning = out["messages"][0]["reasoning_content"]

    assert "Anna Müller" not in reasoning
    assert "anna@example.de" not in reasoning
    assert "<REF" in reasoning


def test_reasoning_content_replay_does_not_leak() -> None:
    """A trace unmasked for display, replayed in the next request, must
    be re-masked — originals must never reach the upstream."""
    vault = Vault()
    vault.get_or_mint("Anna Müller", "PERSON", "A")
    # what the user saw after _unmask_choice restored the trace:
    displayed_trace = "Earlier I decided to ping Anna Müller first."
    body = {"messages": [{"role": "assistant",
                          "reasoning_content": displayed_trace}]}

    out = mask_request(body, vault, _masker)

    assert "Anna Müller" not in out["messages"][0]["reasoning_content"]


def test_no_reasoning_content_is_harmless() -> None:
    """Messages without reasoning_content pass through untouched."""
    vault = Vault()
    token = vault.get_or_mint("Anna Müller", "PERSON", "A").token
    body = {"choices": [{"index": 0, "message": {
        "role": "assistant", "content": f"Hi {token}."}}]}

    out = unmask_response(body, vault, secret_resolver=None)
    msg = out["choices"][0]["message"]

    assert "reasoning_content" not in msg
    assert msg["content"] == "Hi Anna Müller."
