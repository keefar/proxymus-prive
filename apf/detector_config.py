"""Detector runtime config — generative stage opt-in.

Reads ``~/.config/apf/config.toml`` (path overridable via the env var
``APF_CONFIG``). The only section consulted today is::

    [detector.generative_stage]
    endpoint    = "http://127.0.0.1:11434/v1"
    model       = "qwen2.5:1.5b-instruct-q4_K_M"
    api_key_env = "DETECTOR_API_KEY"   # optional — env name to read at runtime
    timeout_s   = 30.0                 # optional, default 30
    max_tokens  = 512                  # optional, default 512

When the section is present, the proxy adds an HTTP-backed generative
detector (see ``benchmarks.adapters_http``) as an additional stage of
the production ensemble. Activation is implicit — setting the section
IS the opt-in (apf-yyz decision (3a)).

Same file is intended to grow other ``[detector.*]`` sub-sections later
(e.g. ``[detector.backend]`` once the auto-detect work in apf-0h8 needs
config-driven override), so this module deliberately scopes itself to
parsing one section rather than owning the whole config.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _config_path() -> Path:
    override = os.environ.get("APF_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "apf" / "config.toml"


def _load_toml(path: Path) -> dict[str, Any]:
    """Load TOML best-effort. Missing or malformed → empty dict."""
    if not path.exists():
        return {}
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
        except ImportError:
            print(
                f"apf: tomllib unavailable; skipping {path}", flush=True
            )
            return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except Exception as exc:
        print(
            f"apf: failed to read {path}: {exc}", flush=True
        )
        return {}


def load_generative_stage_config() -> dict[str, Any] | None:
    """Return constructor kwargs for OpenAICompatibleDetectorAdapter, or None.

    None means: no opt-in, run the base ensemble alone. Required keys
    (``endpoint``, ``model``) missing → also None with a stderr warning,
    so a half-finished config does not silently enable the stage.

    ``api_key_env`` is dereferenced here (the env var is read at config
    time) so the adapter itself stays oblivious to env conventions.
    """
    raw = _load_toml(_config_path()).get("detector", {})
    section = raw.get("generative_stage")
    if not section:
        return None

    endpoint = section.get("endpoint")
    model = section.get("model")
    if not endpoint or not model:
        print(
            "apf: [detector.generative_stage] needs endpoint and model "
            "— stage disabled",
            flush=True,
        )
        return None

    kwargs: dict[str, Any] = {
        "endpoint": str(endpoint),
        "model": str(model),
    }

    api_key_env = section.get("api_key_env")
    if api_key_env:
        kwargs["api_key"] = os.environ.get(str(api_key_env), "")

    if "timeout_s" in section:
        kwargs["timeout_s"] = float(section["timeout_s"])
    if "max_tokens" in section:
        kwargs["max_tokens"] = int(section["max_tokens"])
    return kwargs
