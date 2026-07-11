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
  verapdf  PDF/A + PDF/UA conformance on rendered PDFs (veraPDF, invoked as a
           CLI SUBPROCESS: the dual GPL/MPL licence election recorded in the
           roadmap, no library embedding). By default validates each PDF
           against the standard it DECLARES (auto-detect; an undeclared plain
           PDF falls back to PDF/A-1b and fails, which is correct: an archival
           gate should reject a non-archival PDF); --pdf-flavour forces one
           (e.g. ua1). Binary override: RENDERFACT_VERAPDF_BIN.
  uids     duplicate renderfact_uid detection across a source tree. uuid4
           generation cannot collide, but FILE COPIES duplicate identity (a
           forked source or a template carrying a renderfact_uid claims the
           original's lineage); at organisational scale that corrupts every
           provenance-anchored round-trip. Deterministic, dependency-free.
  plainlang  repeated-phrase-across-sections scan (issue #76), the one
           PlainLanguage check that is not a Vale rule (see
           docstyle/plain_language.py for why: it needs the document's own
           text as the source of the pattern to search for, which nothing in
           Vale's DSL can express). A cheap n-gram/exact-match scan, no NLP.
           UNLIKE every other stage here, a finding does NOT fail the run by
           default: a repeated multi-word run is very often legitimate (a
           programme or component name used consistently), not a defect, so
           report-only matches this repo's own `render qa leaks
           --fail-on-hits` precedent rather than the fail-closed default.
           Pass --plainlang-fail-on-hits to make it CI-blocking once tuned.
           Deterministic, dependency-free.
All stages self-scope by file type, so one `render gate <dir>` run applies
each stage to the files it understands.

Usage:
    render gate <files-or-dirs...> [--stages vale,lychee,verapdf] [--vale-config PATH]
                [--online] [--pdf-flavour ua1|2b|...]
                [--plainlang-min-words N] [--plainlang-min-count N] [--plainlang-fail-on-hits]

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


def run_verapdf(targets: list[str], flavour: str | None = None,
                which=shutil.which, runner=subprocess.run) -> StageResult:
    files = _resolve_files(targets, (".pdf",))
    if not files:
        return StageResult("verapdf", "NO_FILES", "no .pdf files among the targets")
    exe = os.environ.get("RENDERFACT_VERAPDF_BIN")
    if not exe:
        for name in ("verapdf", "verapdf.bat"):
            exe = which(name)
            if exe:
                break
    if not exe:
        return StageResult("verapdf", "TOOL_MISSING",
                           "verapdf not installed (verapdf.org, needs a JRE); a requested gate "
                           "that cannot run is a FAILED gate, not a skipped one")
    cmd = [exe, "--format", "text"]
    if flavour:
        cmd += ["-f", flavour]
    proc = runner(
        [*cmd, *map(str, files)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )
    output = (proc.stdout or "").strip()
    # verified against the real 1.30.2 CLI: 0 = all compliant, 1 = non-compliant
    if proc.returncode == 0:
        mode = f"flavour {flavour}" if flavour else "declared-standard auto-detect"
        return StageResult("verapdf", "PASS", f"{len(files)} PDF(s) compliant ({mode})")
    if proc.returncode == 1:
        return StageResult("verapdf", "FAIL", output or "non-compliant PDF(s)")
    return StageResult("verapdf", "TOOL_MISSING",
                       f"verapdf invocation unusable (exit {proc.returncode}): "
                       f"{(proc.stderr or output).strip()[:300]}")


def run_uids(targets: list[str], **_ignored) -> StageResult:
    """Duplicate renderfact_uid scan across markdown frontmatter and YAML/JSON
    graph sources. No tool dependency: this stage can never be TOOL_MISSING."""
    import re

    import yaml as yaml_mod

    files = _resolve_files(targets, (".md", ".yaml", ".yml", ".json"))
    if not files:
        return StageResult("uids", "NO_FILES", "no source files among the targets")
    owners: dict[str, list[str]] = {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        uid = None
        if f.suffix.lower() == ".md":
            m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
            if m:
                try:
                    uid = (yaml_mod.safe_load(m.group(1)) or {}).get("renderfact_uid")
                except yaml_mod.YAMLError:
                    uid = None
        else:
            try:
                data = yaml_mod.safe_load(text)
                if isinstance(data, dict):
                    uid = data.get("renderfact_uid")
            except yaml_mod.YAMLError:
                uid = None
        if uid:
            owners.setdefault(str(uid), []).append(str(f))
    dupes = {u: paths for u, paths in owners.items() if len(paths) > 1}
    if dupes:
        lines = ["  " + u + ":" + "".join("\n    " + p for p in paths)
                 for u, paths in dupes.items()]
        return StageResult("uids", "FAIL",
                           f"{len(dupes)} renderfact_uid value(s) claimed by multiple sources "
                           "(a file copy duplicated identity; strip the uid from the fork):\n"
                           + "\n".join(lines))
    return StageResult("uids", "PASS",
                       f"{sum(len(p) for p in owners.values())} uid-carrying source(s), all unique")


def run_plain_language(targets: list[str], min_words: int = 5, min_count: int = 3,
                       fail_on_hits: bool = False) -> StageResult:
    """Repeated-phrase-across-sections scan (issue #76). See
    docstyle/plain_language.py's module docstring for why this is a Python
    check and not a Vale rule, and why it is report-only by default (findings
    do not fail the run unless --plainlang-fail-on-hits is passed): unlike
    the other stages here, a hit is often legitimate prose (a repeated
    programme/component name), not a defect."""
    from docstyle import plain_language

    files = _resolve_files(targets, (".md",))
    if not files:
        return StageResult("plainlang", "NO_FILES", "no .md files among the targets")
    findings = plain_language.check_paths(files, min_words=min_words, min_count=min_count)
    if not findings:
        return StageResult("plainlang", "PASS", f"{len(files)} file(s), no repeated phrase found")
    lines = []
    total_hits = 0
    for path, hits in findings.items():
        total_hits += len(hits)
        for hit in hits:
            lines.append(f"  {path}: '{hit.phrase}' x{hit.count}")
    detail = f"{total_hits} repeated phrase(s) across {len(findings)} file(s):\n" + "\n".join(lines)
    if fail_on_hits:
        return StageResult("plainlang", "FAIL", detail)
    return StageResult("plainlang", "PASS",
                       detail + "\n  (report-only: pass --plainlang-fail-on-hits to block on this)")


STAGES = {
    "vale": run_vale,
    "lychee": run_lychee,
    "verapdf": run_verapdf,
    "uids": run_uids,
    "plainlang": run_plain_language,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="render gate",
        description="Deterministic fail-closed QA gate chain (B3). No LLM, no network.",
    )
    ap.add_argument("targets", nargs="+", help="files or directories to gate")
    ap.add_argument("--stages", default="vale,lychee,verapdf,uids,plainlang",
                    help=f"comma-separated stages to run (available: {', '.join(sorted(STAGES))})")
    ap.add_argument("--vale-config", type=Path, default=None,
                    help="Vale config override (default: the generic-core "
                         "gates/vale/vale.ini, or RENDERFACT_VALE_CONFIG)")
    ap.add_argument("--online", action="store_true",
                    help="lychee: also check external URLs (non-deterministic, "
                         "network-dependent; default is offline file-link integrity)")
    ap.add_argument("--pdf-flavour", default=None,
                    help="verapdf: force a validation flavour (e.g. ua1, 2b); "
                         "default validates each PDF against the standard it declares")
    ap.add_argument("--plainlang-min-words", type=int, default=5,
                    help="plainlang: minimum phrase length in words (default: 5)")
    ap.add_argument("--plainlang-min-count", type=int, default=3,
                    help="plainlang: minimum near-verbatim repeat count to flag (default: 3)")
    ap.add_argument("--plainlang-fail-on-hits", action="store_true",
                    help="plainlang: fail the run on a repeated-phrase finding (default: "
                         "report-only, since a hit is often legitimate repeated terminology)")
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
        elif stage == "verapdf":
            results.append(run_verapdf(args.targets, flavour=args.pdf_flavour))
        elif stage == "uids":
            results.append(run_uids(args.targets))
        elif stage == "plainlang":
            results.append(run_plain_language(args.targets, min_words=args.plainlang_min_words,
                                              min_count=args.plainlang_min_count,
                                              fail_on_hits=args.plainlang_fail_on_hits))

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
