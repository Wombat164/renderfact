"""docstyle/plain_language.py: repeated-phrase-across-sections detection (issue #76).

Part of the PlainLanguage check trio (see
demo/skin/vale/styles/PlainLanguage/README.md for the other two: sentence
length and nominalisation density, which ARE expressible as Vale rules and
ship as a Vale style package). This third check is not: every Vale rule type
(existence, substitution, occurrence, repetition, consistency, conditional,
spelling, capitalization, sequence) matches against a pattern fixed at
authoring time. Flagging "the same phrase, whatever it turns out to be,
appearing 3+ times in THIS document" needs the document's own text as the
source of the pattern to search for, which nothing in Vale's DSL can do. So
it ships as a small, dependency-free, deterministic Python check instead: a
cheap n-gram/exact-match scan, no NLP model, per the issue's own framing.

Wired into `render gate` as the `plainlang` stage (gates/run_gates.py). Unlike
the other gate stages (vale, lychee, verapdf, uids), a plainlang finding does
NOT fail the run by default: a repeated 5-word run very often IS legitimate
(a programme name, a component name, a defined term used consistently), not
a defect, so treating every hit as fail-closed would make the check noise
rather than signal. Report-only by default (matches `render qa`'s
`leaks --fail-on-hits` shape); pass fail_on_hits=True / --plainlang-fail-on-hits
to make it CI-blocking once a consumer has tuned the thresholds for their
corpus.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# Words only (contractions and hyphenated compounds kept whole); markdown
# punctuation, table pipes, and numbers act as natural n-gram breaks once
# stripped out, which is what the join-then-tokenize below relies on.
_WORD_RE = re.compile(r"[A-Za-z']+(?:-[A-Za-z']+)*")
_CODE_FENCE_RE = re.compile(r"^\s*```")
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_HEADING_RE = re.compile(r"^#{1,6}\s")


@dataclass(frozen=True)
class RepeatedPhrase:
    phrase: str
    count: int


def _prose_lines(text: str) -> list[str]:
    """Drop code fences, table rows, and headings before scanning.

    These are structural boilerplate that legitimately repeats (a fenced
    block's closing marker, a table's header cells reused as row labels, a
    heading word like "Overview" reused in a sub-heading) and would swamp the
    scan with matches that have nothing to do with repeated PROSE phrasing.
    """
    lines = []
    in_code = False
    for line in text.splitlines():
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        if _TABLE_ROW_RE.match(line) or _HEADING_RE.match(line):
            continue
        lines.append(line)
    return lines


def find_repeated_phrases(text: str, min_words: int = 5, min_count: int = 3) -> list[RepeatedPhrase]:
    """Find a multi-word phrase recurring near-verbatim min_count+ times.

    Case-insensitive, whitespace-normalized exact match over a sliding
    min_words-word window. min_words defaults to 5, not 3-4: a shorter window
    over-matches ordinary repeated domain terminology (a component or
    programme name mentioned in several sections is normal and not a defect);
    a mechanically-reused comparator/transition phrase ("in the same way as
    the X approach", "similar to the arrangement for Y") is still reliably
    caught at 5+ words while cutting most of that noise. Both thresholds are
    the tunable knobs (see gates/run_gates.py --plainlang-min-words/
    --plainlang-min-count): lower them for a stricter scan on a corpus known
    to repeat template sentences, raise them if 5 words still over-fires on
    a terminology-heavy document.

    Known limitation, accepted deliberately for a "cheap n-gram scan, no NLP"
    check (issue #76's own framing): a single longer repeated run (say, 9
    identical words) surfaces as SEVERAL overlapping min_words-length hits,
    one per sliding-window position, rather than being collapsed into one
    maximal phrase. That is noisier than a smarter scan would be, but still
    correctly signals "this document repeats a phrase," which is all a
    report-only advisory check needs to do; a human (or the LLM pass this
    check sits underneath) reads the handful of overlapping hits as one issue.
    """
    words = _WORD_RE.findall(" ".join(_prose_lines(text)).lower())
    if len(words) < min_words:
        return []
    counts = Counter(
        " ".join(words[i:i + min_words])
        for i in range(len(words) - min_words + 1)
    )
    hits = [RepeatedPhrase(phrase, n) for phrase, n in counts.items() if n >= min_count]
    return sorted(hits, key=lambda r: (-r.count, r.phrase))


def check_paths(paths: list[Path], min_words: int = 5,
                 min_count: int = 3) -> dict[Path, list[RepeatedPhrase]]:
    """Scan each path independently (a repeated phrase is scored per-document,
    not pooled across files: "across sections" means within one document)."""
    findings: dict[Path, list[RepeatedPhrase]] = {}
    for p in paths:
        text = p.read_text(encoding="utf-8", errors="replace")
        hits = find_repeated_phrases(text, min_words=min_words, min_count=min_count)
        if hits:
            findings[p] = hits
    return findings
