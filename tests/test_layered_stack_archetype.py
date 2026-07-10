"""
Tests for lint/layered_stack.py - the layered-stack diagram archetype
(issue #68, FR1-FR3: the core deliverable; the ArchiMate adapter, FR4-FR7,
is out of scope and tracked as a separate follow-up issue).

Covers: source parsing + validation (fail-closed on structural problems),
content-sniff dispatch, the NFR6 element-budget gate (reusing
lint/element_budget.py's own tier table), D2 emission for the N=1 degenerate
case and the N>1 side-by-side case, brand-token resolution (default AND a
consumer override, proving colours are resolved, not hardcoded), and an
end-to-end integration render through the real `render diagram` dispatch
(skipped if the host has no D2 CLI).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lint"))
sys.path.insert(0, str(REPO_ROOT / "tokens" / "gen"))

import element_budget  # noqa: E402
import layered_stack as ls  # noqa: E402


def _load_lint_render():
    """Load lint/render.py under a private module name. The repo ALSO has a
    top-level render.py (the CLI entry point); a plain `import render` would
    silently reuse whichever one another test file imported first under the
    bare name "render" in sys.modules, since both would collide there --
    fragile and collection-order-dependent. Loading lint/render.py explicitly
    by file path sidesteps the collision regardless of test collection order."""
    spec = importlib.util.spec_from_file_location(
        "_lint_render_for_layered_stack_tests", REPO_ROOT / "lint" / "render.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diagram_render = _load_lint_render()  # lint/render.py, the diagram dispatcher

HAVE_D2 = diagram_render._find_executable("d2", fallback=diagram_render.D2_EXE) is not None
needs_d2 = pytest.mark.skipif(not HAVE_D2, reason="d2 CLI not installed on this host")


def _write_yaml(tmp_path: Path, doc: dict, name: str = "source.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


MINIMAL_DOC = {
    "archetype": "layered-stack",
    "title": "Minimal stack",
    "stack": [
        {"type": "layer", "id": "top", "label": "Top Layer"},
        {"type": "layer", "id": "bottom", "label": "Bottom Layer"},
    ],
}


def _full_doc(n_chains: int = 2) -> dict:
    chains = []
    for i in range(n_chains):
        letter = chr(ord("a") + i)
        chains.append({
            "id": f"vendor-{letter}",
            "label": f"Vendor {letter.upper()}",
            "layers": [
                {"id": f"cmp-{letter}", "label": "CMP"},
                {"id": f"hyp-{letter}", "label": "Hypervisor"},
            ],
        })
    return {
        "archetype": "layered-stack",
        "title": "Full worked example",
        "stack": [
            {"type": "layer", "id": "workload", "label": "Workloads"},
            {"type": "interface", "id": "iface-provisioning", "label": "Provisioning interface"},
            {"type": "chains", "id": "cmp-tier", "chains": chains},
            {"type": "interface", "id": "iface-compute", "label": "Compute interface"},
            {"type": "layer", "id": "transport", "label": "Transport"},
        ],
    }


# --- parsing / validation -------------------------------------------------------


def test_parse_minimal_two_layer_source():
    model = ls.parse_model(MINIMAL_DOC, "minimal")
    assert model.title == "Minimal stack"
    assert model.tier == ls.DEFAULT_TIER
    assert [el.id for el in model.elements] == ["top", "bottom"]


def test_parse_full_source_with_interfaces_and_chains():
    model = ls.parse_model(_full_doc(), "full")
    kinds = [type(el).__name__ for el in model.elements]
    assert kinds == ["Layer", "Interface", "ChainsBlock", "Interface", "Layer"]
    chains_block = model.elements[2]
    assert len(chains_block.chains) == 2
    assert [c.id for c in chains_block.chains] == ["vendor-a", "vendor-b"]
    assert len(chains_block.chains[0].layers) == 2


@pytest.mark.parametrize("bad_archetype", [None, "hub-spoke", "layered_stack", ""])
def test_parse_rejects_wrong_or_missing_archetype_key(bad_archetype):
    doc = dict(MINIMAL_DOC)
    doc["archetype"] = bad_archetype
    with pytest.raises(ls.LayeredStackError, match="archetype"):
        ls.parse_model(doc, "bad-archetype")


def test_parse_rejects_missing_stack():
    doc = {"archetype": "layered-stack", "title": "No stack"}
    with pytest.raises(ls.LayeredStackError, match="stack"):
        ls.parse_model(doc, "no-stack")


def test_parse_rejects_empty_stack_list():
    doc = {"archetype": "layered-stack", "title": "Empty", "stack": []}
    with pytest.raises(ls.LayeredStackError, match="stack"):
        ls.parse_model(doc, "empty-stack")


def test_parse_rejects_duplicate_top_level_ids():
    doc = {
        "archetype": "layered-stack",
        "title": "Dupe",
        "stack": [
            {"type": "layer", "id": "same", "label": "A"},
            {"type": "layer", "id": "same", "label": "B"},
        ],
    }
    with pytest.raises(ls.LayeredStackError, match="duplicate"):
        ls.parse_model(doc, "dupe")


@pytest.mark.parametrize("bad_id", ["has space", "1starts-with-digit", "has.dot", "", None])
def test_parse_rejects_malformed_ids(bad_id):
    doc = {
        "archetype": "layered-stack",
        "title": "Bad id",
        "stack": [{"type": "layer", "id": bad_id, "label": "X"}],
    }
    with pytest.raises(ls.LayeredStackError, match="id"):
        ls.parse_model(doc, "bad-id")


def test_parse_rejects_unknown_stack_entry_type():
    doc = {
        "archetype": "layered-stack",
        "title": "Unknown type",
        "stack": [{"type": "wormhole", "id": "x"}],
    }
    with pytest.raises(ls.LayeredStackError, match="unknown type"):
        ls.parse_model(doc, "unknown-type")


def test_chain_with_zero_layers_rejected():
    doc = {
        "archetype": "layered-stack",
        "title": "Empty chain",
        "stack": [{
            "type": "chains", "id": "block",
            "chains": [{"id": "c1", "label": "C1", "layers": []}],
        }],
    }
    with pytest.raises(ls.LayeredStackError, match="layers"):
        ls.parse_model(doc, "empty-chain-layers")


def test_chains_block_with_zero_chains_rejected():
    doc = {
        "archetype": "layered-stack",
        "title": "Zero chains",
        "stack": [{"type": "chains", "id": "block", "chains": []}],
    }
    with pytest.raises(ls.LayeredStackError, match="chains"):
        ls.parse_model(doc, "zero-chains")


def test_chains_block_duplicate_chain_id_rejected():
    doc = {
        "archetype": "layered-stack",
        "title": "Dupe chain",
        "stack": [{
            "type": "chains", "id": "block",
            "chains": [
                {"id": "c1", "label": "C1", "layers": [{"id": "a", "label": "A"}]},
                {"id": "c1", "label": "C1-again", "layers": [{"id": "b", "label": "B"}]},
            ],
        }],
    }
    with pytest.raises(ls.LayeredStackError, match="duplicate"):
        ls.parse_model(doc, "dupe-chain")


def test_view_tier_default_is_most_permissive():
    assert ls.DEFAULT_TIER == "procurement-annex"
    assert ls.DEFAULT_TIER in element_budget.VALID_TIERS


def test_view_tier_invalid_value_rejected():
    doc = dict(MINIMAL_DOC)
    doc["view-tier"] = "not-a-real-tier"
    with pytest.raises(ls.LayeredStackError, match="view-tier"):
        ls.parse_model(doc, "bad-tier")


def test_load_model_rejects_unreadable_path(tmp_path):
    with pytest.raises(ls.LayeredStackError):
        ls.load_model(tmp_path / "does-not-exist.yaml")


def test_load_model_rejects_invalid_yaml(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("archetype: [unterminated\n", encoding="utf-8")
    with pytest.raises(ls.LayeredStackError):
        ls.load_model(p)


# --- content-sniff dispatch -------------------------------------------------------


def test_sniff_archetype_recognizes_valid_source(tmp_path):
    p = _write_yaml(tmp_path, MINIMAL_DOC)
    assert ls.sniff_archetype(p) == "layered-stack"


def test_sniff_archetype_returns_none_for_unrelated_yaml(tmp_path):
    p = _write_yaml(tmp_path, {"colour": {"brand": {"primary": "#000"}}})
    assert ls.sniff_archetype(p) is None


def test_sniff_archetype_returns_none_for_non_yaml_garbage(tmp_path):
    p = tmp_path / "garbage.yaml"
    p.write_bytes(b"\x00\x01\xff not: yaml: at: all: [[[")
    assert ls.sniff_archetype(p) is None


def test_sniff_archetype_returns_none_for_missing_file(tmp_path):
    assert ls.sniff_archetype(tmp_path / "nope.yaml") is None


# --- NFR6 element budget -----------------------------------------------------------


def test_count_elements_plain_layers():
    model = ls.parse_model(MINIMAL_DOC, "minimal")
    assert ls.count_elements(model) == 2


def test_count_elements_with_chains_block():
    model = ls.parse_model(_full_doc(n_chains=3), "full3")
    # 1 workload layer + 1 interface + (3 chains * 2 layers) + 1 interface + 1 transport
    assert ls.count_elements(model) == 1 + 1 + 6 + 1 + 1


def test_element_budget_passes_within_tier():
    doc = dict(_full_doc())
    doc["view-tier"] = "operator-handoff"  # hard 25, well above this model's 10
    model = ls.parse_model(doc, "within-budget")
    ls.check_element_budget(model)  # must not raise


def test_element_budget_fails_closed_with_actionable_message():
    doc = {
        "archetype": "layered-stack",
        "title": "Too big",
        "view-tier": "executive-cover",  # hard 7
        "stack": [{"type": "layer", "id": f"l{i}", "label": f"L{i}"} for i in range(10)],
    }
    model = ls.parse_model(doc, "too-big")
    with pytest.raises(ls.ElementBudgetExceeded, match="Split this into multiple views"):
        ls.check_element_budget(model)


def test_generate_d2_source_raises_before_render_on_budget_breach(tmp_path):
    doc = {
        "archetype": "layered-stack",
        "title": "Too big",
        "view-tier": "executive-cover",
        "stack": [{"type": "layer", "id": f"l{i}", "label": f"L{i}"} for i in range(10)],
    }
    p = _write_yaml(tmp_path, doc)
    with pytest.raises(ls.ElementBudgetExceeded):
        ls.generate_d2_source(p)


# --- D2 emission --------------------------------------------------------------------


def test_render_d2_degenerate_n1_uses_grid_columns_1():
    doc = {
        "archetype": "layered-stack",
        "title": "N=1",
        "stack": [
            {"type": "layer", "id": "top", "label": "Top"},
            {"type": "chains", "id": "mid", "chains": [
                {"id": "only", "label": "Only Chain", "layers": [{"id": "a", "label": "A"}]},
            ]},
            {"type": "layer", "id": "bottom", "label": "Bottom"},
        ],
    }
    model = ls.parse_model(doc, "n1")
    d2 = ls.render_d2(model, ls.load_tokens())
    assert "grid-columns: 1" in d2
    assert '"mid"."only"."a"' in d2  # quoted dotted path into the single realizing chain


def test_render_d2_n_parallel_chains_side_by_side():
    model = ls.parse_model(_full_doc(n_chains=4), "n4")
    d2 = ls.render_d2(model, ls.load_tokens())
    assert "grid-columns: 4" in d2
    for letter in "abcd":
        assert f'"vendor-{letter}"' in d2
        assert f'"cmp-tier"."vendor-{letter}"."cmp-{letter}"' in d2
    # each chain fans in/out to the SAME shared interface on either side
    assert d2.count('"iface-provisioning" -- "cmp-tier"."vendor-') == 4
    assert d2.count('-- "iface-compute"') == 4


def test_render_d2_identifiers_are_always_quoted_including_reserved_words():
    # "top"/"bottom" collide with D2's own reserved position keywords when
    # emitted bare - quoting every id sidesteps the whole reserved-word
    # surface (discovered during development: an unquoted "top" broke the
    # D2 compiler with "reserved keywords are prohibited in edges").
    doc = {
        "archetype": "layered-stack",
        "title": "Reserved word ids",
        "stack": [
            {"type": "layer", "id": "top", "label": "Top"},
            {"type": "layer", "id": "bottom", "label": "Bottom"},
        ],
    }
    model = ls.parse_model(doc, "reserved")
    d2 = ls.render_d2(model, ls.load_tokens())
    assert '"top": {' in d2
    assert '"bottom": {' in d2
    assert '"top" -- "bottom"' in d2


def test_render_d2_interface_is_visually_distinct_from_layers():
    model = ls.parse_model(_full_doc(), "full")
    tokens = ls.load_tokens()
    d2 = ls.render_d2(model, tokens)
    palette = ls.resolve_palette(tokens)
    assert "shape: oval" in d2  # interfaces
    assert "shape: rectangle" in d2  # layers
    assert palette.interface_fill != palette.layer_fill
    assert "style.stroke-width: 3" in d2  # boundary marker gets a thicker stroke


def test_render_d2_labels_escape_quotes_and_newlines():
    doc = {
        "archetype": "layered-stack",
        "title": 'A "quoted" title',
        "stack": [{"type": "layer", "id": "x", "label": 'Has "quotes" and back\\slash'}],
    }
    model = ls.parse_model(doc, "escaping")
    d2 = ls.render_d2(model, ls.load_tokens())
    assert '\\"quoted\\"' in d2
    assert '\\"quotes\\"' in d2
    assert "back\\\\slash" in d2
    # interface stereotype line-break must be the two-char escape, never a raw
    # newline inside a D2 quoted string (a raw newline breaks the D2 parser --
    # verified against d2 0.7.1 during development)
    doc2 = dict(_full_doc())
    d2_full = ls.render_d2(ls.parse_model(doc2, "iface"), ls.load_tokens())
    assert "\\n" in d2_full
    for line in d2_full.splitlines():
        assert line.count('"') % 2 == 0  # no line has an unterminated quote


# --- brand-token resolution: roles, not hardcoded colours --------------------------


def test_render_d2_uses_default_brand_tokens():
    tokens = ls.load_tokens()
    model = ls.parse_model(_full_doc(), "full")  # needs an interface element too
    d2 = ls.render_d2(model, tokens)
    assert tokens["colour"]["brand"]["fill"] in d2
    assert tokens["colour"]["brand"]["primary"] in d2
    assert tokens["colour"]["status"]["info"] in d2


def test_consumer_brand_override_changes_emitted_colours(tmp_path):
    override = {"colour": {"brand": {"primary": "#123456", "fill": "#ABCDEF"}}}
    override_path = tmp_path / "consumer-brand.yaml"
    override_path.write_text(yaml.safe_dump(override), encoding="utf-8")

    default_tokens = ls.load_tokens()
    custom_tokens = ls.load_tokens(override_path)

    model = ls.parse_model(MINIMAL_DOC, "minimal")
    default_d2 = ls.render_d2(model, default_tokens)
    custom_d2 = ls.render_d2(model, custom_tokens)

    assert "#123456" in custom_d2
    assert "#ABCDEF" in custom_d2
    # the default brand primary must NOT leak into a consumer-overridden render
    assert default_tokens["colour"]["brand"]["primary"] not in custom_d2


def test_generate_d2_source_end_to_end_from_file(tmp_path):
    p = _write_yaml(tmp_path, _full_doc())
    d2 = ls.generate_d2_source(p)
    assert "direction: down" in d2
    assert "Vendor A" in d2
    assert "Vendor B" in d2


# --- CLI --------------------------------------------------------------------------


def test_cli_writes_d2_to_out_file(tmp_path):
    src = _write_yaml(tmp_path, MINIMAL_DOC)
    out = tmp_path / "out.d2"
    rc = ls.main([str(src), "-o", str(out)])
    assert rc == 0
    assert out.exists()
    assert "Top Layer" in out.read_text(encoding="utf-8")


def test_cli_rejects_invalid_source_with_nonzero_exit(tmp_path, capsys):
    src = _write_yaml(tmp_path, {"archetype": "layered-stack", "title": "x", "stack": []})
    rc = ls.main([str(src)])
    assert rc == 1
    assert "REJECT" in capsys.readouterr().err


# --- lint/render.py dispatch (extension + directory scan) --------------------------


def test_non_archetype_yaml_in_directory_scan_is_skipped_not_crashed(tmp_path, capsys):
    p = tmp_path / "not-a-diagram.yaml"
    p.write_text("some: config\n", encoding="utf-8")
    ok = diagram_render.render_file(p, tmp_path, ["svg"])
    assert ok is True
    assert "SKIP" in capsys.readouterr().out


def test_render_file_rejects_over_budget_archetype_source(tmp_path, capsys):
    doc = {
        "archetype": "layered-stack",
        "title": "Too big",
        "view-tier": "executive-cover",
        "stack": [{"type": "layer", "id": f"l{i}", "label": f"L{i}"} for i in range(10)],
    }
    p = _write_yaml(tmp_path, doc)
    ok = diagram_render.render_file(p, tmp_path, ["svg"])
    assert ok is False
    assert "REJECT" in capsys.readouterr().err


@needs_d2
def test_render_file_produces_real_svg_with_expected_labels(tmp_path):
    src = _write_yaml(tmp_path, _full_doc(n_chains=2))
    ok = diagram_render.render_file(src, tmp_path, ["svg"])
    assert ok is True
    out_svg = tmp_path / "source.svg"
    assert out_svg.exists()
    svg_text = out_svg.read_text(encoding="utf-8")
    for expected in ("Workloads", "Vendor A", "Vendor B", "Provisioning interface", "Transport"):
        assert expected in svg_text
    generated_d2 = tmp_path / "source.generated.d2"
    assert generated_d2.exists()


@needs_d2
def test_render_diagram_dispatch_end_to_end_subprocess(tmp_path):
    src = _write_yaml(tmp_path, _full_doc(n_chains=2))
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "render.py"), "diagram", str(src),
         "--output-dir", str(tmp_path), "--formats", "svg"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "source.svg").exists()


@needs_d2
def test_directory_scan_picks_up_archetype_yaml(tmp_path):
    src_dir = tmp_path / "sources"
    src_dir.mkdir()
    _write_yaml(src_dir, MINIMAL_DOC, name="stack.yaml")
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "render.py"), "diagram", str(src_dir),
         "--output-dir", str(out_dir), "--formats", "svg"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (out_dir / "stack.svg").exists()


def test_demo_exemplar_is_a_valid_layered_stack_source():
    demo_path = REPO_ROOT / "demo" / "diagrams" / "layered-stack-example.yaml"
    assert demo_path.exists()
    model = ls.load_model(demo_path)
    ls.check_element_budget(model)  # the shipped demo must itself pass NFR6
    assert any(isinstance(el, ls.ChainsBlock) and len(el.chains) >= 2 for el in model.elements)


@needs_d2
def test_demo_exemplar_renders(tmp_path):
    demo_path = REPO_ROOT / "demo" / "diagrams" / "layered-stack-example.yaml"
    ok = diagram_render.render_file(demo_path, tmp_path, ["svg"])
    assert ok is True
    assert (tmp_path / "layered-stack-example.svg").exists()
