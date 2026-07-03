#!/usr/bin/env python3
"""run_gates.py: the deterministic pre-publish QA gate chain (Track B3).

Unlike `render doctor` (report-only, never fails), a gate is FAIL-CLOSED:
findings fail the run, and a REQUESTED stage whose tool is not installed also
fails the run (exit 2): a gate you cannot execute is not a gate you passed.
All stages are deterministic CLI subprocesses, no LLM anywhere (the B3 gate
philosophy); heavyweight prose intelligence belongs to a consumer's own
config, not this core.

Stages (each adopted per docs/ROADMAP.md B3, CLI-subprocess only):
  vale     text hygiene on markdown sources (errata-ai/vale). Generic default
           config: gates/vale/vale.ini (repetition blocks, spelling warns);
           override with --vale-config or RENDERFACT_VALE_CONFIG.
  lychee   link integrity on markdown sources (lycheeverse/lychee). OFFLINE by
           default (relative file links + anchors only; external URLs excluded)
           so the verdict is deterministic and CI-safe; --online opts into
           checking external URLs, accepting network flakiness. Binary override:
           RENDERFACT_LYCHEE_BIN (for hosts where lychee is not on PATH).
Planned next: verapdf (PDF/A + PDF/UA conformance, CLI-subprocess invocation
per the recorded licence election).

Usage:
    render gate <files-or-dirs...> [--stages vale,lychee] [--vale-config PATH] [--online]

Exit codes: 0 every requested stage passed; 1 findings; 2 a requested stage's
tool is missing or the invocation itself is unusable.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALE_CONFIG = REPO_ROOT / "gates" / "vale" / "vale.ini"


@dataclass
class StageResult:
    stage: str
    status: str  # PASS | FAIL | TOOL_MISSING | NO_FILES
    detail: str = ""


def _resolve_files(targets: list[str], suffixes: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            files.extend(sorted(q for q in p.rglob("*") if q.suffix.lower() in suffixes))
        elif p.suffix.lower() in suffixes:
            files.append(p)
    return files


def run_vale(targets: list[str], config: Path | None,
             which=shutil.which, runner=subprocess.run) -> StageResult:
    files = _resolve_files(targets, (".md",))
    if not files:
        return StageResult("vale", "NO_FILES", "no .md files among the targets")
    exe = which("vale")
    if not exe:
        return StageResult("vale", "TOOL_MISSING",
                           "vale not installed (errata-ai/vale); a requested gate that "
                           "cannot run is a FAILED gate, not a skipped one")
    cfg = config or Path(os.environ.get("RENDERFACT_VALE_CONFIG", DEFAULT_VALE_CONFIG))
    proc = runner(
        [exe, "--config", str(cfg), "--output", "line", *map(str, files)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    output = (proc.stdout or "").strip()
    if proc.returncode == 0:
        return StageResult("vale", "PASS", f"{len(files)} file(s) clean")
    if proc.returncode == 1:
        return StageResult("vale", "FAIL", output or "findings at or above the blocking level")
    return StageResult("vale", "TOOL_MISSING",
                       f"vale invocation unusable (exit {proc.returncode}): "
                       f"{(proc.stderr or output).strip()[:300]}")


def run_lychee(targets: list[str], online: bool = False,
               which=shutil.which, runner=subprocess.run) -> StageResult:
    files = _resolve_files(targets, (".md",))
    if not files:
        return StageResult("lychee", "NO_FILES", "no .md files among the targets")
    exe = os.environ.get("RENDERFACT_LYCHEE_BIN") or which("lychee")
    if not exe:
        return StageResult("lychee", "TOOL_MISSING",
                           "lychee not installed (lycheeverse/lychee); a requested gate that "
                           "cannot run is a FAILED gate, not a skipped one")
    cmd = [exe, "--no-progress"]
    if not online:
        cmd.append("--offline")  # deterministic: file links only, external URLs excluded
    proc = runner(
        [*cmd, *map(str, files)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
    )
    output = (proc.stdout or "").strip()
    # lychee exit codes: 0 = clean, 2 = broken links found, anything else = unusable run
    if proc.returncode == 0:
        mode = "online" if online else "offline"
        return StageResult("lychee", "PASS", f"{len(files)} file(s) clean ({mode})")
    if proc.returncode == 2:
        return StageResult("lychee", "FAIL", output or "broken links found")
    return StageResult("lychee", "TOOL_MISSING",
                       f"lychee invocation unusable (exit {proc.returncode}): "
                       f"{(proc.stderr or output).strip()[:300]}")


STAGES = {
    "vale": run_vale,
    "lychee": run_lychee,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="render gate",
        description="Deterministic fail-closed QA gate chain (B3). No LLM, no network.",
    )
    ap.add_argument("targets", nargs="+", help="files or directories to gate")
    ap.add_argument("--stages", default="vale,lychee",
                    help=f"comma-separated stages to run (available: {', '.join(sorted(STAGES))})")
    ap.add_argument("--vale-config", type=Path, default=None,
                    help="Vale config override (default: the generic-core "
                         "gates/vale/vale.ini, or RENDERFACT_VALE_CONFIG)")
    ap.add_argument("--online", action="store_true",
                    help="lychee: also check external URLs (non-deterministic, "
                         "network-dependent; default is offline file-link integrity)")
    args = ap.parse_args(argv)

    requested = [s.strip() for s in args.stages.split(",") if s.strip()]
    unknown = [s for s in requested if s not in STAGES]
    if unknown:
        print(f"ERROR: unknown stage(s): {', '.join(unknown)} "
              f"(available: {', '.join(sorted(STAGES))})", file=sys.stderr)
        return 2

    results = []
    for stage in requested:
        if stage == "vale":
            results.append(run_vale(args.targets, args.vale_config))
        elif stage == "lychee":
            results.append(run_lychee(args.targets, online=args.online))

    worst = 0
    for r in results:
        print(f"[{r.stage}] {r.status}" + (f"\n{r.detail}" if r.detail else ""))
        if r.status == "FAIL":
            worst = max(worst, 1)
        elif r.status == "TOOL_MISSING":
            worst = max(worst, 2)
    print(f"\ngate: {sum(r.status == 'PASS' for r in results)}/{len(results)} stage(s) passed "
          f"(fail-closed: findings or a missing tool fail the run)")
    return worst


if __name__ == "__main__":
    sys.exit(main())
