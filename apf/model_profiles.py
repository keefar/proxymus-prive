"""Model profile registry — per-upstream-model token-handling profiles (apf-ao2).

apf masks PII either to opaque ``<REF_N>`` tokens (default) or to plausible
surrogate values (flag-gated). Which strategy is best depends on the upstream
model: a weak model mangles opaque tokens (apf-2qz), a strong one handles them
fine; dense opaque-token clusters can trip a capable model's injection
defences (apf-76s). This module is the *data layer* for that decision — a
declarative, per-model registry. Wiring the choice into the proxy request
path is a separate ticket (apf-dkf); nothing here imports or touches the proxy.

Profiles are TOML, keyed by the ``model`` field of an incoming
OpenAI/Anthropic request:

    [[models]]
    model = "Qwen2.5-Coder-7B-Instruct-MLX-4bit"
    token_passthrough = "mangles"        # verbatim | mangles | unknown
    recommended_strategy = "surrogate"   # opaque | surrogate
    injection_sensitivity = "low"        # low | high
    notes = "free text — the evidence trail"

Layering — mirrors ``apf/endpoint_policy.py``:

  1. Shipped profiles in the in-repo ``model_profiles/`` directory
     (one file per model by convention; multiple ``[[models]]`` tables
     per file are accepted).
  2. User overrides in ``~/.config/apf/model_profiles.toml`` (file
     optional). A user entry for a model id replaces the shipped profile
     for that id.

The config path can be redirected with the ``APF_MODEL_PROFILE_CONFIG``
environment variable (used by the test suite for isolation).

Unknown model ids resolve to a conservative DEFAULT profile:
``token_passthrough=unknown``, ``recommended_strategy=opaque``,
``injection_sensitivity=low``. Opaque is the *safe* default — surrogate
has known robustness costs, so an untested model is never silently
switched to surrogate.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --- Enum values. Module-level constants for downstream import. ----------

# token_passthrough — how the model treats opaque <REF_N> tokens.
PASSTHROUGH_VERBATIM = "verbatim"   # tokens come back byte-identical
PASSTHROUGH_MANGLES = "mangles"     # tokens get renumbered / paraphrased
PASSTHROUGH_UNKNOWN = "unknown"     # not tested

# recommended_strategy — which masking strategy apf should use.
STRATEGY_OPAQUE = "opaque"          # <REF_N> placeholders (safe default)
STRATEGY_SURROGATE = "surrogate"    # plausible fake values

# injection_sensitivity — apf-76s dense-opaque-cluster decline risk.
SENSITIVITY_LOW = "low"
SENSITIVITY_HIGH = "high"

_VALID_PASSTHROUGH = {PASSTHROUGH_VERBATIM, PASSTHROUGH_MANGLES, PASSTHROUGH_UNKNOWN}
_VALID_STRATEGY = {STRATEGY_OPAQUE, STRATEGY_SURROGATE}
_VALID_SENSITIVITY = {SENSITIVITY_LOW, SENSITIVITY_HIGH}


@dataclass(frozen=True)
class ModelProfile:
    """A resolved token-handling profile for one upstream model."""

    model: str
    token_passthrough: str = PASSTHROUGH_UNKNOWN
    recommended_strategy: str = STRATEGY_OPAQUE
    injection_sensitivity: str = SENSITIVITY_LOW
    notes: str = ""
    # True when this is the synthesised conservative default rather than
    # a real (shipped or user-supplied) profile. Lets the strategy
    # selector (apf-dkf) tell "we have evidence" from "we are guessing".
    is_default: bool = False


# Conservative profile returned for any model id with no registered
# entry. Opaque, never auto-surrogate. See module docstring.
def _default_profile(model: str) -> ModelProfile:
    return ModelProfile(
        model=model,
        token_passthrough=PASSTHROUGH_UNKNOWN,
        recommended_strategy=STRATEGY_OPAQUE,
        injection_sensitivity=SENSITIVITY_LOW,
        notes="No profile on record — conservative default (apf-ao2). "
              "Opaque masking; never auto-surrogate an untested model.",
        is_default=True,
    )


# In-repo directory holding the shipped profile TOML files.
_SHIPPED_DIR = Path(__file__).resolve().parent.parent / "model_profiles"


def _import_tomllib():
    """Return a TOML reader module, or None if none is available."""
    try:
        import tomllib
        return tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
            return tomllib
        except ImportError:
            return None


def _parse_entry(entry: dict, source: str) -> ModelProfile | None:
    """Validate one ``[[models]]`` table. Return a ModelProfile, or None
    if the entry is malformed — a bad entry is skipped, never fatal."""
    if not isinstance(entry, dict):
        return None
    model = entry.get("model")
    if not isinstance(model, str) or not model.strip():
        print(f"apf: model profile in {source} missing 'model' key — skipped",
              flush=True)
        return None

    passthrough = entry.get("token_passthrough", PASSTHROUGH_UNKNOWN)
    strategy = entry.get("recommended_strategy", STRATEGY_OPAQUE)
    sensitivity = entry.get("injection_sensitivity", SENSITIVITY_LOW)
    notes = entry.get("notes", "")

    if passthrough not in _VALID_PASSTHROUGH:
        print(f"apf: model profile '{model}' in {source}: bad "
              f"token_passthrough {passthrough!r} — entry skipped", flush=True)
        return None
    if strategy not in _VALID_STRATEGY:
        print(f"apf: model profile '{model}' in {source}: bad "
              f"recommended_strategy {strategy!r} — entry skipped", flush=True)
        return None
    if sensitivity not in _VALID_SENSITIVITY:
        print(f"apf: model profile '{model}' in {source}: bad "
              f"injection_sensitivity {sensitivity!r} — entry skipped", flush=True)
        return None
    if not isinstance(notes, str):
        notes = ""

    return ModelProfile(
        model=model,
        token_passthrough=passthrough,
        recommended_strategy=strategy,
        injection_sensitivity=sensitivity,
        notes=notes,
        is_default=False,
    )


def _load_toml_file(path: Path, into: dict[str, ModelProfile]) -> None:
    """Parse one TOML file's ``[[models]]`` tables into ``into``.
    Best-effort — a malformed file logs and is skipped, the registry
    keeps whatever it already has."""
    tomllib = _import_tomllib()
    if tomllib is None:
        print(f"apf: tomllib unavailable; skipping {path}", flush=True)
        return
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception as exc:
        print(f"apf: failed to read model profile file {path}: {exc}",
              flush=True)
        return
    for entry in data.get("models", []) or []:
        prof = _parse_entry(entry, str(path))
        if prof is not None:
            into[prof.model] = prof


def _load_shipped() -> dict[str, ModelProfile]:
    """Load every ``*.toml`` under the in-repo ``model_profiles/`` dir."""
    profiles: dict[str, ModelProfile] = {}
    if not _SHIPPED_DIR.is_dir():
        return profiles
    for path in sorted(_SHIPPED_DIR.glob("*.toml")):
        _load_toml_file(path, profiles)
    return profiles


def _user_config_path() -> Path:
    """Resolve the user-override TOML path. APF_MODEL_PROFILE_CONFIG
    overrides the default ``~/.config/apf/model_profiles.toml``."""
    path_env = os.environ.get("APF_MODEL_PROFILE_CONFIG")
    if path_env:
        return Path(path_env).expanduser()
    return Path.home() / ".config" / "apf" / "model_profiles.toml"


def _load_user_overrides() -> dict[str, ModelProfile]:
    """Load user overrides if the config file exists. Best-effort — a
    missing or malformed file returns an empty map (matches
    endpoint_policy)."""
    path = _user_config_path()
    if not path.exists():
        return {}
    overrides: dict[str, ModelProfile] = {}
    _load_toml_file(path, overrides)
    return overrides


def _effective_map() -> dict[str, ModelProfile]:
    """Shipped profiles overridden by user config. Loaded on each lookup
    so config edits take effect without a proxy restart — the registry
    is tiny, a re-read per call is cheap (mirrors endpoint_policy)."""
    m = _load_shipped()
    m.update(_load_user_overrides())
    return m


def profile_for_model(model: str | None) -> ModelProfile:
    """Return the token-handling profile for an upstream model id.

    Unknown / empty / None model ids return the conservative DEFAULT
    profile (``is_default=True``): opaque strategy, never auto-surrogate.
    """
    if not model or not model.strip():
        return _default_profile(model or "")
    m = _effective_map()
    prof = m.get(model)
    if prof is not None:
        return prof
    return _default_profile(model)


def all_profiles() -> dict[str, ModelProfile]:
    """Return the full effective registry (shipped + user overrides),
    keyed by model id. Does not include the synthesised default."""
    return _effective_map()
