#!/usr/bin/env python3
"""
Generate Typst token variables from tokens/brand.yaml (chunk 0.4 / A1).

Emits a `tokens.typ` importable module: `#import "tokens.typ": *` gives any Typst
source (posters, decks via touying, PDF briefs) the same brand/status/data colours
and fonts as every other engine. Shape proven in production 2026-07-02 (the
poster-pipeline's own tokens.typ, hand-written before this generator existed --
this generalizes that pattern instead of hand-typing it per consumer).

Usage:
    python tokens/gen/typst_tokens.py [--brand path/to/consumer/brand.yaml] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_tokens, resolve_output_dir  # noqa: E402


def render_typst(tokens: dict) -> str:
    colour = tokens["colour"]
    brand = colour["brand"]
    status = colour["status"]
    data = colour["data"]
    type_ = tokens["type"]

    lines = [
        "// GENERATED from tokens/brand.yaml -- do not edit by hand.",
        "// Regenerate: python tokens/gen/typst_tokens.py",
        "",
        "#let brand = (",
        f'  primary: rgb("{brand["primary"]}"),',
        f'  accent: rgb("{brand["accent"]}"),',
        f'  background: rgb("{brand["background"]}"),',
        f'  ink: rgb("{brand["ink"]}"),',
        f'  fill: rgb("{brand["fill"]}"),',
        "  white: rgb(\"#FFFFFF\"),",
        ")",
        "#let status = (",
        f'  ok: rgb("{status["ok"]}"),',
        f'  warn: rgb("{status["warn"]}"),',
        f'  risk: rgb("{status["risk"]}"),',
        f'  info: rgb("{status["info"]}"),',
        ")",
        "#let data = (",
        "  " + ", ".join(f'rgb("{c}")' for c in data) + ",",
        ")",
        f'#let brand-font = "{type_["body_font"]}"',
        f'#let print-font = "{type_["print_font"]}"',
        f'#let mono-font = "{type_["mono_font"]}"',
        f'#let body-min-pt = {type_["body_min_px"]}',
        "",
        "// peace-of-posters theme, derived from the tokens (brand identity,",
        "// scientific layout stays separate -- import peace-of-posters yourself)",
        "#let brand-theme = (",
        '  "body-box-args": (inset: 0.8em, width: 100%, fill: brand.background, stroke: none),',
        '  "body-text-args": (fill: brand.ink),',
        '  "heading-box-args": (inset: 0.7em, width: 100%, fill: brand.primary, stroke: brand.primary),',
        '  "heading-text-args": (fill: white, weight: "bold"),',
        '  "title-text-args": (fill: white),',
        ")",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", type=Path, default=None,
                         help="Consumer brand.yaml override (optional)")
    parser.add_argument("--output-dir", default=None,
                         help="Output directory (default: tokens/gen/out/typst/)")
    args = parser.parse_args()

    tokens = load_tokens(args.brand)
    out_dir = resolve_output_dir(args.output_dir, "typst")
    out_file = out_dir / "tokens.typ"
    out_file.write_text(render_typst(tokens), encoding="utf-8")
    print(f"wrote {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
