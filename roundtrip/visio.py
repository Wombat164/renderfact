#!/usr/bin/env python3
"""visio.py: the editable-diagram round-trip, vsdx adapter (C8, chunk C8.2).

The Microsoft-ecosystem sibling of roundtrip/drawio.py (the lead adapter) --
operator decision 2026-07-04: drawio leads for the OSS/freeware ecosystem,
.vsdx is the separate MS-Visio adapter, and NEVER a bridge between the two
(draw.io removed VSDX export in v26.1.0). Same loop, same doctrine:

  GENERATE a .vsdx from the canonical concept graph -> a human hand-edits it
  in Microsoft Visio -> RE-INGEST the edited file, verify provenance, diff
  against the source with ID-FIRST matching, and route:

    layout   (PinX/PinY/size per known ID)  -> the separate layout file
    semantic (added/removed shapes and connectors, relabels, rewires)
                                            -> reported for the canonical source

The concept-graph contract, uid bootstrap and layout-file doctrine live in
drawio.py (the lead adapter owns the shared source contract); this module
imports them rather than duplicating. The layout file is PER-ADAPTER: Visio
coordinates are page inches with a bottom-left origin (PinX/PinY are shape
CENTERS), so a drawio layout file and a vsdx layout file for the same graph
are different files by design (suggested suffix: .vsdx-layout.yaml).

Format mechanics ([adopt the `vsdx` Python lib], per
docs/prior-art-diagram-roundtrip.md): generation copies prototype shapes out
of the library's own bundled media.vsdx (BSD-3-Clause, installed WITH the
dependency: renderfact redistributes no Visio assets, honouring the stencil
licence caution) and wires connectors via vsdx.Connect.create, which manages
the Dynamic-connector master registration. The concept id anchor is the
shape's NameU attribute ("rf.<id>"), a standard Visio shape attribute that
survives hand-editing. Provenance rides docProps/core.xml dc:identifier via
roundtrip/provenance.py's generic OPC adapter (same mechanism as
DOCX/XLSX/PPTX; .vsdx is the same OPC package family).

v1 limitations, deliberate: concept `group` is not projected into Visio
containers (flat page; regrouping is therefore not detected either), and
style changes are not classified (the template layer for vsdx does not exist
yet) -- both are recorded in the C8 roadmap entry.

The `vsdx` library is an OPTIONAL dependency (pip install renderfact[vsdx]):
importing this module without it gives a clean actionable error, mirroring
the markitdown containment in reingest.py.

Usage:
    render vsdx generate <graph.yaml|json> [-o out.vsdx] [--layout layout.yaml]
    render vsdx reingest <edited.vsdx> --source <graph.yaml|json>
                [--layout layout.yaml] [--apply-layout] [--json]
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drawio  # the lead adapter owns the shared concept-graph contract
import provenance as prov_mod


class VsdxError(RuntimeError):
    """A user-facing round-trip mistake: clean message, not a traceback."""


def _require_vsdx():
    try:
        import vsdx  # noqa: F401

        return vsdx
    except ImportError:
        raise VsdxError(
            "the 'vsdx' library is not installed -- the Visio adapter needs it: "
            "pip install renderfact[vsdx]  (or: pip install vsdx)"
        ) from None


# Visio page inches, bottom-left origin, PinX/PinY are shape centers.
NODE_W, NODE_H = 1.6, 0.6
GRID_X, GRID_Y, PER_ROW = 2.1, 1.2, 4
ORIGIN_X, ORIGIN_Y = 1.4, 9.6
_ANCHOR = "rf."
_GEO_TOLERANCE = 0.01  # Visio serializes long floats; sub-1/100-inch is noise


def _anchor_of(shape) -> str | None:
    nameu = shape.xml.attrib.get("NameU", "")
    return nameu[len(_ANCHOR):] if nameu.startswith(_ANCHOR) else None


def _grid_pos(n: int) -> tuple[float, float]:
    return (ORIGIN_X + (n % PER_ROW) * GRID_X,
            ORIGIN_Y - (n // PER_ROW) * GRID_Y)


def _edge_ids(graph: dict) -> dict[str, dict]:
    """rel:<from>-><to>[:n] keying, identical to the drawio adapter so a graph
    has ONE edge-identity scheme across both ecosystems."""
    known, counts = {}, {}
    for r in graph.get("relations", []):
        base = f"rel:{r['from']}->{r['to']}"
        n = counts.get(base, 0)
        counts[base] = n + 1
        known[base if n == 0 else f"{base}:{n}"] = r
    return known


def _build_provenance(graph_path: Path) -> prov_mod.Provenance:
    return prov_mod.Provenance(
        source_uid=drawio.get_or_create_graph_uid(graph_path),
        source_version=drawio._content_version(graph_path),
        rendered_at=prov_mod.now_iso(),
        tool_version=prov_mod.tool_version(),
        source_commit=prov_mod.source_commit(graph_path) or None,
    )


# -------------------------------------------------------------- generation --

def generate(graph_path: Path, out_path: Path, layout_path: Path | None = None) -> None:
    vsdx = _require_vsdx()
    from vsdx import Connect, Media, VisioFile

    graph = drawio.load_graph(graph_path)
    layout = drawio.load_layout(layout_path)
    prov = _build_provenance(graph_path)

    # The library's own media.vsdx is the canvas: prototypes present, the
    # Dynamic-connector master already registered (Connect.create's clean path).
    media_src = Path(vsdx.__file__).resolve().parent / "media" / "media.vsdx"
    shutil.copy(str(media_src), str(out_path))

    with VisioFile(str(out_path)) as vf:
        page = vf.pages[0]
        page.name = graph.get("title", "diagram")
        media = Media()
        proto = {
            None: media.rectangle,
            "store": media.circle,
            "actor": media.circle,
        }

        prototype_ids = {s.ID for s in page.child_shapes}

        node_shape: dict[str, object] = {}
        for n, c in enumerate(graph.get("concepts", [])):
            cid = c["id"]
            shape = proto.get(c.get("kind"), media.rectangle).copy(page)
            shape.text = c.get("label", cid)
            shape.xml.set("NameU", _ANCHOR + cid)
            geo = layout.get(cid, {})
            gx, gy = _grid_pos(n)
            shape.x = float(geo.get("x", gx))
            shape.y = float(geo.get("y", gy))
            if "w" in geo:
                shape.width = float(geo["w"])
            if "h" in geo:
                shape.height = float(geo["h"])
            node_shape[cid] = shape

        for eid, r in _edge_ids(graph).items():
            # the library prints internal debug lines from Connect.create;
            # a public CLI must not leak them
            with contextlib.redirect_stdout(io.StringIO()):
                conn = Connect.create(page=page,
                                      from_shape=node_shape[r["from"]],
                                      to_shape=node_shape[r["to"]])
            conn.text = r.get("label", "")
            conn.xml.set("NameU", _ANCHOR + eid)

        # Drop the media prototypes (and their example connects) from the output.
        for shape in list(page.child_shapes):
            if shape.ID in prototype_ids:
                shape.remove()
        connects_el = page.xml.find(f"{vsdx.namespace}Connects")
        if connects_el is not None:
            for cel in list(connects_el):
                if (cel.get("FromSheet") in prototype_ids
                        or cel.get("ToSheet") in prototype_ids):
                    connects_el.remove(cel)

        # the library requires an explicit filename (save_vsdx() with no
        # argument crashes on None inside the library)
        vf.save_vsdx(str(out_path))

    prov_mod.embed(out_path, prov)


# ---------------------------------------------------------------- reingest --

def check_provenance(edited_path: Path, source_path: Path) -> str:
    prov = prov_mod.extract(edited_path)
    if prov is None:
        raise VsdxError("the edited file carries no renderfact provenance: "
                        "it was not generated by 'render vsdx generate'")
    declared = drawio.load_graph(source_path).get("renderfact_uid")
    if not declared:
        raise VsdxError(f"{source_path} declares no renderfact_uid: not the canonical "
                        f"source this diagram was generated from")
    if str(declared) != prov.source_uid:
        raise VsdxError(f"UID mismatch: diagram from {prov.source_uid}, source is "
                        f"{declared}: wrong file/source pairing")
    current = drawio._content_version(source_path)
    return "FAST_FORWARD" if current == prov.source_version else "DIVERGED"


def _read_page(path: Path):
    _require_vsdx()
    from vsdx import VisioFile

    vf = VisioFile(str(path))
    if not vf.pages:
        raise VsdxError(f"{path}: no pages")
    return vf, vf.pages[0]


def classify(graph: dict, page, layout: dict) -> dict:
    """ID-first classification of the edited Visio page against the canonical
    graph: semantic (shapes/connectors/labels/rewires) vs layout (geometry).
    Mirrors the drawio adapter's buckets; style is empty by design (v1)."""
    known_nodes = {c["id"]: c for c in graph["concepts"]}
    known_edges = _edge_ids(graph)

    # connector participation: Connect rows have from_id=connector sheet id
    endpoint: dict[str, dict[str, str]] = {}
    for con in page.get_connects():
        endpoint.setdefault(con.from_id, {})[con.from_rel] = con.to_id

    sheet_anchor = {s.ID: _anchor_of(s) for s in page.child_shapes}

    semantic, layout_changes = [], {}
    seen = set()
    for shape in page.child_shapes:
        anchor = sheet_anchor.get(shape.ID)
        is_connector = shape.ID in endpoint
        text = (shape.text or "").strip()

        if anchor and anchor in known_nodes:
            seen.add(anchor)
            c = known_nodes[anchor]
            if text != c.get("label", anchor):
                semantic.append({"kind": "relabel-node", "id": anchor,
                                 "old": c.get("label", anchor), "new": text})
            stored = layout.get(anchor, {})
            new_geo = {"x": round(float(shape.x), 3), "y": round(float(shape.y), 3),
                       "w": round(float(shape.width or NODE_W), 3),
                       "h": round(float(shape.height or NODE_H), 3)}
            if any(abs(float(stored.get(k, -9999)) - v) > _GEO_TOLERANCE
                   for k, v in new_geo.items()):
                layout_changes[anchor] = new_geo

        elif anchor and anchor in known_edges:
            seen.add(anchor)
            r = known_edges[anchor]
            if text != r.get("label", ""):
                semantic.append({"kind": "relabel-edge", "id": anchor,
                                 "old": r.get("label", ""), "new": text})
            ends = endpoint.get(shape.ID, {})
            got_from = sheet_anchor.get(ends.get("BeginX")) or ends.get("BeginX")
            got_to = sheet_anchor.get(ends.get("EndX")) or ends.get("EndX")
            if got_from != r["from"] or got_to != r["to"]:
                semantic.append({"kind": "rewire-edge", "id": anchor,
                                 "old": f"{r['from']}->{r['to']}",
                                 "new": f"{got_from}->{got_to}"})

        elif is_connector:
            ends = endpoint.get(shape.ID, {})
            got_from = sheet_anchor.get(ends.get("BeginX")) or ends.get("BeginX") or "?"
            got_to = sheet_anchor.get(ends.get("EndX")) or ends.get("EndX") or "?"
            semantic.append({"kind": "add-edge", "id": anchor or shape.ID,
                             "new": f"{got_from}->{got_to} '{text}'"})
        else:
            semantic.append({"kind": "add-node", "id": anchor or shape.ID,
                             "new": text or str(shape.ID)})

    for cid, c in known_nodes.items():
        if cid not in seen:
            semantic.append({"kind": "remove-node", "id": cid,
                             "old": c.get("label", cid)})
    for eid, r in known_edges.items():
        if eid not in seen:
            semantic.append({"kind": "remove-edge", "id": eid,
                             "old": f"{r['from']}->{r['to']} '{r.get('label', '')}'"})
    return {"semantic": semantic, "style": [], "layout": layout_changes}


# --------------------------------------------------------------------- CLI --

def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="render vsdx",
        description="Editable-diagram round-trip, Visio adapter (C8.2): generate a .vsdx "
                    "from a concept graph; re-ingest hand-edits with ID-first classification.",
    )
    sub = ap.add_subparsers(dest="action", required=True)

    gen = sub.add_parser("generate", help="concept graph -> .vsdx (NameU anchors, OPC provenance)")
    gen.add_argument("graph", type=Path)
    gen.add_argument("-o", "--output", type=Path, default=None)
    gen.add_argument("--layout", type=Path, default=None,
                     help="ID-keyed layout yaml IN VISIO INCHES (separate from any drawio "
                          "layout file); stored positions win, new nodes get a grid")

    rei = sub.add_parser("reingest", help="edited .vsdx -> provenance verdict + classified diff report")
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
                raise VsdxError(f"graph source not found: {args.graph}")
            out = args.output or args.graph.with_suffix(".vsdx")
            generate(args.graph, out, args.layout)
            print(f"wrote {out} (open in Microsoft Visio to hand-edit; NameU anchors "
                  f"are stable, re-ingest with 'render vsdx reingest')")
            return 0

        if not args.edited.exists():
            raise VsdxError(f"edited file not found: {args.edited}")
        if not args.source.exists():
            raise VsdxError(f"source not found: {args.source}")
        verdict = check_provenance(args.edited, args.source)
        graph = drawio.load_graph(args.source)
        layout = drawio.load_layout(args.layout)
        vf, page = _read_page(args.edited)
        try:
            buckets = classify(graph, page, layout)
        finally:
            vf.close_vsdx()

        applied = None
        if args.apply_layout:
            if args.layout is None:
                raise VsdxError("--apply-layout needs --layout <file> to write to")
            applied = drawio.apply_layout(args.layout, buckets["layout"])

        if args.json:
            print(json.dumps({"verdict": verdict, **buckets, "layout_applied": applied}, indent=2))
            return 0

        print(f"# vsdx re-ingestion: {args.edited.name}")
        print(f"verdict: {verdict}" + ("" if verdict == "FAST_FORWARD" else
              " (the graph source evolved since generation: reconcile semantic items by hand)"))
        print(f"\nsemantic ({len(buckets['semantic'])}) -> route to the canonical source:")
        for s in buckets["semantic"] or []:
            old = f" old='{s.get('old', '')}'" if s.get("old") else ""
            print(f"  - {s['kind']} {s['id']}:{old} new='{s.get('new', '')}'")
        if not buckets["semantic"]:
            print("  (none)")
        print(f"\nlayout ({len(buckets['layout'])}) -> layout file"
              + (f": APPLIED {applied}" if applied is not None else " (pass --apply-layout to write)"))
        for cid, geo in buckets["layout"].items():
            print(f"  - {cid}: x={geo['x']} y={geo['y']} w={geo['w']} h={geo['h']}")
        return 0
    except (VsdxError, drawio.DrawioError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
