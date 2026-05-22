"""apf-c1b: GET /v1/sessions lists active session ids + counts-only summaries.

apf's per-session endpoints (status / audit / uncertain / whitelist) are all
keyed by session id, but a client driven through apf (e.g. Hermes) sends no
x-apf-session header — apf assigns an anon-<uuid> the caller never sees, so
the session cannot be inspected afterwards. This endpoint makes the live
sessions discoverable. The per-session payload is vault.summary() — counts
only, no original values, no surface tokens (same data as
/v1/sessions/{id}/status, already deemed safe to surface).

TestClient is used without its context manager so the FastAPI lifespan (and
the MLX detector load) is skipped — this endpoint never touches the detector.
"""
from __future__ import annotations

import os

os.environ.setdefault("APF_UPSTREAM_BASE", "http://mock-upstream.invalid")
os.environ.setdefault("APF_OPENAI_UPSTREAM",
                      "http://mock-openai-upstream.invalid")

from fastapi.testclient import TestClient  # noqa: E402

import apf.proxy as proxy  # noqa: E402

_SUMMARY_KEYS = {"total", "per_tier", "per_label", "third_party"}


def test_list_sessions_empty(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "_VAULTS", {})
    resp = TestClient(proxy.app).get("/v1/sessions")
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "sessions": []}


def test_list_sessions_reports_ids_and_summaries(monkeypatch) -> None:
    monkeypatch.setattr(proxy, "_VAULTS", {})
    proxy._get_or_create_vault("sess-a")
    proxy._get_or_create_vault("anon-deadbeef0001")
    resp = TestClient(proxy.app).get("/v1/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert {s["session_id"] for s in body["sessions"]} == {
        "sess-a", "anon-deadbeef0001"}
    # Every session carries the counts-only summary shape — nothing else,
    # so no original value or surface token can ride along.
    for s in body["sessions"]:
        assert set(s["summary"]) == _SUMMARY_KEYS
