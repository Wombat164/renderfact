"""
Tests for tokens/gen/*.py -- the brand.yaml -> per-engine theme generators (A1, chunk 0.4).

Covers: default tokens parse, consumer-override deep-merge works, each generator
produces syntactically valid output in its target format, and generate_all.py
runs all four cleanly. Run: pytest tests/test_token_generators.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tokens" / "gen"))

from _common import load_tokens  # noqa: E402
import marp_theme  # noqa: E402
import mermaid_theme  # noqa: E402
import pandoc_template_profile  # noqa: E402
import typst_tokens  # noqa: E402


def test_default_brand_yaml_parses():
    tokens = load_tokens()
    assert tokens["colour"]["brand"]["primary"] == "#2B4A6F"
    assert tokens["colour"]["brand"]["background"] == "#F5F5F2"  # the bug fixed 2026-07-02
    assert len(tokens["colour"]["data"]) == 8  # Wong-8


def test_consumer_override_deep_merges():
    override = {"colour": {"brand": {"primary": "#FF0000"}}}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        yaml.safe_dump(override, f)
        override_path = Path(f.name)
    try:
        tokens = load_tokens(override_path)
        # overridden value wins
        assert tokens["colour"]["brand"]["primary"] == "#FF0000"
        # non-overridden siblings survive the merge
        assert tokens["colour"]["brand"]["accent"] == "#3E7CB1"
        assert tokens["colour"]["status"]["ok"] == "#2E7D32"
    finally:
        override_path.unlink()


def test_missing_consumer_override_raises():
    with pytest.raises(FileNotFoundError):
        load_tokens(Path("/nonexistent/brand.yaml"))


def test_mermaid_theme_is_valid_json_and_carries_tokens():
    tokens = load_tokens()
    config = mermaid_theme.render_mermaid_config(tokens)
    # round-trips through json.dumps/loads cleanly
    parsed = json.loads(json.dumps(config))
    assert parsed["themeVariables"]["primaryColor"] == tokens["colour"]["brand"]["fill"]
    assert parsed["themeVariables"]["fontFamily"] == tokens["type"]["body_font"]
    # the Wong-8/status limitation is documented, not silently dropped
    assert "_note" in parsed
    assert "Wong-8" in parsed["_note"] or "categorical" in parsed["_note"]


def test_marp_css_carries_all_data_colours():
    tokens = load_tokens()
    css = marp_theme.render_marp_css(tokens)
    assert "@theme" in css
    for i, colour in enumerate(tokens["colour"]["data"]):
        assert f"--data-{i}: {colour};" in css
    assert tokens["colour"]["brand"]["primary"] in css


def test_pandoc_template_profile_flat_schema_from_descriptor():
    # #32: FLAT keys consumed by docstyle/style_postprocess, sourced from the
    # theme descriptor. base heading_role = accent; financial = primary.
    tokens = load_tokens()
    profile = pandoc_template_profile.render_template_profile(tokens)
    assert profile["accent"] == tokens["colour"]["brand"]["accent"]
    assert profile["font"] == tokens["type"]["print_font"]
    assert profile["body"] == tokens["colour"]["brand"]["ink"]
    assert profile["margin_cm"] == 2.2 and profile["page_width_cm"] == 21.0
    fin = pandoc_template_profile.render_template_profile(tokens, "financial")
    assert fin["accent"] == tokens["colour"]["brand"]["primary"]


def test_docx_post_processor_consumes_the_descriptor_profile(tmp_path):
    # #32 engine-agnostic proof: the SAME descriptor the typst chrome uses feeds
    # the DOCX house-style post-processor. A financial variant recolours DOCX
    # headings/table-headers to the primary role, exactly as it does in typst.
    import yaml

    from docstyle import style_postprocess as sp

    tokens = load_tokens()
    profile = pandoc_template_profile.render_template_profile(tokens, "financial")
    p = tmp_path / "template-profile.yaml"
    p.write_text(yaml.safe_dump(profile), encoding="utf-8")
    sp.apply_template_profile(str(p))
    assert sp.NAVY == sp._rgb(tokens["colour"]["brand"]["primary"])
    assert sp.FONT_NAME == tokens["type"]["print_font"]


def test_typst_tokens_no_leftover_branding():
    tokens = load_tokens()
    typ = typst_tokens.render_typst(tokens)
    assert "#let brand = (" in typ
    assert f'primary: rgb("{tokens["colour"]["brand"]["primary"]}")' in typ
    # regression guard: this generator is generic-core, must never hardcode a
    # specific consumer's branding into its own template
    assert "defence" not in typ.lower()


def test_generate_all_runs_every_generator_and_writes_files(tmp_path):
    import generate_all

    old_argv = sys.argv
    try:
        sys.argv = ["generate_all.py", "--output-dir", str(tmp_path)]
        rc = generate_all.main()
    finally:
        sys.argv = old_argv
    assert rc == 0
    assert (tmp_path / "mermaid" / "mermaid-theme.json").exists()
    assert (tmp_path / "marp" / "deck-theme.css").exists()
    assert (tmp_path / "pandoc" / "template-profile.yaml").exists()
    assert (tmp_path / "typst" / "tokens.typ").exists()
    assert (tmp_path / "typst" / "chrome.typ").exists()  # #32 theme descriptor
