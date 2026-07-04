#!/usr/bin/env python3
"""
svg_metrics.py -- deterministic visual-QA layer for rendered Mermaid SVG.

Closes the framework gap surfaced 2026-05-25: text-rubric reviewers
(architect/security/operator/executive/accessibility) read source-text
criteria and miss visual layout problems that are obvious to a human
eye (overlapping arrows, dense legend, vertical-stretched nodes, low
whitespace).

Plug-in point: between `mmdc` render and `iterate/synthesize.py`.
Deterministic, cheap, CI-gateable. Complements (does not replace) the
vision-reviewer 6th-role agent option for subjective layout review.

Metrics computed:
  - edge_crossings    -- pairwise edge-path Bezier intersection count
  - node_overlap      -- AABB pair-intersection count
  - whitespace_ratio  -- 1 - sum(node bbox area) / viewport area
  - density_score     -- nodes per 1000 px^2 (lower = more breathable)
  - tier_compliance   -- thresholds per view-tier (exec / programme / operator / procurement-annex)

Doctrine refs:
  - the predecessor diagram harness's multi-output rendering spec (v0.3, section 5.4)
  - AaC Diagram Authoring Playbook section 2 pre-flight checklist (extended)
  - Visual-QA layer design 2026-05-25 (Phase A')

Usage:
  python lint/svg_metrics.py <rendered.svg> --tier operator-handoff [--strict]

Exit codes:
  0 = all metrics within tier thresholds
  1 = WARN-level breach (logged, build continues)
  2 = BLOCK-level breach (CI fails)
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# Tier thresholds. Empirical baselines from 2026-05-25 cell-topology iterations.
# WARN = soft cap (report but continue); BLOCK = hard cap (CI gate).
TIER_THRESHOLDS: dict[str, dict[str, tuple[int, int]]] = {
    # tier: { metric: (warn, block) }
    "executive-cover": {
        "edge_crossings":   (0, 2),
        "node_overlap":     (0, 1),
        "whitespace_ratio": (60, 40),   # min % whitespace; below = denser than allowed
    },
    "programme-planning": {
        "edge_crossings":   (2, 5),
        "node_overlap":     (0, 2),
        "whitespace_ratio": (50, 35),
    },
    "operator-handoff": {
        "edge_crossings":   (5, 10),
        "node_overlap":     (1, 3),
        "whitespace_ratio": (40, 25),
    },
    "procurement-annex": {
        "edge_crossings":   (8, 15),
        "node_overlap":     (2, 5),
        "whitespace_ratio": (35, 20),
    },
}


@dataclass
class Metrics:
    edge_crossings: int
    node_overlap_pairs: int
    whitespace_pct: float
    node_count: int
    edge_count: int
    viewport_w: float
    viewport_h: float
    density_per_kpx2: float


def parse_svg(svg_file: Path) -> Metrics:
    """Parse a rendered Mermaid SVG and compute layout metrics.

    Uses svgpathtools for edge-path Bezier intersection (handles curved edges)
    and svgelements for node bounding-boxes from <rect>/<polygon>/<path>.
    """
    try:
        from svgpathtools import svg2paths2, Path as SVGPath
        from svgelements import SVG
    except ImportError as e:
        print(f"missing dependency: {e} -- pip install svgpathtools svgelements", file=sys.stderr)
        sys.exit(3)

    paths, attributes, svg_attrs = svg2paths2(str(svg_file))

    # Edges vs nodes: Mermaid renders edges as <path class="flowchart-link...">
    # and nodes as <g class="node">. svgpathtools collapses everything into paths.
    # Classify by class attribute when present.
    edge_paths = []
    for ep, attr in zip(paths, attributes):
        cls = attr.get("class", "")
        if "flowchart-link" in cls or "edgePath" in cls or "messageLine" in cls:
            edge_paths.append(ep)

    # Pairwise edge crossings via Bezier intersection.
    crossings = 0
    for i, p1 in enumerate(edge_paths):
        for p2 in edge_paths[i + 1:]:
            try:
                ints = p1.intersect(p2)
                # Each intersection is a tuple of segment-info; filter trivial
                # endpoint-shared intersections (small parameter values).
                for (T1, seg1, t1), (T2, seg2, t2) in ints:
                    if 0.01 < T1 < 0.99 and 0.01 < T2 < 0.99:
                        crossings += 1
            except Exception:
                # svgpathtools' intersect can raise on degenerate paths; treat as no-crossing
                pass

    # Node bounding boxes via svgelements (robust SVG2 parser).
    svg = SVG.parse(str(svg_file))
    node_boxes: list[tuple[float, float, float, float]] = []
    # svgelements: width/height attributes; fall back to bbox if missing.
    viewport_w = float(getattr(svg, "width", None) or 800)
    viewport_h = float(getattr(svg, "height", None) or 600)
    if (viewport_w == 800 or viewport_h == 600):
        # try root bbox
        try:
            bb = svg.bbox()
            if bb is not None:
                viewport_w = float(bb[2] - bb[0])
                viewport_h = float(bb[3] - bb[1])
        except Exception:
            pass

    # Node-box filter: Mermaid renders each node as a <rect>/<polygon>/<path>
    # within a <g class="node ...">. svg.elements() walks recursively and reports
    # bboxes for EVERY element (text glyphs, nested containers, edge labels...).
    # Filter heuristically:
    #   - drop very small (text glyphs / arrowhead markers): w < 60 or h < 30
    #   - drop canvas-spanning (viewport / root <g>): w or h > 60% of viewport
    #   - dedupe by approximate bbox identity (round to nearest px to merge
    #     near-identical nested boxes that share a transform)
    seen_bboxes: set[tuple[int, int, int, int]] = set()
    for elem in svg.elements():
        if not (hasattr(elem, "bbox") and callable(elem.bbox)):
            continue
        bbox = elem.bbox()
        if bbox is None:
            continue
        x0, y0, x1, y1 = bbox
        w = x1 - x0
        h = y1 - y0
        if w < 60 or h < 30:
            continue
        if w > viewport_w * 0.6 or h > viewport_h * 0.6:
            continue
        key = (round(x0), round(y0), round(x1), round(y1))
        if key in seen_bboxes:
            continue
        seen_bboxes.add(key)
        node_boxes.append((x0, y0, x1, y1))

    # Node overlap: pairwise AABB intersection.
    overlap_pairs = 0
    for i, (ax0, ay0, ax1, ay1) in enumerate(node_boxes):
        for (bx0, by0, bx1, by1) in node_boxes[i + 1:]:
            if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                overlap_pairs += 1

    # Whitespace ratio: 1 - sum(node area) / viewport area.
    node_area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in node_boxes)
    viewport_area = viewport_w * viewport_h
    whitespace_pct = round(100 * (1 - node_area / viewport_area), 1) if viewport_area else 0.0

    density_per_kpx2 = round(1000 * len(node_boxes) / viewport_area, 4) if viewport_area else 0.0

    return Metrics(
        edge_crossings=crossings,
        node_overlap_pairs=overlap_pairs,
        whitespace_pct=whitespace_pct,
        node_count=len(node_boxes),
        edge_count=len(edge_paths),
        viewport_w=viewport_w,
        viewport_h=viewport_h,
        density_per_kpx2=density_per_kpx2,
    )


def check_thresholds(m: Metrics, tier: str) -> tuple[int, list[str]]:
    """Compare metrics against tier thresholds. Return (severity, messages).

    severity: 0 = pass, 1 = WARN, 2 = BLOCK.
    """
    if tier not in TIER_THRESHOLDS:
        return 0, [f"unknown tier '{tier}' -- skipping threshold checks"]
    t = TIER_THRESHOLDS[tier]
    severity = 0
    messages: list[str] = []

    # edge_crossings: lower = better
    warn, block = t["edge_crossings"]
    if m.edge_crossings > block:
        severity = max(severity, 2)
        messages.append(f"BLOCK edge_crossings={m.edge_crossings} > tier block={block}")
    elif m.edge_crossings > warn:
        severity = max(severity, 1)
        messages.append(f"WARN edge_crossings={m.edge_crossings} > tier warn={warn}")

    # node_overlap: lower = better
    warn, block = t["node_overlap"]
    if m.node_overlap_pairs > block:
        severity = max(severity, 2)
        messages.append(f"BLOCK node_overlap_pairs={m.node_overlap_pairs} > tier block={block}")
    elif m.node_overlap_pairs > warn:
        severity = max(severity, 1)
        messages.append(f"WARN node_overlap_pairs={m.node_overlap_pairs} > tier warn={warn}")

    # whitespace: higher = better; thresholds are minimums
    warn_min, block_min = t["whitespace_ratio"]
    if m.whitespace_pct < block_min:
        severity = max(severity, 2)
        messages.append(f"BLOCK whitespace_pct={m.whitespace_pct} < tier min={block_min}")
    elif m.whitespace_pct < warn_min:
        severity = max(severity, 1)
        messages.append(f"WARN whitespace_pct={m.whitespace_pct} < tier min={warn_min}")

    if not messages:
        messages.append(f"PASS all metrics within tier '{tier}' thresholds")
    return severity, messages


def main() -> int:
    ap = argparse.ArgumentParser(description="Visual-QA metrics for rendered Mermaid SVG")
    ap.add_argument("svg", type=Path, help="Path to rendered SVG")
    ap.add_argument("--tier", default="operator-handoff",
                    choices=list(TIER_THRESHOLDS.keys()),
                    help="View-tier thresholds to apply")
    ap.add_argument("--strict", action="store_true",
                    help="Exit non-zero on WARN as well as BLOCK")
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON to stdout (machine-readable)")
    args = ap.parse_args()

    if not args.svg.exists():
        print(f"file not found: {args.svg}", file=sys.stderr)
        return 3

    metrics = parse_svg(args.svg)
    severity, messages = check_thresholds(metrics, args.tier)

    if args.json:
        payload = {
            "file": str(args.svg),
            "tier": args.tier,
            "metrics": asdict(metrics),
            "severity": severity,
            "messages": messages,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(f"=== svg_metrics {args.svg.name} (tier={args.tier}) ===")
        for k, v in asdict(metrics).items():
            print(f"  {k:24} = {v}")
        print("--- threshold check ---")
        for msg in messages:
            print(f"  {msg}")

    # Exit code: 0 pass, 1 WARN (only fails CI if --strict), 2 BLOCK
    if severity == 2:
        return 2
    if severity == 1 and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
