"""Standalone test of the SSE rewriter.

Verifies:
1. Text deltas with tokens get unmasked, even when the token straddles
   chunk boundaries.
2. Tool-use input JSON is accumulated across deltas, parsed at
   content_block_stop, resolved via the vault, and emitted as a single
   final delta.
3. Tier-C `<REF>` markers in text are NOT auto-resolved (they're
   ambiguous when multiple secrets are vaulted).
"""
from __future__ import annotations

import sys

from apf.sse import SSERewriter
from apf.vault import Vault


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        print(f"FAIL  {label}")
        print(f"  expected: {expected!r}")
        print(f"  actual:   {actual!r}")
        sys.exit(1)
    print(f"  ok    {label}")


def collect(events: list) -> list[tuple[str, dict]]:
    """Flatten the [(type, data), …] feed output into a single list."""
    return list(events)


def text_deltas_from(stream: list[tuple[str, dict]]) -> str:
    """Join all text_delta payloads in order."""
    out = []
    for ev_type, data in stream:
        if (ev_type == "content_block_delta"
                and data.get("delta", {}).get("type") == "text_delta"):
            out.append(data["delta"]["text"])
    return "".join(out)


def tool_input_jsons(stream: list[tuple[str, dict]]) -> list[str]:
    out = []
    for ev_type, data in stream:
        if (ev_type == "content_block_delta"
                and data.get("delta", {}).get("type") == "input_json_delta"):
            out.append(data["delta"]["partial_json"])
    return out


def test_text_token_straddle() -> None:
    print("\n=== Test 1: token straddles chunk boundary ===")
    vault = Vault()
    e = vault.get_or_mint("anna@example.de", "EMAIL", "A")
    # e.token is "<REF_1>" under the opaque-default scheme.
    rew = SSERewriter(vault)

    # Simulate upstream stream that splits e.token across two text deltas.
    split_at = len(e.token) // 2
    chunk_a = "Send to " + e.token[:split_at]
    chunk_b = e.token[split_at:] + " at 3pm."
    out = []
    out.extend(rew.feed("content_block_start",
                        {"type": "content_block_start", "index": 0,
                         "content_block": {"type": "text", "text": ""}}))
    out.extend(rew.feed("content_block_delta",
                        {"type": "content_block_delta", "index": 0,
                         "delta": {"type": "text_delta", "text": chunk_a}}))
    out.extend(rew.feed("content_block_delta",
                        {"type": "content_block_delta", "index": 0,
                         "delta": {"type": "text_delta", "text": chunk_b}}))
    out.extend(rew.feed("content_block_stop",
                        {"type": "content_block_stop", "index": 0}))
    out.extend(rew.flush())

    full = text_deltas_from(out)
    if e.token in full:
        print(f"FAIL  token leaked through to client text: {full!r}")
        sys.exit(1)
    if "anna@example.de" not in full:
        print(f"FAIL  original not restored: {full!r}")
        sys.exit(1)
    print(f"  ok    text reassembled: {full!r}")


def test_tool_use_resolution() -> None:
    print("\n=== Test 2: tool_use input JSON resolves at content_block_stop ===")
    vault = Vault()
    e = vault.get_or_mint("thomas.weber@example.de", "EMAIL", "A")
    p = vault.get_or_mint("Anna", "PERSON", "A")

    rew = SSERewriter(vault)
    out = []
    out.extend(rew.feed("content_block_start",
                        {"type": "content_block_start", "index": 0,
                         "content_block": {"type": "tool_use", "id": "tu_1",
                                           "name": "send_email", "input": {}}}))
    # Stream the JSON in fragments
    fragments = [
        '{"to": "',
        e.token,
        '", "body": "Hi ',
        p.token,
        ', see attached."}',
    ]
    for frag in fragments:
        out.extend(rew.feed("content_block_delta",
                            {"type": "content_block_delta", "index": 0,
                             "delta": {"type": "input_json_delta",
                                       "partial_json": frag}}))
    out.extend(rew.feed("content_block_stop",
                        {"type": "content_block_stop", "index": 0}))
    out.extend(rew.flush())

    jsons = tool_input_jsons(out)
    # During streaming, no input_json_delta should have been forwarded —
    # they're held back until content_block_stop.
    if len(jsons) != 1:
        print(f"FAIL  expected 1 emitted input_json_delta (the resolved one), got {len(jsons)}: {jsons!r}")
        sys.exit(1)
    resolved = jsons[0]
    if e.token in resolved or p.token in resolved:
        print(f"FAIL  tokens still in resolved JSON: {resolved!r}")
        sys.exit(1)
    if "thomas.weber@example.de" not in resolved or "Anna" not in resolved:
        print(f"FAIL  originals missing in resolved JSON: {resolved!r}")
        sys.exit(1)
    print(f"  ok    tool_use input resolved at boundary: {resolved!r}")


def test_secret_marker_not_auto_resolved() -> None:
    print("\n=== Test 3: <REF> markers stay opaque in streaming text ===")
    vault = Vault()
    vault.get_or_mint("xk-fake-AAA", "API_KEY", "C")
    vault.get_or_mint("ghp_FAKE", "TOKEN", "C")

    rew = SSERewriter(vault)
    out = []
    out.extend(rew.feed("content_block_start",
                        {"type": "content_block_start", "index": 0,
                         "content_block": {"type": "text", "text": ""}}))
    out.extend(rew.feed("content_block_delta",
                        {"type": "content_block_delta", "index": 0,
                         "delta": {"type": "text_delta",
                                   "text": "Use <REF> for API"}}))
    out.extend(rew.feed("content_block_stop",
                        {"type": "content_block_stop", "index": 0}))
    out.extend(rew.flush())

    full = text_deltas_from(out)
    if "xk-fake-AAA" in full or "ghp_FAKE" in full:
        print(f"FAIL  secret leaked into text stream: {full!r}")
        sys.exit(1)
    if "<REF>" not in full:
        print(f"FAIL  <REF> marker was rewritten: {full!r}")
        sys.exit(1)
    print(f"  ok    secret marker stayed opaque: {full!r}")


def main() -> int:
    test_text_token_straddle()
    test_tool_use_resolution()
    test_secret_marker_not_auto_resolved()
    print("\nALL SSE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
