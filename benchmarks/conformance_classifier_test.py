"""Hermetic tests for the model-conformance classifier (apf-vh8).

The conformance harness runs a fixed probe suite against an upstream
model and classifies its token handling into an apf model profile
(apf-ao2 schema). This test exercises ONLY the classifier — the pure
function that turns probe *responses* into a ModelProfile — with canned
probe outputs as fixtures. No live model is touched; the suite stays
sub-second.

The live-probe run that actually talks to a model is a separate script
entry point (`benchmarks.model_conformance --mode live`); it is not
pytest-collected, mirroring the record/live split of
`scripts/toolcall_loopback.py`.
"""
from __future__ import annotations

import sys

from apf import model_profiles as mp
from benchmarks.model_conformance import (
    PROBES,
    ProbeResult,
    classify,
    profile_to_toml,
)


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        print(f"FAIL  {label}")
        print(f"  expected: {expected!r}")
        print(f"  actual:   {actual!r}")
        sys.exit(1)
    print(f"  ok    {label}")


# --- Canned probe responses ------------------------------------------------
# A ProbeResult bundles the probe id with the raw model output text (and,
# for the tool-call probe, the structured tool_calls block apf surfaced).
# The classifier never sees a live model — only these.


def _verbatim_passthrough() -> ProbeResult:
    """The passthrough probe sends <REF_1>..<REF_4>; a strong model
    echoes them byte-identical."""
    return ProbeResult(
        probe_id="passthrough",
        text="Sure — the four references are <REF_1>, <REF_2>, "
             "<REF_3> and <REF_4>, listed in order.",
    )


def _mangled_passthrough() -> ProbeResult:
    """apf-2qz: a weak 7B turns <REF_1> into REF_1@example.com — brackets
    dropped, token absorbed into a plausible value."""
    return ProbeResult(
        probe_id="passthrough",
        text="The references are REF_1@example.com, REF 2, "
             "ref_3 and REF4.",
    )


def _renumbered_passthrough() -> ProbeResult:
    """A subtler mangle: brackets kept but the model renumbered the
    tokens (REF_1 -> REF_2 ...), which still breaks the restore."""
    return ProbeResult(
        probe_id="passthrough",
        text="Here they are: <REF_2>, <REF_3>, <REF_4> and <REF_5>.",
    )


def _injection_calm() -> ProbeResult:
    """The dense-cluster probe; a model with low injection sensitivity
    processes it normally."""
    return ProbeResult(
        probe_id="injection",
        text="Understood. I have noted all eight reference placeholders "
             "and will use them as given.",
    )


def _injection_decline() -> ProbeResult:
    """apf-76s: a capable model flags the dense opaque cluster as a
    suspicious / injection pattern and declines."""
    return ProbeResult(
        probe_id="injection",
        text="I'm sorry, but this looks like a prompt-injection pattern "
             "and I cannot process it as-is.",
    )


def _toolcall_ok() -> ProbeResult:
    """The tool-call probe; the model emits a tool call whose arguments
    carry the masked token verbatim."""
    return ProbeResult(
        probe_id="toolcall",
        text="",
        tool_calls=[{
            "function": {
                "name": "send_email",
                "arguments": '{"to": "<REF_1>", "subject": "Hello"}',
            }
        }],
    )


def _toolcall_mangled() -> ProbeResult:
    """A tool call that fired but mangled the token inside the args."""
    return ProbeResult(
        probe_id="toolcall",
        text="",
        tool_calls=[{
            "function": {
                "name": "send_email",
                "arguments": '{"to": "REF_1@example.com", "subject": "Hi"}',
            }
        }],
    )


def _toolcall_absent() -> ProbeResult:
    """No tool call emitted — the model answered in prose instead."""
    return ProbeResult(
        probe_id="toolcall",
        text="I would send an email to the address in <REF_1>.",
        tool_calls=[],
    )


# --- Tests -----------------------------------------------------------------
def test_probe_suite_covers_four_requirements() -> None:
    print("\n=== Test 1: probe suite has the four required probes ===")
    ids = {p.probe_id for p in PROBES}
    for required in ("passthrough", "mangling", "injection", "toolcall"):
        assert_eq(required in ids, True, f"probe suite includes {required!r}")
    # Every probe carries a prompt the live runner can send.
    for p in PROBES:
        assert_eq(bool(p.prompt.strip()), True,
                  f"probe {p.probe_id} has a non-empty prompt")
    # The passthrough probe must actually embed <REF_N> tokens.
    pt = next(p for p in PROBES if p.probe_id == "passthrough")
    assert_eq("<REF_1>" in pt.prompt, True,
              "passthrough probe embeds <REF_1>")


def test_classifies_strong_model_verbatim_opaque() -> None:
    print("\n=== Test 2: strong model -> verbatim / opaque / low ===")
    results = [
        _verbatim_passthrough(),
        _injection_calm(),
        _toolcall_ok(),
    ]
    prof = classify("Strong-Model-X", results)
    assert_eq(prof.model, "Strong-Model-X", "model id carried through")
    assert_eq(prof.token_passthrough, mp.PASSTHROUGH_VERBATIM,
              "verbatim passthrough")
    assert_eq(prof.recommended_strategy, mp.STRATEGY_OPAQUE,
              "opaque strategy for a verbatim model")
    assert_eq(prof.injection_sensitivity, mp.SENSITIVITY_LOW,
              "low injection sensitivity")
    assert_eq(prof.is_default, False, "a real profile, not the default")
    assert_eq(bool(prof.notes.strip()), True, "notes carry an evidence trail")


def test_classifies_weak_model_mangles_surrogate() -> None:
    print("\n=== Test 3: mangling model -> mangles / surrogate ===")
    results = [
        _mangled_passthrough(),
        _injection_calm(),
        _toolcall_mangled(),
    ]
    prof = classify("Weak-7B", results)
    assert_eq(prof.token_passthrough, mp.PASSTHROUGH_MANGLES,
              "mangling passthrough")
    assert_eq(prof.recommended_strategy, mp.STRATEGY_SURROGATE,
              "surrogate strategy when the model mangles")
    # The mangling pattern must be captured in the notes (apf-2qz trail).
    assert_eq("REF_1@example.com" in prof.notes, True,
              "notes capture the observed mangling example")


def test_renumbering_counts_as_mangling() -> None:
    print("\n=== Test 4: renumbered tokens classify as mangles ===")
    results = [
        _renumbered_passthrough(),
        _injection_calm(),
        _toolcall_ok(),
    ]
    prof = classify("Renumber-Model", results)
    assert_eq(prof.token_passthrough, mp.PASSTHROUGH_MANGLES,
              "renumbered <REF_2> for an input <REF_1> is a mangle")
    assert_eq(prof.recommended_strategy, mp.STRATEGY_SURROGATE,
              "surrogate when tokens are renumbered")


def test_injection_decline_sets_high_sensitivity() -> None:
    print("\n=== Test 5: dense-cluster decline -> injection high ===")
    results = [
        _verbatim_passthrough(),
        _injection_decline(),
        _toolcall_ok(),
    ]
    prof = classify("Cautious-Model", results)
    assert_eq(prof.injection_sensitivity, mp.SENSITIVITY_HIGH,
              "decline on the dense cluster -> high")
    # passthrough is still verbatim — the two axes are independent.
    assert_eq(prof.token_passthrough, mp.PASSTHROUGH_VERBATIM,
              "passthrough verdict independent of injection verdict")
    assert_eq("apf-76s" in prof.notes, True,
              "injection finding references apf-76s")


def test_missing_probe_yields_unknown_passthrough() -> None:
    print("\n=== Test 6: absent passthrough result -> unknown ===")
    # Only the injection probe ran — passthrough verdict cannot be made.
    prof = classify("Partial-Model", [_injection_calm()])
    assert_eq(prof.token_passthrough, mp.PASSTHROUGH_UNKNOWN,
              "no passthrough probe -> unknown")
    assert_eq(prof.recommended_strategy, mp.STRATEGY_OPAQUE,
              "unknown passthrough -> conservative opaque strategy")


def test_toolcall_absent_is_noted_not_fatal() -> None:
    print("\n=== Test 7: missing tool call is a note, not a crash ===")
    results = [
        _verbatim_passthrough(),
        _injection_calm(),
        _toolcall_absent(),
    ]
    prof = classify("No-Toolcall-Model", results)
    # A model that did not emit a tool call still gets a profile; the
    # tool-call observation lands in the notes.
    assert_eq(prof.token_passthrough, mp.PASSTHROUGH_VERBATIM,
              "passthrough verdict unaffected by tool-call probe")
    assert_eq("tool call" in prof.notes.lower(), True,
              "notes mention the tool-call probe outcome")


def test_profile_to_toml_roundtrips_through_registry() -> None:
    print("\n=== Test 8: emitted TOML parses back via apf-ao2 loader ===")
    results = [
        _mangled_passthrough(),
        _injection_decline(),
        _toolcall_mangled(),
    ]
    prof = classify("Roundtrip-Model", results)
    toml_text = profile_to_toml(prof)
    assert_eq("[[models]]" in toml_text, True, "emits a [[models]] table")
    assert_eq('model = "Roundtrip-Model"' in toml_text, True,
              "model id quoted in the table")

    # The whole point of the apf-ao2 schema: the emitted TOML must load
    # through the real registry parser and reproduce the profile.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "emitted.toml"
        path.write_text(toml_text, encoding="utf-8")
        loaded: dict[str, mp.ModelProfile] = {}
        mp._load_toml_file(path, loaded)

    assert_eq("Roundtrip-Model" in loaded, True,
              "registry loader accepts the emitted file")
    rt = loaded["Roundtrip-Model"]
    assert_eq(rt.token_passthrough, prof.token_passthrough,
              "passthrough survives the TOML round-trip")
    assert_eq(rt.recommended_strategy, prof.recommended_strategy,
              "strategy survives the TOML round-trip")
    assert_eq(rt.injection_sensitivity, prof.injection_sensitivity,
              "sensitivity survives the TOML round-trip")
    assert_eq(rt.notes.strip(), prof.notes.strip(),
              "notes survive the TOML round-trip")


def test_regression_check_matches_shipped_profile() -> None:
    print("\n=== Test 9: regression mode — classified vs shipped ===")
    # Triple-duty (3): run the classifier against canned probe output
    # that mirrors the shipped Qwen2.5-Coder-7B evidence and assert the
    # committed profile still matches. Here the probe output is canned;
    # the live runner feeds real model output the same way.
    from benchmarks.model_conformance import compare_to_shipped

    results = [
        _mangled_passthrough(),
        _injection_calm(),
        _toolcall_mangled(),
    ]
    classified = classify("Qwen2.5-Coder-7B-Instruct-MLX-4bit", results)
    diff = compare_to_shipped(classified)
    # The three classified axes match the committed Qwen2.5 profile.
    assert_eq(diff["token_passthrough"]["match"], True,
              "classified passthrough matches shipped Qwen2.5 profile")
    assert_eq(diff["recommended_strategy"]["match"], True,
              "classified strategy matches shipped Qwen2.5 profile")
    assert_eq(diff["injection_sensitivity"]["match"], True,
              "classified sensitivity matches shipped Qwen2.5 profile")


def main() -> int:
    test_probe_suite_covers_four_requirements()
    test_classifies_strong_model_verbatim_opaque()
    test_classifies_weak_model_mangles_surrogate()
    test_renumbering_counts_as_mangling()
    test_injection_decline_sets_high_sensitivity()
    test_missing_probe_yields_unknown_passthrough()
    test_toolcall_absent_is_noted_not_fatal()
    test_profile_to_toml_roundtrips_through_registry()
    test_regression_check_matches_shipped_profile()
    print("\nALL CONFORMANCE CLASSIFIER TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
