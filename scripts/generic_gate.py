#!/usr/bin/env python3
"""generic_gate.py: the PUBLIC hygiene gate (ships with the repo; no data file).

The private-phase publish gate (scan_denylist.py + its term list + baseline) never
ships: publishing the term list would reveal what was scrubbed. This gate is its
public successor and checks only GENERIC hygiene, with every pattern visible right
here:

  - personal filesystem paths in tracked text (Windows user-profile paths,
    /home/<user>/ paths, /Users/<user>/ paths)
  - author/committer emails outside the allowlist (maintainer noreply identities
    plus bots), across ALL history: boundary-free, works on any depth of history
  - obvious credential shapes are left to dedicated tools (gitleaks class); this
    gate is not a secrets scanner and says so

Exit codes: 0 clean, 1 findings, 2 environment error.
Usage: python scripts/generic_gate.py [--allow-email ADDR]...
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The gate mechanism itself legitimately contains example personal-path strings
# (patterns here, fixtures in its test); everything else is scanned.
EXEMPT_PATHS = {
    "scripts/generic_gate.py",
    "tests/test_generic_gate.py",
}

PATH_PATTERNS = [
    (re.compile(r"[A-Za-z]:[/\\]Users[/\\](?!YOURNAME\b)[A-Za-z0-9._-]+"), "Windows user-profile path"),
    (re.compile(r"/home/(?!user\b|runner\b|USER\b)[A-Za-z0-9._-]+/"), "Linux home path"),
    (re.compile(r"/Users/(?!user\b|USER\b)[A-Za-z0-9._-]+/"), "macOS home path"),
]

DEFAULT_ALLOWED_EMAIL_PATTERNS = [
    re.compile(r"^[0-9]+\+[A-Za-z0-9._-]+@users\.noreply\.github\.com$"),
    re.compile(r"^[A-Za-z0-9._-]+@users\.noreply\.github\.com$"),
    re.compile(r"^(dependabot(\[bot\])?|github-actions(\[bot\])?)@users\.noreply\.github\.com$"),
    re.compile(r"^\d+\+(dependabot|github-actions)\[bot\]@users\.noreply\.github\.com$"),
    # GitHub's own web-flow identity: the committer on UI squash-merges AND on the
    # synthetic refs/pull/N/merge commit CI checks out for PRs. Inherently neutral.
    re.compile(r"^noreply@github\.com$"),
]


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode not in (0, 1):
        raise SystemExit(f"git {' '.join(args[:3])}... failed: {result.stderr.strip()}")
    return result.stdout


def scan_tree_paths() -> list[str]:
    findings = []
    files = [p for p in _git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
             if p and p not in EXEMPT_PATHS]
    for rel in files:
        path = REPO_ROOT / rel
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:8192]:
            continue
        text = data.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat, label in PATH_PATTERNS:
                m = pat.search(line)
                if m:
                    findings.append(f"{rel}:{lineno}  [{label}]  {m.group(0)}")
    return findings


def scan_identities(extra_allowed: list[str]) -> list[str]:
    exact_allowed = set(extra_allowed)
    out = _git("log", "--all", "--format=%H%x1f%ae%x1f%ce")
    problems = []
    for record in out.splitlines():
        sha, ae, ce = (record.split("\x1f") + [""] * 3)[:3]
        for email in {ae, ce}:
            if not email or email in exact_allowed:
                continue
            if any(p.match(email) for p in DEFAULT_ALLOWED_EMAIL_PATTERNS):
                continue
            problems.append(f"{sha[:12]}: {email}")
    return sorted(set(problems))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--allow-email", action="append", default=[],
                    help="additional exact email to allow (repeatable)")
    args = ap.parse_args(argv)

    findings = scan_tree_paths()
    identity_problems = scan_identities(args.allow_email)

    if findings:
        print(f"GENERIC GATE FAIL: {len(findings)} personal-path hit(s):")
        for f in findings[:100]:
            print(f"  {f}")
    if identity_problems:
        print(f"GENERIC GATE FAIL: {len(identity_problems)} non-allowlisted commit identity(ies):")
        for p in identity_problems[:100]:
            print(f"  {p}")
    if findings or identity_problems:
        return 1
    print("generic gate OK: no personal paths in tree, all commit identities allowlisted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
