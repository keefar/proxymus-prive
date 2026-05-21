"""apf-3pe: a streaming /v1/messages request whose upstream returns an
error (e.g. 429) must surface that status to the client — not a 200
StreamingResponse wrapping the error JSON.

Before the fix, `_stream_messages` returned a StreamingResponse (HTTP 200)
regardless of upstream status, so the client saw 200 + a non-SSE body.
The streaming proxy path otherwise had no test coverage; the 200 case
here is also its first happy-path regression guard.
"""
from __future__ import annotations

import os

os.environ.setdefault("APF_UPSTREAM_BASE", "http://mock-upstream.invalid")
os.environ.setdefault("APF_OPENAI_UPSTREAM",
                      "http://mock-openai-upstream.invalid")

from fastapi.testclient import TestClient  # noqa: E402

import apf.proxy as proxy  # noqa: E402


class _FakeStreamResp:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = {"content-type": "application/json"}

    async def aread(self) -> bytes:
        return self._body

    async def aiter_text(self):
        yield self._body.decode("utf-8")

    async def aclose(self) -> None:
        pass


class _FakeClient:
    """Stand-in for httpx.AsyncClient. Supports both the pre-fix path
    (`async with client.stream(...)`) and the post-fix path
    (`client.send(client.build_request(...), stream=True)`), so the same
    429 test fails before the fix and passes after."""

    def __init__(self, resp: _FakeStreamResp) -> None:
        self._resp = resp

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *a) -> bool:
        return False

    def stream(self, *a, **kw):
        resp = self._resp

        class _Ctx:
            async def __aenter__(self_inner):
                return resp

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()

    def build_request(self, *a, **kw):
        return object()

    async def send(self, request, stream: bool = False):
        return self._resp

    async def aclose(self) -> None:
        pass


class _NullDetector:
    name = "null"

    def warmup(self) -> "_NullDetector":
        return self

    def detect(self, text: str):
        return []


def _post_stream(monkeypatch, status_code: int, body: bytes):
    monkeypatch.setattr(proxy, "_DETECTOR", _NullDetector())
    monkeypatch.setattr(
        proxy.httpx, "AsyncClient",
        lambda *a, **kw: _FakeClient(_FakeStreamResp(status_code, body)))
    client = TestClient(proxy.app)
    return client.post(
        "/v1/messages",
        json={"model": "claude-opus-4-7", "max_tokens": 16, "stream": True,
              "messages": [{"role": "user", "content": "hello there"}]},
        headers={"x-api-key": "k", "x-apf-session": "s-3pe"},
    )


def test_streaming_upstream_429_surfaces_429(monkeypatch) -> None:
    err = (b'{"type":"error","error":{"type":"rate_limit_error",'
           b'"message":"Error"}}')
    resp = _post_stream(monkeypatch, 429, err)
    assert resp.status_code == 429, (
        f"a streaming upstream 429 must reach the client as 429, "
        f"got {resp.status_code}")
    assert b"rate_limit_error" in resp.content


def test_streaming_upstream_200_still_streams(monkeypatch) -> None:
    # The fix must not break the happy path: a 200 upstream still yields
    # a normal 200 streaming response.
    resp = _post_stream(monkeypatch, 200, b"")
    assert resp.status_code == 200, (
        f"a streaming upstream 200 must stay 200, got {resp.status_code}")
