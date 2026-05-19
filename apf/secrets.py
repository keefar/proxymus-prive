"""Local secret stores.

The ideal data flow is:
  proxy detects `OPENAI_API_KEY=sk-…` in outbound text
    → vault remembers "this secret came from key OPENAI_API_KEY"
    → LLM sees `<REF>` token, never the real value
    → LLM emits tool_use referencing `<REF>`
    → local executor needs the real key — secret store reads it from
      env / Keychain by name and returns it
    → vault never had to hand out the value

This module provides pluggable stores so the resolver can pull values
from the local environment without needing them in the vault at all.

For the PoC we ship two stores:
- EnvSecretStore: reads from os.environ by key name. Cheapest, works for
  the .env-style configs we typically see in dev.
- VaultFallbackStore: returns the vault entry's `original` value as a
  last resort, when the real env lookup misses. Defensible during PoC,
  but should be disabled in a real deployment so a malicious
  prompt-injected agent can't extract secrets the vault saw but env doesn't.

`ChainedSecretStore` lets you compose them with a deterministic order.
"""
from __future__ import annotations

import os
from typing import Callable, Protocol

from .vault import VaultEntry


class SecretStore(Protocol):
    def lookup(self, entry: VaultEntry) -> str | None: ...


class EnvSecretStore:
    """Looks up by entry.secret_key_name in os.environ.

    An optional `aliases` dict maps detector-side key names to env-var
    names (e.g. the detector might capture `SMTP_PASSWORD` from a config
    file but the local env has it as `SMTP_PASS`)."""

    def __init__(self, aliases: dict[str, str] | None = None) -> None:
        self.aliases = aliases or {}

    def lookup(self, entry: VaultEntry) -> str | None:
        key = entry.secret_key_name
        if not key:
            return None
        # Try the captured key name first, then any alias.
        candidates = [key, self.aliases.get(key)]
        for cand in candidates:
            if cand and cand in os.environ:
                return os.environ[cand]
        return None


class VaultFallbackStore:
    """Returns the vault entry's stored original value.

    Use this only when the env store misses AND the deployment is OK with
    the vault holding the secret. In a hardened deployment, disable it
    and let unresolved secrets surface as an explicit error to the tool
    executor.
    """

    def __init__(self, allow_vault_fallback: bool = True) -> None:
        self.allow_vault_fallback = allow_vault_fallback

    def lookup(self, entry: VaultEntry) -> str | None:
        if not self.allow_vault_fallback:
            return None
        return entry.original


class ChainedSecretStore:
    """Tries stores in order; first non-None wins."""

    def __init__(self, stores: list[SecretStore]) -> None:
        self.stores = stores

    def lookup(self, entry: VaultEntry) -> str | None:
        for store in self.stores:
            result = store.lookup(entry)
            if result is not None:
                return result
        return None


def make_default_store(allow_vault_fallback: bool = True) -> SecretStore:
    """Standard composition: env first, then optional vault fallback."""
    return ChainedSecretStore([
        EnvSecretStore(),
        VaultFallbackStore(allow_vault_fallback=allow_vault_fallback),
    ])


# Adapter for the resolver's `secret_resolver` callable signature.
# The resolver currently takes a no-arg callable; this adapter binds it to
# a SecretStore + a list of candidate vault entries to try in order.
def resolver_for_vault(vault, store: SecretStore) -> Callable[[], str | None]:
    """Build a callable suitable for `resolve_tool_call_args(secret_resolver=)`.

    The resolver iterates Tier-C entries in vault-insertion order, returning
    the first one the store can resolve. This is appropriate when there's
    exactly one secret in scope (the common case for env-style configs).
    For multi-secret tool calls we'd need a different protocol — see TODO
    below."""
    entries = [e for e in vault.all_entries() if e.tier == "C"]
    iterator = iter(entries)

    def resolve() -> str | None:
        try:
            entry = next(iterator)
        except StopIteration:
            return None
        return store.lookup(entry)

    return resolve

# TODO: multi-secret tool calls. The current resolver is stateful and
# returns secrets in vault order. If a single tool call contains two
# different bare `<REF>` markers, both get resolved against entries 1 and 2
# of the vault — which is order-dependent and fragile. A better protocol
# would have the LLM emit numbered Tier-C surface tokens (e.g. `<REF_S1>`,
# `<REF_S2>`), trading marginal information disclosure (the count) for
# unambiguous resolution. Tracked as a follow-up issue.
