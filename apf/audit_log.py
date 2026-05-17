"""In-memory audit log (apf-ive v1 scaffold).

Records per-message category counts when explicitly enabled. Default
state is OFF — the audit log is itself a concentrated attack target
(anyone who reads it learns exactly what categories you've processed
over the recording window), so the user opts in deliberately.

v1 — in-memory only:
- enable via env APF_AUDIT_LOG=1
- in-process ring buffer, evicts oldest beyond MAX_ENTRIES
- entry shape: timestamp + session_id + per-category counts (NO values,
  NO surface tokens — never the values themselves)
- inspect via /v1/sessions/{id}/audit (proxy.py)

v2 — durable storage (DEFERRED, not in this commit):
- macOS Keychain-derived symmetric key
- ~/.local/share/apf/audit.sqlite3
- 30-day rolling retention
- Same data shape; only the substrate changes

Important non-goal: the log NEVER stores original values, surface
tokens, or detected text. Counts and labels only. If the user wants
to know what the proxy did to a specific message, the request body is
the source of truth (transient by definition); the audit log only
answers 'how often, in which categories, over time'.
"""
from __future__ import annotations

import os
import time
from collections import deque
from threading import Lock
from typing import Iterable

MAX_ENTRIES = 1000  # per-process ring buffer cap


def _enabled() -> bool:
    return os.environ.get("APF_AUDIT_LOG", "0") not in ("0", "", "false", "no")


class AuditLog:
    """Per-session-scope-agnostic in-memory append-only log. One instance
    is shared by all sessions in a single proxy process; entries carry
    their session_id so per-session queries filter at read time."""

    def __init__(self) -> None:
        self._entries: deque[dict] = deque(maxlen=MAX_ENTRIES)
        self._lock = Lock()

    def record(self, session_id: str, summary: dict) -> None:
        """Append one entry. summary is the vault.summary() shape, but
        we strip any keys that might inadvertently carry values — only
        counts survive."""
        if not _enabled():
            return
        # Defensive copy + sanitisation. We accept the caller could pass
        # an extended summary in future; only allow scalar counts through.
        safe = {
            "total": int(summary.get("total", 0)),
            "per_tier": {
                str(k): int(v) for k, v in (summary.get("per_tier") or {}).items()
            },
            "per_label": {
                str(k): int(v) for k, v in (summary.get("per_label") or {}).items()
            },
            "third_party": int(summary.get("third_party", 0)),
        }
        with self._lock:
            self._entries.append({
                "ts": time.time(),
                "session_id": session_id,
                "summary": safe,
            })

    def entries_for(self, session_id: str | None = None) -> list[dict]:
        with self._lock:
            if session_id is None:
                return list(self._entries)
            return [e for e in self._entries if e["session_id"] == session_id]

    def __len__(self) -> int:
        return len(self._entries)


# Module-level singleton — one log per proxy process.
LOG = AuditLog()


def enabled() -> bool:
    """Public predicate so callers can avoid building summary payloads
    when audit is off."""
    return _enabled()
