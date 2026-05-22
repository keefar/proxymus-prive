"""Tool-call boundary resolver.

When the LLM produces a tool call (e.g. `send_email(to="<REF_3>")` or
`Bash(command="grep -r '<REF_3>' /Users/<REF_1>/inbox")`), the local
tool executor needs the *real* values to do real work. The resolver walks
the tool-call arguments (JSON-shaped) and substitutes vault tokens with
their originals.

Critical: the resolved arguments MUST NOT be sent back into the LLM's
context. The contract is:
  1. LLM emits tool_use with masked args.
  2. Local harness calls `resolve_tool_call_args(args, vault)` →
     plain-text args (originals).
  3. Local executor runs the tool with the plain-text args.
  4. The tool result is *re-masked* before being sent back to the LLM
     in the next turn (using the same vault, so token identities stay
     consistent).

Tier-C secrets (the bare `<REF>` marker, no number suffix) cannot be
resolved by this function alone — its vault lookup is ambiguous for
`<REF>`. Pass a secret_resolver callable that knows which env var /
keychain slot to read for a given context. The callable is invoked with
no arguments and may return None to signal "no fill available; pass the
literal token through" or a string to fill in.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from .unmasker import TOKEN_RE
from .vault import Vault

SecretResolver = Callable[[], str | None]
UnresolvedCallback = Callable[[str], None]

# apf-tu9: tolerant matcher for *mangled* REF-token variants.
#
# A weak upstream model does not always pass `<REF_N>` through verbatim.
# Verified 2026-05-22: Qwen2.5-Coder-7B turned `<REF_1>` into
# `REF_1@example.com` — dropped the angle brackets, normalised it into an
# email-shaped string. The strict `TOKEN_RE` (`<REF_N>`) does not match
# the mangled form, so the token would never resolve and the client would
# receive a garbage value.
#
# This regex recognises a *bounded* set of mangling variants:
#   - brackets stripped:    REF_1
#   - case changed:         ref_1, Ref_1, <ref_1>
#   - whitespace injected:  < REF_1 >, REF 1
#   - shape-normalised:     REF_1@example.com, ref-1.example
#
# Anchoring keeps it conservative:
#   - `(?<![A-Za-z0-9])` left boundary: 'reference', 'preferred' etc. do
#     NOT match — the 'ref' must not be preceded by an alphanumeric.
#   - `REF` + a separator (`_`, `-`, or whitespace) + one or more DIGITS
#     is mandatory. A numberless `REF`/`ref` (the bare Tier-C marker is
#     `<REF>`) never matches — its cardinality ambiguity is deliberate.
#   - the trailing shape-decoration is an *optional, bounded* run
#     (`@host` or `.host`) so the matcher cannot swallow arbitrary text.
#
# Group `num` is the numeric ID; it is the only thing used to look the
# token up. The decoration (angle brackets, case, separators, hallucinated
# `@example.com`) is discarded — the whole matched span is replaced by the
# vaulted original when the ID maps to exactly one minted token.
_MANGLED_REF_RE = re.compile(
    r"""(?<![A-Za-z0-9])      # left boundary — not mid-word
        <?\s*                 # optional opening bracket + whitespace
        [Rr][Ee][Ff]          # the REF literal, any case
        [\s_-]+               # mandatory separator: underscore/dash/space
        (?P<num>\d+)          # the numeric ID — mandatory
        \s*>?                 # optional whitespace + closing bracket
        (?:[@.][A-Za-z0-9.\-]*[A-Za-z0-9])?  # optional shape decoration
    """,
    re.VERBOSE,
)


def _tolerant_resolve(value: str, vault: Vault,
                      on_unresolved: UnresolvedCallback | None) -> str:
    """Resolve mangled REF-token variants left over after the strict pass.

    For each `REF`-and-digit shape, normalise to the numeric ID and look up
    `<REF_N>` in the vault. Resolve only when the ID maps to exactly one
    minted token — never guess. A mangled shape whose ID was never minted
    is left literal (so the breakage stays loud, not a silent garbage
    value) and reported via `on_unresolved` if a hook was given.
    """
    def replace(m: re.Match[str]) -> str:
        variant = m.group(0)
        canonical = f"<REF_{m.group('num')}>"
        original = vault.get_original(canonical)
        if original is not None:
            return original
        # Shape looked like a token but the ID was never minted: leave it
        # literal and fail loud rather than pass a broken value silently.
        if on_unresolved is not None:
            on_unresolved(variant)
        return variant

    return _MANGLED_REF_RE.sub(replace, value)


def _resolve_string(value: str, vault: Vault,
                    secret_resolver: SecretResolver | None,
                    on_unresolved: UnresolvedCallback | None = None) -> str:
    """Resolve all vault tokens in a string."""
    def replace(m):
        token = m.group(0)
        original = vault.get_original(token)
        return original if original is not None else token

    out = TOKEN_RE.sub(replace, value)

    # apf-okt: resolve surrogate surface forms back to originals so the
    # local executor runs the tool with the real value. Longest-first;
    # no debug marker here — it would corrupt tool arguments.
    surrogates = [(e.surrogate, e.original) for e in vault.all_entries()
                  if e.surrogate is not None]
    for surrogate, original in sorted(surrogates, key=lambda p: -len(p[0])):
        if surrogate in out:
            out = out.replace(surrogate, original)

    # apf-tu9: model-agnostic safety net. After the strict + surrogate
    # passes, mop up any mangled `<REF_N>` variants a weak upstream model
    # produced. This runs BEFORE the bare-`<REF>` secret substitution so a
    # numbered token can never be misread as a Tier-C marker.
    out = _tolerant_resolve(out, vault, on_unresolved)

    if "<REF>" in out and secret_resolver is not None:
        replacement = secret_resolver()
        if replacement is not None:
            out = out.replace("<REF>", replacement)
    return out


def resolve_tool_call_args(
    args: Any,
    vault: Vault,
    secret_resolver: SecretResolver | None = None,
    on_unresolved: UnresolvedCallback | None = None,
) -> Any:
    """Walk a JSON-shaped arg structure and resolve every string leaf.

    Accepts strings, ints, floats, bools, None, lists, and dicts. Returns
    a new structure of the same shape with strings substituted.

    `secret_resolver` is called when a bare `<REF>` marker is seen. Pass a
    callable that returns the real secret (e.g. from env or keychain). If
    None, `<REF>` markers are left in place — usually a bug, since the
    tool will then fail to authenticate; but explicit is better than
    silently leaking.

    `on_unresolved` (apf-tu9) is invoked once per mangled REF-token variant
    that *looks* like a token (the `REF`+digit shape a weak upstream model
    produces) but whose numeric ID was never minted in the vault. Such a
    value is left literal — never replaced with a guess — and the hook lets
    a caller log/alert on the broken round-trip instead of shipping garbage
    blind. Bare Tier-C `<REF>` is deliberately ambiguous, not 'unresolved',
    and never trips the hook.
    """
    if isinstance(args, str):
        return _resolve_string(args, vault, secret_resolver, on_unresolved)
    if isinstance(args, list):
        return [resolve_tool_call_args(v, vault, secret_resolver, on_unresolved)
                for v in args]
    if isinstance(args, dict):
        return {k: resolve_tool_call_args(v, vault, secret_resolver,
                                          on_unresolved)
                for k, v in args.items()}
    return args  # ints, floats, bools, None — pass through
