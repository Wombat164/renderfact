"""Shared marking/classification pattern list (#123). Single source of truth for two
consumers that both need to recognize "this looks like a classification marking":
`template_import.py` (flag it at import time, before any render happens) and
`marking_lint.py` (flag it at render time if nothing configured ended up matching it).

Deliberately a plain substring/regex list, not a real classification taxonomy -- this
repo has no opinion on what a consumer's real marking scheme is (see D-series decisions
on keeping the projection engine's clearance ladder consumer-defined, same posture
applied here). The list exists to catch the COMMON English-language patterns a
corporate template is likely to carry in its header/footer, not to be exhaustive.
Extend it in a consumer's own skin tooling if a real marking scheme uses different
vocabulary -- these two modules take the list as a parameter for exactly that reason.
"""
import re

DEFAULT_MARKING_PATTERNS = [
    r"\bUNCLASS(?:IFIED)?\b",
    r"\bCONFIDENTIAL\b",
    r"\bSECRET\b",
    r"\bTOP\s+SECRET\b",
    r"\bRESTRICTED\b",
    r"\bINTERNAL(?:\s+USE\s+ONLY)?\b",
    r"\bPROPRIETARY\b",
    r"\bFOR\s+OFFICIAL\s+USE\s+ONLY\b",
    r"\bFOUO\b",
]


def find_marking_matches(text, patterns=None):
    """Return the list of distinct literal substrings in `text` that matched any
    pattern in `patterns` (default DEFAULT_MARKING_PATTERNS), case-insensitive,
    each occurring exactly as matched (not the pattern itself) so a caller can
    show/compare the real text found. Empty list if nothing matched or text is
    empty/None."""
    if not text:
        return []
    patterns = patterns if patterns is not None else DEFAULT_MARKING_PATTERNS
    found = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            matched = m.group(0)
            if matched not in found:
                found.append(matched)
    return found
