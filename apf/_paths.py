"""Cross-platform config directory resolution (apf-d6y).

A single function ``config_dir()`` so the rest of the code never
hand-rolls ``Path.home() / ".config" / "apf"`` — that string was wrong
on Windows. macOS and Linux behaviour is preserved bit-for-bit so users
who already have files under ``~/.config/apf/`` keep working without a
migration.

Resolution order:

1. ``APF_CONFIG_DIR`` env override (any platform — for test isolation
   and operators who want a non-default location).
2. Windows (``sys.platform == "win32"``): ``%APPDATA%\\apf`` —
   ``%APPDATA%`` already points to ``C:\\Users\\<u>\\AppData\\Roaming``
   on every supported Windows version, so we don't need ``platformdirs``
   for one lookup.
3. Linux / macOS: ``$XDG_CONFIG_HOME/apf`` if set, else
   ``~/.config/apf``. macOS gets the XDG path on purpose — that's where
   apf has always written, and the existing test suite, examples, and
   user installs all assume it.

Per-file helpers are intentionally not provided. Callers that need
``config.toml``, ``endpoints.toml``, ``model_profiles.toml`` etc. just
do ``config_dir() / "config.toml"``. Their existing env overrides
(``APF_CONFIG``, ``APF_ENDPOINT_CONFIG``, ``APF_MODEL_PROFILE_CONFIG``)
still win — those are file-level escape hatches, this module is the
directory-level one.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def config_dir() -> Path:
    """Return the directory apf reads its TOML config from."""
    override = os.environ.get("APF_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "apf"
        return Path.home() / "AppData" / "Roaming" / "apf"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg).expanduser() / "apf"
    return Path.home() / ".config" / "apf"
