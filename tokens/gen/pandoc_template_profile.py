#!/usr/bin/env python3
"""
Generate a pandoc/DOCX template-profile YAML from tokens/brand.yaml (chunk 0.4 / A1).

Emits `template-profile.yaml`: the generic shape a DOCX house-style post-processor
consumes to skin pandoc's output (accent colour, fonts, margins) without hand-typing
values into that post-processor's own code. Matches the `--template-profile <yaml>`
flag already wired in container/render-doc.sh, which the consumer's house-style
post-processor reads to configure itself; this generator only produces the
config, it doesn't implement or assume a specific post-processor.

Usage:
    python tokens/gen/pandoc_template_profile.py [--brand path/to/consumer/brand.yaml] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_tokens, resolve_output_dir  # noqa: E402
from theme_tokens import resolve_theme  # noqa: E402

# A4 page size in cm (the descriptor names a page, the DOCX post-processor wants dims).
_PAGE_CM = {"A4": (21.0, 29.7), "A5": (14.8, 21.0), "LETTER": (21.59, 27.94)}


def _role(brand: dict, name: str) -> str:
    """Resolve a colour ROLE (a key in colour.brand) to its hex, defaulting to ink."""
    return brand.get(name, brand["ink"])


def render_template_profile(tokens: dict, variant: str = "base") -> dict:
    """Emit the FLAT template-profile that docstyle/style_postprocess consumes
    (its apply_template_profile reads top-level font/accent/body/margin_cm/
    page_*_cm keys), sourced from the SAME engine-agnostic `theme` descriptor the
    typst backend uses (#32). A variant that changes heading_role recolours the
    DOCX headings + table headers exactly as it does the typst chrome -- so one
    descriptor drives both engines. Keys the descriptor does not own are omitted,
    leaving the post-processor's tuned defaults (body_muted/table_body/zebra)."""
    colour = tokens["colour"]
    brand = colour["brand"]
    type_ = tokens["type"]
    geometry = tokens.get("geometry", {}) or {}
    theme = resolve_theme(tokens, variant)
    margin = theme.get("margin_cm", {}) or {}

    profile = {
        "_generated_from": "tokens/brand.yaml [theme] -- do not edit by hand; regenerate",
        "_variant": variant,
        # flat keys consumed by docstyle/style_postprocess.apply_template_profile:
        "font": type_["print_font"],
        "accent": _role(brand, theme.get("heading_role", "accent")),  # headings + table header
        "body": brand["ink"],
        "margin_cm": margin.get("x", geometry.get("margin_cm", 2.0)),
    }
    dims = _PAGE_CM.get(str(geometry.get("page", "A4")).upper())
    if dims:
        profile["page_width_cm"], profile["page_height_cm"] = dims
    return profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", type=Path, default=None,
                         help="Consumer brand.yaml override (optional)")
    parser.add_argument("--variant", default="base",
                         help="theme variant from brand.yaml [theme.variants] (default: base)")
    parser.add_argument("--output-dir", default=None,
                         help="Output directory (default: tokens/gen/out/pandoc/)")
    args = parser.parse_args()

    tokens = load_tokens(args.brand)
    out_dir = resolve_output_dir(args.output_dir, "pandoc")
    out_file = out_dir / "template-profile.yaml"
    profile = render_template_profile(tokens, args.variant)
    with out_file.open("w", encoding="utf-8") as f:
        f.write("# GENERATED from tokens/brand.yaml -- do not edit by hand.\n")
        f.write("# Regenerate: python tokens/gen/pandoc_template_profile.py\n")
        yaml.safe_dump(profile, f, default_flow_style=False, sort_keys=False)
    print(f"wrote {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
