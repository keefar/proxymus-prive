"""Tests for the endpoint trust map (apf-ycu)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from apf import endpoint_policy as ep


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        print(f"FAIL  {label}")
        print(f"  expected: {expected!r}")
        print(f"  actual:   {actual!r}")
        sys.exit(1)
    print(f"  ok    {label}")


def test_defaults() -> None:
    print("\n=== Test 1: built-in policy defaults ===")
    # Point APF_ENDPOINT_CONFIG at a non-existent path so any
    # user-machine ~/.config/apf/endpoints.toml override (which a
    # developer may have created for local-loopback smoke testing,
    # see docs/INTEGRATION.md) does not pollute these built-in
    # default assertions.
    os.environ["APF_ENDPOINT_CONFIG"] = "/nonexistent/apf-test-isolation.toml"
    # Loopback / local
    for host in ("localhost", "127.0.0.1", "::1"):
        assert_eq(ep.policy_for_host(host), ep.POLICY_OFF, f"{host} → off")
    assert_eq(ep.policy_for_host("my-mini.local"), ep.POLICY_OFF, "*.local → off (mDNS)")
    # Cloud explicit
    for host in ("api.anthropic.com", "api.openai.com", "api.groq.com"):
        assert_eq(ep.policy_for_host(host), ep.POLICY_FULL, f"{host} → full")
    # Unknown
    assert_eq(ep.policy_for_host("evil.example.com"), ep.POLICY_FULL,
              "unknown host → DEFAULT_POLICY=full")
    # Empty
    assert_eq(ep.policy_for_host(""), ep.POLICY_FULL, "empty host → default")
    assert_eq(ep.policy_for_host(None), ep.POLICY_FULL, "None host → default")


def test_url_parsing() -> None:
    print("\n=== Test 2: policy_for_url ===")
    assert_eq(ep.policy_for_url("http://localhost:11434/api/chat"),
              ep.POLICY_OFF, "Ollama default url → off")
    assert_eq(ep.policy_for_url("https://api.anthropic.com/v1/messages"),
              ep.POLICY_FULL, "Anthropic url → full")
    assert_eq(ep.policy_for_url("https://api.openai.com/v1/chat/completions"),
              ep.POLICY_FULL, "OpenAI url → full")
    assert_eq(ep.policy_for_url("http://192.168.1.50:8080"),
              ep.POLICY_FULL, "LAN IP without .local → default full")


def test_user_overrides() -> None:
    print("\n=== Test 3: user config override ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "endpoints.toml"
        cfg.write_text(
            '[[endpoints]]\n'
            'host = "api.anthropic.com"\n'
            'policy = "off"\n'
            '\n'
            '[[endpoints]]\n'
            'host = "my-trusted-proxy.tail-scale.ts.net"\n'
            'policy = "off"\n',
            encoding="utf-8",
        )
        old = os.environ.get("APF_ENDPOINT_CONFIG")
        os.environ["APF_ENDPOINT_CONFIG"] = str(cfg)
        try:
            assert_eq(ep.policy_for_host("api.anthropic.com"), ep.POLICY_OFF,
                      "user override flips anthropic → off (paranoid mode inverted)")
            assert_eq(ep.policy_for_host("my-trusted-proxy.tail-scale.ts.net"),
                      ep.POLICY_OFF, "tailscale endpoint trusted via config")
            assert_eq(ep.policy_for_host("api.openai.com"), ep.POLICY_FULL,
                      "non-overridden cloud still full")
        finally:
            if old is None:
                del os.environ["APF_ENDPOINT_CONFIG"]
            else:
                os.environ["APF_ENDPOINT_CONFIG"] = old


def test_malformed_config_is_safe() -> None:
    print("\n=== Test 4: malformed config does not break lookup ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "endpoints.toml"
        cfg.write_text("this is not valid toml [[[", encoding="utf-8")
        os.environ["APF_ENDPOINT_CONFIG"] = str(cfg)
        try:
            assert_eq(ep.policy_for_host("api.anthropic.com"), ep.POLICY_FULL,
                      "malformed config silently ignored, defaults restored")
        finally:
            del os.environ["APF_ENDPOINT_CONFIG"]


def main() -> int:
    test_defaults()
    test_url_parsing()
    test_user_overrides()
    test_malformed_config_is_safe()
    print("\nALL ENDPOINT POLICY TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
