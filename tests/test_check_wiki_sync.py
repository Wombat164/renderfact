"""
Tests for scripts/check_wiki_sync.py -- the CI gate that keeps the wiki command
reference in sync with render.py's MODES (the "UX change must update the wiki"
doctrine, made deterministic).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "check_wiki_sync", REPO_ROOT / "scripts" / "check_wiki_sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_repo_is_in_sync_now():
    """The shipped repo must pass its own gate."""
    assert _load().main() == 0


def test_every_command_is_documented_or_exempt():
    mod = _load()
    sys.path.insert(0, str(REPO_ROOT))
    import render

    ref = (REPO_ROOT / "wiki" / "content" / "reference" / "index.md").read_text(encoding="utf-8")
    for cmd in render.MODES:
        if cmd in mod.ALLOW_UNDOCUMENTED:
            continue
        assert f"render {cmd}" in ref, f"'{cmd}' is neither documented nor exempt"


def test_missing_command_would_fail(monkeypatch, tmp_path):
    """A new command absent from the reference must make the gate fail (exit 1)."""
    mod = _load()
    monkeypatch.setattr(mod, "render_commands", lambda: ["docx", "brand-new-undocumented-cmd"])
    assert mod.main() == 1
