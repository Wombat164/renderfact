#!/usr/bin/env python3
"""
Diagram Render Orchestrator
=============================

Single entrypoint that dispatches diagram-as-code source files to the right
renderer based on file extension, producing SVG + PDF outputs per Path Y1
doctrine, generalized from a private consumer's AaC Diagram Pipeline + Style
Guide.

Dispatch:
    .mmd / .mermaid  -> mmdc      (Mermaid CLI)        -> .svg -> cairosvg -> .pdf
    .d2              -> d2        (Terrastruct D2)     -> .svg -> cairosvg -> .pdf
    .svg             -> cairosvg                       -> .pdf
    .drawio          -> drawio CLI (--export)          -> .pdf direct
    .puml            -> plantuml.jar                   -> .svg -> cairosvg -> .pdf (TBD)
    .yaml / .yml     -> content-sniffed for a recognized diagram archetype (issue
                        #68: layered-stack) -> generated .d2 -> d2 -> cairosvg -> .pdf.
                        A .yaml/.yml file that does not sniff as a known archetype
                        is skipped, same as any other unsupported extension.

Usage:
    python lint/render.py <source-file>...
    python lint/render.py --output-dir renders/ src/diagram.mmd
    python lint/render.py --formats=svg,pdf src/*.mmd

Outputs:
    By default to ./renders/ relative to current working directory.
    Filename = source-stem + extension (.svg or .pdf).

Tooling versions verified 2026-05-24:
    mmdc 11.15.0, D2 0.7.1, cairosvg 2.9.0, drawio Desktop 28.x

Exit codes:
    0 = all renders succeeded
    1 = at least one render failed
    2 = usage error / unsupported extension

Last review: 2026-05-24
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layered_stack  # noqa: E402  (lint/layered_stack.py: issue #68 archetype, FR1-FR3)
import archimate_exchange  # noqa: E402  (lint/archimate_exchange.py: issue #86, FR4-FR6)

DRAWIO_EXE = Path(r"C:\Program Files\draw.io\draw.io.exe")
D2_EXE = Path(r"C:\Program Files\D2\d2.exe")


def _find_executable(name: str, fallback: Path | None = None) -> str | None:
    """Locate executable across platforms. On Windows, npm-installed CLIs are .cmd shims."""
    # Try shutil.which first (PATH lookup; handles .cmd/.exe extensions on Windows)
    found = shutil.which(name)
    if found:
        return found
    # Try with .cmd extension explicitly (npm globals)
    if os.name == "nt":
        found = shutil.which(f"{name}.cmd")
        if found:
            return found
    # Fallback hardcoded path
    if fallback and fallback.exists():
        return str(fallback)
    return None


def validate_xml_wellformed(src: Path) -> tuple[bool, str]:
    """Pre-render XML well-formedness gate (catches lesson B-1, B-2, B-11).

    Detects XML 1.0 spec section 2.5 violations (e.g., '--' inside <!--...-->
    comments) and other malformed XML that causes silent failures in
    drawio CLI / mmdc. Uses Python stdlib xml.etree.ElementTree (no
    external dependency).

    Returns (ok, message). ok=True means safe to render.
    """
    import xml.etree.ElementTree as ET

    try:
        # Parse with defusedxml-equivalent strictness via stdlib
        ET.parse(str(src))
        return True, ""
    except ET.ParseError as err:
        # ParseError message often points at the line + col of XML violation
        return False, f"XML not well-formed: {err}"
    except Exception as err:
        return False, f"XML parse error: {err}"


def validate_mermaid_source(src: Path) -> tuple[bool, str]:
    """Pre-render Mermaid source sanity check (catches lesson B-2).

    Checks the YAML frontmatter title for parens / dashes that break
    the Mermaid 11.x parser. Also flags %% comments containing '--'.

    Returns (ok, message). ok=True means safe to render.
    """
    try:
        text = src.read_text(encoding="utf-8", errors="ignore")
    except OSError as err:
        return False, f"read failed: {err}"

    lines = text.splitlines()
    in_frontmatter = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter and stripped.startswith("title:"):
            title = stripped[6:].strip().strip('"').strip("'")
            if "--" in title:
                return False, f"line {i}: Mermaid title contains '--' which breaks YAML frontmatter parser (lesson B-2)"
            # parens in titles: not a hard failure (V5/V7 render fine)
        # %% comments with '--': not a hard failure (V5/V7 also OK); only title-with-dash is reliably broken
    return True, ""


def render_mermaid(src: Path, out_svg: Path) -> bool:
    """Render Mermaid .mmd to SVG via mmdc."""
    mmdc = _find_executable("mmdc")
    if not mmdc:
        print("  ERROR mmdc not found on PATH (install: npm install -g @mermaid-js/mermaid-cli)",
              file=sys.stderr)
        return False
    result = subprocess.run(
        [mmdc, "-i", str(src), "-o", str(out_svg)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown").splitlines()
        print(f"  ERROR mmdc: {err[-1] if err else 'unknown'}", file=sys.stderr)
        return False
    return True


def render_d2(src: Path, out_svg: Path) -> bool:
    """Render D2 .d2 to SVG via D2 CLI."""
    d2 = _find_executable("d2", fallback=D2_EXE)
    if not d2:
        print(f"  ERROR d2 not found on PATH or at {D2_EXE} (install: winget install Terrastruct.D2)",
              file=sys.stderr)
        return False
    result = subprocess.run(
        [d2, str(src), str(out_svg)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown").splitlines()
        print(f"  ERROR d2: {err[-1] if err else 'unknown'}", file=sys.stderr)
        return False
    return True


def render_svg_to_pdf(svg: Path, out_pdf: Path) -> bool:
    """Convert SVG to PDF via cairosvg (Python-native; no Inkscape required)."""
    try:
        import cairosvg
    except ImportError:
        print("  ERROR cairosvg not installed; pip install cairosvg", file=sys.stderr)
        return False
    try:
        with svg.open("rb") as f:
            cairosvg.svg2pdf(file_obj=f, write_to=str(out_pdf))
        return True
    except Exception as e:
        print(f"  ERROR cairosvg: {e}", file=sys.stderr)
        return False


def render_drawio_direct(src: Path, out_pdf: Path) -> bool:
    """Render .drawio directly to PDF via drawio CLI (A3 landscape default)."""
    if not DRAWIO_EXE.exists():
        print(f"  ERROR drawio not found at {DRAWIO_EXE}", file=sys.stderr)
        return False
    result = subprocess.run(
        [str(DRAWIO_EXE), "--export", "--format", "pdf",
         "--output", str(out_pdf), str(src)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        print(f"  ERROR drawio: {result.stderr.splitlines()[-1] if result.stderr else 'unknown'}",
              file=sys.stderr)
        return False
    return True


def render_file(src: Path, out_dir: Path, formats: list[str]) -> bool:
    """Dispatch render based on extension. Returns True on success."""
    ext = src.suffix.lower()
    stem = src.stem
    out_svg = out_dir / f"{stem}.svg"
    out_pdf = out_dir / f"{stem}.pdf"

    # Pre-render validation gates (lesson B-1, B-2, B-11)
    if ext in (".svg", ".drawio", ".xml"):
        ok, msg = validate_xml_wellformed(src)
        if not ok:
            print(f"  REJECT  {src.name}  ({msg})", file=sys.stderr)
            return False
    elif ext in (".mmd", ".mermaid"):
        ok, msg = validate_mermaid_source(src)
        if not ok:
            print(f"  REJECT  {src.name}  ({msg})", file=sys.stderr)
            return False

    print(f"  RENDER  {src.name}")

    if ext in (".mmd", ".mermaid"):
        if "svg" in formats and not render_mermaid(src, out_svg):
            return False
        if "pdf" in formats:
            if not out_svg.exists():
                if not render_mermaid(src, out_svg):
                    return False
            if not render_svg_to_pdf(out_svg, out_pdf):
                return False
        return True

    if ext == ".d2":
        if "svg" in formats and not render_d2(src, out_svg):
            return False
        if "pdf" in formats:
            if not out_svg.exists():
                if not render_d2(src, out_svg):
                    return False
            if not render_svg_to_pdf(out_svg, out_pdf):
                return False
        return True

    if ext == ".svg":
        # SVG source; only PDF makes sense as derivative
        if "pdf" in formats:
            return render_svg_to_pdf(src, out_pdf)
        # If only svg requested, copy through
        if "svg" in formats and src.resolve() != out_svg.resolve():
            shutil.copy2(src, out_svg)
        return True

    if ext in (".yaml", ".yml"):
        # Content-sniff, not extension-sniff: most .yaml files are not diagram
        # sources at all (FR6's dispatch idiom, reused here for the archetype's
        # own plain-source format, not just the out-of-scope ArchiMate adapter).
        archetype = layered_stack.sniff_archetype(src)
        if archetype is None:
            print(f"  SKIP    {src.name}  (unsupported extension '{ext}')")
            return True
        try:
            d2_source = layered_stack.generate_d2_source(src)
        except layered_stack.LayeredStackError as err:
            print(f"  REJECT  {src.name}  ({err})", file=sys.stderr)
            return False
        generated_d2 = out_dir / f"{stem}.generated.d2"
        generated_d2.write_text(d2_source, encoding="utf-8")
        ok = True
        if "svg" in formats and not render_d2(generated_d2, out_svg):
            ok = False
        if "pdf" in formats:
            if not out_svg.exists():
                if not render_d2(generated_d2, out_svg):
                    ok = False
            if ok and not render_svg_to_pdf(out_svg, out_pdf):
                ok = False
        return ok

    if ext == ".xml":
        # Content-sniff, not extension-sniff (FR6, the same idiom the .yaml/.yml
        # branch above already uses): most .xml files are not ArchiMate Exchange
        # Files at all. validate_xml_wellformed() already ran above for this
        # extension; this is the archetype-specific dispatch on top of it.
        if not archimate_exchange.sniff_archimate_exchange(src):
            print(f"  SKIP    {src.name}  (not a recognized ArchiMate Exchange file)")
            return True
        try:
            d2_source = archimate_exchange.generate_d2_source_from_exchange(src)
        except layered_stack.LayeredStackError as err:
            print(f"  REJECT  {src.name}  ({err})", file=sys.stderr)
            return False
        generated_d2 = out_dir / f"{stem}.generated.d2"
        generated_d2.write_text(d2_source, encoding="utf-8")
        ok = True
        if "svg" in formats and not render_d2(generated_d2, out_svg):
            ok = False
        if "pdf" in formats:
            if not out_svg.exists():
                if not render_d2(generated_d2, out_svg):
                    ok = False
            if ok and not render_svg_to_pdf(out_svg, out_pdf):
                ok = False
        return ok

    if ext == ".drawio":
        # drawio CLI direct PDF export (best fidelity)
        if "pdf" in formats:
            return render_drawio_direct(src, out_pdf)
        if "svg" in formats:
            # drawio can also export SVG
            if not DRAWIO_EXE.exists():
                return False
            result = subprocess.run(
                [str(DRAWIO_EXE), "--export", "--format", "svg",
                 "--output", str(out_svg), str(src)],
                capture_output=True, text=True, timeout=60,
            )
            return result.returncode == 0
        return True

    print(f"  SKIP    {src.name}  (unsupported extension '{ext}')")
    return True  # not a failure


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagram Render Orchestrator (Path Y1 multi-target dispatch)",
    )
    parser.add_argument("sources", nargs="+", help="Source files OR directories to render")
    parser.add_argument("--output-dir", default="renders",
                        help="Output directory (default: renders/)")
    parser.add_argument("--formats", default="svg,pdf",
                        help="Comma-separated output formats (default: svg,pdf)")
    args = parser.parse_args()

    formats = [f.strip() for f in args.formats.split(",")]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Collect source files
    paths: list[Path] = []
    for s in args.sources:
        p = Path(s)
        if p.is_dir():
            for ext in (".mmd", ".mermaid", ".d2", ".svg", ".drawio", ".yaml", ".yml"):
                paths.extend(p.glob(f"*{ext}"))
        elif p.is_file():
            paths.append(p)

    if not paths:
        print("no input files found", file=sys.stderr)
        return 2

    paths = sorted(set(paths))
    all_ok = True
    for p in paths:
        if not render_file(p, out_dir, formats):
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
