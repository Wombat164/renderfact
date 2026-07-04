#!/usr/bin/env python3
"""
Generate a Marp deck CSS theme from tokens/brand.yaml (chunk 0.4 / A1).

Emits a Marp-compatible CSS theme file (`@theme` directive + CSS custom properties)
usable via `marp --theme deck-theme.css slides.md`.

Usage:
    python tokens/gen/marp_theme.py [--brand path/to/consumer/brand.yaml] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_tokens, resolve_output_dir  # noqa: E402


def render_marp_css(tokens: dict) -> str:
    colour = tokens["colour"]
    brand = colour["brand"]
    status = colour["status"]
    data = colour["data"]
    type_ = tokens["type"]

    data_vars = "\n".join(f"  --data-{i}: {c};" for i, c in enumerate(data))

    return f"""/* GENERATED from tokens/brand.yaml -- do not edit by hand. */
/* Regenerate: python tokens/gen/marp_theme.py */

/*
@theme brand-deck
@auto-scaling true
*/

:root {{
  --brand-primary: {brand["primary"]};
  --brand-accent: {brand["accent"]};
  --brand-background: {brand["background"]};
  --brand-ink: {brand["ink"]};
  --brand-fill: {brand["fill"]};
  --status-ok: {status["ok"]};
  --status-warn: {status["warn"]};
  --status-risk: {status["risk"]};
  --status-info: {status["info"]};
{data_vars}
  --font-body: "{type_["body_font"]}", sans-serif;
  --font-mono: "{type_["mono_font"]}", monospace;
}}

section {{
  background-color: var(--brand-background);
  color: var(--brand-ink);
  font-family: var(--font-body);
  font-size: {type_["body_min_px"] + 4}px;
}}

h1, h2, h3, h4 {{
  color: var(--brand-primary);
}}

a {{
  color: var(--brand-accent);
}}

code, pre {{
  font-family: var(--font-mono);
}}

.status-ok {{ color: var(--status-ok); }}
.status-warn {{ color: var(--status-warn); }}
.status-risk {{ color: var(--status-risk); }}
.status-info {{ color: var(--status-info); }}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", type=Path, default=None,
                         help="Consumer brand.yaml override (optional)")
    parser.add_argument("--output-dir", default=None,
                         help="Output directory (default: tokens/gen/out/marp/)")
    args = parser.parse_args()

    tokens = load_tokens(args.brand)
    out_dir = resolve_output_dir(args.output_dir, "marp")
    out_file = out_dir / "deck-theme.css"
    out_file.write_text(render_marp_css(tokens), encoding="utf-8")
    print(f"wrote {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
