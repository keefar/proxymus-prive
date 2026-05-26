"""Cross-platform portability invariants for the detector module.

Production proxy path imports `EnsembleMaxAdapter` from
`benchmarks.adapters_mlx`. Despite the file name, the *adapters* in the
production ensemble (regex, Presidio, GLiNER, locked-category regex) do
not require MLX — MLX is only needed for the experimental adapters
(Nemotron, Qwen3, Anonymizer) that are not wired into EnsembleMax.

These tests pin the invariant that lets pip skip mlx / mlx-lm on Linux,
Windows, and Intel Mac via environment markers in requirements.txt:

    1. No top-level `import mlx*` in `benchmarks/adapters_mlx.py` —
       all MLX imports must live inside method bodies so the module
       loads on machines without mlx installed.
    2. `EnsembleMaxAdapter` is constructible without the mlx packages
       importable; warmup() loads only the cross-platform detectors.

Regression for apf-h09 (cross-platform portability).
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path


def test_adapters_mlx_has_no_top_level_mlx_imports() -> None:
    src_path = Path(__file__).parent / "adapters_mlx.py"
    tree = ast.parse(src_path.read_text())
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("mlx"), (
                    f"Top-level `import {alias.name}` in adapters_mlx.py "
                    "breaks cross-platform install; move into "
                    "warmup()/detect() to keep the module loadable "
                    "without mlx."
                )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert not mod.startswith("mlx"), (
                f"Top-level `from {mod} import ...` in adapters_mlx.py "
                "breaks cross-platform install; move into "
                "warmup()/detect() to keep the module loadable "
                "without mlx."
            )


def test_ensemblemax_importable_without_mlx(monkeypatch) -> None:
    # Sentinel-None makes `import mlx` raise ImportError, mimicking a
    # Linux / Windows / Intel Mac install where the pip marker skipped
    # both packages.
    monkeypatch.setitem(sys.modules, "mlx", None)
    monkeypatch.setitem(sys.modules, "mlx_lm", None)

    mod_name = "benchmarks.adapters_mlx"
    # Force a fresh import under the mocked condition so any future
    # top-level `import mlx` regression would surface here.
    sys.modules.pop(mod_name, None)
    try:
        mod = importlib.import_module(mod_name)
        adapter = mod.EnsembleMaxAdapter()
        assert adapter.name == "ensemble-max"
        # Component classes used by EnsembleMax.warmup() must be reachable
        # — verifies no MLX-only symbols leak into the production path.
        assert hasattr(mod, "PresidioAdapter")
        assert hasattr(mod, "GlinerMultiPiiAdapter")
        assert hasattr(mod, "GlinerNvidiaAdapter")
    finally:
        # Reset so the rest of the suite gets the normal module.
        sys.modules.pop(mod_name, None)
        importlib.import_module(mod_name)
