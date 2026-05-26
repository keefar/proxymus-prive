"""Tests for the detector composition layer (apf-yyz).

Covers:
- SoftDegradeWrapper: warmup() is hard-fail, detect() swallows + counts
- CompositeDetector: stages are warmed in order; spans are merged
- build_proxy_detector(): base path without config, composite path with
"""
from __future__ import annotations

from benchmarks.adapters import Span
from apf.detector_stage import (
    CompositeDetector,
    SoftDegradeWrapper,
    build_proxy_detector,
)


class _FakeDetector:
    """Stub stage with scripted detect() output and a warmup counter."""

    def __init__(self, name: str, spans: list[Span] | None = None,
                 raise_on_warmup: bool = False,
                 raise_on_detect: bool = False) -> None:
        self.name = name
        self._spans = spans or []
        self.warmups = 0
        self.raise_on_warmup = raise_on_warmup
        self.raise_on_detect = raise_on_detect

    def warmup(self) -> None:
        if self.raise_on_warmup:
            raise RuntimeError("warmup blew up")
        self.warmups += 1

    def detect(self, text: str) -> list[Span]:
        if self.raise_on_detect:
            raise RuntimeError("detect blew up")
        return self._spans


def test_softdegrade_passes_through_normal_detect() -> None:
    inner = _FakeDetector(
        "inner", spans=[Span(0, 5, "PERSON", "A")]
    )
    w = SoftDegradeWrapper(inner)
    w.warmup()
    spans = w.detect("anything")
    assert len(spans) == 1
    assert spans[0].label == "PERSON"
    assert w.failure_count == 0


def test_softdegrade_warmup_is_hard_fail() -> None:
    inner = _FakeDetector("inner", raise_on_warmup=True)
    w = SoftDegradeWrapper(inner)
    import pytest
    with pytest.raises(RuntimeError, match="warmup blew up"):
        w.warmup()


def test_softdegrade_swallows_detect_exceptions() -> None:
    inner = _FakeDetector("inner", raise_on_detect=True)
    w = SoftDegradeWrapper(inner)
    w.warmup()
    # First failing detect: empty result, counter at 1.
    assert w.detect("text") == []
    assert w.failure_count == 1
    # Counter increments per failure — does not crash even after many.
    for _ in range(5):
        w.detect("text")
    assert w.failure_count == 6


def test_softdegrade_name_defaults_to_wrapped() -> None:
    inner = _FakeDetector("inner-name")
    w = SoftDegradeWrapper(inner)
    assert w.name == "inner-name"


def test_softdegrade_name_override() -> None:
    inner = _FakeDetector("inner-name")
    w = SoftDegradeWrapper(inner, name="custom")
    assert w.name == "custom"


def test_composite_requires_at_least_one_stage() -> None:
    import pytest
    with pytest.raises(ValueError):
        CompositeDetector([])


def test_composite_warmup_runs_all_stages_in_order() -> None:
    a = _FakeDetector("a")
    b = _FakeDetector("b")
    c = CompositeDetector([a, b])
    c.warmup()
    assert a.warmups == 1
    assert b.warmups == 1


def test_composite_detect_merges_spans() -> None:
    # Two stages produce disjoint spans → merge keeps both.
    s1 = Span(0, 5, "PERSON", "A")
    s2 = Span(10, 15, "EMAIL", "A")
    a = _FakeDetector("a", spans=[s1])
    b = _FakeDetector("b", spans=[s2])
    c = CompositeDetector([a, b])
    text = "Alice yes bob@x rest"
    spans = c.detect(text)
    labels = {s.label for s in spans}
    assert {"PERSON", "EMAIL"} <= labels


def test_composite_detect_with_softdegrade_stage_failure() -> None:
    # One healthy stage + one failing-then-degrading stage. Composite
    # must still return the healthy stage's spans.
    healthy = _FakeDetector(
        "healthy", spans=[Span(0, 5, "PERSON", "A")]
    )
    flaky_inner = _FakeDetector("flaky", raise_on_detect=True)
    flaky = SoftDegradeWrapper(flaky_inner)
    c = CompositeDetector([healthy, flaky])
    c.warmup()
    spans = c.detect("Alice anything")
    assert len(spans) == 1
    assert spans[0].label == "PERSON"
    assert flaky.failure_count == 1


def test_build_proxy_detector_without_config(tmp_path, monkeypatch) -> None:
    # APF_CONFIG points at a non-existent file → no opt-in, base ensemble.
    monkeypatch.setenv("APF_CONFIG", str(tmp_path / "no.toml"))
    detector = build_proxy_detector()
    # Should be the bare EnsembleMaxAdapter, not a composite.
    assert detector.__class__.__name__ == "EnsembleMaxAdapter"


def test_build_proxy_detector_with_config(tmp_path, monkeypatch) -> None:
    # Generative-stage section opts in → composite with two stages.
    cfg = tmp_path / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        '[detector.generative_stage]\n'
        'endpoint = "http://127.0.0.1:11434/v1"\n'
        'model = "qwen2.5:1.5b-instruct-q4_K_M"\n'
    )
    monkeypatch.setenv("APF_CONFIG", str(cfg))
    detector = build_proxy_detector()
    assert isinstance(detector, CompositeDetector)
    assert len(detector.stages) == 2
    # Stage 0: EnsembleMax. Stage 1: SoftDegradeWrapper around HTTP.
    assert detector.stages[0].__class__.__name__ == "EnsembleMaxAdapter"
    assert isinstance(detector.stages[1], SoftDegradeWrapper)
    assert detector.stages[1].name == "generative-stage"
