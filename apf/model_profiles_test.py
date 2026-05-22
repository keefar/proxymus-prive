"""Tests for the model profile registry (apf-ao2).

Declarative per-upstream-model token-handling profiles: shipped TOML
profiles in `model_profiles/`, user overrides in
`~/.config/apf/model_profiles.toml`, with a conservative DEFAULT for
unknown models. This is the data layer only — proxy wiring is apf-dkf.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from apf import model_profiles as mp


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        print(f"FAIL  {label}")
        print(f"  expected: {expected!r}")
        print(f"  actual:   {actual!r}")
        sys.exit(1)
    print(f"  ok    {label}")


def _isolate_user_config() -> None:
    """Point the user-override path at a non-existent file so a
    developer's real ~/.config/apf/model_profiles.toml cannot pollute
    shipped-default assertions (mirrors endpoint_policy_test)."""
    os.environ["APF_MODEL_PROFILE_CONFIG"] = "/nonexistent/apf-ao2-isolation.toml"


def test_shipped_profiles() -> None:
    print("\n=== Test 1: shipped profiles load and look up ===")
    _isolate_user_config()

    # Qwen2.5-Coder-7B mangles opaque tokens (apf-2qz) → surrogate.
    p = mp.profile_for_model("Qwen2.5-Coder-7B-Instruct-MLX-4bit")
    assert_eq(p.token_passthrough, mp.PASSTHROUGH_MANGLES,
              "Qwen2.5-Coder-7B token_passthrough = mangles")
    assert_eq(p.recommended_strategy, mp.STRATEGY_SURROGATE,
              "Qwen2.5-Coder-7B recommended_strategy = surrogate")
    assert_eq(p.injection_sensitivity, mp.SENSITIVITY_LOW,
              "Qwen2.5-Coder-7B injection_sensitivity = low")
    assert_eq(p.is_default, False, "Qwen2.5-Coder-7B is a real shipped profile")

    # Qwen3.6-35B Holo keeps <REF_N> verbatim → opaque.
    p2 = mp.profile_for_model("Qwen3.6-35B-A3B-Holo3-Qwopus-mxfp4-mlx")
    assert_eq(p2.token_passthrough, mp.PASSTHROUGH_VERBATIM,
              "Qwen3.6-35B token_passthrough = verbatim")
    assert_eq(p2.recommended_strategy, mp.STRATEGY_OPAQUE,
              "Qwen3.6-35B recommended_strategy = opaque")
    assert_eq(p2.is_default, False, "Qwen3.6-35B is a real shipped profile")


def test_unknown_model_returns_conservative_default() -> None:
    print("\n=== Test 2: unknown model → conservative default ===")
    _isolate_user_config()
    p = mp.profile_for_model("some-model-nobody-has-tested-v9")
    # Conservative: unknown passthrough, OPAQUE (the safe strategy —
    # never auto-surrogate an untested model), low sensitivity.
    assert_eq(p.token_passthrough, mp.PASSTHROUGH_UNKNOWN,
              "unknown model token_passthrough = unknown")
    assert_eq(p.recommended_strategy, mp.STRATEGY_OPAQUE,
              "unknown model recommended_strategy = opaque (safe default)")
    assert_eq(p.injection_sensitivity, mp.SENSITIVITY_LOW,
              "unknown model injection_sensitivity = low")
    assert_eq(p.is_default, True, "unknown model profile is flagged is_default")
    # None / empty also hit the default.
    assert_eq(mp.profile_for_model(None).is_default, True, "None model → default")
    assert_eq(mp.profile_for_model("").is_default, True, "empty model → default")


def test_user_override_precedence() -> None:
    print("\n=== Test 3: user override beats a shipped profile ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "model_profiles.toml"
        # User has tested the 7B themselves and finds it actually keeps
        # tokens verbatim on their setup — flip it to opaque.
        cfg.write_text(
            '[[models]]\n'
            'model = "Qwen2.5-Coder-7B-Instruct-MLX-4bit"\n'
            'token_passthrough = "verbatim"\n'
            'recommended_strategy = "opaque"\n'
            'injection_sensitivity = "high"\n'
            'notes = "my box keeps REF tokens fine"\n'
            '\n'
            '[[models]]\n'
            'model = "my-private-finetune-v1"\n'
            'token_passthrough = "mangles"\n'
            'recommended_strategy = "surrogate"\n'
            'injection_sensitivity = "low"\n',
            encoding="utf-8",
        )
        old = os.environ.get("APF_MODEL_PROFILE_CONFIG")
        os.environ["APF_MODEL_PROFILE_CONFIG"] = str(cfg)
        try:
            # Override wins over the shipped Qwen2.5-Coder-7B profile.
            p = mp.profile_for_model("Qwen2.5-Coder-7B-Instruct-MLX-4bit")
            assert_eq(p.token_passthrough, mp.PASSTHROUGH_VERBATIM,
                      "user override flips 7B passthrough → verbatim")
            assert_eq(p.recommended_strategy, mp.STRATEGY_OPAQUE,
                      "user override flips 7B strategy → opaque")
            assert_eq(p.injection_sensitivity, mp.SENSITIVITY_HIGH,
                      "user override flips 7B sensitivity → high")
            assert_eq(p.is_default, False, "overridden profile is not the default")
            # A model only the user knows about resolves from config.
            p2 = mp.profile_for_model("my-private-finetune-v1")
            assert_eq(p2.recommended_strategy, mp.STRATEGY_SURROGATE,
                      "user-only model resolves from config")
            assert_eq(p2.is_default, False, "user-only model is not the default")
            # A non-overridden shipped profile is untouched.
            p3 = mp.profile_for_model("Qwen3.6-35B-A3B-Holo3-Qwopus-mxfp4-mlx")
            assert_eq(p3.recommended_strategy, mp.STRATEGY_OPAQUE,
                      "non-overridden shipped profile still resolves")
            assert_eq(p3.is_default, False, "non-overridden shipped profile intact")
        finally:
            if old is None:
                del os.environ["APF_MODEL_PROFILE_CONFIG"]
            else:
                os.environ["APF_MODEL_PROFILE_CONFIG"] = old


def test_malformed_config_is_safe() -> None:
    print("\n=== Test 4: malformed user config does not break lookup ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "model_profiles.toml"
        cfg.write_text("this is not valid toml [[[", encoding="utf-8")
        os.environ["APF_MODEL_PROFILE_CONFIG"] = str(cfg)
        try:
            # Malformed config → ignored; shipped profiles still resolve.
            p = mp.profile_for_model("Qwen2.5-Coder-7B-Instruct-MLX-4bit")
            assert_eq(p.recommended_strategy, mp.STRATEGY_SURROGATE,
                      "malformed config ignored, shipped profile restored")
            # And the default still works for unknowns.
            assert_eq(mp.profile_for_model("whatever").is_default, True,
                      "malformed config ignored, default still works")
        finally:
            del os.environ["APF_MODEL_PROFILE_CONFIG"]


def test_malformed_entries_skipped() -> None:
    print("\n=== Test 5: individual bad entries are skipped, not fatal ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "model_profiles.toml"
        cfg.write_text(
            # Bad: invalid enum value for recommended_strategy.
            '[[models]]\n'
            'model = "bad-enum-model"\n'
            'recommended_strategy = "telepathy"\n'
            '\n'
            # Bad: missing the model key entirely.
            '[[models]]\n'
            'token_passthrough = "verbatim"\n'
            '\n'
            # Good: should still be picked up despite the bad neighbours.
            '[[models]]\n'
            'model = "good-model"\n'
            'token_passthrough = "verbatim"\n'
            'recommended_strategy = "opaque"\n'
            'injection_sensitivity = "high"\n',
            encoding="utf-8",
        )
        os.environ["APF_MODEL_PROFILE_CONFIG"] = str(cfg)
        try:
            good = mp.profile_for_model("good-model")
            assert_eq(good.recommended_strategy, mp.STRATEGY_OPAQUE,
                      "good entry resolves despite bad neighbours")
            assert_eq(good.is_default, False, "good entry is a real profile")
            # The bad-enum model name is not registered → falls to default.
            assert_eq(mp.profile_for_model("bad-enum-model").is_default, True,
                      "entry with bad enum value is skipped → default")
        finally:
            del os.environ["APF_MODEL_PROFILE_CONFIG"]


def test_all_profiles_inventory() -> None:
    print("\n=== Test 6: all_profiles exposes the shipped inventory ===")
    _isolate_user_config()
    profiles = mp.all_profiles()
    assert_eq("Qwen2.5-Coder-7B-Instruct-MLX-4bit" in profiles, True,
              "shipped inventory contains the 7B profile")
    assert_eq("Qwen3.6-35B-A3B-Holo3-Qwopus-mxfp4-mlx" in profiles, True,
              "shipped inventory contains the 35B profile")
    # Every shipped profile carries non-empty notes (it is the evidence
    # trail — apf-2qz etc.).
    for model_id, prof in profiles.items():
        assert_eq(bool(prof.notes.strip()), True,
                  f"shipped profile {model_id} has non-empty notes")


def main() -> int:
    test_shipped_profiles()
    test_unknown_model_returns_conservative_default()
    test_user_override_precedence()
    test_malformed_config_is_safe()
    test_malformed_entries_skipped()
    test_all_profiles_inventory()
    print("\nALL MODEL PROFILE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
