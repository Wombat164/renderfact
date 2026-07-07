#!/usr/bin/env python3
"""store.py: the renderfact project registry (Track J).

A "project" is a directory under the projects root holding a `renderfact.yaml`
manifest (the git-tracked source of truth), the profiled source(s) it points
at, and a `.renderfact/` operational directory (the render ledger). There is
no central database of record: discovery is a depth-limited scan of the
projects root, and the manifest on disk is authoritative (D9 API-first,
docs-as-code). SQLite is specified only as a future rebuildable read-cache and
is deliberately NOT built in v1 (design spike section 3.3).

Read side (chunk 6.1): parse and validate manifests (fail-closed on unknown
top-level keys), scan with an mtime cache, read the render-ledger tail, report
git facts.

Write side (chunk 6.2): create_project() scaffolds a new project directory
(manifest, seeded source, profiles skeleton, .gitignore, git init if needed,
initial commit); update_project_config() mutates manifest fields with the same
optimistic-concurrency shape as the editor spec (base_hash, 409 on staleness,
one commit per diff-carrying change, required non-empty commit message).
Both are the first write paths in the API and are wired behind the full D15
mutating-endpoint guard set (CSRF token, Origin/Host, path jail) at the route
layer in api/app.py, not here -- this module has no knowledge of HTTP.

CLI (D9: CLI-proven before the UI):
    render projects list [--projects-root DIR] [--json]
    render projects show <name> [--projects-root DIR] [--limit N]
    render projects new <name> [--projects-root DIR] [--template REF]
        [--doc-type TYPE] [--diagram-scaffold none|mermaid|d2]
        [--default-profile NAME] [--formats pdf,docx] [--locale CODE]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

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


class ProjectExistsError(ManifestError):
    """POST /projects named a slug that already has a project directory."""


class StaleManifestError(ManifestError):
    """PUT .../config carried a base_hash that no longer matches the manifest
    on disk (concurrent edit); the caller should re-GET and retry."""


class CommitMessageError(ManifestError):
    """A commit message was empty (after control-character stripping / trim)
    or exceeded the length cap. Schema validation only protects enumerated
    fields (D15); free text gets its own check."""


# Manifest fields a config-mutation PUT may touch. `name`, `created`, `source`,
# and `profiles` are identity/wiring set at creation time and are not exposed
# here; loosening this later is a additive schema change, not a breaking one.
MUTABLE_MANIFEST_KEYS = frozenset({
    "default_profile", "template", "doc_type", "diagram_scaffold", "render",
})

MAX_COMMIT_MESSAGE_BYTES = 4096
# Strip C0/C1 control characters except newline and tab (D15: length caps,
# control-character stripping, before any free text becomes a commit message).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def valid_slug(name: str) -> bool:
    """A project slug is lowercase ASCII + digits + hyphens, no traversal."""
    return isinstance(name, str) and bool(_SLUG_RE.match(name))


def sanitize_commit_message(message: object) -> str:
    """Validate + clean a human-supplied commit message (D15 free-text rule).
    The "human-confirm before commit" half of D15 is structural, not a
    parameter here: the API never invents or defaults this string, so a
    non-empty value in the request IS the confirmation."""
    if not isinstance(message, str):
        raise CommitMessageError("commit message must be a string")
    if len(message.encode("utf-8")) > MAX_COMMIT_MESSAGE_BYTES:
        raise CommitMessageError(
            f"commit message exceeds {MAX_COMMIT_MESSAGE_BYTES} bytes")
    cleaned = _CONTROL_CHARS_RE.sub("", message).strip()
    if not cleaned:
        raise CommitMessageError("commit message must not be empty")
    return cleaned


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


def manifest_hash_of(project_dir: Path) -> str:
    """sha256 of the raw manifest text as it sits on disk: the optimistic-
    concurrency token for PUT .../config, the same idiom the editor spec uses
    for its per-section content hash."""
    raw = (project_dir / MANIFEST_NAME).read_text(encoding="utf-8")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _dump_yaml(data: dict) -> str:
    import yaml  # noqa: PLC0415  (PyYAML: an existing repo dependency)

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _deep_merge(base: dict, patch: dict) -> dict:
    """Recursive dict merge for config patches: a nested mapping merges key
    by key (`{"template": {"mode": "auto"}}` touches only `mode`, leaves
    `ref` alone); any other value type replaces the base value outright."""
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


BUILTIN_TEMPLATES_DIR = REPO_ROOT / "templates"

_DEFAULT_SOURCE_STUB = """---
title: "{title}"
lang: en
---

# {title}

[Start writing here.]
"""


def _seed_source_text(title: str, template: str | None) -> str:
    """Best-effort seed for a new project's source file: a matching built-in
    template pack file (templates/<ref>.md) if one exists, else a minimal
    stub. The full template library (name resolution, consumer-supplied
    packs, auto-choose) is chunk 6.3; this only needs *a* starting file."""
    if template:
        candidate = BUILTIN_TEMPLATES_DIR / f"{template}.md"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return _DEFAULT_SOURCE_STUB.format(title=title)


def _run_git(cwd: Path, *args: str, timeout: int = 10):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, timeout=timeout)


def _ensure_git_repo(project_dir: Path) -> None:
    """git init the project directory unless it already sits inside a work
    tree (design spike 3.6: "git init if not already inside a work tree")."""
    if git_facts(project_dir)["git"]:
        return
    result = _run_git(project_dir, "init", "-q")
    if result.returncode != 0:
        raise ManifestError(f"git init failed: {result.stderr.strip()}")


def _git_commit_all(project_dir: Path, message: str) -> str:
    """Stage everything under project_dir and commit; return the short SHA.
    Raises ManifestError with git's own stderr on failure (e.g. no identity
    configured) rather than papering over it."""
    add = _run_git(project_dir, "add", "-A")
    if add.returncode != 0:
        raise ManifestError(f"git add failed: {add.stderr.strip()}")
    commit = _run_git(project_dir, "commit", "-m", message)
    if commit.returncode != 0:
        raise ManifestError(f"git commit failed: {commit.stderr.strip()}")
    head = _run_git(project_dir, "rev-parse", "--short", "HEAD")
    return head.stdout.strip() if head.returncode == 0 else ""


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
            "manifest_hash": manifest_hash_of(match),
            "history": read_ledger(match, limit),
            "git": git_facts(match),
        }

    def create(self, name: str, *, title: str | None = None,
               template: str | None = None, doc_type: str = "report",
               diagram_scaffold: str = "none", default_profile: str = "internal-full",
               formats: list[str] | None = None, locale: str = "en-US") -> dict:
        """Scaffold a new project: manifest, seeded source, a profiles.yaml
        skeleton, .gitignore, git init if the directory is not already inside
        a work tree, and one initial commit (design spike 3.6 / chunk 6.2)."""
        if not valid_slug(name):
            raise ManifestError(f"invalid project name: {name!r}")
        project_dir = self.root / name
        if project_dir.exists():
            raise ProjectExistsError(f"project already exists: {name!r}")
        self.root.mkdir(parents=True, exist_ok=True)
        project_dir.mkdir(parents=True)

        display_title = title or name
        (project_dir / "src.md").write_text(
            _seed_source_text(display_title, template), encoding="utf-8")

        example_profiles = REPO_ROOT / "projection" / "profiles-example.yaml"
        (project_dir / "profiles.yaml").write_text(
            example_profiles.read_text(encoding="utf-8"), encoding="utf-8")

        manifest = {
            "renderfact": 1,
            "name": display_title,
            "created": datetime.date.today().isoformat(),
            "source": "src.md",
            "profiles": "profiles.yaml",
            "default_profile": default_profile,
            "template": {"ref": template or "none", "mode": "manual"},
            "doc_type": doc_type,
            "diagram_scaffold": diagram_scaffold,
            "render": {"formats": formats or ["pdf"], "locale": locale,
                      "variant": "base", "paper": "a4"},
        }
        (project_dir / MANIFEST_NAME).write_text(_dump_yaml(manifest), encoding="utf-8")
        # the render ledger is derived/operational data, not intent -- untracked
        # by default (design spike 3.4; OQ14 leaves the door open per-consumer)
        (project_dir / ".gitignore").write_text(".renderfact/\n", encoding="utf-8")

        _ensure_git_repo(project_dir)
        _git_commit_all(project_dir, f"renderfact: create project {name}")

        self._cache.pop(project_dir, None)
        return self.get(name)

    def update_config(self, name: str, patch: dict, base_hash: str, message: str) -> dict:
        """Mutate manifest fields with optimistic concurrency: base_hash must
        match the manifest currently on disk (StaleManifestError if not), the
        diff (if any) commits with the caller-supplied message
        (CommitMessageError if empty/oversized after sanitization), and a
        no-diff patch is a no-op that never touches git -- same rule as the
        editor spec's no-diff-save (200, nothing to commit)."""
        if not valid_slug(name):
            raise ManifestError(f"invalid project name: {name!r}")
        match = next((p for p in self._iter_project_dirs() if p.name == name), None)
        if match is None:
            raise ManifestError(f"no such project: {name!r}")
        if not isinstance(patch, dict) or not patch:
            raise ManifestError("patch must be a non-empty object")
        unknown = set(patch) - MUTABLE_MANIFEST_KEYS
        if unknown:
            raise ManifestError(
                f"config PUT may not touch: {', '.join(sorted(unknown))} "
                f"(mutable fields: {', '.join(sorted(MUTABLE_MANIFEST_KEYS))})")
        if not git_facts(match)["git"]:
            raise ManifestError(
                f"{match} is not a git work tree; config mutation requires one (D9/D12)")

        current_hash = manifest_hash_of(match)
        if base_hash != current_hash:
            raise StaleManifestError(
                "manifest changed since base_hash was read; re-GET and retry")

        current = load_manifest(match)
        merged = _deep_merge(current, patch)
        unknown_after = set(merged) - MANIFEST_KEYS - {EXTENSION_KEY}
        if unknown_after:
            raise ManifestError(
                f"merged manifest has unknown key(s): {', '.join(sorted(unknown_after))}")
        if merged == current:
            return {"changed": False, "manifest_hash": current_hash}

        clean_message = sanitize_commit_message(message)
        new_raw = _dump_yaml(merged)
        mpath = match / MANIFEST_NAME
        tmp = mpath.with_suffix(mpath.suffix + ".tmp")
        tmp.write_text(new_raw, encoding="utf-8")
        os.replace(tmp, mpath)
        self._cache.pop(match, None)

        commit_sha = _git_commit_all(match, clean_message)
        return {"changed": True, "manifest_hash": manifest_hash_of(match), "commit": commit_sha}


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
        description="The project registry: list/show (chunk 6.1), new (chunk 6.2). "
                    "Config mutation (PUT .../config) is API/UI-only for now: it "
                    "needs a base_hash from a prior GET, which does not fit a "
                    "one-shot CLI invocation cleanly.")
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

    p_new = sub.add_parser("new", help="scaffold a new project (chunk 6.2)")
    p_new.add_argument("name", help="project slug: lowercase, digits, hyphens")
    p_new.add_argument("--projects-root", default=None,
                       help=f"default: ./{DEFAULT_PROJECTS_SUBDIR}")
    p_new.add_argument("--title", default=None, help="display name (default: the slug)")
    p_new.add_argument("--template", default=None,
                       help="built-in templates/ pack name to seed from (e.g. pitch-1pager)")
    p_new.add_argument("--doc-type", default="report",
                       choices=["report", "deck", "poster", "sheet"])
    p_new.add_argument("--diagram-scaffold", default="none",
                       choices=["none", "mermaid", "d2"])
    p_new.add_argument("--default-profile", default="internal-full")
    p_new.add_argument("--formats", default="pdf",
                       help="comma-separated render formats (default: pdf)")
    p_new.add_argument("--locale", default="en-US")

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

    if args.cmd == "new":
        store = ProjectStore(_resolve_root(args.projects_root))
        try:
            detail = store.create(
                args.name, title=args.title, template=args.template,
                doc_type=args.doc_type, diagram_scaffold=args.diagram_scaffold,
                default_profile=args.default_profile,
                formats=[f.strip() for f in args.formats.split(",") if f.strip()],
                locale=args.locale)
        except ManifestError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(json.dumps(detail, indent=2))
        return 0

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
