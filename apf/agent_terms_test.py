"""apf-xt5: AGENT_TERMS — agent operational terms detected but not masked.

The NER detector mis-fires on agent vocabulary — most visibly tool names
like "Grep" detected as PERSON. A masked tool name breaks the agent
outright. proxy._mask_text drops a span whose *entire* text is an agent
term; partial matches stay masked.
"""
from __future__ import annotations

import apf.proxy as proxy
from apf.masker import Span
from apf.vault import Vault


def _install_detector(monkeypatch, word: str, label: str = "PERSON") -> None:
    """Stub detector flagging every occurrence of `word`."""
    class _Stub:
        name = "stub"

        def detect(self, text: str):
            spans, start = [], 0
            while (i := text.find(word, start)) != -1:
                spans.append(Span(start=i, end=i + len(word), label=label,
                                  tier="A", confidence=1.0))
                start = i + len(word)
            return spans
    monkeypatch.setattr(proxy, "_DETECTOR", _Stub())


def test_tool_name_not_masked(monkeypatch) -> None:
    _install_detector(monkeypatch, "Grep", "PERSON")
    monkeypatch.setattr(proxy, "AGENT_TERMS", frozenset({"grep"}))
    vault = Vault()
    out = proxy._mask_text("Use the Grep tool", vault)
    assert out == "Use the Grep tool"
    assert vault.all_entries() == []


def test_non_agent_term_still_masked(monkeypatch) -> None:
    _install_detector(monkeypatch, "Anneliese", "PERSON")
    monkeypatch.setattr(proxy, "AGENT_TERMS", frozenset({"grep"}))
    vault = Vault()
    out = proxy._mask_text("Hello Anneliese", vault)
    assert "Anneliese" not in out
    assert "<REF_" in out


def test_agent_term_match_is_case_insensitive(monkeypatch) -> None:
    _install_detector(monkeypatch, "GREP", "PERSON")
    monkeypatch.setattr(proxy, "AGENT_TERMS", frozenset({"grep"}))
    vault = Vault()
    assert proxy._mask_text("run GREP now", vault) == "run GREP now"


def test_partial_match_is_not_allowlisted(monkeypatch) -> None:
    # a span whose text only CONTAINS an agent term is still masked —
    # the allowlist is a whole-span match.
    _install_detector(monkeypatch, "grepson@example.de", "EMAIL")
    monkeypatch.setattr(proxy, "AGENT_TERMS", frozenset({"grep"}))
    vault = Vault()
    out = proxy._mask_text("mail grepson@example.de", vault)
    assert "grepson@example.de" not in out
    assert "<REF_" in out


def test_load_agent_terms_includes_builtins(monkeypatch) -> None:
    monkeypatch.delenv("APF_AGENT_TERMS", raising=False)
    terms = proxy._load_agent_terms()
    assert {"grep", "bash", "read", "edit"} <= terms


def test_load_agent_terms_env_extends_builtins(monkeypatch) -> None:
    monkeypatch.setenv("APF_AGENT_TERMS", "frobnicate, WidgetCo")
    terms = proxy._load_agent_terms()
    assert "grep" in terms              # built-ins still present
    assert "frobnicate" in terms        # added
    assert "widgetco" in terms          # added, lowercased
