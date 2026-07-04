#!/usr/bin/env python3
"""
SVG accessibility post-patcher.

Mermaid CLI generates SVG with `<title>` + `<desc>` (from accTitle/accDescr directives)
but does NOT add `role="img"` or `aria-labelledby` to the root `<svg>` element.

This patcher closes the gap by:
  1. Detecting <title id="X"> and <desc id="Y"> child elements inside the <svg>
  2. Injecting role="img" + aria-labelledby="X Y" into the <svg> opening tag

GR-8 compliance fix. Idempotent (safe to re-run).

Usage:
  python lint/patch_svg_a11y.py <svg-file>...

Exit codes: 0 always (warns but does not block)

Last review: 2026-05-24
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def patch_svg(path: Path) -> tuple[bool, str]:
    """Patch one SVG file. Returns (changed, message)."""
    if not path.exists():
        return False, f"NOT FOUND: {path}"
    if path.suffix.lower() != ".svg":
        return False, f"SKIP non-svg: {path}"

    text = path.read_text(encoding="utf-8")
    original = text

    # Find first <title id="..."> and <desc id="..."> inside the SVG
    title_match = re.search(r'<title\s+id\s*=\s*["\']([^"\']+)["\']', text)
    desc_match = re.search(r'<desc\s+id\s*=\s*["\']([^"\']+)["\']', text)

    # If accTitle/accDescr were used, Mermaid emits <title> + <desc> with auto ids
    # If no id, Mermaid emits bare <title>...</title>; we still want role="img" + aria-label
    if title_match and desc_match:
        title_id = title_match.group(1)
        desc_id = desc_match.group(1)
        ids = f"{title_id} {desc_id}"
    elif title_match:
        ids = title_match.group(1)
    else:
        # No accTitle anchor; fall back to role="img" + aria-label from <title> content
        title_text_match = re.search(r"<title[^>]*>([^<]+)</title>", text)
        if title_text_match:
            ids = ""  # no id-based labelling
        else:
            return False, f"NO TITLE: {path} -- cannot patch (add accTitle to source)"

    # Patch the <svg ...> opening tag
    def svg_replace(match):
        attrs = match.group(1)
        # Idempotency: skip if any accessible-image role is already present
        # (img / graphics-document / graphics-symbol -- all valid WAI-ARIA Graphics 1.0)
        # Mermaid 11+ emits role="graphics-document document" by default; do NOT duplicate.
        if re.search(r'\brole\s*=\s*["\'](?:img|graphics-document|graphics-symbol)', attrs):
            return match.group(0)
        new_attrs = attrs.rstrip()
        new_attrs += ' role="img"'
        if ids:
            new_attrs += f' aria-labelledby="{ids}"'
        return f"<svg{new_attrs}>"

    text = re.sub(r"<svg([^>]*?)>", svg_replace, text, count=1)

    if text == original:
        return False, f"NO CHANGE: {path} (already patched)"

    path.write_text(text, encoding="utf-8")
    return True, f"PATCHED: {path}"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: patch_svg_a11y.py <svg>...", file=sys.stderr)
        return 2
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            for svg in p.rglob("*.svg"):
                changed, msg = patch_svg(svg)
                print(msg)
        else:
            changed, msg = patch_svg(p)
            print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
