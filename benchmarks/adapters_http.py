"""HTTP-backed detector adapters.

Drive an external inference daemon (Ollama, oMLX, LM Studio,
llama.cpp-server, vLLM) over the OpenAI Chat Completions endpoint and
parse the response into PII spans. Cross-platform pure httpx — no MLX,
no platform-specific code.

The contract is identical to Qwen3Adapter in adapters_mlx.py: prompt the
model to emit a `{"pii":[{"text": ..., "type": ...}]}` JSON object, then
recover offsets by searching the original input. Kept duplicated (not
imported) so this module has no transitive dependency on adapters_mlx.

Profile config (model_profiles/*.toml — wired by the EnsembleMax-stage
integration in apf-yyz):

    [detector.generative_stage]
    endpoint    = "http://127.0.0.1:11434/v1"
    model       = "qwen2.5:1.5b-instruct-q4_K_M"
    api_key_env = "DETECTOR_API_KEY"   # optional
    timeout_s   = 30.0                 # optional, default 30
    max_tokens  = 512                  # optional, default 512
"""
from __future__ import annotations

import os

from .adapters import LABEL_TIER, Span


# Same span-schema prompt as Qwen3Adapter. Duplicated on purpose: keeps
# adapters_http free of any adapters_mlx import path so Linux installs
# without `mlx` still have a working generative-detector option.
DETECT_TASK = (
    "You detect personally identifiable information (PII) in text. Output ONLY "
    "a JSON object on a single line with the schema:\n"
    '{"pii":[{"text":"<exact substring>","type":"<one of: PERSON, EMAIL, '
    "PHONE, ADDRESS, LOCATION, ORG, DATE, APPOINTMENT, HEALTH, RELATIONSHIP, "
    "FINANCIAL, NOTE_SENSITIVE, IMPLICIT_PII, PATH, FILENAME, HOSTNAME, IP, "
    "URL_LOCAL, CREDENTIAL, API_KEY, PRIVATE_KEY, PASSWORD, TOKEN, "
    'CONNECTION_STRING>"}]}\n'
    'Use the exact original substring from the input. Output {"pii":[]} if none.'
)


def _parse_pii_json(raw: str) -> list[dict]:
    """Extract the {pii: [...]} object from chat-completion content.

    Tolerant of <think> blocks, prose before/after the JSON, and trailing
    chatter — picks the first balanced object whose top-level key is "pii".
    """
    import json
    import re
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    for m in re.finditer(
        r"\{[^{}]*\"pii\"\s*:\s*\[(?:[^][]|\[[^]]*\])*\][^{}]*\}",
        raw, re.DOTALL,
    ):
        try:
            data = json.loads(m.group(0))
            return data.get("pii", []) or []
        except json.JSONDecodeError:
            continue
    return []


def _infer_label_fallback(text: str) -> str:
    """Map an unknown surface form to a label via RegexBaseline patterns."""
    from .adapters import RegexBaseline
    for label, rx in RegexBaseline.PATTERNS:
        if rx.search(text):
            return label
    return "NOTE_SENSITIVE"


class OpenAICompatibleDetectorAdapter:
    """Generic OpenAI-compatible HTTP detector.

    Covers any daemon that serves /v1/chat/completions per the OpenAI
    Chat Completions spec — Ollama (`/v1` path), oMLX, LM Studio,
    llama.cpp-server, vLLM. The daemon owns the model lifecycle
    (download, load, quant, GPU placement); this adapter just speaks
    HTTP. Cross-platform.
    """

    name = "openai-compat"

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str = "",
        timeout_s: float = 30.0,
        max_tokens: int = 512,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self._client = None

    @classmethod
    def from_env(
        cls, prefix: str = "APF_GEN_DETECTOR"
    ) -> "OpenAICompatibleDetectorAdapter":
        """Build an adapter from env vars (for ad-hoc / benchmark runs).

        Reads {prefix}_ENDPOINT, {prefix}_MODEL, {prefix}_API_KEY,
        {prefix}_TIMEOUT_S, {prefix}_MAX_TOKENS. Defaults assume a local
        Ollama daemon on 11434 with a small Qwen 2.5 instruct model —
        useful as a quick "does it run at all" smoke target.
        """
        endpoint = os.environ.get(
            f"{prefix}_ENDPOINT", "http://127.0.0.1:11434/v1"
        )
        model = os.environ.get(
            f"{prefix}_MODEL", "qwen2.5:1.5b-instruct-q4_K_M"
        )
        api_key = os.environ.get(f"{prefix}_API_KEY", "")
        timeout = float(os.environ.get(f"{prefix}_TIMEOUT_S", "30"))
        max_tok = int(os.environ.get(f"{prefix}_MAX_TOKENS", "512"))
        return cls(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            timeout_s=timeout,
            max_tokens=max_tok,
        )

    def warmup(self) -> None:
        import httpx
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.Client(
            base_url=self.endpoint,
            timeout=self.timeout_s,
            headers=headers,
        )

    def detect(self, text: str) -> list[Span]:
        assert self._client is not None, "call warmup() before detect()"
        resp = self._client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": DETECT_TASK},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.0,
                "max_tokens": self.max_tokens,
                "stream": False,
            },
        )
        resp.raise_for_status()
        body = resp.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return []
        return self._content_to_spans(content, text)

    @staticmethod
    def _content_to_spans(content: str, text: str) -> list[Span]:
        items = _parse_pii_json(content)
        spans: list[Span] = []
        used: list[tuple[int, int]] = []
        for it in items:
            original = (it.get("text") or "").strip()
            if not original:
                continue
            search_from = 0
            idx = -1
            end = 0
            while True:
                idx = text.find(original, search_from)
                if idx < 0:
                    break
                end = idx + len(original)
                if not any(s < end and e > idx for s, e in used):
                    break
                search_from = idx + 1
            if idx < 0:
                continue
            type_ = (it.get("type") or "").strip().upper()
            label = (
                type_ if type_ in LABEL_TIER else _infer_label_fallback(original)
            )
            tier = LABEL_TIER.get(label, "A")
            spans.append(Span(start=idx, end=end, label=label, tier=tier))
            used.append((idx, end))
        spans.sort(key=lambda s: s.start)
        return spans


def register(adapters: dict) -> None:
    """Register HTTP adapters with the benchmark harness.

    The harness has no way to pass adapter-specific kwargs, so the
    registered factory reads its config from env vars (APF_GEN_DETECTOR_*).
    Production / proxy integration goes through model profiles —
    see apf-yyz.
    """
    adapters["openai-compat"] = lambda: OpenAICompatibleDetectorAdapter.from_env()
