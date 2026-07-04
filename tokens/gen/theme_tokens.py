#!/usr/bin/env python3
"""
Generate the engine-agnostic THEME descriptor as a typst `theme.typ` (issue #32).

Where typst_tokens.py emits the raw palette+fonts (tokens.typ), this emits the
chrome + component layer (page margins, header/footer slots, heading/title/rule
colour ROLES) from tokens/brand.yaml's `theme` section. The typst PDF theme
(pdf/theme/default.typ) imports the result and resolves roles to colours at
render time -- the same generated-values / static-logic split as tokens.typ.

Variants: `theme.variants.<name>` inherits `theme.base` and overrides only the
keys it names, so a "financial" skin shares the base chrome and restyles a few
components. The descriptor is role-based and engine-neutral by design: an OOXML
consumer can read the same fields (the Golden Rule -- one source -- extended from
palette to house-style).

Usage:
    python tokens/gen/theme_tokens.py [--brand brand.yaml] [--variant NAME] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import _deep_merge, load_tokens, resolve_output_dir  # noqa: E402

_SLOT_KEYS = ("org", "title", "date", "pagenumber", "none")


def resolve_theme(tokens: dict, variant: str = "base") -> dict:
    """The effective theme dict for a variant: base, deep-merged with the named
    variant's overrides. `base` and an unknown variant both yield base as-is."""
    theme = tokens.get("theme", {}) or {}
    base = theme.get("base", {}) or {}
    if variant in ("base", "", None):
        return dict(base)
    override = (theme.get("variants", {}) or {}).get(variant)
    if override is None:
        raise KeyError(f"unknown theme variant: {variant!r} "
                       f"(known: {sorted((theme.get('variants') or {}).keys())})")
    return _deep_merge(base, override)


def _typ_bool(value) -> str:
    return "true" if value else "false"


def _typ_str(value) -> str:
    if value is None:
        return "none"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _slot(value) -> str:
    """A header/footer slot value -> a typst string key, or `none`."""
    if value in (None, "none"):
        return "none"
    return _typ_str(value)


def render_theme(tokens: dict, variant: str = "base") -> str:
    """Emit chrome.typ (a single `#let chrome = (...)`) for the resolved variant.
    Named `chrome` (page chrome + components) to sit beside the palette tokens
    without colliding with the layout file the backend writes as theme.typ."""
    t = resolve_theme(tokens, variant)
    margin = t.get("margin_cm", {}) or {}
    header = t.get("header", {}) or {}
    footer = t.get("footer", {}) or {}
    callout = t.get("callout", {}) or {}
    statement = t.get("statement", {}) or {}

    def cm(key, default):
        return f'{margin.get(key, default)}cm'

    lines = [
        "// GENERATED from tokens/brand.yaml [theme] -- do not edit by hand.",
        f"// Variant: {variant}. Regenerate: python tokens/gen/theme_tokens.py",
        "",
        "#let chrome = (",
        f'  margin: (x: {cm("x", 2.2)}, top: {cm("top", 2.6)}, bottom: {cm("bottom", 2.4)}),',
        f'  body-pt: {t.get("body_pt", 10.5)},',
        f'  justify: {_typ_bool(t.get("justify", True))},',
        f'  heading-role: {_typ_str(t.get("heading_role", "accent"))},',
        f'  title-role: {_typ_str(t.get("title_role", "primary"))},',
        f'  rule-role: {_typ_str(t.get("rule_role", "primary"))},',
        f'  header: (left: {_slot(header.get("left"))}, right: {_slot(header.get("right"))}),',
        f'  footer: (left: {_slot(footer.get("left"))}, right: {_slot(footer.get("right"))}),',
        f'  callout: (fill-role: {_typ_str(callout.get("fill_role", "fill"))}, '
        f'border-role: {_typ_str(callout.get("border_role", "accent"))}),',
        f'  statement: (rule-role: {_typ_str(statement.get("rule_role", "primary"))}, '
        f'heading-role: {_typ_str(statement.get("heading_role", "accent"))}),',
        ")",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brand", type=Path, default=None,
                        help="Consumer brand.yaml override (optional)")
    parser.add_argument("--variant", default="base", help="theme variant (default: base)")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory (default: tokens/gen/out/typst/)")
    args = parser.parse_args()

    tokens = load_tokens(args.brand)
    out_dir = resolve_output_dir(args.output_dir, "typst")
    out_file = out_dir / "chrome.typ"
    out_file.write_text(render_theme(tokens, args.variant), encoding="utf-8")
    print(f"wrote {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
