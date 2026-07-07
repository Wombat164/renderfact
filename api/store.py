#!/usr/bin/env python3
"""store.py: the renderfact project registry, read side (chunk 6.1 / Track J).

A "project" is a directory under the projects root holding a `renderfact.yaml`
manifest (the git-tracked source of truth), the profiled source(s) it points
at, and a `.renderfact/` operational directory (the render ledger). There is
no central database of record: discovery is a depth-limited scan of the
projects root, and the manifest on disk is authoritative (D9 API-first,
docs-as-code). SQLite is specified only as a future rebuildable read-cache and
is deliberately NOT built in v1 (design spike section 3.3).

This module is pure read-side: parse and validate manifests (fail-closed on
unknown top-level keys), scan with an mtime cache, read the render-ledger
tail, and report git facts. Creation and mutation land in chunk 6.2.

CLI (D9: CLI-proven before the UI):
    render projects list [--projects-root DIR] [--json]
    render projects show <name> [--projects-root DIR] [--limit N]
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

MANIFEST_NAME = "renderfact.yaml"
LEDGER_REL = Path(".renderfact") / "renders.jsonl"
SCAN_MAX_DEPTH = 2          # projects live at depth 1 or 2 below the root
DEFAULT_PROJECTS_SUBDIR = "projects"
EXTENSION_KEY = "x-skin"    # the single sanctioned consumer extension namespace

# Allowed top-level manifest keys. Anything else is rejected (fail-closed),
# except the x-skin extension namespace (design spike section 3.5).
MANIFEST_KEYS = frozenset({
    "renderfact", "name", "created", "source", "profiles", "default_profile",
    "template", "doc_type", "diagram_scaffold", "render",
})

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ManifestError(ValueError):
    """A renderfact.yaml that is missing, unparseable, or fails validation."""


def valid_slug(name: str) -> bool:
    """A project slug is lowercase ASCII + digits + hyphens, no traversal."""
    return isinstance(name, str) and bool(_SLUG_RE.match(name))


def _json_safe(obj):
    """Coerce a parsed manifest into JSON-serialisable primitives. PyYAML turns
    an unquoted `created: 2026-07-07` into a datetime.date, which json.dumps
    cannot serialise; normalise dates to ISO strings so the API and CLI never
    trip on them."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return obj


def _load_yaml(path: Path):
    import yaml  # noqa: PLC0415  (PyYAML: an existing repo dependency)

    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_manifest(project_dir: Path) -> dict:
    """Parse and validate project_dir/renderfact.yaml. Fail-closed: the top
    level must be a mapping, must declare a supported `renderfact` version, and
    must carry no unknown top-level keys (only the `x-skin` namespace is a
    sanctioned free-form extension point)."""
    mpath = project_dir / MANIFEST_NAME
    if not mpath.is_file():
        raise ManifestError(f"no {MANIFEST_NAME} in {project_dir}")
    try:
        data = _load_yaml(mpath)
    except Exception as e:  # yaml.YAMLError and any decode error
        raise ManifestError(f"{mpath}: not valid YAML: {e}") from None
    if not isinstance(data, dict):
        raise ManifestError(f"{mpath}: top level must be a mapping")
    if data.get("renderfact") != 1:
        raise ManifestError(
            f"{mpath}: unsupported or missing manifest version "
            f"(expected `renderfact: 1`, got {data.get('renderfact')!r})")
    unknown = set(data) - MANIFEST_KEYS - {EXTENSION_KEY}
    if unknown:
        raise ManifestError(
            f"{mpath}: unknown top-level key(s): {', '.join(sorted(unknown))} "
            f"(consumer extensions belong under `{EXTENSION_KEY}:`)")
    return _json_safe(data)


def read_ledger(project_dir: Path, limit: int | None = 20) -> list[dict]:
    """Return the last `limit` entries of the project's render ledger
    (.renderfact/renders.jsonl), newest last. Tolerant: a torn or malformed
    line is skipped rather than raised, and a missing ledger yields []."""
    lpath = project_dir / LEDGER_REL
    if not lpath.is_file():
        return []
    entries: list[dict] = []
    try:
        with lpath.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    if limit is not None and limit >= 0:
        return entries[-limit:]
    return entries


def _ledger_last(project_dir: Path):
    tail = read_ledger(project_dir, 1)
    return tail[-1] if tail else None


def git_facts(project_dir: Path) -> dict:
    """Report {git, branch, head, dirty} for a project directory. Local
    read-only git plumbing via subprocess (no GitPython dependency). A
    non-git directory or a missing git binary returns {"git": False}."""
    def _git(*args):
        return subprocess.run(
            ["git", "-C", str(project_dir), *args],
            capture_output=True, text=True, timeout=10)

    try:
        inside = _git("rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.SubprocessError):
        return {"git": False}
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return {"git": False}
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or None
    head = _git("rev-parse", "--short", "HEAD")
    head_commit = head.stdout.strip() if head.returncode == 0 else None
    status = _git("status", "--porcelain")
    dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    return {"git": True, "branch": branch, "head": head_commit, "dirty": dirty}


class ProjectStore:
    """Read-side registry over a projects root. Discovery is a bounded scan;
    manifests are cached per (path, mtime) and revalidated only when the file
    changes on disk (design spike section 3.3)."""

    def __init__(self, projects_root: Path):
        self.root = Path(projects_root).resolve()
        self._cache: dict[Path, tuple[int, dict]] = {}

    def _iter_project_dirs(self):
        """Yield directories under root (depth 1..SCAN_MAX_DEPTH) that hold a
        manifest. A project directory is a scan leaf: never descend into one,
        and skip hidden directories."""
        if not self.root.is_dir():
            return
        stack = [(self.root, 0)]
        while stack:
            d, depth = stack.pop()
            if d != self.root and (d / MANIFEST_NAME).is_file():
                yield d
                continue
            if depth >= SCAN_MAX_DEPTH:
                continue
            try:
                for child in sorted(d.iterdir()):
                    if child.is_dir() and not child.name.startswith("."):
                        stack.append((child, depth + 1))
            except OSError:
                continue

    def _load_cached(self, project_dir: Path) -> dict:
        mpath = project_dir / MANIFEST_NAME
        try:
            mtime = mpath.stat().st_mtime_ns
        except OSError as e:
            raise ManifestError(f"{mpath}: {e}") from None
        hit = self._cache.get(project_dir)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        data = load_manifest(project_dir)
        self._cache[project_dir] = (mtime, data)
        return data

    def scan(self) -> list[dict]:
        """Return a summary row per discovered project. A project whose
        manifest fails validation is surfaced with an `error` field rather than
        aborting the whole scan."""
        out: list[dict] = []
        for pdir in sorted(self._iter_project_dirs()):
            row = {"name": pdir.name, "path": str(pdir)}
            try:
                data = self._load_cached(pdir)
            except ManifestError as e:
                row["error"] = str(e)
                out.append(row)
                continue
            tmpl = data.get("template")
            row.update({
                "doc_type": data.get("doc_type"),
                "template": tmpl.get("ref") if isinstance(tmpl, dict) else tmpl,
                "default_profile": data.get("default_profile"),
                "last_render": _ledger_last(pdir),
            })
            out.append(row)
        return out

    def get(self, name: str, limit: int = 20) -> dict:
        """Return one project's parsed manifest, render-ledger tail, and git
        facts. `name` is matched against discovered directory names (never used
        to build a path), so traversal cannot escape the projects root."""
        if not valid_slug(name):
            raise ManifestError(f"invalid project name: {name!r}")
        match = next((p for p in self._iter_project_dirs() if p.name == name), None)
        if match is None:
            raise ManifestError(f"no such project: {name!r}")
        return {
            "name": name,
            "path": str(match),
            "manifest": self._load_cached(match),
            "history": read_ledger(match, limit),
            "git": git_facts(match),
        }


def _resolve_root(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    return (Path.cwd() / DEFAULT_PROJECTS_SUBDIR).resolve()


def _print_list(rows: list[dict], root: Path) -> None:
    if not rows:
        print(f"no projects under {root}")
        return
    width = max(len(r["name"]) for r in rows)
    for r in rows:
        if "error" in r:
            print(f"{r['name']:<{width}}  !! {r['error']}")
            continue
        last = r.get("last_render")
        when = last.get("ts") if isinstance(last, dict) else None
        print(f"{r['name']:<{width}}  {r.get('doc_type') or '-':<8}  "
              f"{r.get('template') or '-':<16}  last: {when or '-'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render projects",
        description="Read-side project registry (chunk 6.1). "
                    "Creation and config mutation land in chunk 6.2.")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="list projects under the projects root")
    p_list.add_argument("--projects-root", default=None,
                        help=f"default: ./{DEFAULT_PROJECTS_SUBDIR}")
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="one project's manifest, history, git facts")
    p_show.add_argument("name")
    p_show.add_argument("--projects-root", default=None)
    p_show.add_argument("--limit", type=int, default=20,
                        help="render-ledger entries to include (default 20)")

    args = parser.parse_args(argv)

    if args.cmd == "list":
        store = ProjectStore(_resolve_root(args.projects_root))
        rows = store.scan()
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            _print_list(rows, store.root)
        return 0

    if args.cmd == "show":
        store = ProjectStore(_resolve_root(args.projects_root))
        try:
            detail = store.get(args.name, limit=max(0, args.limit))
        except ManifestError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(json.dumps(detail, indent=2))
        return 0

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
