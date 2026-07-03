"""
source_uid.py -- D11 part 2 (chunk 4.1): stable per-source-document identity +
content-versioning, the two inputs roundtrip/provenance.py's embed() needs
beyond what a single render invocation already knows (render timestamp, tool
version).

A stable UID must survive content edits AND file renames alike -- neither the
file path nor its content hash can serve as identity, so it lives in the
source's own YAML frontmatter (`renderfact_uid:`), generated once (first
render) and persisted back into the file; idempotent thereafter. Content
version is a plain content hash AT RENDER TIME -- a deliberately separate
concept from identity, used from chunk 4.4 onward to detect whether the
canonical source changed since a render.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import yaml

_UID_KEY = "renderfact_uid"


def _frontmatter_bounds(text: str) -> tuple[int, int] | None:
    """Return (start, end) byte offsets of the RAW frontmatter block's body --
    the text between the two `---` delimiter lines -- or None if there is no
    frontmatter. Never reformatted; only used to locate where to insert one
    new line, so any pre-existing frontmatter content is preserved byte-for-
    byte (a full yaml.safe_load/safe_dump round-trip would risk silently
    reformatting quoting/ordering/style of fields this function never touches)."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    return 4, end + 1  # body spans [4, end+1) -- includes the trailing \n


def get_or_create_source_uid(source_path: Path) -> str:
    """Read `renderfact_uid:` from the source's YAML frontmatter, or generate
    one (uuid4) and persist it back into the file if absent. Idempotent --
    calling this again on the same file returns the same UID without a write.

    Multi-user guarantee: uuid4 is 122 random bits, so independently generated
    UIDs do not collide at any organisational scale, with no coordination or
    central registry. The one identity hazard is therefore FILE COPYING: a
    duplicated source (or a template that already carries a renderfact_uid)
    claims the original's lineage. Strip renderfact_uid when forking a
    document; the 'uids' gate stage detects duplicates across a tree."""
    text = source_path.read_text(encoding="utf-8")
    bounds = _frontmatter_bounds(text)

    if bounds is not None:
        start, end = bounds
        frontmatter_text = text[start:end]
        try:
            data = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError:
            data = None
        if isinstance(data, dict) and _UID_KEY in data:
            return str(data[_UID_KEY])

        new_uid = str(uuid.uuid4())
        new_text = text[:end] + f"{_UID_KEY}: {new_uid}\n" + text[end:]
    else:
        new_uid = str(uuid.uuid4())
        new_text = f"---\n{_UID_KEY}: {new_uid}\n---\n\n{text}"

    source_path.write_text(new_text, encoding="utf-8")
    return new_uid


def content_version(source_path: Path) -> str:
    """A content-hash of the source AT RENDER TIME (D11's own wording).
    Identity (get_or_create_source_uid) and version (this) are deliberately
    separate: the UID never changes across edits, the version always does.
    sha256, truncated to 16 hex chars -- collision-irrelevant at this scale,
    short enough to be a readable version stamp."""
    return hashlib.sha256(source_path.read_bytes()).hexdigest()[:16]
