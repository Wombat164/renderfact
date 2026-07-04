#!/usr/bin/env python3
"""
Diagram Element-Budget Linter
==============================

Enforces GR-4 (view-tier element budgets), generalized from a private
consumer's AaC diagram-pipeline style guide.

Budgets (per view tier):
  executive-cover    hard 7  soft 5    (V1 concentric ring)
  programme-planning hard 15 soft 12   (programme summary)
  operator-handoff   hard 25 soft 20   (runbook references)
  procurement-annex  hard 30 soft 25   (procurement annex)

Input formats supported (Phase 3 starter):
  - .mmd (Mermaid)        : counts non-comment, non-empty lines containing -->/--/:::
  - .d2  (D2)             : counts statements (lines with `:` or `->`)
  - .svg (SVG)            : counts top-level <g> + <rect> + <circle> + <ellipse> + <polygon>
  - .yaml/.yml (viewpoint overlays): counts items in top-level lists across overlay blocks
  - .puml (PlantUML)      : counts component/node/database declarations

For each input file, tier is inferred from filename suffix or `# view-tier:` header
comment. Example:
    # view-tier: executive-cover
    # view-tier: procurement-annex

Exit codes:
  0 = all files within hard budget (warns for soft target overruns)
  1 = at least one hard-budget violation
  2 = usage error / unparseable input

Compliance: GR-4 enforcement; non-conformance blocks at CI per doctrine §8.7.

Usage:
  python lint/element_budget.py <file_or_dir>...
  python lint/element_budget.py --tier=procurement-annex path/to/diagram.svg
  python lint/element_budget.py --json path/...    # machine-readable output

Last review: 2026-05-24
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

BUDGETS = {
    "executive-cover": {"hard": 7, "soft": 5},
    "programme-planning": {"hard": 15, "soft": 12},
    "operator-handoff": {"hard": 25, "soft": 20},
    "procurement-annex": {"hard": 30, "soft": 25},
}

VALID_TIERS = set(BUDGETS.keys())


def detect_tier(path: Path, override: str | None) -> str:
    """Detect view-tier from override, filename suffix, or header comment."""
    if override:
        if override not in VALID_TIERS:
            raise ValueError(f"unknown tier '{override}'; expected one of {VALID_TIERS}")
        return override

    # Filename pattern: foo.executive-cover.svg
    for tier in VALID_TIERS:
        if f".{tier}." in path.name:
            return tier

    # Header comment: # view-tier: procurement-annex    (Mermaid/D2/YAML/PlantUML)
    #                 <!-- view-tier: ... -->    (SVG / XML)
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:4096]
        match = re.search(r"view-tier:\s*(\S+)", head)
        if match:
            tier = match.group(1).strip(" -->")  # strip trailing XML comment chars
            if tier in VALID_TIERS:
                return tier
    except OSError:
        pass

    # Default to most permissive (warns but rarely blocks)
    return "procurement-annex"


def count_mermaid(text: str) -> int:
    """Count Mermaid nodes via lines containing -->, ---, :::, or first-of-line node decls."""
    count = 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("%%") or s.startswith("#"):
            continue
        # Edge declarations
        if "-->" in s or "---" in s or ":::" in s:
            count += 1
        # Top-level node-style declarations (heuristic)
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*[\[(\{]", s):
            count += 1
    return count


def count_d2(text: str) -> int:
    """Count D2 statements (lines with ':' or '->' that aren't comments)."""
    count = 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" in s or "->" in s or "--" in s:
            count += 1
    return count


def count_svg(text: str) -> int:
    """Count semantic visual blocks in SVG. Prefer top-level <g> groups; fall back to shapes."""
    # Strip <defs>...</defs> + <style>...</style> blocks first (don't count theme/setup)
    text_clean = re.sub(r"<defs\b[\s\S]*?</defs>", "", text)
    text_clean = re.sub(r"<style\b[\s\S]*?</style>", "", text_clean)

    # Prefer counting <g> semantic groups (each represents a logical visual block)
    groups = re.findall(r"<g\b", text_clean)
    if groups:
        return len(groups)

    # Fallback for SVGs without <g>: count primitive shapes
    shapes = re.findall(
        r"<(?:rect|circle|ellipse|polygon|path|line)\b",
        text_clean,
    )
    return len(shapes)


def count_yaml(text: str) -> int:
    """Count top-level list items in viewpoint-overlay YAML blocks."""
    # Heuristic: count `- ` at column 2 or 4 within sections that look like overlays
    count = 0
    in_overlay = False
    for line in text.splitlines():
        if re.match(r"^[a-z_]+_overlay:\s*$", line):
            in_overlay = True
            continue
        if in_overlay and re.match(r"^[A-Za-z_]", line):
            in_overlay = False
        if in_overlay and re.match(r"^\s{2,4}-\s", line):
            count += 1
    return count


def count_plantuml(text: str) -> int:
    """Count PlantUML component/node/database/actor declarations."""
    return len(re.findall(
        r"^\s*(?:component|node|database|actor|rectangle|cloud|frame|package)\b",
        text,
        flags=re.MULTILINE,
    ))


COUNTERS = {
    ".mmd": count_mermaid,
    ".mermaid": count_mermaid,
    ".d2": count_d2,
    ".svg": count_svg,
    ".yaml": count_yaml,
    ".yml": count_yaml,
    ".puml": count_plantuml,
    ".plantuml": count_plantuml,
}


def lint_file(path: Path, override_tier: str | None) -> dict:
    """Lint one file. Returns dict with file, tier, count, hard, soft, status."""
    ext = path.suffix.lower()
    if ext not in COUNTERS:
        return {
            "file": str(path),
            "status": "SKIP",
            "reason": f"unsupported extension '{ext}'",
        }

    tier = detect_tier(path, override_tier)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as err:
        return {"file": str(path), "status": "ERROR", "reason": str(err)}

    count = COUNTERS[ext](text)
    hard = BUDGETS[tier]["hard"]
    soft = BUDGETS[tier]["soft"]

    if count > hard:
        status = "BLOCK"
    elif count > soft:
        status = "WARN"
    else:
        status = "OK"

    return {
        "file": str(path),
        "tier": tier,
        "count": count,
        "hard": hard,
        "soft": soft,
        "status": status,
    }


def collect_paths(inputs: Iterable[str]) -> list[Path]:
    """Expand input args to a flat list of files."""
    out: list[Path] = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            for ext in COUNTERS:
                out.extend(p.rglob(f"*{ext}"))
        elif p.is_file():
            out.append(p)
    return sorted(set(out))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagram Element-Budget Linter (GR-4 enforcement)",
    )
    parser.add_argument("paths", nargs="+", help="Files or directories to lint")
    parser.add_argument("--tier", choices=sorted(VALID_TIERS),
                        help="Override view-tier detection")
    parser.add_argument("--json", action="store_true",
                        help="Machine-readable JSON output")
    args = parser.parse_args()

    paths = collect_paths(args.paths)
    if not paths:
        print("no input files found", file=sys.stderr)
        return 2

    results = [lint_file(p, args.tier) for p in paths]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        # Human-readable
        for r in results:
            if r["status"] == "SKIP":
                print(f"  SKIP  {r['file']}  ({r['reason']})")
                continue
            if r["status"] == "ERROR":
                print(f"  ERR   {r['file']}  ({r['reason']})")
                continue
            marker = {"OK": "  OK ", "WARN": " WARN", "BLOCK": "BLOCK"}[r["status"]]
            print(
                f"{marker}  {r['file']}  "
                f"[{r['tier']}]  {r['count']} elements  "
                f"(soft {r['soft']}, hard {r['hard']})"
            )

    # Exit code: 1 if any BLOCK, else 0
    return 1 if any(r.get("status") == "BLOCK" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
