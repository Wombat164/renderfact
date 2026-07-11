"""
Tests for lint/archimate_exchange.py - the ArchiMate Exchange-XML adapter for
the layered-stack archetype (issue #86, FR4-FR6 of the #68 follow-up; FR7
fast-re-render is a separate stretch item, not built here).

Covers: content-sniff (FR6), element parsing + type mapping into the
archetype's existing StackModel shape (FR4), fail-closed behaviour on an
unsupported ArchiMate element type and on structurally invalid XML (FR5),
reuse of the archetype's own NFR6 element-budget gate and D2 emission
unchanged, and the lint/render.py .xml dispatch integration (FR6, mirroring
the existing .yaml/.yml content-sniff branch).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lint"))
sys.path.insert(0, str(REPO_ROOT / "tokens" / "gen"))

import archimate_exchange as ax  # noqa: E402
import layered_stack as ls  # noqa: E402


def _load_lint_render():
    """See tests/test_layered_stack_archetype.py's own copy of this helper
    for why a plain `import render` is unsafe here (name collision with the
    top-level render.py CLI entry point)."""
    spec = importlib.util.spec_from_file_location(
        "_lint_render_for_archimate_tests", REPO_ROOT / "lint" / "render.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diagram_render = _load_lint_render()
HAVE_D2 = diagram_render._find_executable("d2", fallback=diagram_render.D2_EXE) is not None
needs_d2 = pytest.mark.skipif(not HAVE_D2, reason="d2 CLI not installed on this host")

NS = 'xmlns="http://www.opengroup.org/xsd/archimate/3.0/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'


def _model_xml(title: str, elements_xml: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<model {NS} identifier="id-model">\n'
        f'  <name xml:lang="en">{title}</name>\n'
        f'  <elements>\n{elements_xml}  </elements>\n'
        f"</model>\n"
    )


def _element_xml(identifier: str, xsi_type: str, name: str) -> str:
    return (
        f'    <element identifier="{identifier}" xsi:type="{xsi_type}">\n'
        f'      <name xml:lang="en">{name}</name>\n'
        f"    </element>\n"
    )


def _write_xml(tmp_path: Path, text: str, name: str = "model.xml") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


MINIMAL_XML = _model_xml(
    "Minimal Stack",
    _element_xml("id-1", "ApplicationComponent", "App")
    + _element_xml("id-2", "ApplicationInterface", "API")
    + _element_xml("id-3", "Node", "Server"),
)


# --- sniff ---------------------------------------------------------------------


def test_sniff_recognizes_valid_exchange_file(tmp_path):
    p = _write_xml(tmp_path, MINIMAL_XML)
    assert ax.sniff_archimate_exchange(p) is True


def test_sniff_returns_false_for_unrelated_xml(tmp_path):
    p = _write_xml(tmp_path, "<config><setting>value</setting></config>\n")
    assert ax.sniff_archimate_exchange(p) is False


def test_sniff_returns_false_for_non_xml_garbage(tmp_path):
    p = _write_xml(tmp_path, "not even close to xml {{{")
    assert ax.sniff_archimate_exchange(p) is False


def test_sniff_returns_false_for_missing_file(tmp_path):
    assert ax.sniff_archimate_exchange(tmp_path / "does-not-exist.xml") is False


def test_sniff_returns_false_for_model_root_without_archimate_namespace(tmp_path):
    # A <model> root that has nothing to do with ArchiMate (a different tool's
    # own "model.xml" convention) must not false-positive.
    p = _write_xml(tmp_path, '<model xmlns="http://example.com/some-other-schema/"></model>\n')
    assert ax.sniff_archimate_exchange(p) is False


# --- parsing + type mapping (FR4) -----------------------------------------------


def test_parse_maps_elements_to_layers_and_interfaces_in_document_order(tmp_path):
    p = _write_xml(tmp_path, MINIMAL_XML)
    model = ax.parse_exchange_file(p)
    assert model.title == "Minimal Stack"
    assert model.tier == ls.DEFAULT_TIER
    assert [type(el).__name__ for el in model.elements] == ["Layer", "Interface", "Layer"]
    assert [el.id for el in model.elements] == ["id-1", "id-2", "id-3"]
    assert [el.label for el in model.elements] == ["App", "API", "Server"]


def test_parse_falls_back_to_identifier_when_name_missing(tmp_path):
    xml = _model_xml(
        "No-name element",
        '    <element identifier="id-1" xsi:type="Node"></element>\n',
    )
    model = ax.parse_exchange_file(_write_xml(tmp_path, xml))
    assert model.elements[0].label == "id-1"


def test_parse_falls_back_to_path_when_model_name_missing(tmp_path):
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<model {NS} identifier="id-model">\n'
        f'  <elements>{_element_xml("id-1", "Node", "Server")}</elements>\n</model>\n'
    )
    p = _write_xml(tmp_path, xml)
    model = ax.parse_exchange_file(p)
    assert model.title == str(p)


# --- fail-closed (FR5) -----------------------------------------------------------


def test_parse_fails_closed_on_unsupported_element_type(tmp_path):
    xml = _model_xml(
        "Has a Capability",
        _element_xml("id-1", "Node", "Server") + _element_xml("id-2", "Capability", "Some Motivation Element"),
    )
    p = _write_xml(tmp_path, xml)
    with pytest.raises(ls.LayeredStackError, match="Capability"):
        ax.parse_exchange_file(p)


def test_parse_error_names_the_offending_element_and_lists_supported_types(tmp_path):
    xml = _model_xml("Has a Capability", _element_xml("id-2", "Capability", "Some Motivation Element"))
    p = _write_xml(tmp_path, xml)
    with pytest.raises(ls.LayeredStackError, match="id-2") as exc_info:
        ax.parse_exchange_file(p)
    assert "Some Motivation Element" in str(exc_info.value)
    assert "Node" in str(exc_info.value)  # a supported type, from the listed allowlist


def test_parse_fails_closed_on_duplicate_identifier(tmp_path):
    xml = _model_xml(
        "Dup ids",
        _element_xml("id-1", "Node", "A") + _element_xml("id-1", "Node", "B"),
    )
    with pytest.raises(ls.LayeredStackError, match="duplicate"):
        ax.parse_exchange_file(_write_xml(tmp_path, xml))


def test_parse_fails_closed_on_missing_elements_block(tmp_path):
    xml = f'<?xml version="1.0"?>\n<model {NS} identifier="id-model"></model>\n'
    with pytest.raises(ls.LayeredStackError, match="elements"):
        ax.parse_exchange_file(_write_xml(tmp_path, xml))


def test_parse_fails_closed_on_empty_elements_block(tmp_path):
    xml = f'<?xml version="1.0"?>\n<model {NS} identifier="id-model"><elements></elements></model>\n'
    with pytest.raises(ls.LayeredStackError, match="elements"):
        ax.parse_exchange_file(_write_xml(tmp_path, xml))


def test_parse_fails_closed_on_non_model_root(tmp_path):
    p = _write_xml(tmp_path, "<config><setting>value</setting></config>\n")
    with pytest.raises(ls.LayeredStackError, match="config"):
        ax.parse_exchange_file(p)


def test_parse_fails_closed_on_malformed_xml(tmp_path):
    p = _write_xml(tmp_path, "<model><elements><element>not closed\n")
    with pytest.raises(ls.LayeredStackError):
        ax.parse_exchange_file(p)


# --- D2 emission reuses the archetype's own gate + renderer unchanged ------------


def test_generate_d2_source_reuses_render_d2_and_contains_labels(tmp_path):
    p = _write_xml(tmp_path, MINIMAL_XML)
    d2 = ax.generate_d2_source_from_exchange(p)
    assert "App" in d2
    assert "API" in d2
    assert "Server" in d2


def test_generate_d2_source_enforces_element_budget(tmp_path):
    # NFR6: same tier budgets lint/element_budget.py already enforces, no
    # second budget mechanism invented for ArchiMate-sourced models.
    elements = "".join(_element_xml(f"id-{i}", "Node", f"Node {i}") for i in range(35))  # > 30, the procurement-annex hard budget
    xml = (
        f'<?xml version="1.0"?>\n<model {NS} identifier="id-model">\n'
        f"  <elements>\n{elements}  </elements>\n</model>\n"
    )
    p = _write_xml(tmp_path, xml)
    with pytest.raises(ls.ElementBudgetExceeded):
        ax.generate_d2_source_from_exchange(p)


# --- lint/render.py .xml dispatch (FR6) -------------------------------------------


def test_non_archimate_xml_in_directory_scan_is_skipped_not_crashed(tmp_path, capsys):
    p = _write_xml(tmp_path, "<config><setting>value</setting></config>\n", name="not-archimate.xml")
    ok = diagram_render.render_file(p, tmp_path, ["svg"])
    assert ok is True
    assert "SKIP" in capsys.readouterr().out


def test_render_file_rejects_unsupported_archimate_element(tmp_path, capsys):
    xml = _model_xml("Bad", _element_xml("id-1", "Capability", "Nope"))
    p = _write_xml(tmp_path, xml)
    ok = diagram_render.render_file(p, tmp_path, ["svg"])
    assert ok is False
    assert "REJECT" in capsys.readouterr().err


@needs_d2
def test_render_file_produces_real_svg_from_archimate_exchange_file(tmp_path):
    p = _write_xml(tmp_path, MINIMAL_XML)
    ok = diagram_render.render_file(p, tmp_path, ["svg"])
    assert ok is True
    out_svg = tmp_path / "model.svg"
    assert out_svg.exists()
    svg_text = out_svg.read_text(encoding="utf-8")
    assert "App" in svg_text
    assert "Server" in svg_text
