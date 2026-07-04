#!/usr/bin/env python3
"""
Mermaid Source-Level Linter (pre-render).

Catches bugs in `.mmd` sources BEFORE invoking mmdc, so we waste no render
cycles and surface root-cause line numbers instead of post-hoc visual defects.

Rules (per V2 framework doctrine + 2026-05-24 web research):
  GR-MM-DIR     flowchart direction in {TB, TD, BT, LR, RL}
  GR-MM-NODEID  node IDs match [A-Za-z0-9_]+ (no spaces / trailing punctuation)
  GR-MM-SEED    deterministicIDSeed asserted (front-matter or theme config)
  GR-MM-DET     architecture-beta forbidden in render-bound directories
                (issue #6024 still open as of 2026-05; layout drifts between renders)
  GR-CHAR-1     no fancy Unicode in source (ASCII + NL/FR/EN diacritics only;
                matches the configured house-style em-dash + smart-quote ban)
  GR-MM-VIEW    `view-tier:` comment present (programme-planning / operator-handoff /
                executive-cover / procurement-annex)
  GR-MM-VP      `NAFv4:` viewpoint stereotype comment per DoD CTO + NATO 2025 guides
                (warn for non-AA tier; block for procurement-annex tier)

Usage:
  python lint/mermaid_source.py <file.mmd>...
  python lint/mermaid_source.py --json <file.mmd>...
  python lint/mermaid_source.py --tier procurement-annex <file.mmd>  # escalate GR-MM-VP to BLOCK

Exit codes:
  0 = clean / WARN only
  1 = at least one BLOCK rule fired
  2 = usage error

Last review: 2026-05-24
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

VALID_DIRECTIONS = {"TB", "TD", "BT", "LR", "RL"}

# Allowed Unicode set: ASCII + Latin-1 supplement diacritics for NL/FR/DE/EN.
# Blocks smart quotes (U+2018-201F), em-dash (U+2014), en-dash (U+2013),
# ellipsis (U+2026), non-breaking space (U+00A0), arrows (U+2190-21FF), etc.
ALLOWED_DIACRITICS = set(
    "àáâãäåçèéêëìíîïñòóôõöùúûüýÿÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝŸ"
    "œŒæÆ"
)

# Additional configured-doctrine symbols allowed in source comments + labels
# §  U+00A7 SECTION SIGN -- standard legal/doctrine reference symbol
# ©  U+00A9 COPYRIGHT
# ®  U+00AE REGISTERED
# ±  U+00B1 PLUS-MINUS
# °  U+00B0 DEGREE
# µ  U+00B5 MICRO
# ½ ¼ ¾  fractions
ALLOWED_DOCTRINE_SYMBOLS = set("§©®±°µ½¼¾")

# NAFv4 viewpoint stereotypes (subset; allow any token starting with these prefixes)
NAF_VIEWPOINT_PREFIXES = ("NSOV-", "NSV-", "NOV-", "NAV-", "NPV-", "NTV-", "NCV-")

# V3.1 F6 hardening: enumerated NAFv4 viewpoint codes per NATO ArchiMate
# Modeling Guide for NAFv4 (Jan 2025). Prefix-only validation lets NSV-99
# pass; enum lookup catches typos + invented codes.
# Source: NATO ArchiMate Modeling Guide for NAFv4 (2025-01) Annex A
NAF_VIEWPOINT_ENUM = {
    # NSOV: NATO Service-Oriented View
    "NSOV-1", "NSOV-2", "NSOV-3", "NSOV-4", "NSOV-5",
    # NSV: NATO Systems View
    "NSV-1", "NSV-2", "NSV-3", "NSV-4", "NSV-5",
    "NSV-6", "NSV-7", "NSV-8", "NSV-9", "NSV-10",
    "NSV-11", "NSV-12",
    # NOV: NATO Operational View
    "NOV-1", "NOV-2", "NOV-3", "NOV-4", "NOV-5",
    "NOV-6", "NOV-7",
    # NAV: NATO All View
    "NAV-1", "NAV-2", "NAV-3",
    # NPV: NATO Programme View
    "NPV-1", "NPV-2", "NPV-3", "NPV-4",
    # NTV: NATO Technical View
    "NTV-1", "NTV-2", "NTV-3", "NTV-4", "NTV-5",
    # NCV: NATO Capability View
    "NCV-1", "NCV-2", "NCV-3", "NCV-4", "NCV-5",
    "NCV-6", "NCV-7",
}

# Tiers that mandate viewpoint declaration
STRICT_TIERS = {"procurement-annex"}


def lint_chars(text: str) -> list[tuple[int, str]]:
    """GR-CHAR-1: flag any byte outside ASCII + allowed Latin diacritics."""
    issues = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for col, ch in enumerate(line, 1):
            cp = ord(ch)
            if cp < 0x80:
                continue
            if ch in ALLOWED_DIACRITICS or ch in ALLOWED_DOCTRINE_SYMBOLS:
                continue
            # Anything else = fancy Unicode
            issues.append(
                (lineno, f"GR-CHAR-1 fancy Unicode U+{cp:04X} '{ch}' at line {lineno} col {col}")
            )
            break  # one report per line
    return issues


def lint_direction(text: str) -> list[tuple[int, str]]:
    """GR-MM-DIR: flowchart direction valid."""
    issues = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        m = re.match(r"^(?:flowchart|graph)\s+([A-Z]+)", stripped)
        if m:
            direction = m.group(1)
            if direction not in VALID_DIRECTIONS:
                issues.append(
                    (lineno, f"GR-MM-DIR invalid direction '{direction}' (valid: {sorted(VALID_DIRECTIONS)})")
                )
    return issues


def lint_node_ids(text: str) -> list[tuple[int, str]]:
    """GR-MM-NODEID: node IDs match [A-Za-z0-9_]+ (no spaces / trailing punct).

    Skipped entirely for `gantt` and `timeline` diagram types -- those use a
    different syntax (`Task Name :status, taskId, start, dur`) where the
    human-readable label legitimately contains whitespace; only the `taskId`
    field needs to be a valid identifier and is validated by Mermaid itself.
    """
    # Detect diagram type from first non-frontmatter / non-comment line
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("%%") or stripped.startswith(("---", "title:", "accTitle:", "accDescr:", "init:", "config:")):
            continue
        if stripped.startswith((
            "gantt", "timeline", "sequenceDiagram", "stateDiagram",
            "quadrantChart", "mindmap", "erDiagram", "pie", "journey",
            "requirementDiagram", "C4Context", "C4Container",
            "C4Component", "C4Deployment", "C4Dynamic",
        )):
            return []
        break
    issues = []
    # Heuristic: an ID-bearing token is at the start of a node declaration
    # of the form `ID[...]`, `ID(...)`, `ID{...}`, `ID("...")`, etc.
    # We catch obvious violations: spaces inside the ID prefix.
    in_classdef = False
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        # Skip pure-comment lines and classDef lines (their syntax is different)
        if stripped.startswith("%%"):
            continue
        if stripped.startswith("classDef") or stripped.startswith("class "):
            continue
        # Skip frontmatter / accDirective / theme directives
        if stripped.startswith(("---", "title:", "accTitle:", "accDescr:", "init:", "config:")):
            continue
        # Skip Mermaid structural keywords -- subgraph/end/direction are keywords, not node IDs
        if stripped.startswith(("subgraph ", "end", "direction ", "flowchart ", "graph ")):
            continue
        # Look for "ID<paren-or-bracket-open>" with ID containing a space
        m = re.match(r"^([^\s\[\(\{<>\-]+(?:\s+[^\s\[\(\{<>\-]+)+)\s*[\[\(\{]", stripped)
        if m:
            issues.append(
                (lineno, f"GR-MM-NODEID node ID '{m.group(1)}' contains whitespace -- collapse to underscore")
            )
    return issues


def lint_arch_beta(text: str, path: Path, render_bound: bool) -> list[tuple[int, str]]:
    """GR-MM-DET: architecture-beta forbidden in render-bound directories."""
    issues = []
    if not render_bound:
        return issues
    for lineno, line in enumerate(text.splitlines(), 1):
        if "architecture-beta" in line:
            issues.append(
                (lineno, "GR-MM-DET architecture-beta in render-bound source; issue #6024 still open -- layout drifts between renders")
            )
            break
    return issues


def lint_view_tier(text: str) -> list[tuple[int, str]]:
    """GR-MM-VIEW: view-tier comment present."""
    if re.search(r"%%\s*view-tier:\s*\w", text):
        return []
    return [(0, "GR-MM-VIEW missing `%% view-tier:` comment (programme-planning|operator-handoff|executive-cover|procurement-annex)")]


def lint_viewpoint(text: str, tier: str | None) -> list[tuple[int, str, str]]:
    """GR-MM-VP: NAFv4 viewpoint stereotype declared (BLOCK for AA, WARN otherwise).

    Per DoD CTO Mission Architecture Style Guide (Jan 2025) + NATO ArchiMate
    Modeling Guide for NAFv4 (Jan 2025): every view declares its NAFv4 viewpoint.
    """
    has = re.search(r"%%\s*NAFv4:\s*([A-Z]+-\w+)", text)
    if has:
        viewpoint = has.group(1)
        # V3.1 F6: enum lookup (not prefix-only) -- NSV-99 must fail
        if viewpoint not in NAF_VIEWPOINT_ENUM:
            sev = "BLOCK" if tier in STRICT_TIERS else "WARN"
            if not viewpoint.startswith(NAF_VIEWPOINT_PREFIXES):
                return [(0, sev, f"GR-MM-VP viewpoint '{viewpoint}' not a recognised NAFv4 prefix (need one of {NAF_VIEWPOINT_PREFIXES})")]
            return [(0, sev, f"GR-MM-VP viewpoint '{viewpoint}' not in NAFv4 enum (Jan 2025 NATO ArchiMate guide); use one of: NSOV-1..5, NSV-1..12, NOV-1..7, NAV-1..3, NPV-1..4, NTV-1..5, NCV-1..7")]
        return []
    sev = "BLOCK" if tier in STRICT_TIERS else "WARN"
    return [(0, sev, "GR-MM-VP missing `%% NAFv4: <viewpoint>` (e.g. NSOV-2, NSV-10) per DoD CTO + NATO 2025 style guides")]


def lint_deterministic_seed(text: str) -> list[tuple[int, str]]:
    """GR-MM-SEED: deterministicIDSeed asserted (in source frontmatter or theme).

    Note: theme JSON file is consumed via mmdc -c flag and may carry the seed
    instead of the source. So this rule WARNS rather than BLOCKS -- the operator
    must verify that EITHER the source OR the theme has it.
    """
    if "deterministicIDSeed" in text or "deterministicIds" in text:
        return []
    return [(0, "GR-MM-SEED no deterministicIDSeed in source -- verify theme JSON has it (issue #6530 string-length bug bites short seeds; use >=8 ASCII chars)")]


def is_render_bound(path: Path) -> bool:
    """Heuristic: is this source destined for committed render output?

    True if the path matches one of the configured render-bound directory
    substrings. False for daily-notes / inbox / sources equivalents.

    The substring list is configurable via the RENDERFACT_RB_SUBSTRINGS
    environment variable (comma-separated, e.g.
    "Templates,templates,diagrams,docs-as-code"). When the env var is
    unset, a generic built-in default is used so consumers are not
    required to fork this check just to match their own folder layout.
    """
    env_override = os.environ.get("RENDERFACT_RB_SUBSTRINGS")
    if env_override:
        rb_substrings = tuple(s.strip() for s in env_override.split(",") if s.strip())
    else:
        rb_substrings = ("Templates", "templates", "diagram-pipeline")
    s = str(path)
    return any(sub in s for sub in rb_substrings)


def lint_file(path: Path, tier: str | None = None) -> dict:
    """Run all rules on one source file. Returns structured result."""
    if not path.exists():
        return {"file": str(path), "status": "ERROR", "reason": "not found"}
    if path.suffix.lower() not in (".mmd", ".d2", ".drawio"):
        return {"file": str(path), "status": "SKIP", "reason": "not a recognised source"}

    text = path.read_text(encoding="utf-8", errors="replace")

    # Apply rules. Some are file-type specific.
    blocks: list[str] = []
    warns: list[str] = []

    if path.suffix.lower() == ".mmd":
        for _, msg in lint_chars(text):
            blocks.append(msg)
        for _, msg in lint_direction(text):
            blocks.append(msg)
        for _, msg in lint_node_ids(text):
            blocks.append(msg)
        for _, msg in lint_arch_beta(text, path, is_render_bound(path)):
            blocks.append(msg)
        for _, msg in lint_view_tier(text):
            warns.append(msg)
        for tup in lint_viewpoint(text, tier):
            _, sev, msg = tup
            (blocks if sev == "BLOCK" else warns).append(msg)
        for _, msg in lint_deterministic_seed(text):
            warns.append(msg)
    elif path.suffix.lower() == ".d2":
        # GR-CHAR-1 applies to all source types
        for _, msg in lint_chars(text):
            blocks.append(msg)
        # GR-D2-PIN: needs sibling .d2.lock
        lock = path.with_suffix(".d2.lock")
        if not lock.exists():
            warns.append(f"GR-D2-PIN missing sibling .d2.lock pinning d2_version/layout_engine/theme_id")
    elif path.suffix.lower() == ".drawio":
        for _, msg in lint_chars(text):
            blocks.append(msg)
        # GR-DRAWIO-FONT: simple allowlist check
        allowed_fonts = {"DejaVu Sans", "Liberation Sans", "Inter"}
        for ff in re.findall(r'fontFamily=([^;"]+)', text):
            if ff.strip().strip("'\"") not in allowed_fonts:
                warns.append(f"GR-DRAWIO-FONT non-allowlist fontFamily '{ff}' (allowed: {sorted(allowed_fonts)})")
                break  # one report per file

    status = "BLOCK" if blocks else ("WARN" if warns else "OK")
    return {
        "file": str(path),
        "status": status,
        "blocks": blocks,
        "warns": warns,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Mermaid source-level linter (pre-render)")
    p.add_argument("paths", nargs="+")
    p.add_argument("--json", action="store_true")
    p.add_argument("--tier", default=None,
                   choices=[None, "executive-cover", "programme-planning",
                            "operator-handoff", "procurement-annex"],
                   help="If set, escalates tier-specific rules (e.g. GR-MM-VP -> BLOCK on procurement-annex)")
    args = p.parse_args()

    files = []
    for inp in args.paths:
        path = Path(inp)
        if path.is_dir():
            for ext in (".mmd", ".d2", ".drawio"):
                files.extend(path.rglob(f"*{ext}"))
        elif path.is_file():
            files.append(path)

    results = [lint_file(f, args.tier) for f in sorted(set(files))]

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            if r["status"] == "ERROR":
                print(f"  ERR  {r['file']}  ({r['reason']})")
                continue
            if r["status"] == "SKIP":
                continue
            marker = {"OK": "  OK ", "WARN": " WARN", "BLOCK": "BLOCK"}[r["status"]]
            print(f"{marker}  {r['file']}")
            for b in r.get("blocks", []):
                print(f"         BLOCK: {b}")
            for w in r.get("warns", []):
                print(f"          WARN: {w}")

    return 1 if any(r.get("status") == "BLOCK" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
