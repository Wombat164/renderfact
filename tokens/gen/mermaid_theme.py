#!/usr/bin/env python3
"""
Generate a Mermaid theme JSON from tokens/brand.yaml (chunk 0.4 / A1).

Emits a themeVariables JSON consumable two ways:
  1. mmdc --configFile: `mmdc -i in.mmd -o out.svg --configFile mermaid-theme.json`
  2. Frontmatter `%%{init: ...}%%` block or YAML frontmatter `config:` key -- paste
     the "themeVariables" object in directly.

Mermaid's theme system only exposes a subset of tokens (no direct Wong-8 categorical
palette support -- pieCharts/xyCharts pick up primaryColor-family variables instead).
Documented explicitly below rather than silently dropping the data palette.

Usage:
    python tokens/gen/mermaid_theme.py [--brand path/to/consumer/brand.yaml] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_tokens, resolve_output_dir  # noqa: E402


def render_mermaid_config(tokens: dict) -> dict:
    colour = tokens["colour"]
    brand = colour["brand"]
    status = colour["status"]
    type_ = tokens["type"]

    return {
        "theme": "base",
        "themeVariables": {
            "primaryColor": brand["fill"],
            "primaryTextColor": brand["ink"],
            "primaryBorderColor": brand["primary"],
            "secondaryColor": brand["background"],
            "tertiaryColor": brand["accent"],
            "lineColor": brand["primary"],
            "textColor": brand["ink"],
            "fontFamily": type_["body_font"],
            "fontSize": f"{type_['body_min_px']}px",
            # Status-semantic mapping -- Mermaid has no native "status colour" concept,
            # closest fit is errorBkgColor/errorTextColor for risk; ok/warn/info don't
            # have first-class variables, so they're only usable via explicit
            # classDef styling in-diagram, not a global theme variable. Documented,
            # not silently dropped.
            "errorBkgColor": status["risk"],
            "errorTextColor": "#FFFFFF",
        },
        "_note": (
            "Mermaid's theme system does not expose a categorical/data-series palette "
            "variable (unlike D2/Typst). Wong-8 colours from tokens/brand.yaml must be "
            "applied per-diagram via explicit classDef/style directives in the .mmd "
            "source, not globally via this theme file. status.ok/warn/info similarly "
            "have no first-class theme variable -- use classDef for those too."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", type=Path, default=None,
                         help="Consumer brand.yaml override (optional)")
    parser.add_argument("--output-dir", default=None,
                         help="Output directory (default: tokens/gen/out/mermaid/)")
    args = parser.parse_args()

    tokens = load_tokens(args.brand)
    out_dir = resolve_output_dir(args.output_dir, "mermaid")
    out_file = out_dir / "mermaid-theme.json"
    config = render_mermaid_config(tokens)
    out_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
