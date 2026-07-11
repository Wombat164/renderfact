"""
Tests for pandoc_markdown.py (issue #69): the single shared source of truth for
the pandoc `--from` markdown extension string, in particular
`wikilinks_title_after_pipe`.

Two tiers:
  - Unit tests over the module's constants/helper (no binaries).
  - Real-pandoc AST tests that reproduce the issue's two claims directly against
    a live `pandoc -t json` dump: (1) without the extension, a `[[x|y]]` bracket
    run is read as literal text fragmented across multiple Str/Space inlines,
    which is exactly why a naive single-Str-token Lua fallback could never
    catch it either; (2) with MARKDOWN_FROM, the same input parses as a genuine
    Link node carrying "y" as its display text. These are skipped, not failed,
    on a host without pandoc.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pandoc_markdown as pm  # noqa: E402

HAVE_PANDOC = shutil.which("pandoc") is not None


# --------------------------------------------------------------- unit tests --

def test_wikilink_extension_is_present_in_the_canonical_string():
    assert pm.WIKILINK_EXTENSION in pm.MARKDOWN_FROM_EXTENSIONS
    assert f"+{pm.WIKILINK_EXTENSION}+" in f"+{pm.MARKDOWN_FROM}+"


def test_markdown_from_dedupes_and_preserves_order():
    assert pm.markdown_from("pipe_tables", "smart") == pm.MARKDOWN_FROM + "+smart"


def test_markdown_from_always_includes_wikilink_extension():
    # No way to opt out: the extension is baked into MARKDOWN_FROM_EXTENSIONS,
    # not appendable-away by any combination of extra args.
    assert pm.WIKILINK_EXTENSION in pm.markdown_from().split("+")


def test_module_run_as_script_prints_markdown_from():
    result = subprocess.run([sys.executable, str(REPO_ROOT / "pandoc_markdown.py")],
                             capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert result.stdout.strip() == pm.MARKDOWN_FROM


# ------------------------------------------------- real pandoc AST evidence --

def _pandoc_ast(text: str, from_value: str) -> dict:
    result = subprocess.run(
        ["pandoc", "--from", from_value, "-t", "json"],
        input=text, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _inlines(ast: dict) -> list:
    return ast["blocks"][0]["c"]


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_bare_markdown_fragments_bracket_wikilink_across_multiple_inlines():
    """Reproduces the issue's second failure mode directly: without the
    extension, pandoc's default `markdown` reader does not hand a naive
    Str-level Lua filter one contiguous token to regex against: the bracket
    run is split across Str/Space inlines. This is WHY no such fallback filter
    was added here instead of fixing the extension: the fallback pattern is
    provably unreliable, not just unlucky in one case."""
    ast = _pandoc_ast("[[some-target|Display Text]]", "markdown")
    inlines = _inlines(ast)
    assert all(inline["t"] != "Link" for inline in inlines)
    # more than one inline token carries a fragment of the bracket run
    str_fragments = [i["c"] for i in inlines if i["t"] == "Str"]
    assert len(str_fragments) >= 2
    assert any("[[" in s for s in str_fragments)


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_markdown_from_parses_wikilink_as_genuine_link_node():
    """The fix, proven against the real AST: with MARKDOWN_FROM, the same
    input pandoc mangled above becomes exactly one Link inline carrying
    "Display Text", so no defensive Lua fallback is needed at all."""
    ast = _pandoc_ast("[[some-target|Display Text]]", pm.MARKDOWN_FROM)
    inlines = _inlines(ast)
    assert len(inlines) == 1
    link = inlines[0]
    assert link["t"] == "Link"
    target = link["c"][2][0]
    display = "".join(part.get("c", " ") if isinstance(part.get("c"), str) else " "
                       for part in link["c"][1])
    assert target == "some-target"
    assert display == "Display Text"
