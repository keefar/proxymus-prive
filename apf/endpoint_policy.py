"""Per-destination filter policy (apf-ycu).

The proxy decides whether to filter a request based on the upstream host:

- `full`  — tokenise everything (default for unknown / cloud hosts)
- `off`   — pass through raw (default for local engines and explicit
            user-trusted endpoints)
- `categorical-only` — reserved for future audited no-log endpoints
            (Apple Private Compute, duck.ai-style claims). Not used in v1.

Local-engine endpoints are trusted-by-default because the user is running
them — that's literally why they installed them. Cloud endpoints default
to `full` until explicitly trusted.

Config:
  Default values are baked into this module. Users can override via
  ~/.config/apf/endpoints.toml (file optional). Example shape:

      [[endpoints]]
      host = "api.openai.com"
      policy = "full"

      [[endpoints]]
      host = "my-trusted-proxy.tail-scale.ts.net"
      policy = "off"

Environment variable APF_ENDPOINT_CONFIG overrides the config path.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

# Policy values. Module-level constants for downstream import.
POLICY_FULL = "full"
POLICY_OFF = "off"
POLICY_CATEGORICAL_ONLY = "categorical-only"

# Default for hosts not otherwise classified — privacy-conservative.
DEFAULT_POLICY = POLICY_FULL


# Loopback hosts; always local, always trusted unless overridden.
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


# Built-in entries that ship with the proxy. User config layers on top.
# Local engines + loopback: trust by default. Common cloud endpoints
# listed explicitly (redundant with DEFAULT_POLICY=full, but makes
# the active inventory visible to anyone reading config).
_BUILTIN_POLICY: dict[str, str] = {
    # Local model engines on standard ports (resolved via host only;
    # port-specific overrides would need a different layout)
    "localhost": POLICY_OFF,
    "127.0.0.1": POLICY_OFF,
    "::1": POLICY_OFF,
    # Major cloud APIs, explicit
    "api.anthropic.com": POLICY_FULL,
    "api.openai.com": POLICY_FULL,
    "api.groq.com": POLICY_FULL,
    "api.together.xyz": POLICY_FULL,
    "api.mistral.ai": POLICY_FULL,
    "openrouter.ai": POLICY_FULL,
    "api.cerebras.ai": POLICY_FULL,
    "api.sambanova.ai": POLICY_FULL,
}


def _load_user_overrides() -> dict[str, str]:
    """Load user TOML overrides if the config file exists. Best-effort —
    malformed or missing files return an empty override map (with a
    log line on stderr) rather than failing the proxy."""
    path_env = os.environ.get("APF_ENDPOINT_CONFIG")
    if path_env:
        path = Path(path_env).expanduser()
    else:
        path = Path.home() / ".config" / "apf" / "endpoints.toml"
    if not path.exists():
        return {}
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
        except ImportError:
            print(f"apf: tomllib unavailable; skipping {path}", flush=True)
            return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception as exc:
        print(f"apf: failed to read endpoint config {path}: {exc}", flush=True)
        return {}
    overrides: dict[str, str] = {}
    for entry in data.get("endpoints", []) or []:
        host = entry.get("host")
        policy = entry.get("policy")
        if isinstance(host, str) and policy in (
            POLICY_FULL, POLICY_OFF, POLICY_CATEGORICAL_ONLY,
        ):
            overrides[host.lower()] = policy
    return overrides


def _effective_map() -> dict[str, str]:
    """Built-ins overridden by user config (loaded on each lookup so config
    edits take effect without proxy restart). Tiny dict, copy is cheap."""
    m = dict(_BUILTIN_POLICY)
    m.update(_load_user_overrides())
    return m


def policy_for_host(host: str | None) -> str:
    """Filter policy for a host name. Empty/None → default policy.

    Local loopback always returns POLICY_OFF unless explicitly overridden
    to something else in user config (downgrade for paranoid users who
    don't fully trust their own local model setup)."""
    if not host:
        return DEFAULT_POLICY
    h = host.lower().strip()
    m = _effective_map()
    if h in m:
        return m[h]
    if h in _LOOPBACK_HOSTS:
        return POLICY_OFF
    if h.endswith(".local"):
        # mDNS LAN-local hosts; tighter user opt-in via config if anyone
        # wants this stricter. Default off because LAN-local typically
        # means user's own hardware.
        return POLICY_OFF
    return DEFAULT_POLICY


def policy_for_url(url: str) -> str:
    """Convenience: parse URL, look up policy for its host."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return DEFAULT_POLICY
    return policy_for_host(parsed.hostname)
