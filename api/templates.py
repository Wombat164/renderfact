"""templates.py: the renderfact template library (Track J, chunk 6.3).

A template library ENTRY is a directory `<library-root>/<name>/` holding a
`template.yaml` metadata file (name, doc_type, description, derived_from,
diagram_scaffolds) plus an optional `scaffold.md` seed source, an optional
`template-profile.yaml` (the C7 import-template output: theme, fonts,
geometry, provenance), and an optional `reference.docx`.

Two roots, never conflated. The BUILT-IN library ships inside this repo at
templates/library/ (read-only, a couple of domain-neutral entries: plain
report, plain deck). A CUSTOM library root (operator-supplied, default
<projects-root>/../templates) holds whatever an operator imports via
POST /templates/import. This is a NEW convention, deliberately distinct from
the pre-existing top-level templates/*.md genre pack (cv, cover-letter,
pitch-*, purchase-request, executive-summary, external-party-brief): that
pack is a documented copy-and-instantiate workflow (templates/README.md)
predating Track J and is untouched here; project creation's best-effort seed
(store.py's _seed_source_text) still reads it directly by filename. The
library convention in this module is additive, not a replacement.

GET /templates lists both roots merged (a custom entry shadows a built-in of
the same name: an operator re-importing e.g. "plain-report" is an
intentional override, not a name collision to reject). POST /templates/import
is a thin wrapper over the shipped docstyle/template_import.py C7 pipeline
(style derivation from a branded DOCX, including its --check idempotency
gate), landing the derived profile plus this module's own template.yaml
metadata into the custom root. D15-hardened at the route layer (CSRF +
guards) since it writes into the library -- this module has no HTTP
knowledge, same split as store.py/api/app.py.

CLI (D9: CLI-proven before the UI):
    render templates list [--templates-root DIR] [--json]
    render templates show <name> [--templates-root DIR]
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_LIBRARY_DIR = REPO_ROOT / "templates" / "library"
DEFAULT_CUSTOM_SUBDIR = "templates"
METADATA_NAME = "template.yaml"
SCAFFOLD_NAME = "scaffold.md"
PROFILE_NAME = "template-profile.yaml"

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class TemplateError(ValueError):
    """A template-library operation that failed: bad name, missing entry,
    unreadable metadata, or a DOCX import that could not be scaffolded."""


class TemplateExistsError(TemplateError):
    """POST /templates/import named an entry that already exists in the
    custom library root."""


def valid_template_name(name: str) -> bool:
    return isinstance(name, str) and bool(_NAME_RE.match(name))


def _load_yaml(path: Path):
    import yaml  # noqa: PLC0415  (PyYAML: an existing repo dependency)

    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _dump_yaml(data: dict) -> str:
    import yaml  # noqa: PLC0415

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _read_entry(entry_dir: Path, *, builtin: bool) -> dict:
    meta_path = entry_dir / METADATA_NAME
    if not meta_path.is_file():
        raise TemplateError(f"no {METADATA_NAME} in {entry_dir}")
    meta = _load_yaml(meta_path)
    if not isinstance(meta, dict) or not meta.get("name"):
        raise TemplateError(f"{meta_path}: must be a mapping with a 'name' key")
    return {
        "name": meta["name"],
        "doc_type": meta.get("doc_type"),
        "description": meta.get("description"),
        "derived_from": meta.get("derived_from"),
        "diagram_scaffolds": meta.get("diagram_scaffolds") or [],
        "builtin": builtin,
        "has_scaffold": (entry_dir / SCAFFOLD_NAME).is_file(),
        "has_profile": (entry_dir / PROFILE_NAME).is_file(),
    }


class TemplateLibrary:
    """Read + import side over the two library roots (built-in, custom)."""

    def __init__(self, custom_root: Path):
        self.custom_root = Path(custom_root).resolve()

    def _iter_roots(self):
        """Built-in first, then custom -- scan() relies on this order so a
        later (custom) entry overwrites an earlier (built-in) one of the
        same name in the name-keyed dict it builds."""
        if BUILTIN_LIBRARY_DIR.is_dir():
            yield BUILTIN_LIBRARY_DIR, True
        if self.custom_root.is_dir():
            yield self.custom_root, False

    def scan(self) -> list[dict]:
        rows: dict[str, dict] = {}
        for root, builtin in self._iter_roots():
            for child in sorted(root.iterdir()):
                if not child.is_dir() or not (child / METADATA_NAME).is_file():
                    continue
                try:
                    rows[child.name] = _read_entry(child, builtin=builtin)
                except TemplateError:
                    continue  # a broken entry is skipped, not fatal to the list
        return [rows[name] for name in sorted(rows)]

    def get(self, name: str) -> dict:
        if not valid_template_name(name):
            raise TemplateError(f"invalid template name: {name!r}")
        row = None
        for root, builtin in self._iter_roots():  # custom (later) wins on collision
            entry_dir = root / name
            if (entry_dir / METADATA_NAME).is_file():
                row = _read_entry(entry_dir, builtin=builtin)
                row["_dir"] = entry_dir
        if row is None:
            raise TemplateError(f"no such template: {name!r}")
        entry_dir = row.pop("_dir")
        if row["has_scaffold"]:
            row["scaffold"] = (entry_dir / SCAFFOLD_NAME).read_text(encoding="utf-8")
        if row["has_profile"]:
            row["profile"] = _load_yaml(entry_dir / PROFILE_NAME)
        return row

    def import_docx(self, name: str, docx_path: Path, *, doc_type: str | None = None,
                    description: str | None = None, diagram_scaffolds: list[str] | None = None,
                    copy_reference: bool = False, check_probe: Path | None = None) -> dict:
        """Thin wrapper over docstyle/template_import.py's C7 pipeline: derive
        a template-profile.yaml from a branded DOCX (theme + style extraction,
        honest not-derivable-key comments), land it plus this module's own
        template.yaml metadata in the custom library root. The optional
        --check idempotency gate runs exactly as the CLI's own; a DRIFT there
        does not delete the entry (the derivation itself succeeded; the gate
        is validation on top), it is reported via idempotency_check_passed."""
        if not valid_template_name(name):
            raise TemplateError(f"invalid template name: {name!r}")
        entry_dir = self.custom_root / name
        if entry_dir.exists():
            raise TemplateExistsError(f"template already exists: {name!r}")
        if not docx_path.is_file():
            raise TemplateError(f"template not found: {docx_path}")

        sys.path.insert(0, str(REPO_ROOT))
        from docstyle import template_import  # noqa: PLC0415

        self.custom_root.mkdir(parents=True, exist_ok=True)
        argv = [str(docx_path), "--out-dir", str(entry_dir)]
        if copy_reference:
            argv.append("--copy-reference")
        if check_probe is not None:
            argv += ["--check", str(check_probe)]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = template_import.main(argv)
        output = buf.getvalue().strip()
        if code != 0 and check_probe is None:
            # a non-check failure (bad/missing docx) never got as far as
            # writing a usable profile; nothing worth keeping
            shutil.rmtree(entry_dir, ignore_errors=True)
            raise TemplateError(f"import failed: {output}")

        meta = {
            "name": name,
            "doc_type": doc_type or "report",
            "description": description or f"Imported from {docx_path.name}",
            "derived_from": docx_path.name,
            "diagram_scaffolds": diagram_scaffolds or [],
        }
        (entry_dir / METADATA_NAME).write_text(_dump_yaml(meta), encoding="utf-8")

        result = self.get(name)
        result["import_output"] = output
        result["idempotency_check_passed"] = (code == 0) if check_probe is not None else None
        return result


def _resolve_custom_root(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    return (Path.cwd() / DEFAULT_CUSTOM_SUBDIR).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render templates",
        description="The template library (chunk 6.3): built-in entries (templates/library/) "
                    "merged with a custom root. Import is API-only for now (it wraps "
                    "render import-template; use that CLI directly for a one-off derivation).")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="list built-in + custom library entries")
    p_list.add_argument("--templates-root", default=None,
                        help=f"custom root; default: ./{DEFAULT_CUSTOM_SUBDIR}")
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="one template entry's metadata")
    p_show.add_argument("name")
    p_show.add_argument("--templates-root", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "list":
        lib = TemplateLibrary(_resolve_custom_root(args.templates_root))
        rows = lib.scan()
        if args.json:
            print(json.dumps(rows, indent=2))
        elif not rows:
            print("no template library entries")
        else:
            width = max(len(r["name"]) for r in rows)
            for r in rows:
                tag = "builtin" if r["builtin"] else "custom"
                print(f"{r['name']:<{width}}  {r.get('doc_type') or '-':<8}  {tag:<7}  "
                      f"{r.get('description') or ''}")
        return 0

    if args.cmd == "show":
        lib = TemplateLibrary(_resolve_custom_root(args.templates_root))
        try:
            detail = lib.get(args.name)
        except TemplateError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(json.dumps(detail, indent=2))
        return 0

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
