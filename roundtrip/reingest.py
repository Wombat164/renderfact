#!/usr/bin/env python3
"""reingest.py: mechanical DOCX re-ingestion (D11 part 3a, chunk 4.4). No LLM.

Forward: canonical markdown renders to a DOCX that goes out for review. Reverse:
the edited DOCX comes back (possibly carrying Word comments, tracked changes,
rewording, deletions) and this module surfaces, deterministically, everything a
reviewer touched, anchored to provenance:

  0. Provenance verdict: the artifact's embedded renderfact provenance is checked
     against the canonical source. UID mismatch is a hard error (wrong source).
     source_version equal to the source's CURRENT content version = FAST_FORWARD
     (nobody touched the source while the DOCX was out: the delta below is purely
     the reviewer's). Different = DIVERGED (the source evolved in the meantime;
     three-way merge is chunk 4.6, so this run reports and refuses to apply).
  1. Word comments (author, date, body).
  2. Tracked changes (w:ins / w:del with authors; note that the plain text view
     below reads as if changes were accepted: w:delText is not part of visible text).
  3. Document structure (headings, paragraphs, tables with per-column widths).
  4. A normalized text delta between the canonical markdown and the edited DOCX
     (difflib): additions, deletions, rewording, spelling fixes.

DEFAULT IS REPORT-ONLY: the canonical source is never written unless --apply is
given, and --apply is deliberately narrow: it back-ports ONLY the mechanically
safe subset: 1:1 reworded lines whose markdown original is markup-free (beyond a
leading bullet/heading marker) and whose normalized text occurs exactly once in
the source. Everything else stays in the report for a human (or a future
LLM-contextualize step, chunk 4.5) to handle. Generalized from a private
consumer's proven reverse-pipeline extractor; the extraction core is a faithful
port (stdlib only: zipfile, ElementTree, difflib).

Usage:
    render reingest <edited.docx> --source <canonical.md>
                    [--report out.md] [--json] [--apply]
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TWIPS_PER_CM = 566.93


class ReingestError(RuntimeError):
    """A user-facing re-ingestion mistake (wrong artifact/source pairing, no
    provenance, applying on a diverged source): clean message, not a traceback."""


# ---------------------------------------------------------------- extraction --

def _text(el) -> str:
    return "".join(t.text or "" for t in el.iter(f"{W}t"))


def _pstyle(p) -> str:
    pr = p.find(f"{W}pPr")
    if pr is None:
        return ""
    st = pr.find(f"{W}pStyle")
    return st.get(f"{W}val") if st is not None else ""


def extract_comments(z: zipfile.ZipFile) -> list[dict]:
    if "word/comments.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("word/comments.xml").decode("utf-8", "ignore"))
    out = []
    for c in root.findall(f"{W}comment"):
        out.append({
            "id": c.get(f"{W}id"),
            "author": c.get(f"{W}author") or "?",
            "date": c.get(f"{W}date") or "",
            "text": _text(c).strip(),
        })
    return out


def _opc_identifier(data: bytes) -> str | None:
    """dc:identifier from any OPC/OOXML zip (docx, xlsx, pptx, AND vsdx: all
    carry docProps/core.xml), read with plain zipfile + ElementTree so no
    per-format library is needed on embedded bytes. None for non-zip or
    core-less content."""
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "docProps/core.xml" not in z.namelist():
                return None
            root = ET.fromstring(z.read("docProps/core.xml"))
            el = root.find("{http://purl.org/dc/elements/1.1/}identifier")
            return el.text if el is not None else None
    except (zipfile.BadZipFile, ET.ParseError, OSError):
        return None


_RENDERFACT_PREFIX = "renderfact:v1:"


def _markitdown_preview(data: bytes, suffix: str) -> tuple[str | None, str]:
    """Best-effort text preview of a non-OOXML embedded object via markitdown
    (optional dependency, extras: embedded-preview). Returns (preview, note)."""
    import io

    try:
        from markitdown import MarkItDown
    except ImportError:
        return None, "no preview: pip install markitdown to extract text from this type"
    try:
        result = MarkItDown().convert_stream(io.BytesIO(data), file_extension=f".{suffix}")
        text = (result.text_content or "").strip()
        return (text[:280] or None), "markitdown preview"
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:
        # BaseException deliberately: markitdown's own UnsupportedFormatException
        # does NOT inherit from Exception (verified against the real library),
        # so a plain `except Exception` lets it escape and crash the report.
        return None, f"markitdown could not convert: {str(e)[:120]}"


def extract_embedded(z: zipfile.ZipFile) -> list[dict]:
    """Inventory + PROVENANCE TRIAGE of OLE-embedded objects (word/embeddings/).
    SURFACED, not silently ignored: a reviewer can edit an embedded workbook too.
    Three classes, treated differently (operator requirement, 2026-07-04):

      renderfact-tracked  the embedded OPC doc carries renderfact provenance:
                          it belongs to this round-trip world; re-ingest it via
                          its own per-format path against ITS canonical source
      unknown-origin      an OPC/OOXML doc (docx/xlsx/pptx/vsdx) WITHOUT
                          renderfact provenance: a foreign attachment; consider
                          'render provenance adopt' to bring it under governance
      foreign             any other type (pdf, bin, ole): tried through
                          markitdown for a text preview when available

    Deep diffing of embedded documents rides the per-format round-trip paths."""
    ooxml = {"docx", "xlsx", "pptx", "vsdx"}
    out = []
    for info in z.infolist():
        # embeddings live under word/embeddings/ in DOCX, but XLSX (xl/), PPTX
        # (ppt/) and VSDX hosts carry them too (operator note, 2026-07-04):
        # match the path segment, not one host's prefix
        if "/embeddings/" not in info.filename:
            continue
        name = info.filename.split("/")[-1]
        kind = Path(name).suffix.lstrip(".").lower() or "ole"
        data = z.read(info.filename)
        entry = {"name": name, "bytes": info.file_size, "kind": kind,
                 "status": "foreign", "provenance": None, "preview": None, "note": ""}
        identifier = _opc_identifier(data)
        if identifier and identifier.startswith(_RENDERFACT_PREFIX):
            try:
                payload = json.loads(identifier[len(_RENDERFACT_PREFIX):])
            except json.JSONDecodeError:
                payload = {"raw": identifier}
            entry["status"] = "renderfact-tracked"
            entry["provenance"] = payload
            entry["note"] = "re-ingest via its own per-format path against ITS canonical source"
        elif identifier is not None or kind in ooxml:
            entry["status"] = "unknown-origin"
            entry["note"] = (("carries a foreign identifier; " if identifier else "")
                             + "no renderfact provenance: consider 'render provenance adopt'")
        else:
            preview, note = _markitdown_preview(data, kind)
            entry["preview"] = preview
            entry["note"] = note
        out.append(entry)
    return out


def extract_tracked(doc_root) -> tuple[list, list]:
    ins, dele = [], []
    for el in doc_root.iter():
        if el.tag == f"{W}ins":
            txt = _text(el).strip()
            if txt:
                ins.append((el.get(f"{W}author") or "?", txt))
        elif el.tag == f"{W}del":
            # deleted text lives in w:delText, not w:t
            txt = "".join(t.text or "" for t in el.iter(f"{W}delText")).strip()
            if txt:
                dele.append((el.get(f"{W}author") or "?", txt))
    return ins, dele


def walk_structure(body) -> list[tuple]:
    """Linear list of ('heading'|'para'|'table', payload). Tables carry cell rows + widths."""
    items = []
    for el in list(body):
        tag = el.tag.split("}")[-1]
        if tag == "p":
            txt = _text(el).strip()
            if not txt:
                continue
            style = _pstyle(el)
            items.append(("heading" if style.startswith("Heading") or style in ("Title", "Subtitle") else "para",
                          {"style": style, "text": txt}))
        elif tag == "tbl":
            grid = el.find(f"{W}tblGrid")
            cols = [int(gc.get(f"{W}w")) for gc in grid.findall(f"{W}gridCol")] if grid is not None else []
            tot = sum(cols) or 1
            rows = []
            for r in el.findall(f"{W}tr"):
                rows.append([_text(c).strip() for c in r.findall(f"{W}tc")])
            items.append(("table", {
                "rows": rows,
                "cm": [round(c / TWIPS_PER_CM, 2) for c in cols],
                "pct": [round(100 * c / tot) for c in cols],
                "header": rows[0] if rows else [],
            }))
    return items


# ------------------------------------------------------------- normalization --

def _norm(s: str) -> str:
    """Normalize away render artifacts so the diff shows only real reviewer edits:
    non-breaking spaces, list bullets, auto-numbered headings, collapsed whitespace."""
    s = s.replace(" ", " ").replace("﻿", "")
    s = re.sub(r"^#> \s*\d+(\.\d+)*\.?\s+", "#> ", s)  # docx auto-numbers headings; md does not
    s = re.sub(r"^[-*•]\s+", "", s)               # list bullets are formatting, not text
    s = re.sub(r"\s+", " ", s).strip()
    return s


def docx_plaintext(items) -> list[str]:
    """Flatten docx structure to comparable lines (headings prefixed, table rows piped)."""
    lines = []
    for kind, p in items:
        if kind == "heading":
            lines.append(f"#> {p['text']}")
        elif kind == "para":
            lines.append(p["text"])
        elif kind == "table":
            for row in p["rows"]:
                lines.append("| " + " | ".join(row) + " |")
    return lines


def md_plaintext(md: str) -> list[str]:
    """Strip frontmatter + HTML comments + image lines; normalize headings/tables to compare."""
    md = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.DOTALL)
    md = re.sub(r"<!--.*?-->", "", md, flags=re.DOTALL)
    out = []
    for ln in md.split("\n"):
        s = ln.strip()
        if not s or s in ("\\newpage",):
            continue
        if s.startswith("!["):  # image embed: not in docx text
            continue
        if re.match(r"^#{1,6}\s", s):
            out.append("#> " + re.sub(r"^#{1,6}\s+", "", s).replace("**", ""))
        elif set(s) <= set("|:- "):  # table separator row
            continue
        else:
            out.append(s.replace("**", "").replace("`", ""))
    return out


# --------------------------------------------------------------- provenance --

def _source_declared_uid(source_path: Path) -> str | None:
    import yaml

    text = source_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not m:
        return None
    fm = yaml.safe_load(m.group(1)) or {}
    return fm.get("renderfact_uid")


def check_provenance(artifact_path: Path, source_path: Path):
    """Return (provenance, verdict): verdict is FAST_FORWARD or DIVERGED.
    Fail closed on: artifact without provenance, source without a UID, UID mismatch."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import provenance as prov_mod
    import source_uid as uid_mod

    prov = prov_mod.extract(artifact_path)
    if prov is None:
        raise ReingestError(
            f"{artifact_path} carries no renderfact provenance: re-ingestion cannot anchor "
            f"it to a source version (use 'render provenance adopt' for externally-authored drafts)"
        )
    declared = _source_declared_uid(source_path)
    if declared is None:
        raise ReingestError(
            f"{source_path} declares no renderfact_uid: it is not the canonical source this "
            f"artifact was rendered from (or was never rendered with provenance)"
        )
    if declared != prov.source_uid:
        raise ReingestError(
            f"UID mismatch: {artifact_path} was rendered from source {prov.source_uid}, "
            f"but {source_path} is {declared}: wrong artifact/source pairing"
        )
    current = uid_mod.content_version(source_path)
    verdict = "FAST_FORWARD" if current == prov.source_version else "DIVERGED"
    return prov, verdict


# -------------------------------------------------------------------- apply --

_INLINE_MARKUP = re.compile(r"(\*\*|__|`|\[[^\]]*\]\()")
_LEADING_MARKER = re.compile(r"^(\s*(?:[-*]\s+|#{1,6}\s+|\d+\.\s+)?)")


# Sentinels + deferral reasons a `manual`-review item can carry. Named so
# downstream consumers (roundtrip/contextualize.py's confidence classifier)
# match on the constant, not a magic string re-typed a second time.
ADDED_MARKER = "(added in the edited DOCX)"
DELETED_MARKER = "(deleted in the edited DOCX)"
WHY_NOT_UNIQUE = "normalized text not unique in the source"
WHY_INLINE_MARKUP = "line carries inline markup a text edit would destroy"
WHY_HEADING = "heading edits change structure: review by hand"


def plan_fast_forward(md_text: str, md_lines_norm: list[str],
                      dx_lines_norm: list[str], dx_lines_raw: list[str]) -> tuple[list, list]:
    """The mechanically safe subset: 1:1 reworded lines (equal-length replace
    opcodes) whose markdown original is markup-free beyond a leading marker and
    whose normalized text occurs exactly once in the source. Returns
    (applicable edits, manual-review edits); an edit is (old_norm, new_raw)."""
    apply_list, manual = [], []
    sm = difflib.SequenceMatcher(a=md_lines_norm, b=dx_lines_norm, autojunk=False)
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op != "replace":
            if op in ("delete", "insert"):
                for i in range(a1, a2):
                    manual.append((md_lines_norm[i], DELETED_MARKER))
                for j in range(b1, b2):
                    manual.append((ADDED_MARKER, dx_lines_raw[j]))
            continue
        if (a2 - a1) != (b2 - b1):
            for i, j in zip(range(a1, a2), range(b1, b2)):
                manual.append((md_lines_norm[i], dx_lines_raw[j]))
            continue
        for i, j in zip(range(a1, a2), range(b1, b2)):
            apply_list.append((md_lines_norm[i], dx_lines_raw[j]))

    source_lines = md_text.split("\n")
    safe, deferred = [], []
    for old_norm, new_raw in apply_list:
        matches = [k for k, ln in enumerate(source_lines) if _norm_source_line(ln) == old_norm]
        if len(matches) != 1:
            deferred.append((old_norm, new_raw, WHY_NOT_UNIQUE))
            continue
        line = source_lines[matches[0]]
        marker = _LEADING_MARKER.match(line).group(1)
        rest = line[len(marker):]
        if _INLINE_MARKUP.search(rest):
            deferred.append((old_norm, new_raw, WHY_INLINE_MARKUP))
            continue
        if old_norm.startswith("#> "):
            deferred.append((old_norm, new_raw, WHY_HEADING))
            continue
        safe.append((matches[0], marker, new_raw, old_norm))
    manual.extend(deferred)
    return safe, manual


def _norm_source_line(ln: str) -> str:
    s = ln.strip()
    if not s or s.startswith("![") or s == "\\newpage" or set(s) <= set("|:- "):
        return ""
    if re.match(r"^#{1,6}\s", s):
        return _norm("#> " + re.sub(r"^#{1,6}\s+", "", s).replace("**", ""))
    return _norm(s.replace("**", "").replace("`", ""))


def apply_fast_forward(source_path: Path, safe_edits: list) -> int:
    text = source_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    for idx, marker, new_raw, _old in safe_edits:
        lines[idx] = marker + new_raw
    source_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return len(safe_edits)


# ------------------------------------------------------------------- report --

def build_report(artifact: Path, prov, verdict: str, comments, ins, dele,
                 items, delta_lines: list[str], safe, manual, applied: int | None,
                 embedded: list[dict] | None = None) -> str:
    tables = [p for k, p in items if k == "table"]
    R = [f"# Re-ingestion extract: {artifact.name}\n"]
    R.append(f"## 0. Provenance verdict: {verdict}\n")
    R.append(f"- source_uid: {prov.source_uid}")
    R.append(f"- rendered from source_version {prov.source_version} at {prov.rendered_at} "
             f"(tool {prov.tool_version}" +
             (f", source commit {prov.source_commit}" if getattr(prov, 'source_commit', None) else "") + ")")
    if verdict == "FAST_FORWARD":
        R.append("- the canonical source is UNCHANGED since this render: the delta below is "
                 "purely the reviewer's")
    else:
        R.append("- the canonical source EVOLVED since this render: three-way merge territory "
                 "(chunk 4.6); apply is refused, reconcile by hand")
    R.append("")
    R.append("## 1. Word comments (reviewer feedback to address)\n")
    R.extend([f"- **{c['author']}** ({c['date'][:10]}): {c['text']}" for c in comments] or ["- (none)"])
    R.append("")
    R.append("## 2. Tracked changes (accept/reject + reconcile)\n")
    if ins or dele:
        R.extend([f"- INSERT [{au}]: {t[:300]}" for au, t in ins])
        R.extend([f"- DELETE [{au}]: {t[:300]}" for au, t in dele])
    else:
        R.append("- (none: edits are direct/accepted; rely on the delta below)")
    R.append("")
    if embedded:
        R.append("## 2b. Embedded objects (NOT diffed here: triaged by provenance)\n")
        for e in embedded:
            line = f"- {e['name']} ({e['kind']}, {e['bytes']} bytes): {e['status'].upper()}"
            if e.get("provenance"):
                line += f" uid={e['provenance'].get('source_uid', '?')}"
            R.append(line)
            if e.get("note"):
                R.append(f"    {e['note']}")
            if e.get("preview"):
                R.append(f"    preview: {e['preview'][:160]}")
        R.append("")
    R.append("## 3. Table column widths (formatting to canonicalize)\n")
    for i, t in enumerate(tables, 1):
        hdr = " | ".join(h[:18] for h in t["header"])
        R.append(f"- T{i} ({len(t['rows'])} rows) [{hdr}]")
        R.append(f"    widths %: {t['pct']}   cm: {t['cm']}")
    R.append("")
    R.append("## 4. Text delta vs canonical markdown\n")
    R.append("> `+` = in the edited DOCX (reviewer ADDED); `-` = only in the md "
             "(reviewer DELETED or reworded). A -/+ pair is a rewording.\n")
    R.extend(delta_lines or ["(no text delta: only formatting changed)"])
    R.append("")
    R.append("## 5. Fast-forward plan (the mechanically safe subset)\n")
    if applied is not None:
        R.append(f"- APPLIED {applied} line edit(s) to the canonical source")
    R.extend([f"- safe: '{old[:80]}' -> '{new[:80]}'" for _i, _m, new, old in safe] or ["- (none)"])
    if manual:
        R.append("")
        R.append(f"### Manual review ({len(manual)}):")
        R.extend([f"- {a[:80]!r} -> {b[:80]!r}" + (f"  [{why}]" if len(entry) > 2 else "")
                  for entry in manual for a, b, *rest in [entry] for why in [rest[0] if rest else ""]])
    return "\n".join(R)


# ---------------------------------------------------------------------- CLI --

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="render reingest",
        description="Mechanical DOCX re-ingestion: provenance verdict + reviewer-edit report "
                    "(+ narrow fast-forward apply). Report-only by default.",
    )
    ap.add_argument("artifact", type=Path, help="the edited .docx that came back from review")
    ap.add_argument("--source", type=Path, required=True, help="the canonical markdown source")
    ap.add_argument("--report", type=Path, default=None, help="write the report here instead of stdout")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--apply", action="store_true",
                    help="apply the mechanically safe fast-forward subset to the source "
                         "(refused on a DIVERGED verdict)")
    args = ap.parse_args(argv)

    try:
        if args.artifact.suffix.lower() != ".docx":
            raise ReingestError(f"re-ingestion is DOCX-only for now: {args.artifact}")
        if not args.artifact.exists():
            raise ReingestError(f"artifact not found: {args.artifact}")
        if not args.source.exists():
            raise ReingestError(f"source not found: {args.source}")

        prov, verdict = check_provenance(args.artifact, args.source)

        z = zipfile.ZipFile(args.artifact)
        doc_root = ET.fromstring(z.read("word/document.xml").decode("utf-8", "ignore"))
        body = doc_root.find(f"{W}body")
        comments = extract_comments(z)
        ins, dele = extract_tracked(doc_root)
        embedded = extract_embedded(z)
        items = walk_structure(body)

        md_text = args.source.read_text(encoding="utf-8")
        md_lines = [x for x in (_norm(y) for y in md_plaintext(md_text)) if x]
        dx_raw = docx_plaintext(items)
        dx_lines = [x for x in (_norm(y) for y in dx_raw) if x]
        dx_raw = [r for r in dx_raw if _norm(r)]

        diff = difflib.unified_diff(md_lines, dx_lines, lineterm="", n=1)
        delta = [d for d in diff if d and d[0] in "+-" and not d.startswith(("+++", "---"))]

        safe, manual = plan_fast_forward(md_text, md_lines, dx_lines, dx_raw)

        applied = None
        if args.apply:
            if verdict != "FAST_FORWARD":
                raise ReingestError(
                    "refusing --apply: the canonical source evolved since this render "
                    "(DIVERGED); three-way merge is not built yet (chunk 4.6)"
                )
            applied = apply_fast_forward(args.source, safe)

        if args.json:
            print(json.dumps({
                "verdict": verdict,
                "provenance": asdict(prov),
                "comments": comments,
                "tracked_insertions": ins,
                "tracked_deletions": dele,
                "embedded_objects": embedded,
                "delta": delta,
                "safe_edits": [{"line": i, "new": n, "old": o} for i, _m, n, o in safe],
                "manual": [list(m) for m in manual],
                "applied": applied,
            }, indent=2))
            return 0

        report = build_report(args.artifact, prov, verdict, comments, ins, dele,
                              items, delta, safe, manual, applied, embedded=embedded)
        if args.report:
            args.report.write_text(report, encoding="utf-8", newline="\n")
            print(f"wrote {args.report}")
        else:
            print(report)
        return 0
    except ReingestError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
