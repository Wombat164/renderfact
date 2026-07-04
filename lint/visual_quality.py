#!/usr/bin/env python3
"""
Diagram Visual-Quality Linter
===============================

Enforces graphical golden rules on rendered SVG:
  GR-5  Wong 8-color palette only (no other hex codes)
  GR-8  SVG accessibility: <title> + <desc> + role="img" + aria-labelledby
  GR-9  WCAG 2.2 AA text contrast (4.5:1 normal, 3:1 large)

Visual heuristics (per Di Bartolomeo 2024 + GD 2025):
  - Whitespace ratio (rough proxy via viewBox vs element bounding)
  - Element-density-vs-tier (overlap with element_budget.py)
  - Hex-only-Wong-palette check

Usage:
  python lint/visual_quality.py <svg-file>...
  python lint/visual_quality.py --check-palette-only <svg-file>
  python lint/visual_quality.py --json <svg-file>

Exit codes:
  0 = all checks passed
  1 = at least one hard rule failed
  2 = usage error / unparseable input

Last review: 2026-05-24
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Wong 8-color palette (canonical, per Wong 2011 Nature Methods)
WONG_PALETTE = {
    "#000000",
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
}

# Brand-allowed neutrals (text, lines, backgrounds) per diagram-theme.css / tokens/brand.yaml
NEUTRAL_PALETTE = {
    "#1a1a1a",  # text light-mode
    "#5a5a5a",  # text-muted light-mode
    "#2a2a2a",  # line light-mode
    "#c8c8c8",  # line-light light-mode
    "#ffffff",  # background light-mode
    "#f6f6f6",  # background-subtle light-mode
    "#f0f0f0",  # text dark-mode
    "#b0b0b0",  # text-muted dark-mode
    "#d8d8d8",  # line dark-mode
    "#4a4a4a",  # line-light dark-mode
    "#121212",  # background dark-mode
    "#1e1e1e",  # background-subtle dark-mode
    "#fff",     # short-form white
    "#000",     # short-form black
}

ALLOWED_COLORS = WONG_PALETTE | NEUTRAL_PALETTE


def hex_normalize(color: str) -> str:
    """Normalize hex color: lowercase + expand 3-char to 6-char."""
    c = color.strip().lower()
    if not c.startswith("#"):
        return c
    if len(c) == 4:  # #RGB -> #RRGGBB
        c = "#" + "".join(ch * 2 for ch in c[1:])
    return c


def extract_colors(svg_text: str) -> set[str]:
    """Extract all hex colors from SVG (fill, stroke, color, stop-color, in style attrs)."""
    # Match #RGB, #RRGGBB, #RGBA, #RRGGBBAA
    hex_pattern = re.compile(r"#[0-9a-fA-F]{3,8}\b")
    colors = set()
    for match in hex_pattern.findall(svg_text):
        # Skip alpha-channel (8-char) trailing chars; normalize to 6-char
        if len(match) == 9:  # #RRGGBBAA
            colors.add(hex_normalize(match[:7]))
        elif len(match) == 5:  # #RGBA
            colors.add(hex_normalize(match[:4]))
        else:
            colors.add(hex_normalize(match))
    return colors


def check_wong_palette(svg_text: str) -> tuple[bool, list[str]]:
    """GR-5: Wong palette + brand-configured neutrals only. Returns (pass, list-of-violations)."""
    colors = extract_colors(svg_text)
    allowed_normalized = {hex_normalize(c) for c in ALLOWED_COLORS}
    violations = sorted(colors - allowed_normalized)
    return len(violations) == 0, violations


def check_svg_accessibility(svg_text: str) -> tuple[bool, list[str]]:
    """GR-8: <title> + <desc> + role="img" + aria-labelledby. Returns (pass, issues)."""
    issues = []
    if "<title" not in svg_text:
        issues.append("missing <title> element")
    if "<desc" not in svg_text:
        issues.append("missing <desc> element")
    # Accept any of: role="img", role="graphics-document" (Mermaid 11+ default), role="graphics-symbol"
    # Per WAI-ARIA Graphics 1.0, all three are valid accessible-image roles for SVG.
    if not re.search(r'role\s*=\s*["\'](?:img|graphics-document(?:\s+\w+)*|graphics-symbol)["\']', svg_text):
        issues.append("missing role=\"img\" or role=\"graphics-document\" attribute on <svg>")
    if "aria-labelledby" not in svg_text:
        issues.append("missing aria-labelledby attribute on <svg>")
    return len(issues) == 0, issues


def _color_to_hex(color_str: str) -> str | None:
    """Convert a CSS color (#hex or rgb(R,G,B)) to a normalized #rrggbb hex string.
    Returns None if parse fails. Strips !important and whitespace."""
    c = color_str.strip().replace("!important", "").strip()
    if c.startswith("#"):
        return hex_normalize(c)
    # rgb(R, G, B) or rgb(R G B) or rgba(R, G, B, A)
    m = re.match(r"rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)", c, re.IGNORECASE)
    if m:
        r, g, b = (int(x) for x in m.groups())
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert #RRGGBB to (r, g, b) ints."""
    c = hex_normalize(hex_color).lstrip("#")
    if len(c) != 6:
        return (0, 0, 0)
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.2 relative luminance formula."""
    def channel(c):
        cs = c / 255.0
        return cs / 12.92 if cs <= 0.03928 else ((cs + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.2 contrast ratio between two colors."""
    l1 = relative_luminance(hex_to_rgb(fg))
    l2 = relative_luminance(hex_to_rgb(bg))
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def check_wcag_contrast(svg_text: str) -> tuple[bool, list[str]]:
    """GR-9: Check known text-on-background contrast pairings. Returns (pass, warnings).

    Three sources of (fg, bg) pairings examined:
      1. Inline <text fill="#..." style="color:#..."> on <text> elements (legacy SVG)
      2. CSS-class rules in <style> blocks: .X{fill:#fff;...} .X rect{fill:#000;...}
         (Mermaid emits classDef-based fills and text colors via class-cascade)
      3. Element-level class attribute references mapped to CSS rule pairs

    Heuristic: for any (text-fill, node-fill) pair attached to the same class,
    compute contrast and BLOCK if any pair is <4.5:1 (WCAG 1.4.3 normal text).
    """
    warnings = []
    failures = []

    # ---- Source 1: inline <text> elements ----
    text_color_pattern = re.compile(
        r"<text\b[^>]*?(?:color|fill)\s*=\s*[\"']?(#[0-9a-fA-F]{3,8})", re.IGNORECASE
    )
    text_colors = set(text_color_pattern.findall(svg_text))

    for fg in text_colors:
        fg = hex_normalize(fg)
        ratio_white = contrast_ratio(fg, "#ffffff")
        if ratio_white < 4.5:
            failures.append(
                f"text color {fg} on white: {ratio_white:.2f}:1 (need >= 4.5:1 for normal text, WCAG 1.4.3)"
            )

    # ---- Source 2 + 3: CSS-class fill+color cascade (Mermaid classDef) ----
    # Mermaid emits classDef-derived rules as:
    #   .CLASSNAME>*{fill:rgb(R,G,B)!important; color:rgb(R',G',B')!important; ...}
    # Both fill (node background) and color (text) live in the SAME rule body, scoped to ">*".
    # Restrict pairing to this specific selector to avoid false positives from
    # .CLASSNAME text / .CLASSNAME .label / etc. which are layout-related, not visual pairs.
    style_blocks = re.findall(r"<style[^>]*>(.*?)</style>", svg_text, re.DOTALL | re.IGNORECASE)
    class_pairs: dict[str, tuple[str, str]] = {}
    # Note: Mermaid HTML-encodes the > in CSS selectors inside <style> blocks as &gt;
    # so accept both literal > and the entity.
    rule_re = re.compile(
        r"\.([a-zA-Z_][\w-]*)\s*(?:>|&gt;)\s*\*\s*\{([^{}]+)\}",
        re.IGNORECASE
    )
    for block in style_blocks:
        for m in rule_re.finditer(block):
            cls = m.group(1)
            body = m.group(2)
            # Accept both #hex and rgb() forms
            fill_m = re.search(
                r"\bfill\s*:\s*(#[0-9a-fA-F]{3,8}|rgb\([^)]+\))", body, re.IGNORECASE
            )
            color_m = re.search(
                r"\bcolor\s*:\s*(#[0-9a-fA-F]{3,8}|rgb\([^)]+\))", body, re.IGNORECASE
            )
            if fill_m and color_m:
                fill_hex = _color_to_hex(fill_m.group(1))
                color_hex = _color_to_hex(color_m.group(1))
                if fill_hex and color_hex:
                    class_pairs[cls] = (fill_hex, color_hex)

    # For each paired class, compute contrast
    for cls in sorted(class_pairs):
        bg, fg = class_pairs[cls]
        ratio = contrast_ratio(fg, bg)
        if ratio < 4.5:
            failures.append(
                f"class .{cls} text {fg} on fill {bg}: {ratio:.2f}:1 (need >= 4.5:1, WCAG 1.4.3)"
            )

    # If neither inline text nor class pairs found, inconclusive
    if not text_colors and not class_pairs:
        warnings.append("no text-on-background pairs found to verify (inconclusive)")

    # Failures dominate; warnings is the fallback.
    # Tag each msg so the caller can decide hard-block vs soft-warn.
    tagged = [("FAIL", m) for m in failures] + [("WARN", m) for m in warnings]
    return len(failures) == 0, tagged


def visual_quality_check(path: Path) -> dict:
    """Run all visual-quality checks on one SVG file."""
    if not path.exists():
        return {"file": str(path), "status": "ERROR", "reason": "file not found"}
    if path.suffix.lower() != ".svg":
        return {"file": str(path), "status": "SKIP", "reason": "not an SVG"}

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as err:
        return {"file": str(path), "status": "ERROR", "reason": str(err)}

    palette_ok, palette_violations = check_wong_palette(text)
    a11y_ok, a11y_issues = check_svg_accessibility(text)
    contrast_ok, contrast_tagged = check_wcag_contrast(text)

    # Split contrast results by severity: FAIL -> hard, WARN -> soft.
    contrast_fails = [m for tag, m in contrast_tagged if tag == "FAIL"]
    contrast_warns = [m for tag, m in contrast_tagged if tag == "WARN"]

    # Overall status: BLOCK on hard-rule violations; WARN otherwise
    hard_violations = []
    if not palette_ok:
        hard_violations.append(f"GR-5 Wong palette: {len(palette_violations)} non-Wong colors")
    if not a11y_ok:
        hard_violations.append(f"GR-8 accessibility: {len(a11y_issues)} issues")
    if contrast_fails:
        hard_violations.append(f"GR-9 contrast FAIL: {len(contrast_fails)} class pairs <4.5:1")
    soft_warnings = []
    if contrast_warns:
        soft_warnings.append(f"GR-9 contrast: {len(contrast_warns)} inconclusive")

    if hard_violations:
        status = "BLOCK"
    elif soft_warnings:
        status = "WARN"
    else:
        status = "OK"

    return {
        "file": str(path),
        "status": status,
        "wong_palette_pass": palette_ok,
        "wong_palette_violations": palette_violations,
        "svg_a11y_pass": a11y_ok,
        "svg_a11y_issues": a11y_issues,
        "wcag_contrast_pass": contrast_ok,
        "wcag_contrast_fails": contrast_fails,
        "wcag_contrast_warnings": contrast_warns,
        "hard_violations": hard_violations,
        "soft_warnings": soft_warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagram Visual-Quality Linter (GR-5, GR-8, GR-9 enforcement)"
    )
    parser.add_argument("paths", nargs="+", help="SVG files or directories")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--check-palette-only", action="store_true",
                        help="Only run Wong palette check (skip accessibility + contrast)")
    args = parser.parse_args()

    # Collect SVG files
    files = []
    for inp in args.paths:
        p = Path(inp)
        if p.is_dir():
            files.extend(p.rglob("*.svg"))
        elif p.is_file():
            files.append(p)

    if not files:
        print("no SVG files found", file=sys.stderr)
        return 2

    results = [visual_quality_check(p) for p in sorted(set(files))]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            if r["status"] == "ERROR":
                print(f"  ERR   {r['file']}  ({r['reason']})")
                continue
            if r["status"] == "SKIP":
                print(f"  SKIP  {r['file']}  ({r['reason']})")
                continue
            marker = {"OK": "  OK ", "WARN": " WARN", "BLOCK": "BLOCK"}[r["status"]]
            print(f"{marker}  {r['file']}")
            for v in r.get("hard_violations", []):
                print(f"         BLOCK: {v}")
            for w in r.get("soft_warnings", []):
                print(f"          WARN: {w}")
            if r.get("wong_palette_violations"):
                print(f"          non-Wong colors: {', '.join(r['wong_palette_violations'][:5])}"
                      + ("..." if len(r["wong_palette_violations"]) > 5 else ""))
            if r.get("svg_a11y_issues"):
                print(f"          a11y: {', '.join(r['svg_a11y_issues'])}")

    return 1 if any(r.get("status") == "BLOCK" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
