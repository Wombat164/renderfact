"""docx_pipeline.py -- a thin Python wrapper over container/render-doc.sh so the
DOCX pipeline is callable as a function (the API's POST /render/docx).

render-doc.sh is the proven bash DOCX pipeline (markdown -> pandoc -> styled
DOCX, with the generic in-repo house style by default and every consumer piece
plugged in via env). Its output filename is composed from the doc's version/date/
suffix, so this wrapper runs it with a caller-chosen OUTPUT_DIR and returns the
single DOCX it produced. `resource_path` lets the caller keep relative image
lookups working while rendering a copy of the source (so the API never mutates a
server file with the provenance-uid frontmatter embed).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "container" / "render-doc.sh"


class DocxBackendError(RuntimeError):
    """A precondition failed (missing bash/script/source) or render-doc.sh failed."""


def find_bash() -> "str | None":
    """Reuse render.py's bash resolver (git-bash on Windows, native elsewhere)."""
    sys.path.insert(0, str(REPO_ROOT))
    import render  # render.py

    return render._find_bash()


def render_docx(
    source: "str | Path",
    out_dir: "str | Path",
    *,
    name: "str | None" = None,
    profile: str = "reference",
    suffix: str = "DRAFT",
    project: "str | None" = None,
    profiles: "str | Path | None" = None,
    resource_path: "str | Path | None" = None,
    bash: "str | None" = None,
) -> Path:
    """Render a markdown source to a DOCX via render-doc.sh; returns the produced
    file path. Raises DocxBackendError on any missing tool or failed step."""
    source = Path(source)
    out_dir = Path(out_dir)
    if not source.is_file():
        raise DocxBackendError(f"source not found: {source}")
    if not SCRIPT.is_file():
        raise DocxBackendError(f"render-doc.sh not found: {SCRIPT}")
    bash = bash or find_bash()
    if not bash:
        raise DocxBackendError("bash not found (render-doc.sh needs bash; on Windows install git-bash)")

    out_dir.mkdir(parents=True, exist_ok=True)
    args = [bash, str(SCRIPT), str(source), "--profile", profile]
    if name:
        args += ["--name", name]
    if project:
        args += ["--project", project]
    args += [suffix]

    env = {**os.environ, "OUTPUT_DIR": str(out_dir)}
    if project and profiles:
        env["PROJECTION_CONFIG"] = str(profiles)
    if resource_path is not None:
        env["RESOURCE_PATH"] = str(resource_path)

    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", env=env)
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
        raise DocxBackendError(f"render-doc.sh failed:\n{msg}")

    produced = sorted(out_dir.glob("*.docx"))
    if not produced:
        raise DocxBackendError("render-doc.sh produced no DOCX")
    return produced[-1]
