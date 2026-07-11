#!/usr/bin/env python3
"""
ArchiMate Exchange-XML adapter for the layered-stack archetype (issue #86,
FR4-FR6 of the original #68 follow-up; FR7 fast-re-render is a separate
stretch item, not built here).

Transforms an Open Group ArchiMate Model Exchange File (the open XML
standard produced by Archi's "Export > ArchiMate Exchange Format" and other
Exchange-File-producing tools -- not Archi's own proprietary `.archimate`
format) into lint/layered_stack.py's existing StackModel shape, so the
archetype's own render_d2()/check_element_budget() run completely unchanged
(NFR6: one budget mechanism, not two).

NFR1: zero new heavy dependency -- the parse is stdlib xml.etree.ElementTree
only. Archi itself (Eclipse RCP, JVM, ACLI, jArchi) never enters renderfact's
toolchain; renderfact only ever reads a file Archi (or any other conformant
tool) already exported.

Deliberate v1 scope decisions (both documented here rather than guessed
around silently, per this repo's "honesty over guessing" posture):

1. STACK ORDER = document order. An Exchange File's <elements> block has no
   inherent "this is a top-to-bottom stack" ordering (ArchiMate is a general
   graph, not a layered-stack DSL) -- inferring vertical order from
   relationship topology is a real, ambiguous graph problem this v1
   deliberately does not attempt. Elements render in the exact order they
   appear in the source XML; re-arrange the model tree in Archi (which
   reorders the exported XML) to change the rendered order. This is an
   honest, deterministic rule (NFR4) rather than a clever-but-fragile
   heuristic that could silently misrepresent the model.
2. CHAINS (N parallel realizing paths under one shared interface, FR2 of the
   core archetype) are NOT auto-detected from ArchiMate relationships in
   this v1 -- every mapped element becomes a plain Layer or Interface, never
   a ChainsBlock. A model with genuinely parallel realizing chains renders
   as a flat sequential stack: simplified, but honest, not wrong. Automatic
   chain detection (grouping elements that Serve/Realize the same downstream
   interface) is real, separate follow-up work, exactly the same
   core-first/adapter-later split #68 itself already used for this file.

Element-type mapping (FR4's "map ArchiMate layer + element type onto the
archetype's layer + boundary model"): a fixed allowlist below, deliberately
covering the Technology, Physical, and Application layers the issue names as
examples. Anything outside the allowlist (a Motivation-layer Capability is
the issue's own example) fails closed via layered_stack.LayeredStackError,
naming the unsupported type and element -- FR5, never silently dropped.

Usage:
    python lint/archimate_exchange.py <model.xml> [-o out.d2] [--brand brand.yaml]
    python lint/render.py <model.xml>   # full pipeline, content-sniff dispatched
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layered_stack  # noqa: E402  (target shape: StackModel/Layer/Interface)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tokens" / "gen"))
from _common import load_tokens  # noqa: E402

# Local (namespace/prefix-stripped) ArchiMate element type -> archetype role.
# Technology + Physical layers (the issue's primary example) plus Application,
# since a model that spans Application->Technology is a common realistic case
# for this archetype (e.g. an app component realized by a technology node).
ARCHIMATE_TYPE_MAP: dict[str, str] = {
    # Technology layer
    "Node": "layer",
    "Device": "layer",
    "SystemSoftware": "layer",
    "TechnologyCollaboration": "layer",
    "TechnologyFunction": "layer",
    "TechnologyProcess": "layer",
    "TechnologyInterface": "interface",
    "Path": "layer",
    "CommunicationNetwork": "layer",
    "Artifact": "layer",
    # Physical layer
    "Equipment": "layer",
    "Facility": "layer",
    "DistributionNetwork": "layer",
    # Application layer
    "ApplicationComponent": "layer",
    "ApplicationCollaboration": "layer",
    "ApplicationFunction": "layer",
    "ApplicationInterface": "interface",
}


def _strip_ns(tag: str) -> str:
    """'{http://...}element' -> 'element'. ElementTree keeps the namespace
    URI baked into every tag; stripping it makes this parser tolerant of the
    exact namespace URI/version a given exporting tool declares (3.0/3.1/3.2
    all differ by a version segment; Archi's own native export sometimes
    diverges from the strict Open Group URI too) without hardcoding one."""
    return tag.rsplit("}", 1)[-1]


def _local_xsi_type(raw: str | None) -> str | None:
    """xsi:type is an attribute VALUE that is itself a QName reference (e.g.
    'archimate:Node' or a bare 'Node' depending on the exporting tool's
    prefix conventions) -- ElementTree does not resolve attribute-value
    QNames, only element/attribute NAMES, so this is a manual, deliberate
    prefix strip rather than a namespace lookup."""
    if raw is None:
        return None
    return raw.rsplit(":", 1)[-1]


def _element_name(el: ET.Element, identifier: str) -> str:
    """The Exchange File standard nests the label as a <name xml:lang="..">
    child; fall back to the bare identifier if absent/empty, mirroring
    layered_stack.py's own _label_or_id fallback for the plain-YAML path."""
    for child in el:
        if _strip_ns(child.tag) == "name" and (child.text or "").strip():
            return child.text.strip()
    return identifier


def sniff_archimate_exchange(path: Path) -> bool:
    """Content-sniff (FR6's dispatch idiom, the .xml peer of
    layered_stack.sniff_archetype's .yaml/.yml check): root element is
    <model>, and SOME declared namespace mentions 'archimate' (case-
    insensitive substring, tolerant of exact spec-version URIs and of
    Archi's own native namespace). Any read/parse failure or non-matching
    shape is treated as not-ours (returns False), never raised -- this gates
    dispatch over arbitrary .xml files, most of which are not ArchiMate
    models at all."""
    try:
        tree = ET.parse(str(path))
    except (ET.ParseError, OSError, UnicodeDecodeError):
        return False
    root = tree.getroot()
    if _strip_ns(root.tag) != "model":
        return False
    ns = root.tag.rpartition("}")[0].lstrip("{") if root.tag.startswith("{") else ""
    if "archimate" in ns.lower():
        return True
    # Some exports omit/mangle the default namespace but still carry the
    # ArchiMate xsi:schemaLocation hint on the root -- a lenient second check.
    for _, val in root.attrib.items():
        if "archimate" in val.lower():
            return True
    return False


def parse_exchange_file(path: Path) -> layered_stack.StackModel:
    """Parse + map an ArchiMate Exchange File to a StackModel. Raises
    layered_stack.LayeredStackError, fail-closed (FR5), on any element type
    outside ARCHIMATE_TYPE_MAP -- never silently drops content from a
    governed source. See the module docstring for the v1 ordering and
    chain-detection scope decisions."""
    try:
        tree = ET.parse(str(path))
    except (ET.ParseError, OSError, UnicodeDecodeError) as err:
        raise layered_stack.LayeredStackError(f"{path}: not a readable/well-formed XML file ({err})") from err
    root = tree.getroot()
    if _strip_ns(root.tag) != "model":
        raise layered_stack.LayeredStackError(
            f"{path}: root element is <{_strip_ns(root.tag)}>, expected <model> "
            "(not an ArchiMate Exchange File)"
        )

    title = str(path)
    for child in root:
        if _strip_ns(child.tag) == "name" and (child.text or "").strip():
            title = child.text.strip()
            break

    elements_block = None
    for child in root:
        if _strip_ns(child.tag) == "elements":
            elements_block = child
            break
    if elements_block is None or len(elements_block) == 0:
        raise layered_stack.LayeredStackError(
            f"{path}: no <elements> block found (or it is empty) -- nothing to render"
        )

    seen_ids: set[str] = set()
    stack_elements: list[layered_stack.StackElement] = []
    for el in elements_block:
        if _strip_ns(el.tag) != "element":
            continue
        identifier = el.get("identifier")
        if not identifier:
            raise layered_stack.LayeredStackError(f"{path}: an <element> is missing its 'identifier' attribute")
        xsi_type_raw = None
        for attr_name, attr_val in el.attrib.items():
            if _strip_ns(attr_name) == "type":
                xsi_type_raw = attr_val
                break
        local_type = _local_xsi_type(xsi_type_raw)
        if local_type not in ARCHIMATE_TYPE_MAP:
            raise layered_stack.LayeredStackError(
                f"{path}: element '{identifier}' ({_element_name(el, identifier)!r}) has type "
                f"{local_type!r}, which the layered-stack archetype does not model. "
                f"Supported types: {', '.join(sorted(ARCHIMATE_TYPE_MAP))}. "
                "Remove/reclassify this element in the source model, or extend "
                "ARCHIMATE_TYPE_MAP if it genuinely belongs in a layered stack."
            )
        if identifier in seen_ids:
            raise layered_stack.LayeredStackError(f"{path}: duplicate element identifier '{identifier}'")
        seen_ids.add(identifier)

        label = _element_name(el, identifier)
        role = ARCHIMATE_TYPE_MAP[local_type]
        if role == "interface":
            stack_elements.append(layered_stack.Interface(id=identifier, label=label))
        else:
            stack_elements.append(layered_stack.Layer(id=identifier, label=label))

    if not stack_elements:
        raise layered_stack.LayeredStackError(f"{path}: no supported ArchiMate elements found to render")

    return layered_stack.StackModel(
        title=title, tier=layered_stack.DEFAULT_TIER, elements=tuple(stack_elements)
    )


def generate_d2_source_from_exchange(xml_path: Path, brand_path: Path | None = None) -> str:
    """Parse, validate, NFR6-budget-check, and render an ArchiMate Exchange
    File to D2 text -- the .xml peer of layered_stack.generate_d2_source(),
    reusing check_element_budget()/render_d2() completely unchanged (only
    the parsing differs, per the issue's own 'should not need any change to
    render_d2() or the element-budget gate')."""
    model = parse_exchange_file(xml_path)
    layered_stack.check_element_budget(model)
    tokens = load_tokens(brand_path)
    return layered_stack.render_d2(model, tokens)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="archimate_exchange",
        description="Render an ArchiMate Exchange File through the layered-stack archetype.",
    )
    ap.add_argument("source", type=Path, help="ArchiMate Exchange File (.xml)")
    ap.add_argument("-o", "--out", type=Path, default=None, help="output .d2 path (default: stdout)")
    ap.add_argument("--brand", type=Path, default=None, help="brand.yaml token file")
    args = ap.parse_args(argv)

    try:
        d2 = generate_d2_source_from_exchange(args.source, args.brand)
    except layered_stack.LayeredStackError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1

    if args.out:
        args.out.write_text(d2, encoding="utf-8")
        print(f"Wrote: {args.out}")
    else:
        print(d2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
