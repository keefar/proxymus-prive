"""Local-only category routing (apf-enr).

Some categories carry harm vectors so severe (asylum status, domestic
abuse content, undocumented immigration, whistleblower intent) that
opaque tokenisation is not enough — *the fact that the user is processing
this category* is itself a leak when forwarded to a cloud LLM provider.
Government subpoena, future-policy-change, and provider-side metadata
correlation are all real risks for these categories.

v1 policy: detected content in these categories triggers a 422 refusal
from the proxy. The user must remove the offending content or route the
message through a local model directly (outside the proxy's path).

v2 (future): proxy routes such messages to a locally-resident small
model (MLX-hosted), no cloud upstream. Tracked here as a follow-up
direction.

The DETECTION of these labels is a detector capability, not implemented
here. The current detector vocabulary (PERSON, EMAIL, ADDRESS, ...)
doesn't emit them. Once the detector layer is extended (e.g., via a
fine-tuned GLiNER head or a small LLM classifier), the check below
activates automatically — no proxy-layer changes needed.
"""
from __future__ import annotations

import os

# Default locked labels. The set of labels the detector may emit that
# should never leave the machine. Aligns with the user decision
# 2026-05-17 (apf-enr) and THREAT-MODEL-PRIVATE.md §5.6.
DEFAULT_LOCKED_LABELS: frozenset[str] = frozenset({
    # Asylum / refugee status anywhere it appears
    "ASYLUM_DETAIL",
    "ASYLUM_STATUS",
    # Domestic abuse, intimate-partner violence content
    "ABUSE_CONTEXT",
    "DOMESTIC_VIOLENCE",
    # Whistleblower / disclosure intent towards an employer/state
    "WHISTLEBLOWER_INTENT",
    # Undocumented immigration; legal documented statuses (H-1B, F-1)
    # are NOT in this set — they're sensitive but not catastrophic.
    "IMMIGRATION_STATUS_UNDOCUMENTED",
    "UNDOCUMENTED_STATUS",
})


def _load_overrides() -> frozenset[str]:
    """Comma-separated env override for the locked label set.

    APF_LOCKED_LABELS=ASYLUM_DETAIL,WHISTLEBLOWER_INTENT,MY_CUSTOM_LABEL

    Empty env var = the default set. Use this rather than editing source
    when a deployment needs to add or remove labels.
    """
    raw = os.environ.get("APF_LOCKED_LABELS")
    if not raw or not raw.strip():
        return DEFAULT_LOCKED_LABELS
    labels = {tok.strip() for tok in raw.split(",") if tok.strip()}
    return frozenset(labels)


def locked_labels() -> frozenset[str]:
    """Effective locked-label set, re-read on each call so changing the
    env var without restart works for ad-hoc testing. Cheap (set of ~5)."""
    return _load_overrides()


def is_locked(label: str) -> bool:
    return label in locked_labels()


def categories_in(spans) -> list[str]:
    """Return the de-duplicated list of locked-category labels present in
    `spans` (a list of Span-like objects with a .label attribute or
    {'label': ...} dicts). Returns [] if none are locked.

    The OUTPUT contains only label names, NEVER the value/text. This is
    safe to surface in a 422 response body or a log line — the user
    learns 'your message contains an asylum-related detail' without
    re-leaking the specific detail to the very channel we're refusing to
    use.
    """
    locked = locked_labels()
    seen: list[str] = []
    for s in spans:
        label = getattr(s, "label", None) if not isinstance(s, dict) else s.get("label")
        if label in locked and label not in seen:
            seen.append(label)
    return seen


def refusal_body(found_labels: list[str]) -> dict:
    """Standard JSON body for a 422 refusal. Categories listed, no
    values. Includes a hint that the user can route via a local model
    directly if they need to process this content with AI."""
    return {
        "type": "error",
        "error": {
            "type": "apf_locked_category",
            "message": (
                "Your message contains content in a category configured "
                "to never leave this machine (see locked_categories). "
                "Remove or rephrase the content to proceed, or route the "
                "request directly to a local-only model (Ollama, mlx-lm, "
                "oMLX, llama.cpp) without going through this proxy."
            ),
            "locked_categories": found_labels,
        },
    }
