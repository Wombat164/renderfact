"""
Tests for roundtrip/drawio.py (C8.1: the drawio adapter of the editable-diagram
round-trip).

Covers: graph validation (missing/duplicate ids, dangling relations fail
closed); uid insertion on YAML sources without disturbing content; generation
(stable IDs verbatim on cells, groups as containers, provenance attributes on
the mxfile root); the Structurizr invariant (stored layout wins on
regeneration; the source stays authoritative for labels); reading the draw.io
compressed diagram format and the official PNG tEXt/zTXt embed (fixtures built
in-test, chunk-level); provenance verdicts (FAST_FORWARD/DIVERGED/UID
mismatch); the ID-first classifier routing relabels/regroupings/added and
removed nodes and edges to semantic, geometry to layout, style strings to the
template bucket; apply_layout writing the geometry channel; and the render.py
CLI end to end.
"""

from __future__ import annotations

import base64
import json
import struct
import subprocess
import sys
import urllib.parse
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "roundtrip"))

import drawio  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"

GRAPH = """title: Payment platform
concepts:
  - {id: gateway, label: API Gateway, group: edge}
  - {id: auth, label: Auth Service, group: core}
  - {id: ledger, label: Ledger, group: core, kind: store}
relations:
  - {from: gateway, to: auth, label: validates via}
  - {from: auth, to: ledger, label: writes}
"""


def _graph(tmp_path: Path) -> Path:
    p = tmp_path / "graph.yaml"
    p.write_text(GRAPH, encoding="utf-8")
    return p


def _generate(tmp_path: Path, layout: Path | None = None) -> tuple[Path, Path]:
    src = _graph(tmp_path)
    out = tmp_path / "graph.drawio"
    out.write_text(drawio.generate(src, layout), encoding="utf-8")
    return src, out


# ---- validation ----

def test_missing_id_fails_closed(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("concepts:\n  - {label: No Id}\n", encoding="utf-8")
    with pytest.raises(drawio.DrawioError, match="stable 'id'"):
        drawio.load_graph(p)


def test_duplicate_id_fails_closed(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("concepts:\n  - {id: x, label: A}\n  - {id: x, label: B}\n", encoding="utf-8")
    with pytest.raises(drawio.DrawioError, match="duplicate"):
        drawio.load_graph(p)


def test_dangling_relation_fails_closed(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("concepts:\n  - {id: a, label: A}\nrelations:\n  - {from: a, to: ghost}\n",
                 encoding="utf-8")
    with pytest.raises(drawio.DrawioError, match="unknown concept"):
        drawio.load_graph(p)


def test_uid_appended_to_yaml_without_disturbing_content(tmp_path):
    src = _graph(tmp_path)
    before = src.read_text(encoding="utf-8")
    uid = drawio.get_or_create_graph_uid(src)
    after = src.read_text(encoding="utf-8")
    assert after.startswith(before)
    assert f"renderfact_uid: {uid}" in after
    assert drawio.get_or_create_graph_uid(src) == uid  # idempotent


# ---- generation ----

def test_generation_carries_stable_ids_groups_and_provenance(tmp_path):
    src, out = _generate(tmp_path)
    root = ET.parse(str(out)).getroot()
    assert root.tag == "mxfile"
    assert root.get("renderfact_uid")
    assert root.get("renderfact_source_version")
    ids = {c.get("id") for c in root.iter("mxCell")}
    assert {"gateway", "auth", "ledger", "group:edge", "group:core",
            "rel:gateway->auth", "rel:auth->ledger"} <= ids
    auth = next(c for c in root.iter("mxCell") if c.get("id") == "auth")
    assert auth.get("parent") == "group:core"
    ledger = next(c for c in root.iter("mxCell") if c.get("id") == "ledger")
    assert "cylinder" in ledger.get("style")  # kind: store


def test_stored_layout_wins_and_source_stays_authoritative(tmp_path):
    layout = tmp_path / "layout.yaml"
    layout.write_text(yaml.safe_dump({"auth": {"x": 400, "y": 77, "w": 200, "h": 80}}),
                      encoding="utf-8")
    src, out = _generate(tmp_path, layout)
    root = ET.parse(str(out)).getroot()
    auth = next(c for c in root.iter("mxCell") if c.get("id") == "auth")
    geo = auth.find("mxGeometry")
    assert (geo.get("x"), geo.get("y")) == ("400", "77")
    assert auth.get("value") == "Auth Service"  # labels come from the source, always


# ---- reading: compressed diagram + PNG embed ----

def _compress_mxfile(xml_model: str, attrs: dict) -> str:
    payload = base64.b64encode(
        zlib.compress(urllib.parse.quote(xml_model, safe="").encode(), 9)[2:-4]
    ).decode()
    a = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f'<mxfile {a}><diagram id="d1" name="x">{payload}</diagram></mxfile>'


def test_reads_compressed_diagram_content(tmp_path):
    model_xml = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>'
    p = tmp_path / "c.drawio"
    p.write_text(_compress_mxfile(model_xml, {"renderfact_uid": "u1"}), encoding="utf-8")
    attrs, model = drawio.read_model(p)
    assert attrs["renderfact_uid"] == "u1"
    assert model.tag == "mxGraphModel"


def _png_with_mxfile(tmp_path: Path, xml: str) -> Path:
    def chunk(ctype: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + ctype + data
                + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))

    encoded = urllib.parse.quote(xml, safe="").encode()
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00")
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"tEXt", b"mxfile\x00" + encoded)
           + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    p = tmp_path / "diagram.png"
    p.write_bytes(png)
    return p


def test_reads_official_png_embed(tmp_path):
    xml = ('<mxfile renderfact_uid="u2"><diagram id="d1" name="x">'
           '<mxGraphModel><root><mxCell id="0"/></root></mxGraphModel>'
           '</diagram></mxfile>')
    p = _png_with_mxfile(tmp_path, xml)
    attrs, model = drawio.read_model(p)
    assert attrs["renderfact_uid"] == "u2"
    assert model.tag == "mxGraphModel"


def test_png_without_embed_fails_closed(tmp_path):
    p = tmp_path / "plain.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
                  + struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0) + b"\x00\x00\x00\x00")
    with pytest.raises(drawio.DrawioError, match="mxfile"):
        drawio._png_embedded_xml(p)


# ---- verdicts ----

def test_verdicts_and_uid_mismatch(tmp_path):
    src, out = _generate(tmp_path)
    attrs, _model = drawio.read_model(out)
    assert drawio.check_provenance(attrs, src) == "FAST_FORWARD"

    src.write_text(src.read_text(encoding="utf-8").replace("Ledger", "General Ledger"),
                   encoding="utf-8")
    assert drawio.check_provenance(attrs, src) == "DIVERGED"

    other = tmp_path / "other.yaml"
    other.write_text("concepts:\n  - {id: z, label: Z}\nrenderfact_uid: someone-else\n",
                     encoding="utf-8")
    with pytest.raises(drawio.DrawioError, match="UID mismatch"):
        drawio.check_provenance(attrs, other)


# ---- classification ----

def _edit_and_classify(tmp_path, mutate):
    src, out = _generate(tmp_path, tmp_path / "layout.yaml")
    tree = ET.parse(str(out))
    mutate(tree.getroot())
    tree.write(str(out), encoding="unicode")
    graph = drawio.load_graph(src)
    _attrs, model = drawio.read_model(out)
    return drawio.classify(graph, model, drawio.load_layout(tmp_path / "layout.yaml"))


def test_relabel_and_added_node_route_to_semantic(tmp_path):
    def mutate(root):
        for c in root.iter("mxCell"):
            if c.get("id") == "auth":
                c.set("value", "Identity Service")
        holder = root.find(".//root")
        new = ET.SubElement(holder, "mxCell", {"id": "audit", "value": "Audit", "vertex": "1",
                                               "parent": "1", "style": "rounded=1;"})
        ET.SubElement(new, "mxGeometry", {"x": "1", "y": "2", "width": "3", "height": "4",
                                          "as": "geometry"})

    buckets = _edit_and_classify(tmp_path, mutate)
    kinds = {(s["kind"], s["id"]) for s in buckets["semantic"]}
    assert ("relabel-node", "auth") in kinds
    assert ("add-node", "audit") in kinds


def test_removed_node_and_edge_route_to_semantic(tmp_path):
    def mutate(root):
        holder = root.find(".//root")
        for c in list(holder):
            if c.get("id") in ("ledger", "rel:auth->ledger"):
                holder.remove(c)

    buckets = _edit_and_classify(tmp_path, mutate)
    kinds = {(s["kind"], s["id"]) for s in buckets["semantic"]}
    assert ("remove-node", "ledger") in kinds
    assert ("remove-edge", "rel:auth->ledger") in kinds


def test_geometry_routes_to_layout_and_style_to_template(tmp_path):
    def mutate(root):
        for c in root.iter("mxCell"):
            if c.get("id") == "gateway":
                c.find("mxGeometry").set("x", "999")
            if c.get("id") == "ledger":
                c.set("style", "shape=cylinder3;fillColor=#ff0000;")

    buckets = _edit_and_classify(tmp_path, mutate)
    assert buckets["layout"]["gateway"]["x"] == 999.0
    assert not any(s["id"] == "gateway" for s in buckets["semantic"])
    assert any(s["id"] == "ledger" for s in buckets["style"])


def test_apply_layout_writes_the_geometry_channel(tmp_path):
    layout = tmp_path / "layout.yaml"
    n = drawio.apply_layout(layout, {"auth": {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}})
    assert n == 1
    assert yaml.safe_load(layout.read_text(encoding="utf-8"))["auth"]["x"] == 1.0


# ---- CLI end to end ----

def test_cli_generate_edit_reingest_json(tmp_path):
    src = _graph(tmp_path)
    out = tmp_path / "g.drawio"
    gen = subprocess.run(
        [sys.executable, str(RENDER_PY), "drawio", "generate", str(src), "-o", str(out),
         "--layout", str(tmp_path / "layout.yaml")],
        capture_output=True, text=True, timeout=120,
    )
    assert gen.returncode == 0, gen.stderr

    tree = ET.parse(str(out))
    for c in tree.getroot().iter("mxCell"):
        if c.get("id") == "auth":
            c.set("value", "Identity Service")
            c.find("mxGeometry").set("x", "421")
    tree.write(str(out), encoding="unicode")

    rei = subprocess.run(
        [sys.executable, str(RENDER_PY), "drawio", "reingest", str(out),
         "--source", str(src), "--layout", str(tmp_path / "layout.yaml"),
         "--apply-layout", "--json"],
        capture_output=True, text=True, timeout=120,
    )
    assert rei.returncode == 0, rei.stderr
    payload = json.loads(rei.stdout)
    assert payload["verdict"] == "FAST_FORWARD"
    assert any(s["kind"] == "relabel-node" and s["id"] == "auth" for s in payload["semantic"])
    assert payload["layout"]["auth"]["x"] == 421.0
    assert payload["layout_applied"] >= 1
    stored = yaml.safe_load((tmp_path / "layout.yaml").read_text(encoding="utf-8"))
    assert stored["auth"]["x"] == 421.0
