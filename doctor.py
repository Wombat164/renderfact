#!/usr/bin/env python3
"""doctor.py: native-mode version-drift check against tools.lock (chunk 1.5, A5/D10).

Container mode has verify-pins.sh: hermetic, fail-closed. Native mode inherently
cannot guarantee hermeticity (the host owns its tools), so `render doctor` WARNS
on drift and never fails closed: it reports and exits 0, always. That asymmetry
is D10's deliberate design, not an oversight. No network calls.

Per tools.lock entry the verdict is one of:
  OK            installed and the pinned version matches (segment-prefix rule:
                a pin of 3.10 accepts 3.10.x, and 3.1 does NOT accept 3.10)
  OK unpinned   installed; the lock deliberately pins no version ("installed")
  DRIFT         installed but a different version than the lock pins
  MISSING       not found on this host
  SKIP          container-scope or non-tool entries (base image, fonts, the
                container's python/chromium) and entries the lock itself marks
                BROKEN: nothing meaningful to check natively

Usage:
    render doctor [--json] [--lock PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_LOCK = REPO_ROOT / "tools.lock"

# Entries with nothing to check on a native host (container-scope or non-tools).
SKIP_ENTRIES = {
    "base-image": "container base image",
    "python": "container interpreter (host python is whatever runs this)",
    "chromium": "container-managed headless engine (marp/mmdc bring their own)",
    "fonts": "font list, not a versioned tool",
}

# CLI tools: lock name -> (command candidates, version args, version regex).
# Windows npm shims resolve via the .cmd candidates.
CLI_PROBES = {
    "pandoc": (("pandoc",), ("--version",), r"pandoc(?:\.exe)?\s+v?([0-9][0-9.]*)"),
    "typst": (("typst",), ("--version",), r"typst\s+v?([0-9][0-9.]*)"),
    "mmdc": (("mmdc", "mmdc.cmd"), ("--version",), r"([0-9]+(?:\.[0-9]+)+)"),
    "d2": (("d2",), ("--version",), r"v?([0-9]+(?:\.[0-9]+)+)"),
    "marp-cli": (("marp", "marp.cmd"), ("--version",), r"v([0-9]+(?:\.[0-9]+)+)"),
    "likec4": (("likec4", "likec4.cmd"), ("--version",), r"([0-9]+(?:\.[0-9]+)+)"),
    "libreoffice": (("soffice",), ("--version",), r"LibreOffice\s+([0-9]+(?:\.[0-9]+)+)"),
}

# Python packages: lock name -> distribution name (importlib.metadata).
PY_PROBES = {
    "cairosvg": "cairosvg",
    "python-docx": "python-docx",
    "openpyxl": "openpyxl",
    "python-pptx": "python-pptx",
    "docxcompose": "docxcompose",
    "pypdf": "pypdf",
}


@dataclass
class Result:
    tool: str
    pinned: str
    found: str | None
    status: str  # OK | OK unpinned | DRIFT | MISSING | SKIP
    note: str = ""


def parse_lock(path: Path = DEFAULT_LOCK) -> dict[str, str]:
    """tools.lock lines are `name: value   # comment`; comments and blanks skipped."""
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        value = value.strip()
        if name.strip() and value:
            pins[name.strip()] = value
    return pins


def versions_match(pinned: str, found: str) -> bool:
    """Segment-prefix rule: every pinned dot-segment must equal the corresponding
    found segment (3.10 accepts 3.10.1; 3.1 rejects 3.10; 0.15.0 rejects 0.15.1)."""
    pin_seg = pinned.split(".")
    found_seg = found.split(".")
    if len(found_seg) < len(pin_seg):
        return False
    return all(p == f for p, f in zip(pin_seg, found_seg))


def probe_cli(candidates, args, regex, which=shutil.which, runner=subprocess.run) -> str | None:
    """Return the installed version string, or None if the tool is absent or
    its version output is unparseable."""
    for name in candidates:
        exe = which(name)
        if not exe:
            continue
        try:
            # explicit utf-8 with replacement: version banners may carry bytes the
            # Windows locale codec (cp1252) cannot decode, which otherwise raises
            # inside subprocess's reader thread
            proc = runner([exe, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        m = re.search(regex, (proc.stdout or "") + (proc.stderr or ""))
        return m.group(1) if m else None
    return None


def probe_python_package(dist_name: str) -> str | None:
    from importlib import metadata

    try:
        return metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        return None


def check(pins: dict[str, str], which=shutil.which, runner=subprocess.run,
          py_probe=probe_python_package) -> list[Result]:
    results: list[Result] = []
    for tool, pinned in pins.items():
        if tool in SKIP_ENTRIES:
            results.append(Result(tool, pinned, None, "SKIP", SKIP_ENTRIES[tool]))
            continue
        if pinned.upper() == "BROKEN":
            results.append(Result(tool, pinned, None, "SKIP", "marked BROKEN in tools.lock"))
            continue
        if tool in CLI_PROBES:
            candidates, args, regex = CLI_PROBES[tool]
            found = probe_cli(candidates, args, regex, which=which, runner=runner)
        elif tool in PY_PROBES:
            found = py_probe(PY_PROBES[tool])
        else:
            results.append(Result(tool, pinned, None, "SKIP", "no native probe defined"))
            continue
        if found is None:
            results.append(Result(tool, pinned, None, "MISSING"))
        elif pinned == "installed":
            results.append(Result(tool, pinned, found, "OK unpinned"))
        elif versions_match(pinned, found):
            results.append(Result(tool, pinned, found, "OK"))
        else:
            results.append(Result(tool, pinned, found, "DRIFT",
                                  "native mode warns, never fails closed (D10)"))
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="render doctor",
        description="Report host tool versions against tools.lock (warn on drift, never fail).",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    args = ap.parse_args(argv)

    results = check(parse_lock(args.lock))
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
        return 0

    width = max(len(r.tool) for r in results)
    for r in results:
        pin = "(unpinned)" if r.pinned == "installed" else r.pinned
        found = r.found or "-"
        line = f"{r.tool:<{width}}  {r.status:<11}  pinned {pin:<22} found {found}"
        if r.note:
            line += f"  ({r.note})"
        print(line)
    counts = {s: sum(1 for r in results if r.status.startswith(s)) for s in ("OK", "DRIFT", "MISSING", "SKIP")}
    print(f"\ndoctor: {counts['OK']} ok, {counts['DRIFT']} drift, {counts['MISSING']} missing, "
          f"{counts['SKIP']} skipped. Native mode warns and never fails closed (D10); "
          f"container mode's verify-pins.sh is the fail-closed check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
