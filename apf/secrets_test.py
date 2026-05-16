"""Tests for the secret store layer."""
from __future__ import annotations

import os
import sys

from apf.secrets import (
    ChainedSecretStore,
    EnvSecretStore,
    VaultFallbackStore,
    resolver_for_vault,
)
from apf.vault import Vault


def ok(label: str) -> None:
    print(f"  ok    {label}")


def fail(label: str, *details) -> None:
    print(f"FAIL  {label}")
    for d in details:
        print(f"  {d}")
    sys.exit(1)


def test_env_store_basic() -> None:
    print("\n=== Test 1: env store reads by key name ===")
    os.environ["APF_TEST_OPENAI_KEY"] = "sk-real-env-value"
    vault = Vault()
    entry = vault.get_or_mint("sk-test-fake-value", "API_KEY", "C",
                              secret_key_name="APF_TEST_OPENAI_KEY")
    store = EnvSecretStore()
    resolved = store.lookup(entry)
    if resolved != "sk-real-env-value":
        fail("env store lookup", f"got {resolved!r}")
    ok(f"env lookup returned {resolved!r}")
    del os.environ["APF_TEST_OPENAI_KEY"]


def test_env_store_alias() -> None:
    print("\n=== Test 2: env store alias mapping ===")
    os.environ["APF_TEST_SMTP_PASS"] = "alias-value"
    vault = Vault()
    entry = vault.get_or_mint("xxx", "PASSWORD", "C",
                              secret_key_name="SMTP_PASSWORD")
    store = EnvSecretStore(aliases={"SMTP_PASSWORD": "APF_TEST_SMTP_PASS"})
    resolved = store.lookup(entry)
    if resolved != "alias-value":
        fail("env store alias", f"got {resolved!r}")
    ok("alias mapping resolved")
    del os.environ["APF_TEST_SMTP_PASS"]


def test_vault_fallback_disabled() -> None:
    print("\n=== Test 3: vault fallback honours the disabled flag ===")
    vault = Vault()
    entry = vault.get_or_mint("super-secret", "PASSWORD", "C")
    store = VaultFallbackStore(allow_vault_fallback=False)
    resolved = store.lookup(entry)
    if resolved is not None:
        fail("disabled fallback should return None", f"got {resolved!r}")
    ok("disabled fallback returns None")


def test_vault_fallback_enabled() -> None:
    print("\n=== Test 4: vault fallback returns original when enabled ===")
    vault = Vault()
    entry = vault.get_or_mint("super-secret", "PASSWORD", "C")
    store = VaultFallbackStore(allow_vault_fallback=True)
    resolved = store.lookup(entry)
    if resolved != "super-secret":
        fail("enabled fallback", f"got {resolved!r}")
    ok("enabled fallback returns original")


def test_chained_env_then_vault() -> None:
    print("\n=== Test 5: chained store, env wins over vault ===")
    os.environ["APF_TEST_KEY"] = "from-env"
    vault = Vault()
    entry = vault.get_or_mint("from-vault", "API_KEY", "C",
                              secret_key_name="APF_TEST_KEY")
    chained = ChainedSecretStore([
        EnvSecretStore(),
        VaultFallbackStore(),
    ])
    resolved = chained.lookup(entry)
    if resolved != "from-env":
        fail("env should win", f"got {resolved!r}")
    ok("env wins over vault when both present")
    del os.environ["APF_TEST_KEY"]


def test_chained_falls_back_to_vault() -> None:
    print("\n=== Test 6: chained store, no env → vault fallback ===")
    vault = Vault()
    entry = vault.get_or_mint("vault-only", "TOKEN", "C",
                              secret_key_name="APF_NO_SUCH_KEY_99999")
    chained = ChainedSecretStore([
        EnvSecretStore(),
        VaultFallbackStore(allow_vault_fallback=True),
    ])
    resolved = chained.lookup(entry)
    if resolved != "vault-only":
        fail("vault fallback", f"got {resolved!r}")
    ok("falls through to vault when env misses")


def test_resolver_for_vault_iterates() -> None:
    print("\n=== Test 7: resolver_for_vault iterates Tier-C entries ===")
    vault = Vault()
    vault.get_or_mint("first", "API_KEY", "C")
    vault.get_or_mint("second", "PASSWORD", "C")
    vault.get_or_mint("Anna", "PERSON", "A")  # Tier A — should be skipped
    store = VaultFallbackStore(allow_vault_fallback=True)
    callable_resolver = resolver_for_vault(vault, store)
    first = callable_resolver()
    second = callable_resolver()
    third = callable_resolver()
    if first != "first":
        fail("first call", f"got {first!r}")
    if second != "second":
        fail("second call", f"got {second!r}")
    if third is not None:
        fail("third call (exhausted)", f"got {third!r}")
    ok("iterator yields Tier-C entries in vault order then exhausts")


def main() -> int:
    test_env_store_basic()
    test_env_store_alias()
    test_vault_fallback_disabled()
    test_vault_fallback_enabled()
    test_chained_env_then_vault()
    test_chained_falls_back_to_vault()
    test_resolver_for_vault_iterates()
    print("\nALL SECRET STORE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
