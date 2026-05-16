"""Tool-call boundary resolver.

When the LLM produces a tool call (e.g. `send_email(to="<EMAIL_3>")` or
`Bash(command="grep -r '<EMAIL_3>' /Users/<USER_PATH_1>/inbox")`), the local
tool executor needs the *real* values to do real work. The resolver walks
the tool-call arguments (JSON-shaped) and substitutes vault tokens with
their originals.

Critical: the resolved arguments MUST NOT be sent back into the LLM's
context. The contract is:
  1. LLM emits tool_use with tokenised args.
  2. Local harness calls `resolve_tool_call_args(args, vault)` →
     plain-text args (originals).
  3. Local executor runs the tool with the plain-text args.
  4. The tool result is *re-tokenised* before being sent back to the LLM
     in the next turn (using the same vault, so token identities stay
     consistent).

Tier-C secrets (the opaque `<SECRET>` marker) cannot be resolved by this
function alone — its vault lookup is ambiguous for `<SECRET>`. Pass a
secret_resolver callable that knows which env var / keychain slot to read
for a given context. The callable is invoked with no arguments and may
return None to signal "no fill available; pass the literal token through"
or a string to fill in.
"""
from __future__ import annotations

from typing import Any, Callable

from .detokenizer import TOKEN_RE
from .vault import Vault

SecretResolver = Callable[[], str | None]


def _resolve_string(value: str, vault: Vault,
                    secret_resolver: SecretResolver | None) -> str:
    """Resolve all vault tokens in a string."""
    def replace(m):
        token = m.group(0)
        original = vault.get_original(token)
        return original if original is not None else token

    out = TOKEN_RE.sub(replace, value)

    if "<SECRET>" in out and secret_resolver is not None:
        replacement = secret_resolver()
        if replacement is not None:
            out = out.replace("<SECRET>", replacement)
    return out


def resolve_tool_call_args(
    args: Any,
    vault: Vault,
    secret_resolver: SecretResolver | None = None,
) -> Any:
    """Walk a JSON-shaped arg structure and resolve every string leaf.

    Accepts strings, ints, floats, bools, None, lists, and dicts. Returns
    a new structure of the same shape with strings substituted.

    `secret_resolver` is called when a `<SECRET>` marker is seen. Pass a
    callable that returns the real secret (e.g. from env or keychain). If
    None, `<SECRET>` markers are left in place — usually a bug, since the
    tool will then fail to authenticate; but explicit is better than
    silently leaking.
    """
    if isinstance(args, str):
        return _resolve_string(args, vault, secret_resolver)
    if isinstance(args, list):
        return [resolve_tool_call_args(v, vault, secret_resolver) for v in args]
    if isinstance(args, dict):
        return {k: resolve_tool_call_args(v, vault, secret_resolver)
                for k, v in args.items()}
    return args  # ints, floats, bools, None — pass through
