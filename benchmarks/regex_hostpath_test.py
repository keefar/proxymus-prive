"""apf-6ql: looser HOSTNAME + PATH regexes in RegexBaseline.

The shipped HOSTNAME regex required a 3-part host (`.x.tld`) and missed
2-part `.lokal` / `.local` hosts. The PATH regex only anchored on a fixed
prefix set (`/Users|home|opt|...`) and missed `~`-rooted paths, bare
relative paths, and absolute paths under other roots.

Both are Tier-B. The loosening must stay precision-aware — bare
single-token hostnames and lone words are deliberately NOT matched.
"""
from __future__ import annotations

from benchmarks.adapters import RegexBaseline


def _detect(text: str) -> list[tuple[str, str, str]]:
    det = RegexBaseline()
    return [(text[s.start:s.end], s.label, s.tier) for s in det.detect(text)]


# ---- HOSTNAME ------------------------------------------------------------

def test_two_part_lokal_host() -> None:
    text = "ssh into backup-nas.lokal now."
    hits = _detect(text)
    assert ("backup-nas.lokal", "HOSTNAME", "B") in hits


def test_two_part_local_host() -> None:
    text = "Printer at printer.local is offline."
    hits = _detect(text)
    assert ("printer.local", "HOSTNAME", "B") in hits


def test_two_part_internal_host() -> None:
    text = "Reach monitor-02.internal for metrics."
    hits = _detect(text)
    assert ("monitor-02.internal", "HOSTNAME", "B") in hits


def test_three_part_host_still_matches() -> None:
    """The pre-existing 3-part case must keep working."""
    text = "Connect to build-runner-03.internal.example.com please."
    hits = _detect(text)
    assert ("build-runner-03.internal.example.com", "HOSTNAME", "B") in hits


def test_plain_word_not_matched_as_host() -> None:
    """A bare word with no dot is not a hostname — precision guard."""
    text = "The jumpbox is configured."
    hits = _detect(text)
    assert not any(label == "HOSTNAME" for _, label, _ in hits)


def test_filename_not_matched_as_host() -> None:
    """`report.local` could collide, but a sentence-final filename like
    `notes.txt` must not be flagged HOSTNAME."""
    text = "Open notes.txt to review."
    hits = _detect(text)
    assert not any(label == "HOSTNAME" for _, label, _ in hits)


# ---- PATH ----------------------------------------------------------------

def test_tilde_rooted_path() -> None:
    text = "cd ~/projekte/datenpipeline and run it."
    hits = _detect(text)
    assert any(label == "PATH" and "~/projekte/datenpipeline" in surface
               for surface, label, _ in hits)


def test_tilde_dotfile_path() -> None:
    text = "key at ~/.ssh/id_ed25519_prod is used."
    hits = _detect(text)
    assert any(label == "PATH" and "~/.ssh/id_ed25519_prod" in surface
               for surface, label, _ in hits)


def test_bare_relative_path() -> None:
    text = "cd src/ && ls"
    hits = _detect(text)
    assert any(label == "PATH" and surface.startswith("src/")
               for surface, label, _ in hits)


def test_absolute_path_under_other_root() -> None:
    text = "tail /data/raw/2026-05-12/batch-0007.json now."
    hits = _detect(text)
    assert any(label == "PATH" and "/data/raw/2026-05-12/batch-0007.json"
               in surface for surface, label, _ in hits)


def test_known_prefix_path_still_matches() -> None:
    """The pre-existing /Users|/var|... prefix case must keep working."""
    text = "see /var/log/buildbot/main.log for errors"
    hits = _detect(text)
    assert any(label == "PATH" and "/var/log/buildbot/main.log" in surface
               for surface, label, _ in hits)


def test_lone_word_not_matched_as_path() -> None:
    """A plain word with no slash is not a path."""
    text = "Run tests now."
    hits = _detect(text)
    assert not any(label == "PATH" for _, label, _ in hits)
