"""
Tests for docstyle/plain_language.py: the repeated-phrase-across-sections
scan (issue #76), the one PlainLanguage check that is not a Vale rule.

Covers: a clean-pass fixture (no repeated phrase), a deliberate-hit fixture
(a comparator phrase reused 3+ times), min_words/min_count tunability,
code-fence/table/heading exclusion (structural boilerplate should not
trigger false positives), the subsumed-phrase dedupe, and check_paths()
over multiple files (per-document scoring, not pooled).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from docstyle import plain_language  # noqa: E402


# ---- find_repeated_phrases: clean pass ----

def test_clean_prose_has_no_repeated_phrase():
    text = (
        "The migration plan covers three phases. The first phase moves the "
        "telemetry feed. The second phase retires the legacy historian. The "
        "third phase closes out the transition and hands over to steady state."
    )
    assert plain_language.find_repeated_phrases(text) == []


def test_two_repeats_of_a_phrase_do_not_trigger_the_default_threshold():
    # "in the same way as" appears twice: below the default min_count of 3.
    text = (
        "Section one behaves in the same way as the pilot did. "
        "Section two behaves in the same way as the pilot did. "
        "Section three is unrelated and stands on its own."
    )
    assert plain_language.find_repeated_phrases(text) == []


# ---- find_repeated_phrases: deliberate hit ----

def test_comparator_phrase_repeated_three_times_is_flagged():
    text = (
        "Section one runs in the same way as the reference design. "
        "Section two runs in the same way as the reference design. "
        "Section three also runs in the same way as the reference design, "
        "for consistency across the rollout."
    )
    hits = plain_language.find_repeated_phrases(text)
    assert hits, "the reused comparator phrase should surface at least one hit"
    assert all(hit.count == 3 for hit in hits)
    assert any("in the same way as" in hit.phrase for hit in hits)


def test_min_count_tunable_lower_threshold_catches_two_repeats():
    text = (
        "Section one behaves in the same way as the pilot did. "
        "Section two behaves in the same way as the pilot did. "
        "Section three is unrelated and stands on its own."
    )
    hits = plain_language.find_repeated_phrases(text, min_count=2)
    assert hits
    assert all(hit.count == 2 for hit in hits)
    assert any("in the same way as" in hit.phrase for hit in hits)


def test_min_words_tunable_shorter_window_catches_shorter_phrase():
    text = (
        "Team A reports just as with team B for review. "
        "Team C notes just as with team D for review. "
        "Team E states just as with team F for review."
    )
    # The verb before the phrase and the team letter after it both vary on
    # every occurrence, so no 5-word window is identical across all three
    # (the invariant core "just as with team" is only 4 words): the default
    # threshold finds nothing. A 3-word window isolates the invariant
    # comparator phrase itself.
    assert plain_language.find_repeated_phrases(text) == []
    hits = plain_language.find_repeated_phrases(text, min_words=3)
    assert any("just as with" in h.phrase for h in hits)


# ---- structural exclusion: code fences, tables, headings ----

def test_code_fence_contents_are_excluded():
    text = (
        "## Overview\n\nProse paragraph, nothing repeated here at all.\n\n"
        "```\nrepeat this line exactly\nrepeat this line exactly\n"
        "repeat this line exactly\n```\n"
    )
    assert plain_language.find_repeated_phrases(text) == []


def test_table_rows_are_excluded():
    text = (
        "## Data\n\n"
        "| Milestone | Indicative date |\n"
        "|-----------|------------------|\n"
        "| Milestone | Indicative date |\n"
        "| Milestone | Indicative date |\n"
        "| Milestone | Indicative date |\n\n"
        "A short unrelated paragraph closes the section out.\n"
    )
    assert plain_language.find_repeated_phrases(text) == []


def test_headings_are_excluded():
    text = (
        "# Programme Overview And Scope\n\n"
        "## Programme Overview And Scope Detail\n\n"
        "### Further Programme Overview And Scope Notes\n\n"
        "A short paragraph body that stands alone.\n"
    )
    assert plain_language.find_repeated_phrases(text) == []


# ---- one real repeated run surfaces as several overlapping windows ----

def test_one_long_repeated_run_surfaces_multiple_overlapping_hits():
    text = (
        "The full baseline note repeats verbatim in three places for review. "
        "The full baseline note repeats verbatim in three places for review. "
        "The full baseline note repeats verbatim in three places for review."
    )
    hits = plain_language.find_repeated_phrases(text, min_words=5, min_count=3)
    # A fixed-window cheap scan does not collapse a long identical run into
    # one maximal phrase (see the module docstring): every 5-word sub-window
    # of the repeated run hits count==3 independently. All of them are real
    # signal (the same underlying repeat), just reported at window
    # granularity rather than merged.
    assert len(hits) > 1
    assert all(hit.count == 3 for hit in hits)
    assert any("full baseline note repeats" in hit.phrase for hit in hits)


# ---- check_paths: per-file scoring, not pooled ----

def test_check_paths_scores_each_file_independently(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text(
        "In the same way as the reference design, section one applies here. "
        "In the same way as the reference design, section two applies here.",
        encoding="utf-8",
    )
    b.write_text("A totally unrelated document with no repeats at all.", encoding="utf-8")
    findings = plain_language.check_paths([a, b], min_count=2)
    assert a in findings
    assert b not in findings


def test_check_paths_empty_when_no_hits(tmp_path):
    clean = tmp_path / "clean.md"
    clean.write_text("Nothing repeats in this short clean document.", encoding="utf-8")
    assert plain_language.check_paths([clean]) == {}
