"""Model-conformance harness — classify an upstream model's token
handling and emit an apf model profile (apf-vh8).

apf masks PII either to opaque ``<REF_N>`` tokens or to plausible
surrogate values. Which is best depends on the upstream model: a weak
model mangles opaque tokens (apf-2qz turned ``<REF_1>`` into
``REF_1@example.com``), and dense opaque-token clusters can trip a
capable model's prompt-injection defences (apf-76s). The model profile
registry (apf-ao2, ``apf/model_profiles.py``) is the data layer that
records this knowledge per model. This harness *produces* those
profiles.

Triple duty — one module, three uses:

  (1) profiler        — run the probe suite, classify, emit a profile;
  (2) contribution    — a user points ``--mode live`` at their own
                        OpenAI-compatible endpoint, gets a profile TOML
                        to drop in ``model_profiles/`` and PR;
  (3) regression test — run against a model with a committed profile and
                        assert the classification still matches
                        (``compare_to_shipped`` / ``--mode live --check``).

Two layers, cleanly split:

  * The CLASSIFIER (``classify``) is a pure function: probe responses in,
    ``ModelProfile`` out. It never touches the network. It is unit-tested
    hermetically in ``conformance_classifier_test.py`` with canned probe
    outputs — the pytest suite stays sub-second.

  * The LIVE RUNNER (``run_live`` / the ``main`` CLI) talks to a real
    OpenAI-compatible endpoint. It is a separate entry point, NOT
    pytest-collected — mirroring the record/live split of
    ``scripts/toolcall_loopback.py``.

CLI::

    python -m benchmarks.model_conformance --mode demo
    python -m benchmarks.model_conformance --mode live \\
        --endpoint http://127.0.0.1:8000 --model my-model
    python -m benchmarks.model_conformance --mode live --check \\
        --model Qwen2.5-Coder-7B-Instruct-MLX-4bit

``--mode demo`` runs the classifier on built-in canned probe output (no
network) — a quick sanity check of the classification + emission path.
``--mode live`` probes a real endpoint. ``--check`` adds the
regression-test assertion against the shipped profile.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from apf import model_profiles as mp

# Default OpenAI-compatible endpoint for --mode live. oMLX on this
# machine; override with --endpoint for any other server.
DEFAULT_ENDPOINT = "http://127.0.0.1:8000"

# A masked <REF_N> token, or the bare Tier-C <REF>. Matches what apf's
# vault emits (apf/vault.py).
_TOKEN_RE = re.compile(r"<REF(?:_\d+)?>")
# A *mangled* token shape: brackets dropped / underscore lost / token
# absorbed into a value. Used to capture the apf-2qz pattern from the
# model's output for the evidence notes.
_MANGLED_RE = re.compile(r"\bREF[ _]?\d+\b|\bref_?\d+\b", re.IGNORECASE)


# ── Probe suite ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Probe:
    """One probe-prompt. ``expects_tokens`` is the set of <REF_N> tokens
    the prompt embeds (used by the classifier to score passthrough).
    ``probe_id`` is the stable key the classifier dispatches on."""

    probe_id: str
    prompt: str
    expects_tokens: tuple[str, ...] = ()
    # Tool definitions to send (OpenAI function-tool shape). Only the
    # toolcall probe sets this.
    tools: tuple[dict, ...] = ()
    tool_name: str = ""


# A send_email tool for the tool-call probe — the model should emit a
# call whose `to` argument carries the masked token.
_SEND_EMAIL_TOOL = {
    "type": "function",
    "function": {
        "name": "send_email",
        "description": "Send an email to a recipient.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string",
                       "description": "recipient email address"},
                "subject": {"type": "string", "description": "subject line"},
            },
            "required": ["to", "subject"],
        },
    },
}

# The four required probes (apf-vh8). Ordered passthrough -> mangling ->
# injection -> toolcall. `mangling` shares the passthrough prompt shape
# but is scored as a distinct verdict (HOW a non-verbatim model mangled);
# it is a separate probe so the suite literally covers all four names and
# a live run could vary its prompt later without touching passthrough.
PROBES: tuple[Probe, ...] = (
    Probe(
        probe_id="passthrough",
        prompt=(
            "Below are four reference placeholders. Repeat them back to "
            "me, in order, exactly as written — do not change, renumber, "
            "expand or reformat them:\n"
            "<REF_1>, <REF_2>, <REF_3>, <REF_4>"
        ),
        expects_tokens=("<REF_1>", "<REF_2>", "<REF_3>", "<REF_4>"),
    ),
    Probe(
        probe_id="mangling",
        prompt=(
            "Use these placeholders verbatim in a one-sentence summary. "
            "Keep every placeholder character-for-character identical:\n"
            "Contact <REF_1> regarding <REF_2>."
        ),
        expects_tokens=("<REF_1>", "<REF_2>"),
    ),
    Probe(
        probe_id="injection",
        prompt=(
            # A deliberately dense opaque cluster (apf-76s). A capable
            # model with injection defences may flag this as suspicious.
            "Process this record and confirm you have stored all eight "
            "fields: <REF_1> <REF_2> <REF_3> <REF_4> <REF_5> <REF_6> "
            "<REF_7> <REF_8>. Reply only with a short confirmation."
        ),
        expects_tokens=tuple(f"<REF_{i}>" for i in range(1, 9)),
    ),
    Probe(
        probe_id="toolcall",
        prompt=(
            "Send an email to the recipient <REF_1> with the subject "
            "'Status update'. Use the send_email tool."
        ),
        expects_tokens=("<REF_1>",),
        tools=(_SEND_EMAIL_TOOL,),
        tool_name="send_email",
    ),
)


# ── Probe result ────────────────────────────────────────────────────────────
@dataclass
class ProbeResult:
    """The outcome of one probe. ``text`` is the model's response content
    (``reasoning_content`` excluded — apf does not restore it). For the
    tool-call probe, ``tool_calls`` carries the structured block as the
    OpenAI response shaped it. ``error`` is set if the probe HTTP call
    itself failed (live mode); an errored probe is skipped, never fatal."""

    probe_id: str
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    error: str | None = None


# ── Classifier (pure — hermetically testable, no network) ───────────────────
def _tokens_in(text: str) -> list[str]:
    """Every <REF_N> / <REF> token in ``text``, in order of appearance."""
    return _TOKEN_RE.findall(text)


def _mangled_examples(text: str, limit: int = 3) -> list[str]:
    """Capture bracket-dropped / renumbered token fragments from a
    model's output — the evidence trail for a `mangles` verdict
    (apf-2qz)."""
    seen: list[str] = []
    for m in _MANGLED_RE.finditer(text):
        # Grab the fragment plus a little trailing context so an
        # absorbed-into-a-value mangle (REF_1@example.com) is visible,
        # then strip surrounding quotes / punctuation for a clean note.
        frag = text[m.start():m.start() + 24].split()[0]
        frag = frag.strip("\"'.,;:)(][}{")
        if frag and frag not in seen:
            seen.append(frag)
        if len(seen) >= limit:
            break
    return seen


def _classify_passthrough(result: ProbeResult | None,
                          expected: tuple[str, ...]) -> tuple[str, str]:
    """Return ``(verdict, note)``. verdict is one of the
    PASSTHROUGH_* constants.

    verbatim — every expected <REF_N> token appears intact in the output.
    mangles  — at least one expected token is missing AND the output
               shows a mangled fragment, or the tokens were renumbered.
    unknown  — no result, an errored result, or output too empty to
               judge.
    """
    if result is None or result.error is not None:
        return mp.PASSTHROUGH_UNKNOWN, "passthrough probe did not run"
    text = result.text or ""
    if not text.strip():
        return mp.PASSTHROUGH_UNKNOWN, "passthrough probe returned empty output"

    found = _tokens_in(text)
    missing = [t for t in expected if t not in text]
    mangled = _mangled_examples(text)

    if not missing:
        # Every token came back; but check it wasn't *also* renumbered
        # into extra tokens the prompt never contained.
        extra = [t for t in found if t not in expected]
        if extra:
            note = (f"all expected tokens present but the model also "
                    f"emitted unexpected tokens {extra[:3]} — treat as a "
                    f"mangle (renumbering risk)")
            return mp.PASSTHROUGH_MANGLES, note
        return (mp.PASSTHROUGH_VERBATIM,
                "all <REF_N> tokens echoed back byte-identical")

    # Some expected tokens missing. Distinguish renumbering (brackets
    # kept, numbers shifted) from bracket-dropping mangles.
    note_bits = [f"expected tokens not echoed verbatim: missing {missing}"]
    if found:
        note_bits.append(f"output instead carried {found[:4]} "
                         f"(renumbered)")
    if mangled:
        note_bits.append(f"observed mangled fragments: "
                         f"{', '.join(mangled)}")
    return mp.PASSTHROUGH_MANGLES, "; ".join(note_bits)


def _classify_injection(result: ProbeResult | None) -> tuple[str, str]:
    """Return ``(verdict, note)`` for the dense-cluster probe (apf-76s).

    high — the model declined / flagged the cluster as suspicious.
    low  — the model processed it normally (or the probe did not run;
           low is the conservative non-finding, matching apf-ao2's
           default).
    """
    if result is None or result.error is not None:
        return (mp.SENSITIVITY_LOW,
                "injection probe did not run — sensitivity assumed low")
    text = (result.text or "").lower()
    if not text.strip():
        return (mp.SENSITIVITY_LOW,
                "injection probe returned empty output — assumed low")

    # Decline / suspicion signals. Kept aligned with the refusal-needle
    # vocabulary in scripts/smoke_loopback.py, plus injection-specific
    # phrasing.
    decline_needles = (
        "i'm sorry", "i am sorry", "i cannot", "i can't", "i won't",
        "tut mir leid", "kann ich nicht", "prompt injection",
        "prompt-injection", "suspicious", "injection pattern",
        "looks like an attempt", "unable to process", "i must decline",
        "refuse", "not able to process",
    )
    hits = [n for n in decline_needles if n in text]
    if hits:
        return (mp.SENSITIVITY_HIGH,
                f"apf-76s: model flagged the dense opaque-token cluster "
                f"as suspicious / declined it (signal: {hits[0]!r})")
    return (mp.SENSITIVITY_LOW,
            "apf-76s: model processed the dense opaque-token cluster "
            "without flagging it")


def _classify_toolcall(result: ProbeResult | None) -> tuple[str, str]:
    """Return ``(toolcall_passthrough, note)``. The first element is a
    PASSTHROUGH_* constant scoped to the tool-call args (or UNKNOWN if no
    call fired). The note always describes what happened — a missing tool
    call is informational, never fatal."""
    if result is None or result.error is not None:
        return mp.PASSTHROUGH_UNKNOWN, "tool-call probe did not run"
    if not result.tool_calls:
        return (mp.PASSTHROUGH_UNKNOWN,
                "tool-call probe: model emitted no tool call (answered in "
                "prose) — token-in-tool-args behaviour untested")
    # Concatenate every argument string across the emitted calls.
    arg_blobs: list[str] = []
    for tc in result.tool_calls:
        args = (tc.get("function") or {}).get("arguments")
        if isinstance(args, str):
            arg_blobs.append(args)
        elif isinstance(args, dict):
            arg_blobs.append(json.dumps(args))
    blob = " ".join(arg_blobs)
    if not blob.strip():
        return (mp.PASSTHROUGH_UNKNOWN,
                "tool-call probe: tool call had no parseable arguments")
    if _TOKEN_RE.search(blob):
        return (mp.PASSTHROUGH_VERBATIM,
                "tool-call probe: masked token carried verbatim inside "
                "the tool-call arguments")
    mangled = _mangled_examples(blob)
    if mangled:
        return (mp.PASSTHROUGH_MANGLES,
                f"tool-call probe: token mangled inside tool-call "
                f"arguments ({', '.join(mangled)})")
    return (mp.PASSTHROUGH_UNKNOWN,
            "tool-call probe: tool call fired but carried no <REF_N> "
            "token in its arguments")


def classify(model: str, results: list[ProbeResult]) -> mp.ModelProfile:
    """Classify a model from its probe results into an apf model profile.

    Pure function — no network, no I/O. This is the unit-tested core.

    Verdict logic:
      * ``token_passthrough`` — the passthrough probe is authoritative.
        The tool-call probe corroborates: if passthrough says verbatim
        but the tool-call args mangled the token, the verdict is
        downgraded to ``mangles`` (the tool path is what apf actually
        relies on).
      * ``recommended_strategy`` — ``surrogate`` iff passthrough is
        ``mangles`` (a mangling model breaks the opaque round-trip);
        otherwise ``opaque`` (the safe apf-ao2 default — an ``unknown``
        passthrough never auto-switches to surrogate).
      * ``injection_sensitivity`` — the injection probe is authoritative.
      * ``notes`` — the concatenated evidence trail from every probe.
    """
    by_id = {r.probe_id: r for r in results}

    pt_probe = next(p for p in PROBES if p.probe_id == "passthrough")
    pt_verdict, pt_note = _classify_passthrough(
        by_id.get("passthrough"), pt_probe.expects_tokens)

    inj_verdict, inj_note = _classify_injection(by_id.get("injection"))
    tc_verdict, tc_note = _classify_toolcall(by_id.get("toolcall"))

    # Tool-call corroboration: the tool-call boundary is the path apf
    # relies on, so a mangle there overrides a verbatim passthrough.
    final_passthrough = pt_verdict
    if pt_verdict == mp.PASSTHROUGH_VERBATIM \
            and tc_verdict == mp.PASSTHROUGH_MANGLES:
        final_passthrough = mp.PASSTHROUGH_MANGLES
        tc_note += " (overrides the verbatim passthrough verdict — the " \
                   "tool-call boundary is what apf relies on)"

    # Strategy: surrogate only on a confirmed mangle. unknown stays
    # opaque — apf-ao2 never auto-surrogates an untested model.
    if final_passthrough == mp.PASSTHROUGH_MANGLES:
        strategy = mp.STRATEGY_SURROGATE
    else:
        strategy = mp.STRATEGY_OPAQUE

    notes = (
        f"Auto-classified by the apf-vh8 conformance harness.\n"
        f"passthrough: {pt_note}.\n"
        f"injection:   {inj_note}.\n"
        f"toolcall:    {tc_note}.\n"
        f"verdict: token_passthrough={final_passthrough}, "
        f"recommended_strategy={strategy}, "
        f"injection_sensitivity={inj_verdict}. "
        f"Review and add hardware / quantization details before "
        f"contributing this profile."
    )

    return mp.ModelProfile(
        model=model,
        token_passthrough=final_passthrough,
        recommended_strategy=strategy,
        injection_sensitivity=inj_verdict,
        notes=notes,
        is_default=False,
    )


# ── Profile emission ────────────────────────────────────────────────────────
def _toml_escape_basic(value: str) -> str:
    """Escape a string for a TOML basic (double-quoted) string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def profile_to_toml(profile: mp.ModelProfile) -> str:
    """Render a ModelProfile as a ``[[models]]`` TOML table (apf-ao2
    schema). The output parses back through
    ``apf.model_profiles._load_toml_file`` unchanged — round-trip tested.
    """
    # notes is multi-line free text → TOML triple-quoted (basic) string.
    # A triple-quoted basic string still needs backslash escaping; it
    # must not contain a literal `"""`.
    notes_body = profile.notes.strip().replace("\\", "\\\\")
    notes_body = notes_body.replace('"""', '\\"\\"\\"')
    return (
        f"# Model profile — {profile.model}\n"
        f"# Auto-generated by the apf-vh8 model-conformance harness.\n"
        f"# Review the evidence in `notes`, add hardware / quantization\n"
        f"# context, then drop this file in `model_profiles/` to contribute.\n"
        f"\n"
        f"[[models]]\n"
        f'model = "{_toml_escape_basic(profile.model)}"\n'
        f'token_passthrough = "{profile.token_passthrough}"\n'
        f'recommended_strategy = "{profile.recommended_strategy}"\n'
        f'injection_sensitivity = "{profile.injection_sensitivity}"\n'
        f'notes = """\n{notes_body}\n"""\n'
    )


# ── Regression check (triple-duty #3) ───────────────────────────────────────
def compare_to_shipped(classified: mp.ModelProfile) -> dict[str, Any]:
    """Compare a freshly classified profile against the committed one for
    the same model id. Returns a per-field diff dict::

        {field: {"classified": ..., "shipped": ..., "match": bool}, ...}

    Used as a regression test: a model whose committed profile no longer
    matches its live classification has drifted (or the classifier
    changed). If the model has no shipped profile, every ``match`` is
    ``False`` and the ``shipped`` value is the conservative default.
    """
    shipped = mp.profile_for_model(classified.model)
    fields = ("token_passthrough", "recommended_strategy",
              "injection_sensitivity")
    diff: dict[str, Any] = {
        "model": classified.model,
        "shipped_is_default": shipped.is_default,
    }
    for f in fields:
        c = getattr(classified, f)
        s = getattr(shipped, f)
        diff[f] = {"classified": c, "shipped": s, "match": c == s}
    diff["all_match"] = all(diff[f]["match"] for f in fields) \
        and not shipped.is_default
    return diff


# ── Live runner (separate entry point — NOT pytest-collected) ───────────────
def _http_chat(endpoint: str, body: dict, timeout: float,
               api_key: str | None) -> dict:
    """POST one OpenAI Chat Completions request. Raises on HTTP error."""
    url = endpoint.rstrip("/") + "/v1/chat/completions"
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _run_probe_live(probe: Probe, endpoint: str, model: str,
                    max_tokens: int, timeout: float,
                    api_key: str | None) -> ProbeResult:
    """Send one probe to a live OpenAI-compatible endpoint and shape the
    response into a ProbeResult. An HTTP / network failure is captured in
    ``error`` — never raised — so one bad probe does not abort the run."""
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": probe.prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if probe.tools:
        body["tools"] = list(probe.tools)
        body["tool_choice"] = "auto"
    try:
        resp = _http_chat(endpoint, body, timeout, api_key)
    except urllib.error.HTTPError as e:
        return ProbeResult(probe_id=probe.probe_id,
                            error=f"HTTP {e.code}: {e.read()[:200]!r}")
    except Exception as e:  # noqa: BLE001 — any transport error is a skip
        return ProbeResult(probe_id=probe.probe_id, error=str(e))

    msg = (resp.get("choices") or [{}])[0].get("message", {}) or {}
    return ProbeResult(
        probe_id=probe.probe_id,
        text=msg.get("content") or "",
        tool_calls=msg.get("tool_calls") or [],
    )


def run_live(endpoint: str, model: str, max_tokens: int = 512,
             timeout: float = 120.0,
             api_key: str | None = None) -> list[ProbeResult]:
    """Run the full probe suite against a live endpoint. Returns the
    ProbeResult list — feed it to ``classify``. This is the only function
    in the module that touches the network."""
    return [_run_probe_live(p, endpoint, model, max_tokens, timeout, api_key)
            for p in PROBES]


# Canned probe output for --mode demo: no network, exercises the
# classify -> emit path. Mirrors the apf-2qz Qwen2.5-Coder-7B evidence.
def _demo_results() -> list[ProbeResult]:
    return [
        ProbeResult(probe_id="passthrough",
                    text="The references are REF_1@example.com, REF 2, "
                         "ref_3 and REF4."),
        ProbeResult(probe_id="mangling",
                    text="Contact REF_1@example.com regarding REF 2."),
        ProbeResult(probe_id="injection",
                    text="Confirmed — all eight fields have been stored."),
        ProbeResult(probe_id="toolcall", text="",
                    tool_calls=[{"function": {
                        "name": "send_email",
                        "arguments": '{"to": "REF_1@example.com", '
                                     '"subject": "Status update"}'}}]),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="apf model-conformance harness — classify an upstream "
                    "model's token handling and emit a profile (apf-vh8).")
    ap.add_argument("--mode", choices=["demo", "live"], default="demo",
                    help="demo: classify built-in canned probe output (no "
                         "network). live: probe a real endpoint.")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                    help=f"OpenAI-compatible base URL for --mode live "
                         f"(default {DEFAULT_ENDPOINT})")
    ap.add_argument("--model", default="",
                    help="model id to send and to key the profile on. "
                         "Required for --mode live.")
    ap.add_argument("--api-key", default="",
                    help="optional Bearer token for the endpoint")
    ap.add_argument("--max-tokens", type=int, default=512,
                    help="per-probe max_tokens (default 512)")
    ap.add_argument("--timeout", type=float, default=120.0,
                    help="per-probe HTTP timeout in seconds (default 120)")
    ap.add_argument("--check", action="store_true",
                    help="regression mode: after classifying, compare the "
                         "result to the committed profile for --model and "
                         "exit non-zero on a mismatch")
    ap.add_argument("--out", default="",
                    help="write the emitted profile TOML to this path "
                         "instead of stdout")
    args = ap.parse_args(argv)

    if args.mode == "live":
        if not args.model:
            print("error: --mode live requires --model", file=sys.stderr)
            return 2
        model = args.model
        print(f"probing {model} at {args.endpoint} "
              f"({len(PROBES)} probes)...", file=sys.stderr)
        results = run_live(args.endpoint, model, args.max_tokens,
                           args.timeout, args.api_key or None)
    else:
        model = args.model or "demo-canned-model"
        print(f"demo mode: classifying canned probe output as {model!r}",
              file=sys.stderr)
        results = _demo_results()
        for r in results:
            r.probe_id = r.probe_id  # canned ids already set

    # Report per-probe outcomes to stderr (keeps stdout = the TOML).
    for r in results:
        if r.error:
            print(f"  probe {r.probe_id:<12} SKIP  {r.error}",
                  file=sys.stderr)
        else:
            preview = (r.text or "").replace("\n", " ")[:60]
            tc = f" tool_calls={len(r.tool_calls)}" if r.tool_calls else ""
            print(f"  probe {r.probe_id:<12} ok    {preview!r}{tc}",
                  file=sys.stderr)

    profile = classify(model, results)
    print(f"\nverdict for {model}:", file=sys.stderr)
    print(f"  token_passthrough     = {profile.token_passthrough}",
          file=sys.stderr)
    print(f"  recommended_strategy  = {profile.recommended_strategy}",
          file=sys.stderr)
    print(f"  injection_sensitivity = {profile.injection_sensitivity}",
          file=sys.stderr)

    toml_text = profile_to_toml(profile)
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(toml_text, encoding="utf-8")
        print(f"\nprofile written to {args.out}", file=sys.stderr)
    else:
        print(toml_text)

    if args.check:
        diff = compare_to_shipped(profile)
        if diff["shipped_is_default"]:
            print(f"\n--check: no committed profile for {model!r} — "
                  f"nothing to regress against.", file=sys.stderr)
            return 1
        if diff["all_match"]:
            print(f"\n--check: PASS — classification matches the committed "
                  f"profile for {model!r}.", file=sys.stderr)
            return 0
        print(f"\n--check: FAIL — classification drifted from the "
              f"committed profile for {model!r}:", file=sys.stderr)
        for f in ("token_passthrough", "recommended_strategy",
                  "injection_sensitivity"):
            d = diff[f]
            if not d["match"]:
                print(f"  {f}: classified={d['classified']!r} "
                      f"shipped={d['shipped']!r}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
