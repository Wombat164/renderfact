#!/usr/bin/env python3
"""Render SVG to PDF via cairosvg. Path-safe wrapper for Windows."""
import sys
import cairosvg
from pathlib import Path

if len(sys.argv) != 3:
    print("usage: render_svg_pdf.py <input.svg> <output.pdf>", file=sys.stderr)
    sys.exit(2)

src = Path(sys.argv[1])
dst = Path(sys.argv[2])

with src.open("rb") as f:
    cairosvg.svg2pdf(file_obj=f, write_to=str(dst))

print(f"rendered: {dst}")
