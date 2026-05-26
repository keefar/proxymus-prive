"""Tests for the [detector.generative_stage] config loader."""
from __future__ import annotations

from pathlib import Path

from apf.detector_config import load_generative_stage_config


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_missing_file_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APF_CONFIG", str(tmp_path / "absent.toml"))
    assert load_generative_stage_config() is None


def test_empty_file_returns_none(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("")
    monkeypatch.setenv("APF_CONFIG", str(cfg))
    assert load_generative_stage_config() is None


def test_section_missing_required_keys_returns_none(
    tmp_path, monkeypatch, capsys
) -> None:
    # endpoint without model: stage stays off, warning on stderr so it's
    # findable but the proxy does not silently enable the stage.
    cfg = tmp_path / "config.toml"
    _write(cfg, '[detector.generative_stage]\nendpoint = "http://x"\n')
    monkeypatch.setenv("APF_CONFIG", str(cfg))
    assert load_generative_stage_config() is None
    out = capsys.readouterr()
    assert "endpoint and model" in (out.out + out.err)


def test_minimal_section_returns_kwargs(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "config.toml"
    _write(
        cfg,
        '[detector.generative_stage]\n'
        'endpoint = "http://127.0.0.1:11434/v1"\n'
        'model = "qwen2.5:1.5b-instruct-q4_K_M"\n',
    )
    monkeypatch.setenv("APF_CONFIG", str(cfg))
    kw = load_generative_stage_config()
    assert kw == {
        "endpoint": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:1.5b-instruct-q4_K_M",
    }


def test_full_section_with_api_key_env(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "config.toml"
    _write(
        cfg,
        '[detector.generative_stage]\n'
        'endpoint = "http://gpu-host:8080/v1"\n'
        'model = "mistral:7b-instruct"\n'
        'api_key_env = "MY_DETECTOR_KEY"\n'
        'timeout_s = 45.0\n'
        'max_tokens = 1024\n',
    )
    monkeypatch.setenv("APF_CONFIG", str(cfg))
    monkeypatch.setenv("MY_DETECTOR_KEY", "secret-xyz")
    kw = load_generative_stage_config()
    assert kw == {
        "endpoint": "http://gpu-host:8080/v1",
        "model": "mistral:7b-instruct",
        "api_key": "secret-xyz",
        "timeout_s": 45.0,
        "max_tokens": 1024,
    }


def test_api_key_env_missing_uses_empty_string(tmp_path, monkeypatch) -> None:
    cfg = tmp_path / "config.toml"
    _write(
        cfg,
        '[detector.generative_stage]\n'
        'endpoint = "http://x/v1"\n'
        'model = "m"\n'
        'api_key_env = "NEVER_SET_KEY"\n',
    )
    monkeypatch.setenv("APF_CONFIG", str(cfg))
    monkeypatch.delenv("NEVER_SET_KEY", raising=False)
    kw = load_generative_stage_config()
    assert kw is not None
    assert kw["api_key"] == ""


def test_malformed_toml_returns_none(tmp_path, monkeypatch, capsys) -> None:
    cfg = tmp_path / "config.toml"
    _write(cfg, "this is not [valid toml")
    monkeypatch.setenv("APF_CONFIG", str(cfg))
    assert load_generative_stage_config() is None
    out = capsys.readouterr()
    assert "failed to read" in (out.out + out.err)
