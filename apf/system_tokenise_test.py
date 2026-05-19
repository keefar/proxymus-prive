"""apf-lnr: role=system tokenisation gating.

Default: system messages pass through verbatim (control-plane prompts
don't bloat the vault with false-positives). Opt-in via APF_TOKENISE_SYSTEM=1
for setups whose system prompts legitimately carry user PII.

Locked-category scan is independent of this flag — covered separately by
endpoint_policy_test / proxy_test.
"""
from __future__ import annotations

import apf.proxy as proxy
from apf.openai_shape import tokenise_request as oai_tokenise_request
from apf.tokenizer import Span
from apf.vault import Vault


# ── Fixture: a tokeniser_fn that doesn't need the real MLX detector ───────
def _fake_tokeniser_fn(text: str, vault: Vault) -> str:
    """Stand-in for proxy._tokenise_text. Detects literal markers so each
    test can control what looks like PII without booting the MLX model."""
    out = text
    if "ANNA" in out:
        span = Span(start=out.index("ANNA"), end=out.index("ANNA") + 4,
                    label="PERSON", tier="A", confidence=1.0)
        from apf.tokenizer import tokenize_text
        out = tokenize_text(out, [span], vault)
    return out


# ── OpenAI shape ──────────────────────────────────────────────────────────

def test_openai_system_skipped_by_default() -> None:
    """Default tokenise_system=False: system passes through, user gets tokenised."""
    vault = Vault()
    body = {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": "You help ANNA with chores."},
            {"role": "user", "content": "Hi ANNA, what's up?"},
        ],
    }
    out = oai_tokenise_request(body, vault, _fake_tokeniser_fn)
    assert out["messages"][0]["content"] == "You help ANNA with chores.", \
        "system message should be untouched"
    assert "ANNA" not in out["messages"][1]["content"], \
        "user message must be tokenised"
    assert "<REF_" in out["messages"][1]["content"]


def test_openai_system_tokenised_when_enabled() -> None:
    """tokenise_system=True: both system and user get tokenised."""
    vault = Vault()
    body = {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": "You help ANNA with chores."},
            {"role": "user", "content": "Hi ANNA, what's up?"},
        ],
    }
    out = oai_tokenise_request(body, vault, _fake_tokeniser_fn,
                               tokenise_system=True)
    assert "ANNA" not in out["messages"][0]["content"]
    assert "<REF_" in out["messages"][0]["content"]
    assert "ANNA" not in out["messages"][1]["content"]


def test_openai_system_with_array_content_skipped() -> None:
    """System with array content (vision-style parts) is also skipped by default."""
    vault = Vault()
    body = {
        "model": "gpt-test",
        "messages": [
            {"role": "system",
             "content": [{"type": "text", "text": "Help ANNA."}]},
            {"role": "user", "content": "Hi ANNA."},
        ],
    }
    out = oai_tokenise_request(body, vault, _fake_tokeniser_fn)
    assert out["messages"][0]["content"][0]["text"] == "Help ANNA."


# ── Anthropic shape (via proxy._tokenise_request_body) ────────────────────

def _install_fake_detector(monkeypatch) -> None:
    """proxy._tokenise_text guards on _DETECTOR; install a minimal stub
    so the tokenisation path runs without the real MLX model."""
    class _StubDetector:
        name = "stub"
        def detect(self, text: str):
            if "ANNA" in text:
                i = text.index("ANNA")
                return [Span(start=i, end=i + 4, label="PERSON", tier="A",
                             confidence=1.0)]
            return []
    monkeypatch.setattr(proxy, "_DETECTOR", _StubDetector())


def test_anthropic_system_skipped_by_default(monkeypatch) -> None:
    _install_fake_detector(monkeypatch)
    monkeypatch.setattr(proxy, "TOKENISE_SYSTEM", False)
    vault = Vault()
    body = {
        "model": "claude-test",
        "system": "You help ANNA with chores.",
        "messages": [{"role": "user", "content": "Hi ANNA."}],
    }
    out = proxy._tokenise_request_body(body, vault)
    assert out["system"] == "You help ANNA with chores.", \
        "system field should be untouched"
    assert "ANNA" not in out["messages"][0]["content"], \
        "user message must be tokenised"


def test_anthropic_system_tokenised_when_enabled(monkeypatch) -> None:
    _install_fake_detector(monkeypatch)
    monkeypatch.setattr(proxy, "TOKENISE_SYSTEM", True)
    vault = Vault()
    body = {
        "model": "claude-test",
        "system": "You help ANNA with chores.",
        "messages": [{"role": "user", "content": "Hi ANNA."}],
    }
    out = proxy._tokenise_request_body(body, vault)
    assert "ANNA" not in out["system"]
    assert "<REF_" in out["system"]


def test_anthropic_system_list_skipped_by_default(monkeypatch) -> None:
    """Anthropic also accepts system as a list of typed parts."""
    _install_fake_detector(monkeypatch)
    monkeypatch.setattr(proxy, "TOKENISE_SYSTEM", False)
    vault = Vault()
    body = {
        "model": "claude-test",
        "system": [{"type": "text", "text": "Help ANNA."}],
        "messages": [{"role": "user", "content": "Hi."}],
    }
    out = proxy._tokenise_request_body(body, vault)
    assert out["system"][0]["text"] == "Help ANNA."
