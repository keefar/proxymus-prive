"""Detector composition for the proxy runtime.

The benchmark harness uses the bare detector classes directly. The
proxy needs two extra capabilities the harness deliberately skips:

1. **Optional generative stage**: an HTTP-backed detector can be
   layered on top of the production ensemble — opt-in via the
   ``[detector.generative_stage]`` section in ``~/.config/apf/config.toml``.
2. **Soft-degrade per detect()**: when the external daemon used by the
   generative stage drops a request (timeout / 500 / unreachable), the
   proxy must not crash. The stage returns ``[]`` for that turn and
   bumps a failure counter; the rest of the ensemble continues.

Startup behaviour (apf-yyz decision (1c)) is the strict half of the
compromise: ``warmup()`` is hard-fail. If the daemon is unreachable
when the proxy boots, the operator finds out at startup time — not at
the first masked request.
"""
from __future__ import annotations

from typing import Any, Protocol


class _DetectorLike(Protocol):
    name: str

    def warmup(self) -> None: ...
    def detect(self, text: str) -> list: ...


class SoftDegradeWrapper:
    """Swallow detect() exceptions, count them, never raise.

    The wrapped detector's ``warmup()`` is still allowed to fail loudly —
    we want the proxy to refuse to start if the external daemon is
    unreachable at boot, so the operator sees the misconfiguration up
    front. After warmup succeeds, any per-request failure is treated as
    a transient issue: this turn just sees no spans from this stage,
    other stages still run, the request still goes through.
    """

    def __init__(self, wrapped: _DetectorLike, *, name: str | None = None):
        self.wrapped = wrapped
        self.name = name or getattr(wrapped, "name", "wrapped")
        self._failure_count = 0

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def warmup(self) -> None:
        # Deliberate: hard-fail at startup so misconfig surfaces early.
        self.wrapped.warmup()

    def detect(self, text: str) -> list:
        try:
            return self.wrapped.detect(text)
        except Exception:
            self._failure_count += 1
            return []


class CompositeDetector:
    """Run multiple detector stages and merge their spans.

    Uses the same merge logic the existing ensemble classes use
    (``benchmarks.adapters_mlx._merge_spans``) so adding the generative
    stage on top of EnsembleMax has identical merge semantics to the
    rest of the inventory — no per-composite tuning, no surprises.
    """

    name = "composite"

    def __init__(self, stages: list[_DetectorLike]):
        if not stages:
            raise ValueError("CompositeDetector needs at least one stage")
        self.stages = stages

    def warmup(self) -> None:
        for stage in self.stages:
            stage.warmup()

    def detect(self, text: str) -> list:
        # Late import keeps adapters_mlx out of module-load on Linux
        # installs without mlx — same pattern as the existing lazy
        # imports inside adapters_mlx itself.
        from benchmarks.adapters_mlx import _merge_spans
        groups = [stage.detect(text) for stage in self.stages]
        return _merge_spans(groups, text)


def build_proxy_detector() -> _DetectorLike:
    """Return the detector instance the FastAPI lifespan should warm up.

    Base case (no opt-in): ``EnsembleMaxAdapter`` directly — same as
    before this wiring landed.

    With ``[detector.generative_stage]`` present in
    ``~/.config/apf/config.toml``: returns a ``CompositeDetector`` that
    runs EnsembleMax followed by a soft-degrade-wrapped
    ``OpenAICompatibleDetectorAdapter``.
    """
    from benchmarks.adapters_mlx import EnsembleMaxAdapter
    base = EnsembleMaxAdapter()

    from .detector_config import load_generative_stage_config
    gen_kwargs = load_generative_stage_config()
    if gen_kwargs is None:
        return base

    from benchmarks.adapters_http import OpenAICompatibleDetectorAdapter
    http = OpenAICompatibleDetectorAdapter(**gen_kwargs)
    wrapped: Any = SoftDegradeWrapper(http, name="generative-stage")
    return CompositeDetector([base, wrapped])
