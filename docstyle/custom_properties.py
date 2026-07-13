#!/usr/bin/env python3
"""
custom_properties.py: POST-RENDER custom document properties, DOCPROPERTY half
of issue #105's sibling feature (dropdown/checkbox is docstyle/filters/form-
controls.lua; this is docProps/custom.xml + the DOCPROPERTY field cache).

A `--template-profile <yaml>` custom_properties: mapping (name -> {type,
value}) is written into docProps/custom.xml, and any `[ ]{.docproperty
name="..."}` markdown span -- converted by docstyle/filters/doc-properties.lua,
DURING the earlier pandoc step, into a real w:fldSimple DOCPROPERTY field with
a guillemet placeholder cached result -- gets that placeholder replaced with
the real value, so the rendered template shows the actual value immediately
instead of waiting on Word's own field recalculation (F9 / update-fields-on-
print). Declaration (this script, template-profile-level) and display
(doc-properties.lua, per-span) are deliberately separate concerns: a template
can move where a property is SHOWN without touching its declared value, or
change the value without hunting down every place it is referenced.

Why this reverses roundtrip/provenance.py's D11 decision to avoid
docProps/custom.xml (its module docstring: "none of the three libraries has
native support for it, and hand-rolling the OOXML content-types + relationship
registration carries real corruption risk... for no functional gain over the
core_properties approach at this stage"). That reasoning holds for D11's own
use case -- ONE opaque JSON blob, machine-read only, never Office-native --
where dc:identifier was a genuinely adequate substitute. This feature needs
the opposite: multiple, independently NAMED, TYPED values a human opens
File > Info > Properties > Advanced to read or edit, and that Word's own
DOCPROPERTY field mechanism can only bind to a real custom property, not an
arbitrary core-property JSON blob. There is no substitute for docProps/
custom.xml here, so the same registration technique
roundtrip/provenance.py's _OpcCoreProps already proved out for docProps/
core.xml on .vsdx is reimplemented (not imported -- see _register_custom_part)
for this second, structurally different part. See docs/DECISIONS.md D24.

Idempotent: re-running with the same properties on an already-processed file
is a no-op (0 return, nothing rewritten) -- verified the same way
heading_numbering.py's numbering injection is (tests/test_custom_properties.py).
A pre-existing docProps/custom.xml (e.g. a consumer's own tooling already set
one) is MERGED, not overwritten: an unmanaged property this script doesn't
know about is left untouched, never removed or reordered.

Usage (post-render, in place):
  python custom_properties.py OUT.docx --template-profile profile.yaml
  python custom_properties.py OUT.docx --template-profile profile.yaml --check
Unconfigured (no custom_properties key, or no --template-profile at all) is a
clean no-op, matching every other optional render-doc.sh step's convention.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

CUSTOM_PART = "docProps/custom.xml"
_CUSTOM_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
_VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
_FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"  # the fixed, well-known custom-properties fmtid
_MINIMAL_CUSTOM_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="%s" xmlns:vt="%s"/>' % (_CUSTOM_NS, _VT_NS)
)

_VALID_TYPES = {"text", "number", "bool", "date"}
_NAME_RE = re.compile(r'^\w+$')


def load_custom_properties(profile_path: Path | None) -> dict[str, dict]:
    """Read the `custom_properties:` mapping from a --template-profile yaml.
    {} when profile_path is None, missing, or the key is absent -- the same
    "unconfigured = no-op" convention every other optional render-doc.sh step
    already follows (--no-toc, QC_SCRIPT, POSTRENDER_GATE_SCRIPT, ...)."""
    if profile_path is None or not profile_path.is_file():
        return {}
    import yaml

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    raw = profile.get("custom_properties") or {}
    out: dict[str, dict] = {}
    for name, spec in raw.items():
        if not _NAME_RE.match(name):
            raise ValueError(
                f"custom_properties key '{name}' must be alphanumeric/underscore only "
                "(it becomes a DOCPROPERTY field name)"
            )
        spec = spec or {}
        typ = spec.get("type", "text")
        if typ not in _VALID_TYPES:
            raise ValueError(
                f"custom_properties.{name}.type '{typ}' must be one of {sorted(_VALID_TYPES)}"
            )
        out[name] = {"type": typ, "value": spec.get("value", "")}
    return out


def _vt_element(typ: str, value) -> tuple[str, str]:
    """(vt tag local-name, string content) for one property's typed value."""
    if typ == "text":
        return "lpwstr", str(value)
    if typ == "bool":
        return "bool", "1" if value else "0"
    if typ == "date":
        s = str(value)
        if not re.match(r'^\d{4}-\d{2}-\d{2}', s):
            raise ValueError(f"date value '{value}' must start with YYYY-MM-DD")
        if 'T' not in s:
            s += "T00:00:00Z"
        elif not s.endswith('Z'):
            s += "Z"
        return "filetime", s
    if typ == "number":
        fval = float(value)
        return ("i4", str(int(fval))) if fval.is_integer() else ("r8", str(fval))
    raise ValueError(f"unknown type '{typ}'")  # unreachable: load_custom_properties already validated


def _read_members(path: Path) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as zf:
        return [(name, zf.read(name)) for name in zf.namelist()]


def _write_members(path: Path, members: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(name, data)


def _register_custom_part(members: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Register docProps/custom.xml in [Content_Types].xml + _rels/.rels: the
    same two-registration technique roundtrip/provenance.py's _OpcCoreProps
    established for docProps/core.xml on .vsdx, reimplemented (not imported)
    for this second, structurally different part -- see the module docstring
    for why sharing is not worth the cross-subsystem coupling here."""
    ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    rtype = ("http://schemas.openxmlformats.org/officeDocument/2006/"
             "relationships/custom-properties")
    out = []
    for name, data in members:
        if name == "[Content_Types].xml":
            root = ET.fromstring(data)
            if not any(o.get("PartName") == "/" + CUSTOM_PART
                       for o in root.iter(f"{{{ct_ns}}}Override")):
                ET.SubElement(root, f"{{{ct_ns}}}Override", {
                    "PartName": "/" + CUSTOM_PART,
                    "ContentType": "application/vnd.openxmlformats-officedocument."
                                   "custom-properties+xml",
                })
            ET.register_namespace("", ct_ns)
            data = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
        elif name == "_rels/.rels":
            root = ET.fromstring(data)
            if not any(r.get("Type") == rtype for r in root.iter(f"{{{rel_ns}}}Relationship")):
                taken = {r.get("Id") for r in root.iter(f"{{{rel_ns}}}Relationship")}
                rid = next(f"rId{i}" for i in range(1, 1000) if f"rId{i}" not in taken)
                ET.SubElement(root, f"{{{rel_ns}}}Relationship", {
                    "Id": rid, "Type": rtype, "Target": CUSTOM_PART,
                })
            ET.register_namespace("", rel_ns)
            data = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
        out.append((name, data))
    return out


def _merge_custom_xml(existing: bytes | None, properties: dict[str, dict]) -> tuple[bytes, int]:
    """Merge `properties` into an existing docProps/custom.xml payload (or a
    fresh minimal one). Updates an already-present name's value IN PLACE (same
    pid, so a foreign property this script doesn't manage is never touched or
    reordered); appends a new name with the next free pid (pid 1 is reserved,
    renderfact starts at 2). Returns (new_xml_bytes, count_actually_changed) --
    a property whose value already matches is left alone and not counted, the
    idempotency invariant this module's docstring promises."""
    ET.register_namespace("", _CUSTOM_NS)
    ET.register_namespace("vt", _VT_NS)
    root = ET.fromstring(existing) if existing is not None else ET.fromstring(_MINIMAL_CUSTOM_XML)

    by_name: dict[str, ET.Element] = {}
    max_pid = 1
    for prop in root.findall(f"{{{_CUSTOM_NS}}}property"):
        by_name[prop.get("name")] = prop
        try:
            max_pid = max(max_pid, int(prop.get("pid", "1")))
        except ValueError:
            pass

    changed = 0
    for name, spec in properties.items():
        tag, text = _vt_element(spec["type"], spec["value"])
        if name in by_name:
            prop = by_name[name]
            current = list(prop)
            if len(current) == 1 and current[0].tag == f"{{{_VT_NS}}}{tag}" and current[0].text == text:
                continue
            for child in list(prop):
                prop.remove(child)
            vt_el = ET.SubElement(prop, f"{{{_VT_NS}}}{tag}")
            vt_el.text = text
            changed += 1
        else:
            max_pid += 1
            prop = ET.SubElement(root, f"{{{_CUSTOM_NS}}}property", {
                "fmtid": _FMTID, "pid": str(max_pid), "name": name,
            })
            vt_el = ET.SubElement(prop, f"{{{_VT_NS}}}{tag}")
            vt_el.text = text
            changed += 1

    return ET.tostring(root, encoding="UTF-8", xml_declaration=True), changed


_FLDSIMPLE_RE = re.compile(
    r'(<w:fldSimple w:instr="[^"]*\bDOCPROPERTY\s+(\w+)\b[^"]*"[^>]*>)(.*?)(</w:fldSimple>)',
    re.DOTALL,
)
_INNER_TEXT_RE = re.compile(r'(<w:t[^>]*>)(.*?)(</w:t>)', re.DOTALL)


def _fill_docproperty_fields(document_xml: str, properties: dict[str, dict]) -> tuple[str, list[str]]:
    """Replace the cached <w:t> result inside every DOCPROPERTY w:fldSimple
    with the real value from `properties`. A field bound to a name NOT present
    in `properties` is left untouched (its doc-properties.lua placeholder
    stays); the caller warns, naming the unbound names."""
    unbound: list[str] = []

    def _repl(m: re.Match) -> str:
        open_tag, name, inner, close_tag = m.group(1), m.group(2), m.group(3), m.group(4)
        if name not in properties:
            unbound.append(name)
            return m.group(0)
        _, text = _vt_element(properties[name]["type"], properties[name]["value"])
        escaped = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        new_inner, n = _INNER_TEXT_RE.subn(lambda tm: tm.group(1) + escaped + tm.group(3), inner, count=1)
        return (open_tag + new_inner + close_tag) if n else m.group(0)

    new_xml = _FLDSIMPLE_RE.sub(_repl, document_xml)
    return new_xml, unbound


def process(path: Path, properties: dict[str, dict], check: bool = False) -> int:
    """Write/merge docProps/custom.xml and fill matching DOCPROPERTY field
    caches in `path`. Returns the number of properties actually written or
    updated (0 = already up to date; a true idempotent no-op that rewrites
    nothing to disk, even outside --check). check=True reports only."""
    if not properties:
        return 0
    members = _read_members(path)
    names = {n for n, _ in members}
    existing_custom = next((d for n, d in members if n == CUSTOM_PART), None)
    new_custom_xml, changed_count = _merge_custom_xml(existing_custom, properties)

    document_xml_bytes = next((d for n, d in members if n == "word/document.xml"), None)
    document_xml = document_xml_bytes.decode("utf-8") if document_xml_bytes is not None else None
    if document_xml is not None:
        new_document_xml, unbound = _fill_docproperty_fields(document_xml, properties)
    else:
        new_document_xml, unbound = document_xml, []
    fields_changed = new_document_xml != document_xml

    if unbound:
        uniq = sorted(set(unbound))
        print(
            f"NOTE: {path}: DOCPROPERTY field(s) reference propert{'y' if len(uniq) == 1 else 'ies'} "
            f"not declared under custom_properties in --template-profile: {uniq} "
            "-- left as the doc-properties.lua placeholder, not filled in.",
            file=sys.stderr,
        )

    if changed_count == 0 and not fields_changed:
        return 0
    if check:
        return changed_count or 1

    new_members = []
    custom_written = False
    for n, d in members:
        if n == CUSTOM_PART:
            new_members.append((n, new_custom_xml))
            custom_written = True
        elif n == "word/document.xml" and fields_changed:
            new_members.append((n, new_document_xml.encode("utf-8")))
        else:
            new_members.append((n, d))
    if not custom_written:
        new_members.append((CUSTOM_PART, new_custom_xml))
    if CUSTOM_PART not in names:
        new_members = _register_custom_part(new_members)

    _write_members(path, new_members)
    return changed_count


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Write docProps/custom.xml and fill DOCPROPERTY field caches from "
                    "--template-profile's custom_properties key (post-render, in place)."
    )
    ap.add_argument("docx", nargs="+", type=Path)
    ap.add_argument("--template-profile", type=Path, default=None)
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    properties = load_custom_properties(args.template_profile)
    if not properties:
        print("custom properties: none configured (no custom_properties key in --template-profile), skipping.")
        return 0

    rc = 0
    for docx in args.docx:
        n = process(docx, properties, check=args.check)
        if n == 0:
            print(f"{docx}: custom properties already up to date")
            continue
        verb = "would update" if args.check else "updated"
        print(f"{docx}: {verb} {n} custom propert{'y' if n == 1 else 'ies'}")
        if args.check:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
