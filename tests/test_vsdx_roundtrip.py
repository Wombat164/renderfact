"""
Tests for roundtrip/visio.py (C8.2: the Visio/.vsdx adapter of the
editable-diagram round-trip) and the generic OPC provenance adapter it rides.

Covers: generation (NameU anchors verbatim, prototype shapes removed, OPC
dc:identifier provenance embedded -- the byte-level verification the prior-art
pass flagged as the first implementation task); the clean round-trip
(FAST_FORWARD, zero semantic noise, layout channel populated then idempotent
after apply); the ID-first classifier routing relabels/adds/removes/rewires to
semantic and PinX/PinY moves to layout against simulated hand-edits made
directly in the page XML (namespace-aware, the way Visio itself would); uid
mismatch and DIVERGED verdicts; provenance strip/re-embed on .vsdx including
the core-part CREATION path (package stripped of docProps/core.xml gets the
part, its content-type override and its package relationship added back); and
the render.py CLI end to end.

The whole module skips cleanly when the optional `vsdx` library is not
installed (pip install renderfact[vsdx]) -- mirroring the pandoc/markitdown
optional-tool discipline.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

pytest.importorskip("vsdx", reason="the Visio adapter needs the optional vsdx library")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "roundtrip"))

import provenance  # noqa: E402
import visio  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"
_VISIO_NS = "http://schemas.microsoft.com/office/visio/2012/main"


def _graph(tmp_path: Path) -> Path:
    p = tmp_path / "graph.yaml"
    p.write_text(
        "title: Payment platform\n"
        "concepts:\n"
        "  - {id: gateway, label: API Gateway}\n"
        "  - {id: auth, label: Auth Service}\n"
        "  - {id: ledger, label: Ledger, kind: store}\n"
        "relations:\n"
        "  - {from: gateway, to: auth, label: validates via}\n"
        "  - {from: auth, to: ledger}\n",
        encoding="utf-8",
    )
    return p


def _generate(tmp_path: Path) -> tuple[Path, Path]:
    graph = _graph(tmp_path)
    out = tmp_path / "d.vsdx"
    visio.generate(graph, out)
    return graph, out


def _page_xml(vsdx_path: Path) -> ET.Element:
    with zipfile.ZipFile(vsdx_path) as zf:
        return ET.fromstring(zf.read("visio/pages/page1.xml"))


def _rewrite_page(src: Path, dst: Path, mutate) -> None:
    """Copy a .vsdx, applying `mutate(page_root)` to page1.xml -- the
    namespace-aware equivalent of a hand-edit saved by Visio."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for name in zin.namelist():
            data = zin.read(name)
            if name == "visio/pages/page1.xml":
                root = ET.fromstring(data)
                mutate(root)
                ET.register_namespace("", _VISIO_NS)
                data = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
            zout.writestr(name, data)


def _shape_by_anchor(root: ET.Element, anchor: str) -> ET.Element:
    for shape in root.iter(f"{{{_VISIO_NS}}}Shape"):
        if shape.get("NameU") == f"rf.{anchor}":
            return shape
    raise AssertionError(f"no shape anchored rf.{anchor}")


# ---------------------------------------------------------------- generate --

def test_generate_anchors_and_prototypes_gone(tmp_path):
    _, out = _generate(tmp_path)
    root = _page_xml(out)
    anchors = {s.get("NameU") for s in root.iter(f"{{{_VISIO_NS}}}Shape")}
    assert {"rf.gateway", "rf.auth", "rf.ledger",
            "rf.rel:gateway->auth", "rf.rel:auth->ledger"} <= anchors
    texts = " ".join((t.text or "") for t in root.iter(f"{{{_VISIO_NS}}}Text"))
    for proto in ("RECTANGLE", "CONNECTED_SHAPE", "STRAIGHT_CONNECTOR",
                  "CURVED_CONNECTOR", "CIRCLE"):
        assert proto not in texts, f"media prototype {proto} leaked into the output"


def test_generate_embeds_opc_provenance(tmp_path):
    graph, out = _generate(tmp_path)
    prov = provenance.extract(out)
    assert prov is not None
    declared = yaml.safe_load(graph.read_text(encoding="utf-8"))["renderfact_uid"]
    assert prov.source_uid == str(declared)
    # byte-level: the dc:identifier lives in docProps/core.xml inside the zip
    with zipfile.ZipFile(out) as zf:
        core = zf.read("docProps/core.xml").decode("utf-8")
    assert "renderfact:v1:" in core


def test_stored_layout_wins_on_regeneration(tmp_path):
    graph = _graph(tmp_path)
    layout = tmp_path / "layout.yaml"
    layout.write_text("gateway: {x: 7.5, y: 3.25}\n", encoding="utf-8")
    out = tmp_path / "d.vsdx"
    visio.generate(graph, out, layout)
    shape = _shape_by_anchor(_page_xml(out), "gateway")
    cells = {c.get("N"): c.get("V") for c in shape.iter(f"{{{_VISIO_NS}}}Cell")}
    assert float(cells["PinX"]) == 7.5 and float(cells["PinY"]) == 3.25


# ------------------------------------------------------------- round-trip --

def test_clean_roundtrip_and_layout_idempotence(tmp_path):
    graph, out = _generate(tmp_path)
    layout = tmp_path / "layout.yaml"
    assert visio.check_provenance(out, graph) == "FAST_FORWARD"

    vf, page = visio._read_page(out)
    try:
        buckets = visio.classify(visio.drawio.load_graph(graph), page,
                                 visio.drawio.load_layout(layout))
    finally:
        vf.close_vsdx()
    assert buckets["semantic"] == []
    assert set(buckets["layout"]) == {"gateway", "auth", "ledger"}

    visio.drawio.apply_layout(layout, buckets["layout"])
    vf, page = visio._read_page(out)
    try:
        again = visio.classify(visio.drawio.load_graph(graph), page,
                               visio.drawio.load_layout(layout))
    finally:
        vf.close_vsdx()
    assert again["layout"] == {} and again["semantic"] == []


def test_classifier_routes_hand_edits(tmp_path):
    graph, out = _generate(tmp_path)
    layout = tmp_path / "layout.yaml"
    # settle the layout channel first so only the simulated move shows up
    vf, page = visio._read_page(out)
    try:
        visio.drawio.apply_layout(
            layout, visio.classify(visio.drawio.load_graph(graph), page,
                                   {})["layout"])
    finally:
        vf.close_vsdx()

    edited = tmp_path / "edited.vsdx"

    def mutate(root):
        ns = f"{{{_VISIO_NS}}}"
        # relabel auth
        for t in _shape_by_anchor(root, "auth").iter(f"{ns}Text"):
            t.text = "Auth Service v2"
        # move gateway
        for c in _shape_by_anchor(root, "gateway").iter(f"{ns}Cell"):
            if c.get("N") == "PinX":
                c.set("V", "4.4")
        # delete ledger AND its connector, the way a user cleans up properly
        # (deleting only the node would leave the connector dangling, which
        # the classifier correctly reports as a rewire, not a removal)
        shapes = root.find(f"{ns}Shapes")
        ledger = _shape_by_anchor(root, "ledger")
        conn = _shape_by_anchor(root, "rel:auth->ledger")
        removed_ids = {ledger.get("ID"), conn.get("ID")}
        shapes.remove(ledger)
        shapes.remove(conn)
        connects = root.find(f"{ns}Connects")
        for cel in list(connects):
            if {cel.get("ToSheet"), cel.get("FromSheet")} & removed_ids:
                connects.remove(cel)
        # add a rogue node the way Visio would (fresh ID, no NameU anchor)
        rogue = ET.SubElement(shapes, f"{ns}Shape",
                              {"ID": "999", "Type": "Shape"})
        txt = ET.SubElement(rogue, f"{ns}Text")
        txt.text = "Fraud Check"

    _rewrite_page(out, edited, mutate)

    vf, page = visio._read_page(edited)
    try:
        buckets = visio.classify(visio.drawio.load_graph(graph), page,
                                 visio.drawio.load_layout(layout))
    finally:
        vf.close_vsdx()

    kinds = {(s["kind"], s["id"]) for s in buckets["semantic"]}
    assert ("relabel-node", "auth") in kinds
    assert ("remove-node", "ledger") in kinds
    assert ("remove-edge", "rel:auth->ledger") in kinds
    assert any(k == "add-node" and s.get("new") == "Fraud Check"
               for k, _ in kinds for s in buckets["semantic"]
               if s["kind"] == "add-node")
    assert "gateway" in buckets["layout"]
    assert abs(buckets["layout"]["gateway"]["x"] - 4.4) < 0.01
    assert "auth" not in buckets["layout"], "a pure relabel must not touch the layout channel"


def test_rewire_detection(tmp_path):
    graph, out = _generate(tmp_path)
    edited = tmp_path / "edited.vsdx"

    def mutate(root):
        ns = f"{{{_VISIO_NS}}}"
        gateway_id = _shape_by_anchor(root, "gateway").get("ID")
        auth_id = _shape_by_anchor(root, "auth").get("ID")
        conn_id = _shape_by_anchor(root, "rel:auth->ledger").get("ID")
        for cel in root.find(f"{ns}Connects"):
            if cel.get("FromSheet") == conn_id and cel.get("FromCell") == "EndX":
                cel.set("ToSheet", gateway_id)
            if cel.get("FromSheet") == conn_id and cel.get("FromCell") == "BeginX":
                cel.set("ToSheet", auth_id)

    _rewrite_page(out, edited, mutate)
    vf, page = visio._read_page(edited)
    try:
        buckets = visio.classify(visio.drawio.load_graph(graph), page, {})
    finally:
        vf.close_vsdx()
    rewires = [s for s in buckets["semantic"] if s["kind"] == "rewire-edge"]
    assert rewires and rewires[0]["new"] == "auth->gateway"


# ---------------------------------------------------------------- verdicts --

def test_uid_mismatch_fails_closed(tmp_path):
    _, out = _generate(tmp_path)
    other = tmp_path / "other.yaml"
    other.write_text("concepts:\n  - {id: x}\nrenderfact_uid: not-the-same\n",
                     encoding="utf-8")
    with pytest.raises(visio.VsdxError, match="UID mismatch"):
        visio.check_provenance(out, other)


def test_diverged_when_source_evolves(tmp_path):
    graph, out = _generate(tmp_path)
    text = graph.read_text(encoding="utf-8")
    graph.write_text(text.replace("label: Ledger", "label: General Ledger"),
                     encoding="utf-8")
    assert visio.check_provenance(out, graph) == "DIVERGED"


# ------------------------------------------------- OPC provenance adapter --

def test_strip_and_reembed_on_vsdx(tmp_path):
    graph, out = _generate(tmp_path)
    assert provenance.strip(out) is True
    assert provenance.extract(out) is None
    provenance.embed(out, provenance.build_provenance(graph))
    assert provenance.extract(out) is not None


def test_core_part_creation_path(tmp_path):
    """A package with NO docProps/core.xml gets the part plus its content-type
    override and package relationship on embed -- the corruption-risk path the
    module docstring warns about, exercised rather than assumed."""
    graph, out = _generate(tmp_path)
    bare = tmp_path / "bare.vsdx"
    with zipfile.ZipFile(out) as zin, zipfile.ZipFile(bare, "w") as zout:
        for name in zin.namelist():
            if name == "docProps/core.xml":
                continue
            data = zin.read(name)
            if name == "_rels/.rels":
                root = ET.fromstring(data)
                rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
                for r in list(root):
                    if "core-properties" in (r.get("Type") or ""):
                        root.remove(r)
                ET.register_namespace("", rel_ns)
                data = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
            zout.writestr(name, data)

    provenance.embed(bare, provenance.build_provenance(graph))
    assert provenance.extract(bare) is not None
    with zipfile.ZipFile(bare) as zf:
        ct = zf.read("[Content_Types].xml").decode("utf-8")
        rels = zf.read("_rels/.rels").decode("utf-8")
    assert "/docProps/core.xml" in ct
    assert "core-properties" in rels


# --------------------------------------------------------------------- CLI --

def test_cli_end_to_end(tmp_path):
    graph = _graph(tmp_path)
    out = tmp_path / "cli.vsdx"
    gen = subprocess.run(
        [sys.executable, str(RENDER_PY), "vsdx", "generate", str(graph), "-o", str(out)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT),
    )
    assert gen.returncode == 0, gen.stderr
    assert "set_move_to" not in gen.stdout, "library debug noise leaked into the CLI"

    rei = subprocess.run(
        [sys.executable, str(RENDER_PY), "vsdx", "reingest", str(out),
         "--source", str(graph), "--json"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT),
    )
    assert rei.returncode == 0, rei.stderr
    payload = json.loads(rei.stdout)
    assert payload["verdict"] == "FAST_FORWARD"
    assert payload["semantic"] == []
