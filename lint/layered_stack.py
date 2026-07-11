#!/usr/bin/env python3
"""
Layered-stack diagram archetype (issue #68, FR1-FR3 - the core deliverable).

An ordered set of technology layers, top to bottom, with an explicit, visually
distinct INTERFACE boundary between adjacent layers, and support for N parallel
REALIZING CHAINS laid out side by side under one shared interface (N=1 is the
degenerate default: an ordinary single-chain stack). Usable from a plain,
hand-authored renderfact YAML source - no dependency on Archi or any ArchiMate
file (FR3). The optional ArchiMate Exchange-XML adapter (FR4-FR7) is deliberately
OUT OF SCOPE here; see the follow-up issue linked from ROADMAP.md.

Source shape (top level):

    archetype: layered-stack
    title: "..."
    view-tier: procurement-annex   # optional; one of lint/element_budget.py's tiers
    stack:                          # ordered TOP TO BOTTOM: index 0 is the topmost
                                     # (most abstract) layer, the last entry is the
                                     # foundation. This matches the common
                                     # documentation convention of listing the
                                     # application/consumer layer first.
      - type: layer
        id: workload
        label: "Workloads"
      - type: interface
        id: iface-provisioning
        label: "Provisioning interface"
      - type: chains                # N parallel realizing chains (FR2)
        id: cmp-tier
        chains:
          - id: vendor-a
            label: "Vendor A"
            layers:
              - { id: cmp-a, label: "CMP" }
              - { id: hyp-a, label: "Hypervisor" }
          - id: vendor-b
            label: "Vendor B"
            layers:
              - { id: cmp-b, label: "CMP" }
              - { id: hyp-b, label: "Hypervisor" }
      - type: interface
        id: iface-compute
        label: "Compute interface"
      - type: layer
        id: transport
        label: "Transport"

A `chains` block with exactly one chain is the FR2 degenerate case: an ordinary
pass-through segment of the stack, rendered the same way as any other single
column. A `stack` with no `chains` blocks at all is an ordinary layered stack
with interface markers between layers - the majority use case per the issue's
own UX analysis (scenario 1: "hand-authored layered stack, no Archi anywhere").

Rendering: renderfact YAML -> D2 source, styled by resolving tokens/brand.yaml
ROLES (colour.brand.*, colour.status.*, colour.data[] for the per-chain
categorical palette) to literal values at generation time - the same pattern
tokens/gen/mermaid_theme.py uses for Mermaid, adapted for D2's inline
`style.*` properties (D2 has no external theme-file injection mechanism to
target, unlike mmdc's --configFile).

Font tokens (type.body_font / type.print_font) are NOT applied: D2's built-in
renderer only ships a small fixed font set and rejects arbitrary family names
outright (verified against D2 0.7.1 - 'style.font: "Inter"' fails to compile).
This is documented here rather than silently dropped, the same honesty
mermaid_theme.py applies to its own theme-system gaps.

NFR6 (element-budget discipline): the model's semantic element count (every
layer box, interface marker, and per-chain layer box) is checked against
lint/element_budget.py's existing tier budgets - the SAME mechanism the
generic .d2/.mmd/.svg budget linter uses - and fails closed with an
actionable message before any D2 is even generated.

Usage:
    python lint/layered_stack.py <source.yaml> [-o out.d2] [--brand brand.yaml]
    python lint/render.py <source.yaml>   # full pipeline: YAML -> D2 -> svg/pdf
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import element_budget  # noqa: E402  (lint/element_budget.py: the shared tier-budget table)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tokens" / "gen"))
from _common import load_tokens  # noqa: E402

ARCHETYPE_NAME = "layered-stack"
DEFAULT_TIER = "procurement-annex"  # most permissive; matches element_budget.py's own default
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class LayeredStackError(ValueError):
    """A structurally invalid layered-stack source. Fail closed (FR5's sibling
    principle applied to the core archetype: never silently drop or guess)."""


class ElementBudgetExceeded(LayeredStackError):
    """The model exceeds its view-tier's hard element budget (NFR6)."""


# --- model -------------------------------------------------------------------


@dataclass(frozen=True)
class Layer:
    id: str
    label: str


@dataclass(frozen=True)
class Interface:
    id: str
    label: str


@dataclass(frozen=True)
class Chain:
    id: str
    label: str
    layers: tuple[Layer, ...]


@dataclass(frozen=True)
class ChainsBlock:
    id: str
    chains: tuple[Chain, ...]


StackElement = Union[Layer, Interface, ChainsBlock]


@dataclass(frozen=True)
class StackModel:
    title: str
    tier: str
    elements: tuple[StackElement, ...]


# --- parsing -------------------------------------------------------------------


def _require_id(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or not _ID_RE.match(raw):
        raise LayeredStackError(
            f"{where}: 'id' must be a string matching {_ID_RE.pattern!r} (got {raw!r})"
        )
    return raw


def _label_or_id(node: dict, id_: str, where: str) -> str:
    label = node.get("label", id_)
    if not isinstance(label, str) or not label.strip():
        raise LayeredStackError(f"{where}: 'label' must be a non-empty string")
    return label


def _parse_layer(node: Any, where: str) -> Layer:
    if not isinstance(node, dict):
        raise LayeredStackError(f"{where}: layer entry must be a mapping")
    id_ = _require_id(node.get("id"), where)
    label = _label_or_id(node, id_, where)
    return Layer(id=id_, label=label)


def _parse_interface(node: Any, where: str) -> Interface:
    if not isinstance(node, dict):
        raise LayeredStackError(f"{where}: interface entry must be a mapping")
    id_ = _require_id(node.get("id"), where)
    label = _label_or_id(node, id_, where)
    return Interface(id=id_, label=label)


def _parse_chain(node: Any, where: str) -> Chain:
    if not isinstance(node, dict):
        raise LayeredStackError(f"{where}: chain entry must be a mapping")
    id_ = _require_id(node.get("id"), where)
    label = _label_or_id(node, id_, where)
    raw_layers = node.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise LayeredStackError(
            f"{where}: chain '{id_}' must have a non-empty 'layers' list "
            "(a chain with zero layers realizes nothing)"
        )
    seen: set[str] = set()
    layers: list[Layer] = []
    for i, raw in enumerate(raw_layers):
        layer = _parse_layer(raw, f"{where}: chain '{id_}' layers[{i}]")
        if layer.id in seen:
            raise LayeredStackError(f"{where}: chain '{id_}' has a duplicate layer id '{layer.id}'")
        seen.add(layer.id)
        layers.append(layer)
    return Chain(id=id_, label=label, layers=tuple(layers))


def _parse_chains_block(node: Any, where: str) -> ChainsBlock:
    if not isinstance(node, dict):
        raise LayeredStackError(f"{where}: chains entry must be a mapping")
    id_ = _require_id(node.get("id"), where)
    raw_chains = node.get("chains")
    if not isinstance(raw_chains, list) or not raw_chains:
        raise LayeredStackError(
            f"{where}: chains block '{id_}' must have a non-empty 'chains' list "
            "(N>=1; N=1 is the degenerate single-chain case, not an empty list - FR2)"
        )
    seen: set[str] = set()
    chains: list[Chain] = []
    for i, raw in enumerate(raw_chains):
        chain = _parse_chain(raw, f"{where}: chains block '{id_}' chains[{i}]")
        if chain.id in seen:
            raise LayeredStackError(f"{where}: chains block '{id_}' has a duplicate chain id '{chain.id}'")
        seen.add(chain.id)
        chains.append(chain)
    return ChainsBlock(id=id_, chains=tuple(chains))


def parse_model(doc: Any, source_name: str = "<source>") -> StackModel:
    """Validate + build a StackModel from a parsed YAML document. Raises
    LayeredStackError, fail-closed, on any structural problem."""
    if not isinstance(doc, dict):
        raise LayeredStackError(f"{source_name}: top level must be a mapping")

    archetype = doc.get("archetype")
    if archetype != ARCHETYPE_NAME:
        raise LayeredStackError(
            f"{source_name}: 'archetype' must be {ARCHETYPE_NAME!r} (got {archetype!r})"
        )

    title = doc.get("title", source_name)
    if not isinstance(title, str) or not title.strip():
        raise LayeredStackError(f"{source_name}: 'title' must be a non-empty string if given")

    tier = doc.get("view-tier", DEFAULT_TIER)
    if tier not in element_budget.VALID_TIERS:
        raise LayeredStackError(
            f"{source_name}: 'view-tier' must be one of {sorted(element_budget.VALID_TIERS)} "
            f"(got {tier!r})"
        )

    raw_stack = doc.get("stack")
    if not isinstance(raw_stack, list) or not raw_stack:
        raise LayeredStackError(
            f"{source_name}: 'stack' must be a non-empty list - an ordered, top-to-bottom "
            "set of layers with interface boundaries between them (FR1/FR3)"
        )

    elements: list[StackElement] = []
    seen_ids: set[str] = set()

    def _claim(id_: str, where: str) -> None:
        if id_ in seen_ids:
            raise LayeredStackError(f"{where}: duplicate top-level id '{id_}'")
        seen_ids.add(id_)

    for i, raw in enumerate(raw_stack):
        where = f"{source_name}: stack[{i}]"
        if not isinstance(raw, dict) or "type" not in raw:
            raise LayeredStackError(
                f"{where}: each stack entry needs a 'type' key ('layer', 'interface', or 'chains')"
            )
        kind = raw["type"]
        if kind == "layer":
            el: StackElement = _parse_layer(raw, where)
        elif kind == "interface":
            el = _parse_interface(raw, where)
        elif kind == "chains":
            el = _parse_chains_block(raw, where)
        else:
            raise LayeredStackError(
                f"{where}: unknown type {kind!r} (expected 'layer', 'interface', or 'chains')"
            )
        _claim(el.id, where)
        elements.append(el)

    return StackModel(title=title, tier=tier, elements=tuple(elements))


def load_model(path: Path) -> StackModel:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise LayeredStackError(f"{path}: cannot read source ({err})") from err
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise LayeredStackError(f"{path}: not valid YAML ({err})") from err
    return parse_model(doc, source_name=str(path))


def sniff_archetype(path: Path) -> str | None:
    """Content-sniff a .yaml/.yml file for a recognized renderfact diagram
    archetype (FR6's dispatch idiom, reused for the core archetype's own plain
    YAML source - not the ArchiMate adapter). Returns the archetype name, or
    None for "not ours": any read/parse failure or non-matching shape is treated
    as not-ours, never raised, since this gates dispatch over arbitrary YAML
    files, most of which are not diagram sources at all."""
    try:
        text = path.read_text(encoding="utf-8")
        doc = yaml.safe_load(text)
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return None
    if isinstance(doc, dict) and doc.get("archetype") == ARCHETYPE_NAME:
        return ARCHETYPE_NAME
    return None


# --- NFR6: element-budget discipline --------------------------------------------


def count_elements(model: StackModel) -> int:
    """Semantic element count: every rendered box (shared layer, interface
    marker, or per-chain layer instance). This is deliberately NOT the generic
    line-count heuristic lint/element_budget.py applies to already-rendered .d2
    text - it counts what the archetype actually draws, before any D2 exists."""
    total = 0
    for el in model.elements:
        if isinstance(el, (Layer, Interface)):
            total += 1
        elif isinstance(el, ChainsBlock):
            total += sum(len(chain.layers) for chain in el.chains)
    return total


def check_element_budget(model: StackModel) -> None:
    """Fail closed (NFR6) using the SAME tier budgets lint/element_budget.py
    already enforces for rendered diagram sources - one budget table, reused,
    not reinvented for this archetype."""
    hard = element_budget.BUDGETS[model.tier]["hard"]
    count = count_elements(model)
    if count > hard:
        raise ElementBudgetExceeded(
            f"'{model.title}' has {count} elements, exceeding the hard budget of {hard} "
            f"for view-tier '{model.tier}'. Split this into multiple views: e.g. one view "
            "per realizing chain, or break the stack at a shared interface boundary into "
            "two linked diagrams."
        )


# --- D2 emission -----------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    layer_fill: str
    layer_stroke: str
    layer_font_color: str
    interface_fill: str
    interface_stroke: str
    interface_font_color: str
    chain_colors: tuple[str, ...]


def resolve_palette(tokens: dict) -> Palette:
    """Resolve brand.yaml ROLES to literal D2 style values at generation time
    (mirrors tokens/gen/mermaid_theme.py's resolution pattern). Never hardcode a
    hex value here that isn't a documented, fixed contrast choice."""
    colour = tokens["colour"]
    brand = colour["brand"]
    status = colour["status"]
    data = colour.get("data") or ["#000000"]
    return Palette(
        layer_fill=brand["fill"],
        layer_stroke=brand["primary"],
        layer_font_color=brand["ink"],
        interface_fill=status["info"],
        interface_stroke=brand["primary"],
        # Fixed contrast text over the status.info fill - the same pattern as
        # tokens/gen/mermaid_theme.py's errorTextColor: a deliberate, documented
        # contrast choice, not a hardcoded brand colour.
        interface_font_color="#FFFFFF",
        chain_colors=tuple(data),
    )


def _d2_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return '"' + escaped + '"'


def _qid(id_: str) -> str:
    """Quote a D2 identifier. Every id this module emits (node keys, container
    keys, edge endpoints, dotted cross-container paths) goes through this --
    D2 reserves a set of bare words (top/bottom/left/right/near/shape/width/
    height/...) that collide with entirely reasonable stack-layer names (a
    layer literally named "top" broke compilation with an unquoted id during
    development: 'reserved keywords are prohibited in edges'). Quoting every
    id sidesteps the whole reserved-word surface rather than chasing it."""
    return _d2_str(id_)


def _emit_shape(
    id_: str, label: str, shape: str, fill: str, stroke: str, font_color: str,
    stroke_width: int | None = None, indent: str = "",
) -> list[str]:
    lines = [f"{indent}{_qid(id_)}: {{"]
    lines.append(f"{indent}  label: {_d2_str(label)}")
    lines.append(f"{indent}  shape: {shape}")
    lines.append(f"{indent}  style.fill: {_d2_str(fill)}")
    lines.append(f"{indent}  style.stroke: {_d2_str(stroke)}")
    lines.append(f"{indent}  style.font-color: {_d2_str(font_color)}")
    if stroke_width is not None:
        lines.append(f"{indent}  style.stroke-width: {stroke_width}")
    lines.append(f"{indent}}}")
    return lines


def render_d2(model: StackModel, tokens: dict) -> str:
    """Emit the D2 source for a validated StackModel. Shared layers and
    interfaces stack top-to-bottom via plain (arrowless) edges; a `chains`
    block is a `grid-columns` container so its N realizing chains lay out
    side by side (FR2), each chain a `direction: down` sub-container of its
    own layers, fanned in/out to the shared interface on either side (the
    ball-and-socket idea: N sockets plugging into one shared interface)."""
    palette = resolve_palette(tokens)
    lines: list[str] = [
        "# GENERATED by lint/layered_stack.py from a layered-stack archetype source.",
        "# Do not edit by hand - regenerate via: render diagram <source.yaml>",
        "# Layers are top-to-bottom in the source; that is also the rendered order.",
        "direction: down",
        "",
        '"__title": {',
        f"  label: {_d2_str(model.title)}",
        "  near: top-center",
        "  shape: text",
        "  style.bold: true",
        "  style.font-size: 20",
        "}",
        "",
    ]

    edges: list[str] = []

    def _connect(froms: list[str], tos: list[str]) -> None:
        for f in froms:
            for t in tos:
                edges.append(f"{f} -- {t}")

    prev_endpoints: list[str] | None = None

    for el in model.elements:
        if isinstance(el, Layer):
            lines += _emit_shape(
                el.id, el.label, "rectangle",
                palette.layer_fill, palette.layer_stroke, palette.layer_font_color,
            )
            lines.append("")
            if prev_endpoints:
                _connect(prev_endpoints, [_qid(el.id)])
            prev_endpoints = [_qid(el.id)]

        elif isinstance(el, Interface):
            label = f"<< interface >>\n{el.label}"
            lines += _emit_shape(
                el.id, label, "oval",
                palette.interface_fill, palette.interface_stroke, palette.interface_font_color,
                stroke_width=3,
            )
            lines.append("")
            if prev_endpoints:
                _connect(prev_endpoints, [_qid(el.id)])
            prev_endpoints = [_qid(el.id)]

        elif isinstance(el, ChainsBlock):
            block_lines = [f"{_qid(el.id)}: {{", f"  grid-columns: {len(el.chains)}"]
            chain_tops: list[str] = []
            chain_bottoms: list[str] = []
            for i, chain in enumerate(el.chains):
                chain_colour = palette.chain_colors[i % len(palette.chain_colors)]
                block_lines.append(f"  {_qid(chain.id)}: {{")
                block_lines.append(f"    label: {_d2_str(chain.label)}")
                block_lines.append("    direction: down")
                prev_layer_id: str | None = None
                for layer in chain.layers:
                    block_lines += _emit_shape(
                        layer.id, layer.label, "rectangle",
                        palette.layer_fill, chain_colour, palette.layer_font_color,
                        indent="    ",
                    )
                    if prev_layer_id:
                        block_lines.append(f"    {_qid(prev_layer_id)} -- {_qid(layer.id)}")
                    prev_layer_id = layer.id
                block_lines.append("  }")
                chain_tops.append(f"{_qid(el.id)}.{_qid(chain.id)}.{_qid(chain.layers[0].id)}")
                chain_bottoms.append(f"{_qid(el.id)}.{_qid(chain.id)}.{_qid(chain.layers[-1].id)}")
            block_lines.append("}")
            lines += block_lines
            lines.append("")
            if prev_endpoints:
                _connect(prev_endpoints, chain_tops)
            prev_endpoints = chain_bottoms

    lines.append("# spine + boundary connections")
    lines += edges
    lines.append("")
    return "\n".join(lines)


# --- pipeline entry points -------------------------------------------------------


def generate_d2_source(yaml_path: Path, brand_path: Path | None = None) -> str:
    """Parse, validate, NFR6-budget-check, and render a layered-stack YAML
    source to D2 text. Raises LayeredStackError (incl. ElementBudgetExceeded)
    fail-closed; never returns a partial or best-effort diagram."""
    model = load_model(yaml_path)
    check_element_budget(model)
    tokens = load_tokens(brand_path)
    return render_d2(model, tokens)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Layered-stack diagram archetype: renderfact YAML -> D2 (issue #68, FR1-FR3).",
    )
    parser.add_argument("source", type=Path, help="layered-stack YAML source file")
    parser.add_argument("-o", "--out", type=Path, default=None,
                        help="write generated D2 here (default: stdout)")
    parser.add_argument("--brand", type=Path, default=None,
                        help="consumer brand.yaml override (optional)")
    args = parser.parse_args(argv)

    try:
        d2_source = generate_d2_source(args.source, args.brand)
    except LayeredStackError as err:
        print(f"REJECT  {args.source}  ({err})", file=sys.stderr)
        return 1

    if args.out:
        args.out.write_text(d2_source, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(d2_source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
