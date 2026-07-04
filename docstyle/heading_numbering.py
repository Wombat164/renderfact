#!/usr/bin/env python3
"""
heading_numbering.py: POST-RENDER injection of field-based heading numbering.

Pandoc regenerates word/numbering.xml on every render and DROPS custom list
definitions imported from a --reference-doc, so binding heading styles to a
multilevel list in the reference template alone does NOT survive. This step runs
AFTER pandoc (like the style post-processor) and injects, idempotently, into the
RENDERED docx:

  1. word/numbering.xml: one <w:abstractNum> (id 8100) with 9 levels linked to
     Heading1..Heading9 via <w:pStyle>; natural decimal numbering:
       1.  /  2.1  /  2.1.1  /  2.1.1.1 ...
     plus the matching <w:num> (numId 8100), schema-correctly placed before any
     trailing <w:numIdMacAtCleanup>.
  2. word/styles.xml: <w:numPr> (numId 8100, ilvl 0-3) on Heading1-4, inserted in
     schema-correct CT_PPr position.

Result: section numbers are Word FIELDS that renumber automatically on manual
insert / reorder / delete. The markdown source must carry number-free headings,
and the render scripts must NOT pass `--number-sections` (which bakes static text).

Usage (post-render, in place):
  python heading_numbering.py OUT1.docx [OUT2.docx ...]
  python heading_numbering.py --check OUT.docx     # report only
Idempotent: re-running on an already-numbered docx is a no-op.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

NUMID = "8100"
ABSTRACTID = "8100"
HEADING_STYLE_IDS = ["Heading1", "Heading2", "Heading3", "Heading4"]
PPR_ANCHORS = ["<w:spacing", "<w:ind", "<w:jc", "<w:outlineLvl"]
EMPTY_NUMBERING = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '</w:numbering>'
)


# inferred number-type vocabulary (template-analysis stage) -> OOXML w:numFmt val
NUMFMT = {"decimal": "decimal", "lower-alpha": "lowerLetter", "upper-alpha": "upperLetter",
          "lower-roman": "lowerRoman", "upper-roman": "upperRoman"}


def build_abstract_num(scheme: str = "modern", levels=None) -> str:
    """Multilevel heading numbering bound to Heading1..9.

      modern       -> 1. / 2.1 / 2.1.1   (level 0 carries a trailing dot; deeper levels do not)
      trailing-dot -> 1. / 1.1. / 1.1.1. (the `%N.` convention: trailing dot at EVERY level)

    `levels` (optional) is a per-level OOXML numFmt list (ilvl 0-first), e.g.
    ['decimal','decimal','lowerLetter','lowerRoman'] -> mixed grammar 1 / 1.1 / 1.1.a / 1.1.a.i.
    It changes ONLY the per-level numFmt; the dot/lvlText convention is unchanged, so the cumulative
    %1.%2.%3 lvlText lets Word render each %k with level-k's own numFmt. When None (default) every
    level is decimal.
    """
    trailing = (scheme == "trailing-dot")
    lvls = []
    for i in range(9):
        numfmt = "decimal"  # natural decimal numbering (matches corpus + cross-refs)
        if levels and i < len(levels) and levels[i]:
            numfmt = levels[i]
        if i == 0:
            lvl_text = "%1."
        else:
            joined = ".".join(f"%{k+1}" for k in range(i + 1))
            lvl_text = joined + "." if trailing else joined
        lvls.append(
            f'<w:lvl w:ilvl="{i}">'
            f'<w:start w:val="1"/><w:numFmt w:val="{numfmt}"/>'
            f'<w:pStyle w:val="Heading{i+1}"/><w:suff w:val="space"/>'
            f'<w:lvlText w:val="{lvl_text}"/><w:lvlJc w:val="left"/>'
            f'<w:pPr><w:ind w:left="0" w:firstLine="0"/></w:pPr></w:lvl>'
        )
    return (f'<w:abstractNum w:abstractNumId="{ABSTRACTID}">'
            f'<w:multiLevelType w:val="multilevel"/>' + "".join(lvls) + '</w:abstractNum>')


def levels_from_profile(path):
    """Read a template-profile yaml; if it carries a heading_scaffold, return the per-level OOXML
    numFmt list (ilvl-0 first). Returns None when absent/unparseable -> caller falls back to decimal.
    Cheap text guard first so the common (no-scaffold) path needs no YAML dependency."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    if "heading_scaffold" not in text:
        return None
    try:
        import yaml
    except ImportError:
        print("  --profile: PyYAML unavailable; cannot read heading_scaffold (using --scheme)", file=sys.stderr)
        return None
    try:
        data = yaml.safe_load(text) or {}
    except Exception:   # noqa: BLE001  (malformed yaml -> fall back)
        return None
    hs = data.get("heading_scaffold") or {}
    m = {}
    for it in (hs.get("levels") or []):
        lvl = it.get("level")
        if lvl:
            m[lvl] = NUMFMT.get((it.get("number") or {}).get("type"), "decimal")
    return [m.get(i + 1, "decimal") for i in range(max(m))] if m else None


def levels_from_csv(s):
    """Explicit per-level list; accepts the friendly vocab (lower-alpha) OR raw OOXML (lowerLetter)."""
    out = [NUMFMT.get(t.strip(), t.strip()) for t in s.split(",") if t.strip()]
    return out or None


def build_num() -> str:
    return f'<w:num w:numId="{NUMID}"><w:abstractNumId w:val="{ABSTRACTID}"/></w:num>'


def patch_numbering_xml(xml: str, scheme: str = "modern", levels=None) -> tuple[str, bool]:
    if f'w:abstractNumId="{ABSTRACTID}"' in xml and f'w:numId="{NUMID}"' in xml:
        return xml, False
    m = re.search(r"<w:num\b", xml)  # abstractNum* must precede num*
    if m:
        xml = xml[: m.start()] + build_abstract_num(scheme, levels) + xml[m.start():]
    else:
        xml = xml.replace("</w:numbering>", build_abstract_num(scheme, levels) + "</w:numbering>")
    m2 = re.search(r"<w:numIdMacAtCleanup\b", xml)  # num* precedes numIdMacAtCleanup?
    if m2:
        xml = xml[: m2.start()] + build_num() + xml[m2.start():]
    else:
        xml = xml.replace("</w:numbering>", build_num() + "</w:numbering>")
    return xml, True


def patch_styles_xml(xml: str) -> tuple[str, list[str]]:
    patched = []
    for ilvl, sid in enumerate(HEADING_STYLE_IDS):
        m = re.search(r'<w:style[^>]*w:styleId="' + sid + r'"[^>]*>.*?</w:style>', xml, re.DOTALL)
        if not m:
            continue
        block = m.group(0)
        if "<w:numPr>" in block:
            continue
        numpr = f'<w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{NUMID}"/></w:numPr>'
        if "<w:pPr>" in block:
            s = block.index("<w:pPr>") + len("<w:pPr>")
            e = block.index("</w:pPr>")
            inner = block[s:e]
            pos = len(inner)
            for a in PPR_ANCHORS:
                f = inner.find(a)
                if f != -1:
                    pos = min(pos, f)
            new_block = block[:s] + inner[:pos] + numpr + inner[pos:] + block[e:]
        elif "<w:pPr/>" in block:
            new_block = block.replace("<w:pPr/>", f"<w:pPr>{numpr}</w:pPr>", 1)
        else:
            nm = re.search(r"</w:name>", block)
            if not nm:
                continue
            new_block = block[: nm.end()] + f"<w:pPr>{numpr}</w:pPr>" + block[nm.end():]
        xml = xml.replace(block, new_block, 1)
        patched.append(sid)
    return xml, patched


def ensure_numbering_wired(content_types: str, doc_rels: str) -> tuple[str, str, bool]:
    """If numbering.xml had to be created, declare it + add a relationship."""
    changed = False
    if "word/numbering.xml" not in content_types:
        decl = ('<Override PartName="/word/numbering.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>')
        content_types = content_types.replace("</Types>", decl + "</Types>")
        changed = True
    if "numbering.xml" not in doc_rels:
        rid = "rIdNum8100"
        rel = (f'<Relationship Id="{rid}" '
               'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" '
               'Target="numbering.xml"/>')
        doc_rels = doc_rels.replace("</Relationships>", rel + "</Relationships>")
        changed = True
    return content_types, doc_rels, changed


def process(docx: Path, check: bool, scheme: str = "modern", levels=None) -> int:
    if not docx.exists():
        print(f"  ERROR missing: {docx}")
        return 2
    with zipfile.ZipFile(docx) as z:
        infos = z.infolist()
        mem = {i.filename: z.read(i.filename) for i in infos}

    had_numbering = "word/numbering.xml" in mem
    num_xml = mem.get("word/numbering.xml", EMPTY_NUMBERING.encode()).decode("utf-8")
    sty_xml = mem["word/styles.xml"].decode("utf-8")
    new_num, num_changed = patch_numbering_xml(num_xml, scheme, levels)
    new_sty, styles_patched = patch_styles_xml(sty_xml)

    if not num_changed and not styles_patched:
        print(f"  {docx.name}: already numbered (no-op)")
        return 0
    print(f"  {docx.name}: numbering {'+list' if num_changed else '(ok)'}; headings: {styles_patched or '(ok)'}")
    if check:
        return 0

    mem["word/numbering.xml"] = new_num.encode("utf-8")
    mem["word/styles.xml"] = new_sty.encode("utf-8")
    if not had_numbering:
        ct = mem["[Content_Types].xml"].decode("utf-8")
        rels_name = "word/_rels/document.xml.rels"
        rels = mem[rels_name].decode("utf-8")
        ct, rels, _ = ensure_numbering_wired(ct, rels)
        mem["[Content_Types].xml"] = ct.encode("utf-8")
        mem[rels_name] = rels.encode("utf-8")

    # atomic in-place rewrite
    fd, tmp = tempfile.mkstemp(suffix=".docx", dir=str(docx.parent))
    os.close(fd)
    order = [i.filename for i in infos]
    for fn in mem:
        if fn not in order:
            order.append(fn)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for fn in order:
            zo.writestr(fn, mem[fn])
    os.replace(tmp, docx)
    print(f"    numbered in place: {docx.name}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("docx", nargs="+", type=Path)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--scheme", default="modern", choices=("modern", "trailing-dot"),
                    help="decimal numbering scheme: modern (1. / 2.1) | trailing-dot (1. / 1.1.)")
    ap.add_argument("--profile", default=None,
                    help="template-profile yaml; if it carries a heading_scaffold, its inferred "
                         "per-level grammar (mixed decimal/alpha/roman) drives the numbering. "
                         "No scaffold -> falls back to --scheme. Safe to always pass.")
    ap.add_argument("--levels", default=None,
                    help="explicit per-level numFmt CSV, overrides --profile "
                         "(e.g. 'decimal,decimal,lower-alpha,lower-roman' or OOXML 'decimal,lowerLetter')")
    args = ap.parse_args()

    levels, source = None, None
    if args.levels:
        levels, source = levels_from_csv(args.levels), "explicit --levels"
    elif args.profile:
        levels = levels_from_profile(args.profile)
        if levels:
            source = f"heading_scaffold in {os.path.basename(args.profile)}"
    if levels:
        print(f"  numbering grammar: {','.join(levels)}  (source: {source})")
    else:
        print(f"  numbering grammar: decimal (scheme: {args.scheme})")

    rc = 0
    for d in args.docx:
        rc = process(d, args.check, args.scheme, levels) or rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
