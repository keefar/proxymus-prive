"""apf-xt5: mask_outside_system_reminders — skip Claude Code harness blocks.

Claude Code injects operational scaffolding (skill catalogues, agent-type
lists, hooks, the CLAUDE.md projection) into the messages array wrapped in
<system-reminder>...</system-reminder>. The detector must not run over it:
that text is not user PII, and masking it shreds the context the model
needs (e.g. tool names turned into <REF_N>).
"""
from __future__ import annotations

from apf.masker import mask_outside_system_reminders


def _upper(t: str) -> str:
    """Fake mask_fn — uppercasing makes it visible which fragments ran."""
    return t.upper()


def test_no_reminder_masks_whole_text() -> None:
    assert mask_outside_system_reminders("hello world", _upper) == "HELLO WORLD"


def test_empty_string() -> None:
    assert mask_outside_system_reminders("", _upper) == ""


def test_reminder_block_kept_verbatim() -> None:
    sr = "<system-reminder>Skill catalog: Grep, Bash</system-reminder>"
    assert mask_outside_system_reminders(sr, _upper) == sr


def test_reminder_content_survives_untouched() -> None:
    # the whole point: PII-shaped tokens inside a reminder are not masked
    sr = "<system-reminder>tool Grep, path /Users/alice/x</system-reminder>"
    out = mask_outside_system_reminders(sr, _upper)
    assert "Grep" in out and "/Users/alice/x" in out


def test_user_text_after_reminder_is_masked() -> None:
    sr = "<system-reminder>harness stuff</system-reminder>"
    assert mask_outside_system_reminders(sr + "user text", _upper) \
        == sr + "USER TEXT"


def test_user_text_before_reminder_is_masked() -> None:
    sr = "<system-reminder>harness</system-reminder>"
    assert mask_outside_system_reminders("typed this" + sr, _upper) \
        == "TYPED THIS" + sr


def test_multiple_reminders_interleaved() -> None:
    a = "<system-reminder>A</system-reminder>"
    b = "<system-reminder>B</system-reminder>"
    assert mask_outside_system_reminders(f"x{a}y{b}z", _upper) \
        == f"X{a}Y{b}Z"


def test_multiline_reminder_block() -> None:
    sr = "<system-reminder>line one\nline two\nline three</system-reminder>"
    out = mask_outside_system_reminders("before " + sr + " after", _upper)
    assert sr in out
    assert out.startswith("BEFORE ") and out.endswith(" AFTER")


def test_unclosed_reminder_is_masked_defensively() -> None:
    # a malformed/truncated reminder with no closing tag is masked, not
    # silently passed through
    assert mask_outside_system_reminders("<system-reminder>oops", _upper) \
        == "<SYSTEM-REMINDER>OOPS"
