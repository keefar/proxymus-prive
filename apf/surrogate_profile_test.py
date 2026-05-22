"""apf-dkf: per-request masking strategy from the active model profile.

The opaque-vs-surrogate choice is resolved per request from the
incoming `model` field via apf.model_profiles.profile_for_model:

  - profile recommends `surrogate` -> mask with the ratified hybrid set
  - profile recommends `opaque`    -> fully opaque
  - unknown model                  -> conservative opaque default
  - explicit APF_SURROGATE_LABELS env override always wins
  - Tier-C secrets stay opaque regardless of profile (absolute invariant)
"""
from __future__ import annotations

import apf.proxy as proxy
from apf.masker import Span
from apf.surrogates import SURROGATE_LABELS
from apf.vault import Vault


# --- helpers ---------------------------------------------------------------

def _write_profiles(tmp_path, monkeypatch, toml: str):
    """Point the model-profile registry at an isolated TOML file."""
    cfg = tmp_path / "model_profiles.toml"
    cfg.write_text(toml)
    monkeypatch.setenv("APF_MODEL_PROFILE_CONFIG", str(cfg))


def _install_person_detector(monkeypatch) -> None:
    """Stub detector: a PERSON (Tier-A) span on 'Anna'."""
    class _Stub:
        name = "stub"

        def detect(self, text: str):
            spans = []
            if "Anna" in text:
                i = text.index("Anna")
                spans.append(Span(start=i, end=i + 4, label="PERSON",
                                  tier="A", confidence=1.0))
            return spans
    monkeypatch.setattr(proxy, "_DETECTOR", _Stub())


def _install_secret_detector(monkeypatch) -> None:
    """Stub detector: a PERSON (Tier-A) span on 'Anna' AND an API_KEY
    (Tier-C) span on 'sk-SECRET'."""
    class _Stub:
        name = "stub"

        def detect(self, text: str):
            spans = []
            if "Anna" in text:
                i = text.index("Anna")
                spans.append(Span(start=i, end=i + 4, label="PERSON",
                                  tier="A", confidence=1.0))
            if "sk-SECRET" in text:
                i = text.index("sk-SECRET")
                spans.append(Span(start=i, end=i + 9, label="API_KEY",
                                  tier="C", confidence=1.0))
            return spans
    monkeypatch.setattr(proxy, "_DETECTOR", _Stub())


# --- _resolve_surrogate_labels: the per-request decision -------------------

def test_profile_surrogate_yields_hybrid_set(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("APF_SURROGATE_LABELS", raising=False)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", None)
    _write_profiles(tmp_path, monkeypatch, """
[[models]]
model = "weak-local-7b"
token_passthrough = "mangles"
recommended_strategy = "surrogate"
""")
    assert proxy._resolve_surrogate_labels("weak-local-7b") == SURROGATE_LABELS


def test_profile_opaque_yields_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("APF_SURROGATE_LABELS", raising=False)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", None)
    _write_profiles(tmp_path, monkeypatch, """
[[models]]
model = "strong-cloud-model"
token_passthrough = "verbatim"
recommended_strategy = "opaque"
""")
    assert proxy._resolve_surrogate_labels("strong-cloud-model") == frozenset()


def test_unknown_model_gets_opaque_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("APF_SURROGATE_LABELS", raising=False)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", None)
    _write_profiles(tmp_path, monkeypatch, "")
    assert proxy._resolve_surrogate_labels("never-seen-model") == frozenset()


def test_none_model_gets_opaque_default(monkeypatch) -> None:
    monkeypatch.delenv("APF_SURROGATE_LABELS", raising=False)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", None)
    assert proxy._resolve_surrogate_labels(None) == frozenset()


def test_env_override_wins_over_surrogate_profile(tmp_path, monkeypatch) -> None:
    # Profile says surrogate-everything; the explicit env override says
    # only EMAIL — the override wins.
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", frozenset({"EMAIL"}))
    _write_profiles(tmp_path, monkeypatch, """
[[models]]
model = "weak-local-7b"
recommended_strategy = "surrogate"
""")
    assert proxy._resolve_surrogate_labels("weak-local-7b") == frozenset({"EMAIL"})


def test_env_override_wins_over_opaque_profile(tmp_path, monkeypatch) -> None:
    # Profile says opaque; the explicit env override says surrogate
    # PERSON — the override still wins (user intent is authoritative).
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE",
                        frozenset({"PERSON"}))
    _write_profiles(tmp_path, monkeypatch, """
[[models]]
model = "strong-cloud-model"
recommended_strategy = "opaque"
""")
    assert proxy._resolve_surrogate_labels("strong-cloud-model") == \
        frozenset({"PERSON"})


def test_empty_env_override_is_not_treated_as_set(tmp_path, monkeypatch) -> None:
    # APF_SURROGATE_LABELS unset -> SURROGATE_LABELS_OVERRIDE is None ->
    # the profile decides.
    monkeypatch.delenv("APF_SURROGATE_LABELS", raising=False)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", None)
    _write_profiles(tmp_path, monkeypatch, """
[[models]]
model = "weak-local-7b"
recommended_strategy = "surrogate"
""")
    assert proxy._resolve_surrogate_labels("weak-local-7b") == SURROGATE_LABELS


# --- _load_surrogate_labels_override: env parsing --------------------------

def test_override_loader_none_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("APF_SURROGATE_LABELS", raising=False)
    assert proxy._load_surrogate_labels_override() is None


def test_override_loader_set_when_env_present(monkeypatch) -> None:
    monkeypatch.setenv("APF_SURROGATE_LABELS", "person,email")
    assert proxy._load_surrogate_labels_override() == \
        frozenset({"PERSON", "EMAIL"})


def test_override_loader_all_keyword(monkeypatch) -> None:
    monkeypatch.setenv("APF_SURROGATE_LABELS", "all")
    assert proxy._load_surrogate_labels_override() == SURROGATE_LABELS


def test_override_loader_only_sensitive_is_empty_but_set(monkeypatch) -> None:
    # Naming only sensitive categories intersects to empty — but the env
    # var WAS set, so the override is the empty frozenset (force opaque),
    # not None (defer to profile).
    monkeypatch.setenv("APF_SURROGATE_LABELS", "HEALTH,API_KEY")
    assert proxy._load_surrogate_labels_override() == frozenset()


def test_only_sensitive_env_override_forces_opaque(tmp_path, monkeypatch) -> None:
    # Profile recommends surrogate, but the user set APF_SURROGATE_LABELS
    # to only-sensitive labels — that is an explicit (if futile) override
    # and it forces opaque, overriding the profile.
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", frozenset())
    _write_profiles(tmp_path, monkeypatch, """
[[models]]
model = "weak-local-7b"
recommended_strategy = "surrogate"
""")
    assert proxy._resolve_surrogate_labels("weak-local-7b") == frozenset()


# --- end-to-end through _mask_text -----------------------------------------

def test_mask_text_surrogates_for_surrogate_profile(tmp_path, monkeypatch) -> None:
    _install_person_detector(monkeypatch)
    monkeypatch.delenv("APF_SURROGATE_LABELS", raising=False)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", None)
    _write_profiles(tmp_path, monkeypatch, """
[[models]]
model = "weak-local-7b"
recommended_strategy = "surrogate"
""")
    vault = Vault()
    out = proxy._mask_text("hi Anna there", vault, model="weak-local-7b")
    assert "Anna" not in out               # original gone
    assert "<REF" not in out               # surrogate, not an opaque token
    assert vault.all_entries()[0].surrogate is not None


def test_mask_text_opaque_for_opaque_profile(tmp_path, monkeypatch) -> None:
    _install_person_detector(monkeypatch)
    monkeypatch.delenv("APF_SURROGATE_LABELS", raising=False)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", None)
    _write_profiles(tmp_path, monkeypatch, """
[[models]]
model = "strong-cloud-model"
recommended_strategy = "opaque"
""")
    out = proxy._mask_text("hi Anna there", Vault(), model="strong-cloud-model")
    assert out == "hi <REF_1> there"


def test_mask_text_opaque_for_unknown_model(tmp_path, monkeypatch) -> None:
    _install_person_detector(monkeypatch)
    monkeypatch.delenv("APF_SURROGATE_LABELS", raising=False)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", None)
    _write_profiles(tmp_path, monkeypatch, "")
    out = proxy._mask_text("hi Anna there", Vault(), model="never-seen")
    assert out == "hi <REF_1> there"


def test_mask_text_env_override_wins(tmp_path, monkeypatch) -> None:
    # Profile recommends surrogate, but the env override forces opaque.
    _install_person_detector(monkeypatch)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", frozenset())
    _write_profiles(tmp_path, monkeypatch, """
[[models]]
model = "weak-local-7b"
recommended_strategy = "surrogate"
""")
    out = proxy._mask_text("hi Anna there", Vault(), model="weak-local-7b")
    assert out == "hi <REF_1> there"


def test_tier_c_secret_stays_opaque_under_surrogate_profile(
        tmp_path, monkeypatch) -> None:
    # The absolute invariant: even with a surrogate profile, a Tier-C
    # secret keeps its opaque <REF_N> token — API_KEY is not in the
    # ratified hybrid set, so the masker's guard keeps it opaque.
    _install_secret_detector(monkeypatch)
    monkeypatch.delenv("APF_SURROGATE_LABELS", raising=False)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE", None)
    _write_profiles(tmp_path, monkeypatch, """
[[models]]
model = "weak-local-7b"
recommended_strategy = "surrogate"
""")
    vault = Vault()
    out = proxy._mask_text("hi Anna key sk-SECRET", vault,
                           model="weak-local-7b")
    assert "sk-SECRET" not in out          # secret masked
    assert "<REF" in out                   # ...to an opaque token
    secret_entry = next(e for e in vault.all_entries()
                        if e.label == "API_KEY")
    assert secret_entry.surrogate is None  # never surrogated
    # the PERSON span, by contrast, IS surrogated
    person_entry = next(e for e in vault.all_entries()
                        if e.label == "PERSON")
    assert person_entry.surrogate is not None


def test_mask_text_default_model_arg_uses_override(monkeypatch) -> None:
    # Backward-compat: a caller that does not pass `model` falls back to
    # the SURROGATE_LABELS_OVERRIDE global (legacy global behaviour).
    _install_person_detector(monkeypatch)
    monkeypatch.setattr(proxy, "SURROGATE_LABELS_OVERRIDE",
                        frozenset({"PERSON"}))
    vault = Vault()
    out = proxy._mask_text("hi Anna there", vault)
    assert "Anna" not in out
    assert "<REF" not in out
    assert vault.all_entries()[0].surrogate is not None
