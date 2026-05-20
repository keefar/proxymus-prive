"""apf-uc1: assistant tool_use blocks are re-masked on the request path.

apf resolves tool_use.input on the response path so the local executor
gets real values. When the client replays that assistant message on the
next turn, the resolved value must be re-masked before it reaches the
upstream model — otherwise the boundary-resolved original leaks back
into the LLM context.
"""
from __future__ import annotations

import apf.proxy as proxy
from apf.masker import Span
from apf.vault import Vault


def _install_detector(monkeypatch) -> None:
    """Stub detector: flags the literal e-mail wherever it appears."""
    needle = "real.person@example.de"

    class _Stub:
        name = "stub"

        def detect(self, text: str):
            spans, start = [], 0
            while (i := text.find(needle, start)) != -1:
                spans.append(Span(start=i, end=i + len(needle),
                                  label="EMAIL", tier="A", confidence=1.0))
                start = i + len(needle)
            return spans
    monkeypatch.setattr(proxy, "_DETECTOR", _Stub())


def test_tool_use_input_is_remasked(monkeypatch) -> None:
    _install_detector(monkeypatch)
    vault = Vault()
    part = {"type": "tool_use", "id": "tu_1", "name": "send_email",
            "input": {"to": "real.person@example.de", "subject": "hi"}}
    out = proxy._mask_part(part, vault)
    assert "real.person@example.de" not in out["input"]["to"]
    assert "<REF_" in out["input"]["to"]
    assert out["input"]["subject"] == "hi"   # untouched
    assert out["name"] == "send_email"       # metadata preserved


def test_tool_use_remask_walks_nested_structures(monkeypatch) -> None:
    _install_detector(monkeypatch)
    vault = Vault()
    part = {"type": "tool_use", "id": "tu_2", "name": "run",
            "input": {"cmds": ["echo real.person@example.de", "ls"],
                      "meta": {"note": "to real.person@example.de"},
                      "count": 3, "flag": True}}
    out = proxy._mask_part(part, vault)
    blob = repr(out["input"])
    assert "real.person@example.de" not in blob
    assert out["input"]["count"] == 3        # non-string leaves pass through
    assert out["input"]["flag"] is True


def test_tool_use_remask_is_deterministic_with_text_masking(monkeypatch) -> None:
    # the token a replayed tool_use collapses to must equal the token the
    # same value got when first masked in a text part — same vault.
    _install_detector(monkeypatch)
    vault = Vault()
    masked_text = proxy._mask_text("contact real.person@example.de", vault)
    token = masked_text.split()[-1]
    part = {"type": "tool_use", "id": "tu_3", "name": "send_email",
            "input": {"to": "real.person@example.de"}}
    out = proxy._mask_part(part, vault)
    assert out["input"]["to"] == token


def test_tool_use_without_input_is_untouched(monkeypatch) -> None:
    _install_detector(monkeypatch)
    vault = Vault()
    part = {"type": "tool_use", "id": "tu_4", "name": "noop"}
    assert proxy._mask_part(part, vault) == part
