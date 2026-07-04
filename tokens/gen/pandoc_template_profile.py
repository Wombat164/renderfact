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


def render_template_profile(tokens: dict) -> dict:
    colour = tokens["colour"]
    brand = colour["brand"]
    status = colour["status"]
    type_ = tokens["type"]
    geometry = tokens["geometry"]

    return {
        "_generated_from": "tokens/brand.yaml (do not edit by hand -- regenerate)",
        "colour": {
            "accent": brand["accent"],
            "primary": brand["primary"],
            "ink": brand["ink"],
            "fill": brand["fill"],
            "background": brand["background"],
            "status_ok": status["ok"],
            "status_warn": status["warn"],
            "status_risk": status["risk"],
            "status_info": status["info"],
        },
        "font": {
            "body": type_["print_font"],
            "mono": type_["mono_font"],
            "body_min_pt": type_["body_min_px"],
            "heading_scale_pt": type_["scale"],
        },
        "geometry": {
            "page": geometry["page"],
            "margin_cm": geometry["margin_cm"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", type=Path, default=None,
                         help="Consumer brand.yaml override (optional)")
    parser.add_argument("--output-dir", default=None,
                         help="Output directory (default: tokens/gen/out/pandoc/)")
    args = parser.parse_args()

    tokens = load_tokens(args.brand)
    out_dir = resolve_output_dir(args.output_dir, "pandoc")
    out_file = out_dir / "template-profile.yaml"
    profile = render_template_profile(tokens)
    with out_file.open("w", encoding="utf-8") as f:
        f.write("# GENERATED from tokens/brand.yaml -- do not edit by hand.\n")
        f.write("# Regenerate: python tokens/gen/pandoc_template_profile.py\n")
        yaml.safe_dump(profile, f, default_flow_style=False, sort_keys=False)
    print(f"wrote {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
