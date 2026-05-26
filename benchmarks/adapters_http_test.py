"""Tests for the OpenAI-compatible HTTP detector adapter.

These exercise the parser + offset recovery + request shape without a
real daemon — httpx.Client is monkeypatched. The same code path is what
runs against Ollama, oMLX, LM Studio, llama.cpp-server, vLLM, etc.; the
adapter only cares about the OpenAI Chat Completions wire format, not
which backend serves it.
"""
from __future__ import annotations

from benchmarks.adapters_http import (
    OpenAICompatibleDetectorAdapter,
    _infer_label_fallback,
    _parse_pii_json,
)


def test_parse_pii_json_simple() -> None:
    raw = '{"pii":[{"text":"Alice","type":"PERSON"}]}'
    assert _parse_pii_json(raw) == [{"text": "Alice", "type": "PERSON"}]


def test_parse_pii_json_strips_think_block() -> None:
    # Some reasoning models (Qwen3, DeepSeek-R1) emit <think>...</think>
    # before the answer. The parser must skip that and find the JSON after.
    raw = (
        "<think>The text contains an email address.</think>\n"
        '{"pii":[{"text":"alice@example.com","type":"EMAIL"}]}'
    )
    assert _parse_pii_json(raw) == [
        {"text": "alice@example.com", "type": "EMAIL"}
    ]


def test_parse_pii_json_empty_pii_array() -> None:
    assert _parse_pii_json('{"pii":[]}') == []


def test_parse_pii_json_garbage_returns_empty() -> None:
    assert _parse_pii_json("not json at all") == []
    assert _parse_pii_json("") == []


def test_parse_pii_json_tolerates_prose_around() -> None:
    raw = (
        "Here is the result:\n"
        '{"pii":[{"text":"Bob","type":"PERSON"}]}\n'
        "Hope this helps!"
    )
    assert _parse_pii_json(raw) == [{"text": "Bob", "type": "PERSON"}]


def test_content_to_spans_recovers_offsets() -> None:
    text = "Hi Alice, please email bob@example.com about the meeting."
    content = (
        '{"pii":['
        '{"text":"Alice","type":"PERSON"},'
        '{"text":"bob@example.com","type":"EMAIL"}'
        "]}"
    )
    spans = OpenAICompatibleDetectorAdapter._content_to_spans(content, text)
    assert len(spans) == 2
    assert (spans[0].start, spans[0].end, spans[0].label) == (3, 8, "PERSON")
    assert spans[1].label == "EMAIL"
    assert text[spans[1].start:spans[1].end] == "bob@example.com"


def test_content_to_spans_unknown_label_uses_regex_fallback() -> None:
    # Model returned a label we do not know. Regex fallback recognises the
    # AWS access key prefix and maps to API_KEY (cross-checked: present in
    # RegexBaseline.PATTERNS).
    text = "key id: AKIA1234567890ABCDEF here"
    content = (
        '{"pii":[{"text":"AKIA1234567890ABCDEF","type":"SOMETHING_WEIRD"}]}'
    )
    spans = OpenAICompatibleDetectorAdapter._content_to_spans(content, text)
    assert len(spans) == 1
    assert spans[0].label == "API_KEY"


def test_content_to_spans_skips_non_substrings() -> None:
    # Models hallucinate. If the claimed PII text isn't actually in the
    # input, drop it rather than inserting a fake span.
    text = "Hello world."
    content = '{"pii":[{"text":"NotInText","type":"PERSON"}]}'
    assert (
        OpenAICompatibleDetectorAdapter._content_to_spans(content, text) == []
    )


def test_content_to_spans_handles_repeated_substrings() -> None:
    # Two distinct items with the same surface form should get two distinct
    # non-overlapping spans.
    text = "Alice met Alice at noon."
    content = (
        '{"pii":['
        '{"text":"Alice","type":"PERSON"},'
        '{"text":"Alice","type":"PERSON"}'
        "]}"
    )
    spans = OpenAICompatibleDetectorAdapter._content_to_spans(content, text)
    assert len(spans) == 2
    assert spans[0].start == 0 and spans[0].end == 5
    assert spans[1].start == 10 and spans[1].end == 15


def test_infer_label_fallback_default_note_sensitive() -> None:
    # No regex match => fall back to NOTE_SENSITIVE (tier A catch-all).
    assert _infer_label_fallback("nothing special") == "NOTE_SENSITIVE"


def test_detect_posts_to_chat_completions(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"pii":[{"text":"Alice","type":"PERSON"}]}'
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, **kw):
            captured["init_kw"] = kw

        def post(self, path: str, json: dict):
            captured["path"] = path
            captured["body"] = json
            return FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)

    adapter = OpenAICompatibleDetectorAdapter(
        endpoint="http://127.0.0.1:11434/v1",
        model="qwen2.5:1.5b-instruct-q4_K_M",
        api_key="testkey",
        max_tokens=256,
    )
    adapter.warmup()
    spans = adapter.detect("Hi Alice.")

    assert len(spans) == 1
    assert spans[0].label == "PERSON"
    assert captured["path"] == "/chat/completions"
    assert captured["body"]["model"] == "qwen2.5:1.5b-instruct-q4_K_M"
    assert captured["body"]["stream"] is False
    assert captured["body"]["temperature"] == 0.0
    assert captured["body"]["max_tokens"] == 256
    # System prompt + user turn — order matters for chat templates.
    msgs = captured["body"]["messages"]
    assert msgs[0]["role"] == "system"
    assert "PII" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "Hi Alice."}
    # Auth header propagated.
    assert (
        captured["init_kw"]["headers"]["Authorization"] == "Bearer testkey"
    )


def test_detect_handles_malformed_response(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None: ...
        def json(self) -> dict:
            return {"unexpected": "shape"}

    class FakeClient:
        def __init__(self, **kw): ...
        def post(self, path: str, json: dict):
            return FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "Client", FakeClient)

    adapter = OpenAICompatibleDetectorAdapter(
        endpoint="http://x", model="m"
    )
    adapter.warmup()
    # Malformed response shape => empty spans, no crash.
    assert adapter.detect("anything") == []


def test_from_env_defaults(monkeypatch) -> None:
    monkeypatch.delenv("APF_GEN_DETECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("APF_GEN_DETECTOR_MODEL", raising=False)
    monkeypatch.delenv("APF_GEN_DETECTOR_API_KEY", raising=False)
    adapter = OpenAICompatibleDetectorAdapter.from_env()
    assert adapter.endpoint.startswith("http")
    assert adapter.model
    assert adapter.api_key == ""


def test_from_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("APF_GEN_DETECTOR_ENDPOINT", "http://my-host:8080/v1/")
    monkeypatch.setenv("APF_GEN_DETECTOR_MODEL", "mistral:7b-instruct")
    monkeypatch.setenv("APF_GEN_DETECTOR_API_KEY", "abc123")
    monkeypatch.setenv("APF_GEN_DETECTOR_TIMEOUT_S", "45")
    monkeypatch.setenv("APF_GEN_DETECTOR_MAX_TOKENS", "1024")
    adapter = OpenAICompatibleDetectorAdapter.from_env()
    assert adapter.endpoint == "http://my-host:8080/v1"  # trailing / stripped
    assert adapter.model == "mistral:7b-instruct"
    assert adapter.api_key == "abc123"
    assert adapter.timeout_s == 45.0
    assert adapter.max_tokens == 1024


def test_register_adds_factory() -> None:
    from benchmarks.adapters_http import register
    adapters: dict = {}
    register(adapters)
    assert "openai-compat" in adapters
    # Factory is callable (don't actually instantiate here — that would
    # try to read env). Just confirm it's wired.
    assert callable(adapters["openai-compat"])
