"""apf-76s: the privacy-filter explainer is injected only when masking
actually happened, into both request shapes, and is env-opt-outable.
"""
from __future__ import annotations

from apf.explainer import (EXPLAINER_TEXT, explainer_enabled,
                           inject_into_anthropic, inject_into_openai)
from apf.vault import Vault


def _vault(*, empty: bool) -> Vault:
    v = Vault()
    if not empty:
        v.get_or_mint("Anna Müller", "PERSON", "A")
    return v


def test_anthropic_no_injection_when_vault_empty() -> None:
    body = {"system": "base", "messages": []}
    assert inject_into_anthropic(body, _vault(empty=True)) == body


def test_anthropic_injects_into_string_system() -> None:
    out = inject_into_anthropic({"system": "base"}, _vault(empty=False))
    assert out["system"].startswith(EXPLAINER_TEXT)
    assert out["system"].endswith("base")


def test_anthropic_injects_into_list_system() -> None:
    body = {"system": [{"type": "text", "text": "base"}]}
    out = inject_into_anthropic(body, _vault(empty=False))
    assert out["system"][0] == {"type": "text", "text": EXPLAINER_TEXT}
    assert out["system"][1]["text"] == "base"


def test_anthropic_injects_when_system_absent() -> None:
    out = inject_into_anthropic({"messages": []}, _vault(empty=False))
    assert out["system"] == [{"type": "text", "text": EXPLAINER_TEXT}]


def test_openai_injects_system_message() -> None:
    body = {"messages": [{"role": "user", "content": "hi"}]}
    out = inject_into_openai(body, _vault(empty=False))
    assert out["messages"][0] == {"role": "system", "content": EXPLAINER_TEXT}
    assert out["messages"][1]["role"] == "user"


def test_openai_no_injection_when_vault_empty() -> None:
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert inject_into_openai(body, _vault(empty=True)) == body


def test_opt_out_via_env(monkeypatch) -> None:
    monkeypatch.setenv("APF_EXPLAINER", "off")
    assert not explainer_enabled()
    body = {"system": "base"}
    assert inject_into_anthropic(body, _vault(empty=False)) == body


def test_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("APF_EXPLAINER", raising=False)
    assert explainer_enabled()


def test_input_body_not_mutated() -> None:
    body = {"system": "base", "messages": []}
    inject_into_anthropic(body, _vault(empty=False))
    assert body == {"system": "base", "messages": []}
