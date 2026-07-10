#!/usr/bin/env python3
"""pandoc_markdown.py: the one canonical pandoc `--from` value for every code
path in this repo that reads renderfact markdown sources into pandoc's AST
(issue #69).

Why this file exists: two sibling pandoc-invoking call sites each hand-rolled
their own markdown extension string. `container/render-doc.sh` (the DOCX path)
included `wikilinks_title_after_pipe`; `pdf/typst_backend.py` (the PDF path)
did not specify `--from` at all, so it fell back to pandoc's plain `markdown`
reader. Without that extension, `[[target|Display Text]]` is read as literal
punctuation/text (fragmented across several Str/Space inline tokens), never as
a `Link` node, so the display text silently never resolves, and the raw
brackets leak into rendered output. A defensive Lua `Str`-level regex fallback
cannot recover it either, for the same reason: the bracket run does not
survive as a single `Str` token to match against (verified via a real
`pandoc -t json` AST dump in tests/test_pandoc_markdown.py).

This is the copy-paste-drift failure mode: it is easy to clone an extension
list from a sibling script and silently drop one extension. The fix is a
single source of truth every call site imports (Python) or shells out to
(Bash), so the extension cannot drift out of one path while staying in
another.

Usage:
    from pandoc_markdown import MARKDOWN_FROM, markdown_from
    subprocess.run([pandoc, "--from", MARKDOWN_FROM, ...])
    subprocess.run([pandoc, "--from", markdown_from("smart"), ...])   # + extra

Bash callers (container/render-doc.sh) get the same literal string by running
this file directly:
    PANDOC_FROM_MD="$("$PYTHON" "$REPO_ROOT/pandoc_markdown.py")"
"""

from __future__ import annotations

# The one extension every renderfact markdown-reading call site needs. Without
# it, "[[target|Display Text]]" wikilinks are read as literal text, not Link
# nodes (see the module docstring and tests/test_pandoc_markdown.py).
WIKILINK_EXTENSION = "wikilinks_title_after_pipe"

# Extensions pinned explicitly even though pandoc >=3's plain "markdown" format
# already defaults them on (verified with `pandoc --list-extensions=markdown`),
# so a call site's behaviour stays stable even if pandoc's own defaults change
# upstream. wikilinks_title_after_pipe is the one extension that is NOT on by
# default and is the reason this module exists.
_PINNED_DEFAULTS = ("pipe_tables", "yaml_metadata_block", "grid_tables", "fenced_divs")

MARKDOWN_FROM_EXTENSIONS = ("markdown", WIKILINK_EXTENSION) + _PINNED_DEFAULTS

# The ready-to-use --from=... value: "markdown+wikilinks_title_after_pipe+...".
MARKDOWN_FROM = "+".join(MARKDOWN_FROM_EXTENSIONS)


def markdown_from(*extra: str) -> str:
    """MARKDOWN_FROM plus any call-site-specific extensions, deduplicated,
    order-preserving. There is no parameter to drop WIKILINK_EXTENSION: by
    design, every caller of this helper gets it."""
    ext = list(MARKDOWN_FROM_EXTENSIONS)
    for e in extra:
        if e not in ext:
            ext.append(e)
    return "+".join(ext)


if __name__ == "__main__":
    # `python pandoc_markdown.py` prints the canonical --from value, so a
    # shell caller (container/render-doc.sh) consumes the exact same string
    # instead of duplicating it.
    print(MARKDOWN_FROM)
