"""Tests for ``apf._paths.config_dir`` (apf-d6y)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import _paths


def _clear_env(monkeypatch) -> None:
    for var in ("APF_CONFIG_DIR", "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(var, raising=False)


def test_apf_config_dir_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("APF_CONFIG_DIR", str(tmp_path / "custom"))
    assert _paths.config_dir() == tmp_path / "custom"


def test_apf_config_dir_env_override_expanduser(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("APF_CONFIG_DIR", "~/custom-apf")
    assert _paths.config_dir() == Path.home() / "custom-apf"


def test_linux_macos_default_is_xdg_config_apf(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(_paths.sys, "platform", "linux")
    assert _paths.config_dir() == Path.home() / ".config" / "apf"


def test_linux_macos_honors_xdg_config_home(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setattr(_paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert _paths.config_dir() == tmp_path / "xdg" / "apf"


def test_macos_default_matches_existing_install_layout(monkeypatch):
    """Existing macOS users have ``~/.config/apf/`` files; preserve it."""
    _clear_env(monkeypatch)
    monkeypatch.setattr(_paths.sys, "platform", "darwin")
    assert _paths.config_dir() == Path.home() / ".config" / "apf"


def test_windows_uses_appdata(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setattr(_paths.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert _paths.config_dir() == tmp_path / "Roaming" / "apf"


def test_windows_fallback_when_appdata_unset(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(_paths.sys, "platform", "win32")
    assert _paths.config_dir() == (
        Path.home() / "AppData" / "Roaming" / "apf"
    )


def test_windows_ignores_xdg_config_home(monkeypatch, tmp_path):
    """XDG vars on Windows (e.g. via Cygwin) must not redirect %APPDATA%."""
    _clear_env(monkeypatch)
    monkeypatch.setattr(_paths.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert _paths.config_dir() == tmp_path / "Roaming" / "apf"
