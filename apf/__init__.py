"""apf — agent privacy filter core.

Library for masking PII in text, resolving tokens at tool-call boundaries,
and restoring originals in agent responses. Separate from `benchmarks/`
(which is the evaluation harness).
"""
from .vault import Vault, VaultEntry
from .masker import mask_text
from .unmasker import unmask_text
from .resolver import resolve_tool_call_args

__all__ = [
    "Vault",
    "VaultEntry",
    "mask_text",
    "unmask_text",
    "resolve_tool_call_args",
]
