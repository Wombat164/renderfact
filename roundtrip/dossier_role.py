"""
dossier_role.py -- issue #77: read a document's `dossier_role` frontmatter
field, a freeform author-stated string describing what this document
uniquely contributes relative to its siblings in a broader dossier/
collection ("what is this document FOR, that no sibling already covers").

This is a pure ANNOTATION, read-only. Unlike `renderfact_uid`
(roundtrip/source_uid.py), nothing here generates or persists a value: the
author writes `dossier_role:` in frontmatter, or leaves it unset, and
nothing in the pipeline ever rewrites it.

Freeform, consumer-defined vocabulary, not an enum -- the same non-enum
posture as the projection engine's clearance/distribution ladders
(projection/projector.py): the engine ships no fixed vocabulary of its own,
so any value is accepted and returned as-is.

Frontmatter access follows the repo's existing byte-preserving idiom (the
SAME regex-then-`yaml.safe_load` pattern as `gates/run_gates.py`'s
`run_uids` and `roundtrip/source_uid.py`'s `_frontmatter_bounds`), rather
than inventing a new frontmatter-parsing path: locate the `---`-delimited
body, `yaml.safe_load` it to read one key, never write anything back.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_KEY = "dossier_role"


def read_dossier_role(source_path: "str | Path") -> "str | None":
    """Return the `dossier_role` frontmatter value for a markdown source, or
    None when the field is absent, empty, or the frontmatter does not parse.
    Read-only: never writes back (contrast `source_uid.get_or_create_source_uid`,
    which persists a generated value on first use -- `dossier_role` is always
    author-stated or absent, never machine-generated)."""
    text = Path(source_path).read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get(_KEY)
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None
