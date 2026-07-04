#!/usr/bin/env python3
"""render_qa.py: deterministic post-render QA gate for DOCX/PDF renders.

Zero-LLM checks over a rendered artefact pair (DOCX + PDF-extracted text),
generalized 2026-07-03 from a private consumer's proven implementation (which
was itself written to feed this repo's QA-gate concept: deterministic gates run
BEFORE any vision/LLM pass, matching the D8 doctrine that hard numbers
accompany every subjective review). Subcommands:

  leaks   <full.txt>            audience-leak scan on rendered text: internal
                                remnants that should never survive projection
                                (wikilink brackets, changelog remnants,
                                annotation-callout remnants, date-suffixed
                                internal note titles). Consumer-specific probes
                                (codenames, internal paths) come from --probes.
  tables  <render.docx>         per-table column-geometry badness: content share
                                vs width share per column, wrap-pressure ranking
  paras   <render.docx>         overweight-paragraph ranking (simplification
                                candidates)
  figs    <source.md> [figsdir] figure inventory + low-contrast pre-filter
                                (adjacent-pixel luminance sampling, needs Pillow;
                                degrades to inventory-only without it)
  all     <source.md> <render.docx> <full.txt>

Probe config (--probes probes.yaml): a mapping under a top-level `probes:` key,
name -> regex. Merged over the generic defaults (same name overrides); pass
--no-default-probes to use only your own. Example consumer probe file:

    probes:
      "internal codename": "\\\\bPROJECT-NIGHTJAR\\\\b"
      "internal path": "internal-wiki/|/drafts/"

Produce the text input for `leaks` with any PDF text extractor (for example
`pdftotext full.pdf full.txt`, page breaks as form feeds).

Output: human-readable findings to stdout. Exit 0 by default (report-only);
`leaks --fail-on-hits` exits 1 when any probe hits, for CI gating.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# ---------------------------------------------------------------- leaks ----
# Generic defaults only: remnants of THIS framework's own source conventions.
# Anything naming a consumer's codenames/paths belongs in their --probes file.
DEFAULT_LEAK_PROBES = {
    "date-suffixed internal note title": r"\(20\d\d-\d\d\)",
    "surviving wikilink brackets": r"\[\[",
    "changelog remnant": r"Change Summary|[Cc]hangelog|[Mm]igration ledger",
    "annotation-callout remnant": r"source-note|open-question\]|staleness\]",
}


def load_probes(path: str | None, use_defaults: bool = True) -> dict[str, str]:
    probes = dict(DEFAULT_LEAK_PROBES) if use_defaults else {}
    if path:
        import yaml

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        extra = data.get("probes", data)
        if not isinstance(extra, dict):
            raise SystemExit(f"probes file {path}: expected a mapping under 'probes:'")
        probes.update({str(k): str(v) for k, v in extra.items()})
    return probes


def cmd_leaks(txt_path: str, probes: dict[str, str], fail_on_hits: bool = False) -> int:
    with open(txt_path, encoding="utf-8") as f:
        text = f.read()
    pages = text.split("\f")
    print(f"== LEAKS scan: {txt_path} ({len(pages)} pages)")
    total = 0
    for name, pat in probes.items():
        hits = []
        for i, page in enumerate(pages, 1):
            for line in page.splitlines():
                if re.search(pat, line):
                    hits.append((i, line.strip()[:110]))
        total += len(hits)
        print(f"\n-- {name}: {len(hits)} hit(s)")
        for pg, line in hits[:12]:
            print(f"   p{pg}: {line}")
        if len(hits) > 12:
            print(f"   ... +{len(hits) - 12} more")
    print(f"\nTOTAL leak hits: {total}")
    return 1 if (fail_on_hits and total) else 0


# --------------------------------------------------------------- tables ----
def _docx_xml(docx_path: str) -> str:
    with zipfile.ZipFile(docx_path) as z:
        return z.read("word/document.xml").decode("utf-8")


def _cell_texts(row_xml: str) -> list[str]:
    cells = re.findall(r"<w:tc\b.*?</w:tc>", row_xml, re.S)
    return ["".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", c, re.S)) for c in cells]


def cmd_tables(docx_path: str, top: int = 15) -> int:
    xml = _docx_xml(docx_path)
    # walk body in order so each table gets its nearest preceding heading
    events = []
    for m in re.finditer(r"<w:tbl\b.*?</w:tbl>|<w:p\b.*?</w:p>", xml, re.S):
        events.append(m.group(0))
    heading = "(start)"
    results = []
    tbl_idx = 0
    for ev in events:
        if ev.startswith("<w:p"):
            # Heading style ids, including localized Word variants (e.g. Kop = NL)
            if re.search(r'w:val="Heading\d"', ev) or re.search(r'w:val="Kop\d"', ev):
                t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", ev, re.S)).strip()
                if t:
                    heading = t[:70]
            continue
        tbl_idx += 1
        widths = [int(w) for w in re.findall(r'<w:gridCol w:w="(\d+)"', ev)]
        rows = re.findall(r"<w:tr\b.*?</w:tr>", ev, re.S)
        if not widths or not rows:
            continue
        ncol = len(widths)
        maxlen = [0] * ncol
        sumlen = [0] * ncol
        for r in rows:
            for ci, t in enumerate(_cell_texts(r)[:ncol]):
                maxlen[ci] = max(maxlen[ci], len(t))
                sumlen[ci] += len(t)
        total_w = sum(widths) or 1
        total_c = sum(sumlen) or 1
        worst = 0.0
        worst_col = -1
        for ci in range(ncol):
            wshare = widths[ci] / total_w
            cshare = sumlen[ci] / total_c
            if cshare > 0.05:  # ignore trivially small columns
                pressure = cshare / max(wshare, 0.01)
                if pressure > worst:
                    worst, worst_col = pressure, ci
        # secondary signal: a very long single cell in a narrow column
        wrapscore = max(
            (maxlen[ci] / max(widths[ci] / 120.0, 1))  # rough chars per line
            for ci in range(ncol)
        )
        results.append((worst, wrapscore, tbl_idx, ncol, len(rows), heading, worst_col, widths, maxlen))
    results.sort(key=lambda x: (x[0], x[1]), reverse=True)
    print(f"== TABLES geometry: {tbl_idx} tables scanned; top {top} by content-vs-width pressure")
    print("   pressure 1.0 = column width matches its content share; >1.8 = squeezed column\n")
    for worst, wrap, i, ncol, nrows, hd, wc, widths, maxlen in results[:top]:
        print(f"tbl#{i:02d} pressure={worst:4.1f} wrap~{wrap:5.0f} cols={ncol} rows={nrows}  under: {hd}")
        print(f"        widths={widths}  maxcell={maxlen}  squeezed-col={wc}")
    return 0


# ---------------------------------------------------------------- paras ----
def cmd_paras(docx_path: str, top: int = 20, limit_words: int = 110) -> int:
    xml = _docx_xml(docx_path)
    heading = "(start)"
    rows = []
    for m in re.finditer(r"<w:p\b.*?</w:p>", xml, re.S):
        p = m.group(0)
        if re.search(r'w:val="Heading\d"', p):
            t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S)).strip()
            if t:
                heading = t[:70]
            continue
        style = re.search(r'<w:pStyle w:val="([^"]+)"', p)
        stylename = style.group(1) if style else "Normal"
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
        words = len(text.split())
        if words >= limit_words:
            rows.append((words, stylename, heading, text[:90]))
    rows.sort(reverse=True)
    print(f"== PARAS: {len(rows)} paragraph(s) >= {limit_words} words (simplification candidates), top {top}\n")
    for words, style, hd, preview in rows[:top]:
        print(f"{words:4d}w [{style:8.8s}] under: {hd}")
        print(f"      {preview}...")
    return 0


# ----------------------------------------------------------------- figs ----
def _luminance(px) -> float:
    r, g, b = px[0] / 255, px[1] / 255, px[2] / 255

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def cmd_figs(md_path: str, figsdir: str | None = None) -> int:
    with open(md_path, encoding="utf-8") as f:
        src = f.read()
    refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", src)
    base = os.path.dirname(os.path.abspath(md_path))
    root = figsdir or os.path.dirname(base)  # parent of the source dir as fallback root
    print(f"== FIGS: {len(refs)} figure reference(s) in {md_path}\n")
    try:
        from PIL import Image
        havepil = True
    except ImportError:
        havepil = False
        print("   (Pillow not installed: inventory only, no contrast pre-filter)")
    for ref in refs:
        cand = [os.path.join(root, ref), os.path.join(base, ref), ref]
        path = next((c for c in cand if os.path.exists(c)), None)
        if not path:
            print(f"MISSING  {ref}")
            continue
        line = f"ok       {ref}"
        if havepil:
            im = Image.open(path).convert("RGB")
            im.thumbnail((600, 600))
            px = im.load()
            wdt, hgt = im.size
            lowpairs = 0
            samples = 0
            for y in range(1, hgt - 1, 3):
                for x in range(1, wdt - 1, 3):
                    a = px[x, y]
                    b = px[x + 1, y]
                    if a == b:
                        continue
                    la, lb = _luminance(a), _luminance(b)
                    ratio = (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
                    samples += 1
                    # dark-on-dark edge: both sides dark AND weak contrast
                    if ratio < 2.0 and max(la, lb) < 0.25:
                        lowpairs += 1
            share = lowpairs / max(samples, 1)
            flag = "  << LOW-CONTRAST candidate (dark-on-dark edges)" if share > 0.10 else ""
            line += f"  dark-low-contrast-edge-share={share:.2f}{flag}"
        print(line)
    return 0


# ------------------------------------------------------------------ main ----
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="render qa",
        description="Deterministic post-render QA gate (report-only by default).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_leaks = sub.add_parser("leaks", help="audience-leak scan on PDF-extracted text")
    p_leaks.add_argument("textfile")
    p_leaks.add_argument("--probes", default=None, help="consumer probe yaml (probes: name -> regex)")
    p_leaks.add_argument("--no-default-probes", action="store_true")
    p_leaks.add_argument("--fail-on-hits", action="store_true", help="exit 1 on any hit (CI gating)")

    p_tables = sub.add_parser("tables", help="table column-geometry pressure ranking")
    p_tables.add_argument("docx")
    p_tables.add_argument("--top", type=int, default=15)

    p_paras = sub.add_parser("paras", help="overweight-paragraph ranking")
    p_paras.add_argument("docx")
    p_paras.add_argument("--top", type=int, default=20)
    p_paras.add_argument("--limit-words", type=int, default=110)

    p_figs = sub.add_parser("figs", help="figure inventory + low-contrast pre-filter")
    p_figs.add_argument("source_md")
    p_figs.add_argument("figsdir", nargs="?", default=None)

    p_all = sub.add_parser("all", help="run every check")
    p_all.add_argument("source_md")
    p_all.add_argument("docx")
    p_all.add_argument("textfile")
    p_all.add_argument("--probes", default=None)

    a = ap.parse_args(argv)
    if a.cmd == "leaks":
        return cmd_leaks(a.textfile, load_probes(a.probes, not a.no_default_probes),
                         fail_on_hits=a.fail_on_hits)
    if a.cmd == "tables":
        return cmd_tables(a.docx, top=a.top)
    if a.cmd == "paras":
        return cmd_paras(a.docx, top=a.top, limit_words=a.limit_words)
    if a.cmd == "figs":
        return cmd_figs(a.source_md, a.figsdir)
    # all
    rc = cmd_leaks(a.textfile, load_probes(a.probes))
    print("\n" + "=" * 70 + "\n")
    cmd_tables(a.docx)
    print("\n" + "=" * 70 + "\n")
    cmd_paras(a.docx)
    print("\n" + "=" * 70 + "\n")
    cmd_figs(a.source_md)
    return rc


if __name__ == "__main__":
    sys.exit(main())
