#!/usr/bin/env python3
"""drawio.py: the editable-diagram round-trip, drawio adapter (C8, chunk C8.1).

The loop (D11's doctrine applied to diagrams; confirmed open ground, see
docs/prior-art-diagram-roundtrip.md): GENERATE a .drawio from a canonical
concept-graph source -> a human hand-edits it in the draw.io app -> RE-INGEST
the edited file (or a .png carrying draw.io's official full-source zTXt embed),
verify provenance, diff against the source with ID-FIRST matching, and route:

  layout   (mxGeometry per known ID)          -> the separate layout file
            (Structurizr's doctrine: manual layout lives OUTSIDE the source,
            merged back on regeneration, surviving as long as IDs are stable)
  style    (style-string changes on known IDs) -> reported for the template layer
  semantic (added/removed nodes and edges, relabels, regrouping)
                                               -> reported for the canonical source
            (report-only, like `render reingest`; auto-applying model changes is
            three-way-merge territory)

Canonical source: a YAML or JSON concept graph, the same shape the projection
of architecture into diagrams has always used:

    title: Payment platform
    concepts:
      - {id: gateway, label: API Gateway, group: edge}
      - {id: auth,    label: Auth Service, group: core}
    relations:
      - {from: gateway, to: auth, label: validates via}

IDs are the round-trip anchor: every generated mxCell carries its concept's id
verbatim, so hand-edits stay attributable after any amount of visual rework.

drawio is the LEAD adapter for the OSS/freeware ecosystem; .vsdx is the
separate Microsoft-ecosystem adapter (operator decision 2026-07-04), and never
a bridge between the two (draw.io removed VSDX export in v26.1.0). Rendering
to PNG/SVG deliberately stays out of scope: generate + re-ingest are pure XML
and the operator's own draw.io app is the visual layer.

Usage:
    render drawio generate <graph.yaml|json> [-o out.drawio] [--layout layout.yaml]
    render drawio reingest <edited.drawio|.png> --source <graph.yaml|json>
                  [--layout layout.yaml] [--apply-layout] [--json]
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import struct
import sys
import urllib.parse
import uuid
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml


class DrawioError(RuntimeError):
    """A user-facing round-trip mistake: clean message, not a traceback."""


# ------------------------------------------------------------ source graph --

def load_graph(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) if path.suffix.lower() in (".yaml", ".yml") else json.loads(text)
    if not isinstance(data, dict) or "concepts" not in data:
        raise DrawioError(f"{path}: a concept graph needs a top-level 'concepts:' list")
    ids = [c.get("id") for c in data.get("concepts", [])]
    if any(not i for i in ids):
        raise DrawioError(f"{path}: every concept needs a stable 'id' (the round-trip anchor)")
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise DrawioError(f"{path}: duplicate concept id(s): {sorted(dupes)}")
    known = set(ids)
    for r in data.get("relations", []):
        for end in ("from", "to"):
            if r.get(end) not in known:
                raise DrawioError(
                    f"{path}: relation {r.get('from')} -> {r.get('to')} references "
                    f"unknown concept '{r.get(end)}'"
                )
    return data


def get_or_create_graph_uid(path: Path) -> str:
    """A stable renderfact_uid on the graph source itself. YAML sources get one
    appended as a top-level key (content otherwise untouched); JSON sources are
    round-tripped through json.dumps once (a one-time reformat, documented)."""
    graph = load_graph(path)
    existing = graph.get("renderfact_uid")
    if existing:
        return str(existing)
    new_uid = str(uuid.uuid4())
    if path.suffix.lower() in (".yaml", ".yml"):
        text = path.read_text(encoding="utf-8")
        if not text.endswith("\n"):
            text += "\n"
        path.write_text(text + f"renderfact_uid: {new_uid}\n", encoding="utf-8", newline="\n")
    else:
        graph["renderfact_uid"] = new_uid
        path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8", newline="\n")
    return new_uid


def _content_version(path: Path) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import source_uid

    return source_uid.content_version(path)


def _provenance_attrs(path: Path) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import provenance as prov_mod

    return {
        "renderfact_uid": get_or_create_graph_uid(path),
        "renderfact_source_version": _content_version(path),
        "renderfact_rendered_at": prov_mod.now_iso(),
        "renderfact_tool_version": prov_mod.tool_version(),
        "renderfact_source_commit": prov_mod.source_commit(path) or "",
    }


# -------------------------------------------------------------- generation --

_KIND_STYLE = {
    None: "rounded=1;whiteSpace=wrap;html=1;",
    "store": "shape=cylinder3;whiteSpace=wrap;html=1;",
    "actor": "shape=umlActor;verticalLabelPosition=bottom;html=1;",
    "boundary": "rounded=0;dashed=1;whiteSpace=wrap;html=1;",
}
_GROUP_STYLE = "rounded=1;whiteSpace=wrap;html=1;verticalAlign=top;fillColor=none;container=1;"

NODE_W, NODE_H, GRID_X, GRID_Y, PER_ROW = 160, 60, 200, 110, 4


def load_layout(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def generate(graph_path: Path, layout_path: Path | None = None) -> str:
    graph = load_graph(graph_path)
    layout = load_layout(layout_path)
    attrs = _provenance_attrs(graph_path)
    # uid insertion may have changed the file: version must reflect what is on disk NOW
    attrs["renderfact_source_version"] = _content_version(graph_path)

    mxfile = ET.Element("mxfile", {"host": "renderfact", **{k: str(v) for k, v in attrs.items()}})
    diagram = ET.SubElement(mxfile, "diagram", {"id": "d1", "name": graph.get("title", "diagram")})
    model = ET.SubElement(diagram, "mxGraphModel", {"dx": "800", "dy": "600", "grid": "1"})
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})

    groups = []
    seen = set()
    for c in graph.get("concepts", []):
        g = c.get("group")
        if g and g not in seen:
            groups.append(g)
            seen.add(g)
    group_cell_id = {g: f"group:{g}" for g in groups}
    for gi, g in enumerate(groups):
        geo = layout.get(group_cell_id[g], {})
        cell = ET.SubElement(root, "mxCell", {
            "id": group_cell_id[g], "value": g, "style": _GROUP_STYLE,
            "vertex": "1", "parent": "1",
        })
        ET.SubElement(cell, "mxGeometry", {
            "x": str(geo.get("x", 40 + gi * (PER_ROW * GRID_X + 80))),
            "y": str(geo.get("y", 40)),
            "width": str(geo.get("w", PER_ROW * GRID_X + 40)),
            "height": str(geo.get("h", 400)), "as": "geometry",
        })

    placed: dict[str, int] = {}
    for c in graph.get("concepts", []):
        cid = c["id"]
        parent = group_cell_id.get(c.get("group"), "1")
        geo = layout.get(cid, {})
        n = placed.get(parent, 0)
        placed[parent] = n + 1
        cell = ET.SubElement(root, "mxCell", {
            "id": cid, "value": c.get("label", cid),
            "style": _KIND_STYLE.get(c.get("kind"), _KIND_STYLE[None]),
            "vertex": "1", "parent": parent,
        })
        # stored positions win; new nodes fall back to a plain grid (a real
        # auto-layout engine is deliberately out of scope for the round-trip)
        ET.SubElement(cell, "mxGeometry", {
            "x": str(geo.get("x", 30 + (n % PER_ROW) * GRID_X)),
            "y": str(geo.get("y", 40 + (n // PER_ROW) * GRID_Y)),
            "width": str(geo.get("w", NODE_W)),
            "height": str(geo.get("h", NODE_H)), "as": "geometry",
        })

    edge_count: dict[str, int] = {}
    for r in graph.get("relations", []):
        base = f"rel:{r['from']}->{r['to']}"
        n = edge_count.get(base, 0)
        edge_count[base] = n + 1
        eid = base if n == 0 else f"{base}:{n}"
        cell = ET.SubElement(root, "mxCell", {
            "id": eid, "value": r.get("label", ""), "style": "edgeStyle=orthogonalEdgeStyle;html=1;",
            "edge": "1", "parent": "1", "source": r["from"], "target": r["to"],
        })
        ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})

    ET.indent(mxfile)
    return ET.tostring(mxfile, encoding="unicode", xml_declaration=False)


# ------------------------------------------------------------------ reading --

def _png_embedded_xml(path: Path) -> str:
    """draw.io's official lossless embed: the full mxfile XML, URL-encoded, in a
    PNG tEXt/zTXt chunk keyed 'mxfile'. Plain chunk parsing, no library."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise DrawioError(f"{path} is not a PNG")
    pos = 8
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8: pos + 8 + length]
        if ctype in (b"tEXt", b"zTXt"):
            key, _, rest = chunk.partition(b"\x00")
            if key == b"mxfile":
                if ctype == b"zTXt":
                    rest = zlib.decompress(rest[1:])  # skip compression-method byte
                return urllib.parse.unquote(rest.decode("utf-8", "replace"))
        pos += 8 + length + 4
    raise DrawioError(f"{path}: no draw.io 'mxfile' text chunk found (was the image "
                      f"exported without 'include a copy of my diagram', or resampled?)")


def _inflate_diagram(diagram: ET.Element) -> ET.Element:
    """A <diagram> may hold its mxGraphModel as base64(raw-deflate(urlencode(xml)))
    (the draw.io compressed format) instead of child XML. Normalize to XML."""
    model = diagram.find("mxGraphModel")
    if model is not None:
        return model
    payload = (diagram.text or "").strip()
    if not payload:
        raise DrawioError("diagram element carries neither child XML nor compressed content")
    raw = zlib.decompress(base64.b64decode(payload), -15)
    return ET.fromstring(urllib.parse.unquote(raw.decode("utf-8")))


def read_model(path: Path) -> tuple[dict, ET.Element]:
    """Return (mxfile root attributes, mxGraphModel element) from a .drawio file
    or a .png carrying the official embed."""
    if path.suffix.lower() == ".png":
        xml = _png_embedded_xml(path)
    else:
        xml = path.read_text(encoding="utf-8")
    mxfile = ET.fromstring(xml)
    if mxfile.tag != "mxfile":
        raise DrawioError(f"{path}: root element is <{mxfile.tag}>, expected <mxfile>")
    diagram = mxfile.find("diagram")
    if diagram is None:
        raise DrawioError(f"{path}: no <diagram> element")
    return dict(mxfile.attrib), _inflate_diagram(diagram)


def _cells(model: ET.Element) -> dict[str, ET.Element]:
    return {c.get("id"): c for c in model.iter("mxCell") if c.get("id") not in ("0", "1")}


# -------------------------------------------------------- verdict + diffing --

def check_provenance(file_attrs: dict, source_path: Path) -> str:
    uid = file_attrs.get("renderfact_uid")
    if not uid:
        raise DrawioError("the edited file carries no renderfact provenance attributes: "
                          "it was not generated by 'render drawio generate'")
    declared = load_graph(source_path).get("renderfact_uid")
    if not declared:
        raise DrawioError(f"{source_path} declares no renderfact_uid: not the canonical "
                          f"source this diagram was generated from")
    if str(declared) != uid:
        raise DrawioError(f"UID mismatch: diagram from {uid}, source is {declared}: "
                          f"wrong file/source pairing")
    current = _content_version(source_path)
    return "FAST_FORWARD" if current == file_attrs.get("renderfact_source_version") else "DIVERGED"


def classify(graph: dict, model: ET.Element, layout: dict) -> dict:
    """ID-first classification of the edited model against the canonical graph:
    semantic (nodes/edges/labels/regrouping) vs layout (geometry) vs style."""
    cells = _cells(model)
    group_ids = {f"group:{c.get('group')}" for c in graph["concepts"] if c.get("group")}
    known_nodes = {c["id"]: c for c in graph["concepts"]}
    known_edges = {}
    counts: dict[str, int] = {}
    for r in graph.get("relations", []):
        base = f"rel:{r['from']}->{r['to']}"
        n = counts.get(base, 0)
        counts[base] = n + 1
        known_edges[base if n == 0 else f"{base}:{n}"] = r

    semantic, style, layout_changes = [], [], {}
    seen_ids = set()
    for cid, cell in cells.items():
        seen_ids.add(cid)
        if cid in known_nodes:
            c = known_nodes[cid]
            if (cell.get("value") or "") != c.get("label", cid):
                semantic.append({"kind": "relabel-node", "id": cid,
                                 "old": c.get("label", cid), "new": cell.get("value") or ""})
            expected_parent = f"group:{c['group']}" if c.get("group") else "1"
            if (cell.get("parent") or "1") != expected_parent:
                semantic.append({"kind": "regroup-node", "id": cid,
                                 "old": expected_parent, "new": cell.get("parent") or "1"})
            expected_style = _KIND_STYLE.get(c.get("kind"), _KIND_STYLE[None])
            if (cell.get("style") or "") != expected_style:
                style.append({"id": cid, "style": cell.get("style") or ""})
            geo = cell.find("mxGeometry")
            if geo is not None:
                stored = layout.get(cid, {})
                new_geo = {"x": float(geo.get("x", 0)), "y": float(geo.get("y", 0)),
                           "w": float(geo.get("width", NODE_W)), "h": float(geo.get("height", NODE_H))}
                if any(float(stored.get(k, -1)) != v for k, v in new_geo.items()):
                    layout_changes[cid] = new_geo
        elif cid in known_edges:
            r = known_edges[cid]
            if (cell.get("value") or "") != r.get("label", ""):
                semantic.append({"kind": "relabel-edge", "id": cid,
                                 "old": r.get("label", ""), "new": cell.get("value") or ""})
            if cell.get("source") != r["from"] or cell.get("target") != r["to"]:
                semantic.append({"kind": "rewire-edge", "id": cid,
                                 "old": f"{r['from']}->{r['to']}",
                                 "new": f"{cell.get('source')}->{cell.get('target')}"})
        elif cid in group_ids:
            geo = cell.find("mxGeometry")
            if geo is not None:
                layout_changes[cid] = {"x": float(geo.get("x", 0)), "y": float(geo.get("y", 0)),
                                       "w": float(geo.get("width", 0)), "h": float(geo.get("height", 0))}
        else:
            if cell.get("edge") == "1":
                semantic.append({"kind": "add-edge", "id": cid,
                                 "new": f"{cell.get('source')}->{cell.get('target')} "
                                        f"'{cell.get('value') or ''}'"})
            else:
                semantic.append({"kind": "add-node", "id": cid,
                                 "new": cell.get("value") or cid})
    for cid in known_nodes:
        if cid not in seen_ids:
            semantic.append({"kind": "remove-node", "id": cid, "old": known_nodes[cid].get("label", cid)})
    for eid, r in known_edges.items():
        if eid not in seen_ids:
            semantic.append({"kind": "remove-edge", "id": eid,
                             "old": f"{r['from']}->{r['to']} '{r.get('label', '')}'"})
    return {"semantic": semantic, "style": style, "layout": layout_changes}


def apply_layout(layout_path: Path, layout_changes: dict) -> int:
    layout = load_layout(layout_path)
    layout.update(layout_changes)
    layout_path.write_text(
        yaml.safe_dump(layout, sort_keys=True, default_flow_style=False),
        encoding="utf-8", newline="\n",
    )
    return len(layout_changes)


# --------------------------------------------------------------------- CLI --

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="render drawio",
        description="Editable-diagram round-trip, drawio adapter (C8): generate from a "
                    "concept graph; re-ingest hand-edits with ID-first classification.",
    )
    sub = ap.add_subparsers(dest="action", required=True)

    gen = sub.add_parser("generate", help="concept graph -> .drawio (stable IDs, provenance attrs)")
    gen.add_argument("graph", type=Path)
    gen.add_argument("-o", "--output", type=Path, default=None)
    gen.add_argument("--layout", type=Path, default=None,
                     help="ID-keyed layout yaml; stored positions win, new nodes get a grid")

    rei = sub.add_parser("reingest", help="edited .drawio (or .png with the official embed) -> "
                                          "provenance verdict + classified diff report")
    rei.add_argument("edited", type=Path)
    rei.add_argument("--source", type=Path, required=True)
    rei.add_argument("--layout", type=Path, default=None)
    rei.add_argument("--apply-layout", action="store_true",
                     help="write geometry changes back to the layout file (the mechanically "
                          "safe channel); semantic changes are always report-only")
    rei.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        if args.action == "generate":
            if not args.graph.exists():
                raise DrawioError(f"graph source not found: {args.graph}")
            xml = generate(args.graph, args.layout)
            out = args.output or args.graph.with_suffix(".drawio")
            out.write_text(xml, encoding="utf-8", newline="\n")
            print(f"wrote {out} (open in the draw.io app to hand-edit; "
                  f"IDs are stable, re-ingest with 'render drawio reingest')")
            return 0

        # reingest
        if not args.edited.exists():
            raise DrawioError(f"edited file not found: {args.edited}")
        if not args.source.exists():
            raise DrawioError(f"source not found: {args.source}")
        attrs, model = read_model(args.edited)
        verdict = check_provenance(attrs, args.source)
        graph = load_graph(args.source)
        layout = load_layout(args.layout)
        buckets = classify(graph, model, layout)

        applied = None
        if args.apply_layout:
            if args.layout is None:
                raise DrawioError("--apply-layout needs --layout <file> to write to")
            applied = apply_layout(args.layout, buckets["layout"])

        if args.json:
            print(json.dumps({"verdict": verdict, **buckets, "layout_applied": applied}, indent=2))
            return 0

        print(f"# drawio re-ingestion: {args.edited.name}")
        print(f"verdict: {verdict}" + ("" if verdict == "FAST_FORWARD" else
              " (the graph source evolved since generation: reconcile semantic items by hand)"))
        print(f"\nsemantic ({len(buckets['semantic'])}) -> route to the canonical source:")
        for s in buckets["semantic"] or []:
            old = f" old='{s.get('old', '')}'" if s.get("old") else ""
            print(f"  - {s['kind']} {s['id']}:{old} new='{s.get('new', '')}'")
        if not buckets["semantic"]:
            print("  (none)")
        print(f"\nstyle ({len(buckets['style'])}) -> template layer:")
        for s in buckets["style"] or []:
            print(f"  - {s['id']}: {s['style'][:100]}")
        if not buckets["style"]:
            print("  (none)")
        print(f"\nlayout ({len(buckets['layout'])}) -> layout file"
              + (f": APPLIED {applied}" if applied is not None else " (pass --apply-layout to write)"))
        for cid, geo in buckets["layout"].items():
            print(f"  - {cid}: x={geo['x']} y={geo['y']} w={geo['w']} h={geo['h']}")
        return 0
    except DrawioError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
