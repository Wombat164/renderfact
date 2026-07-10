"""
Regression + proof tests for issue #96: the shared pandoc `--from` spec
(pandoc_markdown.MARKDOWN_FROM) now pins `raw_attribute`, the reader extension
that turns a fenced code block tagged ```{=openxml} into a genuine `RawBlock`
AST node instead of an inert, literal `Code` block.

Scope of THIS fix, precisely: this is a manual, advanced escape hatch, not a
new markdown feature. It does not add native syntax for Word content controls
(checkboxes/dropdowns) or merged/spanned table cells -- both gaps that #96
reported. It only unblocks a hand-authored ```{=openxml} block from reaching
the docx writer as raw OOXML at all, which #96 itself identifies as the
prerequisite for even attempting either workaround. Native syntax for those
two gaps is deliberately deferred to a follow-up issue.

Two tiers, mirroring tests/test_wikilink_resolution.py's own structure for the
sibling #69 fix:
  - A real end-to-end render (render.py -> render-doc.sh -> pandoc -> docx),
    not a mock and not an AST-only check, proving the escape hatch reaches
    the actual rendered .docx file's word/document.xml.
  - A negative control: the exact same fixture, run through the OLD
    (pre-#96) `--from` value with `raw_attribute` missing, to prove the
    fenced block really was inert before this fix (not passing "by luck" on
    this pandoc version's own defaults) and that the difference is
    attributable to the extension, not to anything else in the pipeline.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDER_PY = REPO_ROOT / "render.py"
sys.path.insert(0, str(REPO_ROOT))

import pandoc_markdown as pm  # noqa: E402

HAVE_PANDOC = shutil.which("pandoc") is not None

# The --from value as it was before issue #96 (no raw_attribute): the exact
# string pandoc_markdown.MARKDOWN_FROM used to produce. Hardcoded here on
# purpose -- this is a fixed historical baseline for the negative control, not
# something that should track future changes to the module.
PRE_96_MARKDOWN_FROM = (
    "markdown+wikilinks_title_after_pipe+pipe_tables+yaml_metadata_block"
    "+grid_tables+fenced_divs"
)

# The same pre-#96 baseline, but with raw_attribute EXPLICITLY disabled
# (pandoc's "-extension" syntax). Needed for the negative control: pandoc >=3's
# plain "markdown" base format already defaults raw_attribute on (see
# pandoc_markdown.py's own docstring/comment), so merely omitting it from the
# --from string (PRE_96_MARKDOWN_FROM above) does not, on a current pandoc,
# actually reproduce the inert-Code-block failure #96 describes -- it is
# already on by inheritance from the base format. Explicitly disabling it is
# what isolates and proves the extension's effect (and is exactly the
# scenario the module's own comment warns about: an older, or differently
# configured, pandoc where raw_attribute is NOT on by default).
PRE_96_MARKDOWN_FROM_RAW_ATTRIBUTE_DISABLED = PRE_96_MARKDOWN_FROM + "-raw_attribute"

# A minimal, valid, self-contained OOXML paragraph fragment: one run holding
# one distinctive marker text. Generic and structurally unremarkable on
# purpose (not resembling any real institution's template), matching
# CONTRIBUTING.md's fixture-must-be-generic rule.
RAW_OOXML_FRAGMENT = "<w:p><w:r><w:t>RAW OOXML MARKER TEXT</w:t></w:r></w:p>"

RAW_ATTRIBUTE_SOURCE = (
    "---\ntitle: Raw Attribute Escape Hatch Check\n---\n\n"
    "# Raw attribute check\n\n"
    "Some prose before the escape hatch.\n\n"
    "```{=openxml}\n"
    f"{RAW_OOXML_FRAGMENT}\n"
    "```\n\n"
    "Some prose after the escape hatch.\n"
)


def _docx_document_xml(docx_path: Path) -> str:
    with zipfile.ZipFile(docx_path) as zf:
        return zf.read("word/document.xml").decode("utf-8")


# ------------------------------------------------- unit-level module check --

def test_raw_attribute_is_pinned_in_the_canonical_string():
    assert "raw_attribute" in pm.MARKDOWN_FROM_EXTENSIONS
    assert f"+{'raw_attribute'}" in pm.MARKDOWN_FROM
    # still carries every extension it had before #96 (additive, not a swap)
    for ext in PRE_96_MARKDOWN_FROM.split("+"):
        assert ext in pm.MARKDOWN_FROM_EXTENSIONS


# ------------------------------------------- real pandoc AST proof (#96) --

@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_raw_openxml_block_is_inert_code_with_raw_attribute_disabled():
    """Negative control: reproduces #96's stated root cause directly against a
    live `pandoc -t json` dump, with raw_attribute explicitly disabled (see
    the constant's docstring for why explicit disable, not mere omission, is
    what isolates the effect on this pandoc version). Without it, a
    ```{=openxml} fenced block is read as a literal, inert Code block -- there
    is no escape hatch at all, manual or otherwise."""
    result = subprocess.run(
        ["pandoc", "--from", PRE_96_MARKDOWN_FROM_RAW_ATTRIBUTE_DISABLED, "-t", "json"],
        input=RAW_ATTRIBUTE_SOURCE, capture_output=True, text=True,
        encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    ast = json.loads(result.stdout)
    block_types = [b["t"] for b in ast["blocks"]]
    assert "RawBlock" not in block_types
    # the fragment survives only as inert code text, never as raw OOXML
    flat = json.dumps(ast["blocks"])
    assert "openxml" in flat  # literal fence-attribute text, not consumed as a tag
    assert "RAW OOXML MARKER TEXT" in flat


def test_pre_96_string_alone_no_longer_demonstrates_the_gap_on_modern_pandoc():
    """Documents, rather than asserts a requirement on, a fact this module's
    own comments already call out: PRE_96_MARKDOWN_FROM (raw_attribute simply
    absent from the string) is NOT equivalent to raw_attribute being disabled,
    because pandoc >=3's plain "markdown" base format already defaults it on.
    Pinning it explicitly (the actual #96 fix) is what keeps that guarantee
    from depending on pandoc's own shifting defaults -- see
    PRE_96_MARKDOWN_FROM_RAW_ATTRIBUTE_DISABLED for the real negative control.
    This test only documents intent; it makes no pandoc call of its own."""
    assert "raw_attribute" not in PRE_96_MARKDOWN_FROM
    assert "-raw_attribute" in PRE_96_MARKDOWN_FROM_RAW_ATTRIBUTE_DISABLED


@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_raw_openxml_block_becomes_rawblock_with_markdown_from():
    """The fix, proven against the real AST: with the current (post-#96)
    MARKDOWN_FROM, the same ```{=openxml} fenced block parses as a genuine
    RawBlock tagged "openxml" carrying the fragment verbatim."""
    result = subprocess.run(
        ["pandoc", "--from", pm.MARKDOWN_FROM, "-t", "json"],
        input=RAW_ATTRIBUTE_SOURCE, capture_output=True, text=True,
        encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    ast = json.loads(result.stdout)
    raw_blocks = [b for b in ast["blocks"] if b["t"] == "RawBlock"]
    assert len(raw_blocks) == 1
    fmt, content = raw_blocks[0]["c"]
    assert fmt == "openxml"
    assert content.strip() == RAW_OOXML_FRAGMENT


# --------------------------------------- real end-to-end docx render proof --

@pytest.mark.skipif(not HAVE_PANDOC, reason="needs pandoc")
def test_docx_render_passes_raw_openxml_block_through_verbatim(tmp_path):
    """End-to-end regression/proof for issue #96: round-trip a hand-authored
    ```{=openxml} fixture through the REAL `render docx` pipeline (render.py
    -> container/render-doc.sh -> pandoc), then inspect the REAL output
    .docx's word/document.xml and confirm the marker text landed as a literal
    paragraph (raw OOXML passthrough), not as escaped/literal code text."""
    src = tmp_path / "raw-attribute.md"
    src.write_text(RAW_ATTRIBUTE_SOURCE, encoding="utf-8")
    env = {**os.environ, "OUTPUT_DIR": str(tmp_path / "out")}
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "docx", str(src)],
        capture_output=True, text=True, timeout=120, env=env, cwd=tmp_path,
    )
    combined = result.stdout + result.stderr
    if result.returncode == 3 and ("pandoc not found" in combined or "bash not found" in combined
                                    or "python not found" in combined):
        pytest.skip("render engines not installed on this host: " + combined.strip()[:160])
    assert result.returncode == 0, combined

    docx_files = sorted((tmp_path / "out").glob("*.docx"))
    assert len(docx_files) == 1, combined
    xml = _docx_document_xml(docx_files[0])

    # The marker text must appear as real run text inside the document body
    # (proving the fragment reached the writer as raw OOXML, not as an
    # escaped/htmlencoded code-block rendering of the same characters).
    assert "<w:t>RAW OOXML MARKER TEXT</w:t>" in xml
    # The fenced-block delimiter syntax itself must never leak into the body.
    assert "{=openxml}" not in xml
    assert "```" not in xml
