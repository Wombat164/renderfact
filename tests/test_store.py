"""
Tests for api/store.py, the read-side project registry (chunk 6.1 / Track J).

Unit tests drive the ProjectStore / manifest parser directly against temporary
project trees; integration tests drive the store through the HTTP API in-process
via the same environ builder as test_api.py (no socket).

Covers: manifest parse happy path, fail-closed validation (missing file, non-
mapping, bad/missing version, unknown top-level key rejected, x-skin accepted,
date coercion to a JSON-safe string), depth-limited scan (finds projects at
depth 1 and 2, never descends into a project or a hidden dir), a broken manifest
surfaced as an error row without aborting the scan, the mtime cache (a stale
cache entry is refreshed when the file changes), render-ledger tail (limit,
tolerance of a torn line, missing ledger), git facts (real repo vs non-repo),
slug validation / traversal rejection, and the GET /projects + GET /projects/{name}
routes (list shape, detail shape, ?limit fold, 404 on unknown/invalid name).
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from api import app as api_app  # noqa: E402
from api import store  # noqa: E402

VALID = """\
renderfact: 1
name: Demo Project
created: 2026-07-07
source: src/briefing.md
profiles: profiles.yaml
default_profile: partner-contextual
template:
  ref: acme-report
  mode: manual
doc_type: report
diagram_scaffold: mermaid
render:
  formats: [pdf, docx]
  locale: nl-BE
x-skin:
  brand: acme
"""


def _project(root: Path, name: str, manifest: str = VALID) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / store.MANIFEST_NAME).write_text(manifest, encoding="utf-8")
    return d


# ---------- manifest parsing / validation ----------

def test_load_manifest_happy(tmp_path):
    d = _project(tmp_path, "demo")
    data = store.load_manifest(d)
    assert data["renderfact"] == 1
    assert data["template"]["ref"] == "acme-report"
    # date is coerced to a JSON-safe ISO string, not a datetime.date
    assert data["created"] == "2026-07-07"
    json.dumps(data)  # must not raise


def test_missing_manifest(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(store.ManifestError):
        store.load_manifest(tmp_path / "empty")


def test_non_mapping_manifest(tmp_path):
    d = _project(tmp_path, "bad", manifest="- just\n- a\n- list\n")
    with pytest.raises(store.ManifestError):
        store.load_manifest(d)


def test_bad_version(tmp_path):
    d = _project(tmp_path, "bad", manifest="renderfact: 2\nname: x\n")
    with pytest.raises(store.ManifestError):
        store.load_manifest(d)


def test_missing_version(tmp_path):
    d = _project(tmp_path, "bad", manifest="name: x\ndoc_type: report\n")
    with pytest.raises(store.ManifestError):
        store.load_manifest(d)


def test_unknown_top_level_key_rejected(tmp_path):
    d = _project(tmp_path, "bad", manifest="renderfact: 1\nname: x\nbogus: 1\n")
    with pytest.raises(store.ManifestError) as ei:
        store.load_manifest(d)
    assert "bogus" in str(ei.value)


def test_x_skin_extension_accepted(tmp_path):
    d = _project(tmp_path, "ok",
                 manifest="renderfact: 1\nname: x\nx-skin:\n  anything: here\n")
    data = store.load_manifest(d)
    assert data["x-skin"] == {"anything": "here"}


# ---------- scan ----------

def test_scan_finds_depth_1_and_2(tmp_path):
    _project(tmp_path, "alpha")
    _project(tmp_path / "group", "beta")   # depth 2
    st = store.ProjectStore(tmp_path)
    names = {r["name"] for r in st.scan()}
    assert names == {"alpha", "beta"}


def test_scan_does_not_descend_into_project_or_hidden(tmp_path):
    outer = _project(tmp_path, "outer")
    # a manifest nested inside a project dir must NOT be reported separately
    _project(outer, "inner")
    # a hidden dir must be skipped
    _project(tmp_path / ".hidden", "ghost")
    st = store.ProjectStore(tmp_path)
    names = {r["name"] for r in st.scan()}
    assert names == {"outer"}


def test_scan_summary_fields_and_last_render(tmp_path):
    d = _project(tmp_path, "demo")
    ledger = d / store.LEDGER_REL
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps({"ts": "2026-07-07T10:00:00Z", "format": "pdf"}) + "\n"
        + json.dumps({"ts": "2026-07-07T12:00:00Z", "format": "docx"}) + "\n",
        encoding="utf-8")
    row = store.ProjectStore(tmp_path).scan()[0]
    assert row["doc_type"] == "report"
    assert row["template"] == "acme-report"
    assert row["default_profile"] == "partner-contextual"
    assert row["last_render"]["format"] == "docx"  # newest entry


def test_scan_surfaces_broken_manifest_without_aborting(tmp_path):
    _project(tmp_path, "good")
    _project(tmp_path, "broken", manifest="renderfact: 1\nname: x\nbogus: 1\n")
    rows = {r["name"]: r for r in store.ProjectStore(tmp_path).scan()}
    assert "error" in rows["broken"]
    assert "error" not in rows["good"]


def test_mtime_cache_refreshes_on_change(tmp_path):
    d = _project(tmp_path, "demo")
    st = store.ProjectStore(tmp_path)
    assert st.scan()[0]["doc_type"] == "report"
    # rewrite with a newer mtime and a different doc_type
    (d / store.MANIFEST_NAME).write_text(
        "renderfact: 1\nname: x\ndoc_type: deck\n", encoding="utf-8")
    import os
    st_now = (d / store.MANIFEST_NAME).stat()
    os.utime(d / store.MANIFEST_NAME, ns=(st_now.st_atime_ns, st_now.st_mtime_ns + 1_000_000))
    assert st.scan()[0]["doc_type"] == "deck"


# ---------- ledger ----------

def test_read_ledger_tail_and_torn_line(tmp_path):
    d = _project(tmp_path, "demo")
    ledger = d / store.LEDGER_REL
    ledger.parent.mkdir(parents=True)
    lines = [json.dumps({"ts": f"t{i}", "n": i}) for i in range(5)]
    lines.insert(3, "{ this is a torn line")  # must be skipped
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tail = store.read_ledger(d, limit=2)
    assert [e["n"] for e in tail] == [3, 4]
    assert len(store.read_ledger(d, limit=None)) == 5  # torn line dropped


def test_read_ledger_missing(tmp_path):
    d = _project(tmp_path, "demo")
    assert store.read_ledger(d) == []


# ---------- git facts ----------

@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_facts_real_repo(tmp_path):
    d = _project(tmp_path, "demo")
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    run = lambda *a: subprocess.run(["git", "-C", str(d), *a], check=True,
                                    capture_output=True)
    subprocess.run(["git", "-C", str(d), "init", "-q"], check=True, capture_output=True)
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "Test")
    run("add", "-A")
    run("commit", "-q", "-m", "init")
    facts = store.git_facts(d)
    assert facts["git"] is True
    assert facts["head"] and len(facts["head"]) >= 4
    assert facts["dirty"] is False
    (d / "new.txt").write_text("x", encoding="utf-8")
    assert store.git_facts(d)["dirty"] is True


def test_git_facts_non_repo(tmp_path):
    d = _project(tmp_path, "demo")
    assert store.git_facts(d) == {"git": False}


# ---------- slug / traversal ----------

def test_valid_slug():
    assert store.valid_slug("my-project-1")
    assert not store.valid_slug("../etc")
    assert not store.valid_slug("Has Space")
    assert not store.valid_slug("")


def test_get_rejects_traversal_and_unknown(tmp_path):
    _project(tmp_path, "demo")
    st = store.ProjectStore(tmp_path)
    with pytest.raises(store.ManifestError):
        st.get("../secret")
    with pytest.raises(store.ManifestError):
        st.get("nope")
    detail = st.get("demo")
    assert detail["manifest"]["renderfact"] == 1
    assert detail["history"] == []
    assert "git" in detail


# ---------- HTTP API integration ----------

def _call(api, method, path, host="127.0.0.1:8385"):
    app = api_app.make_wsgi_app(api)
    environ = {
        "REQUEST_METHOD": method, "PATH_INFO": path, "HTTP_HOST": host,
        "REMOTE_ADDR": "127.0.0.1", "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    captured = {}

    def start_response(status, headers):
        captured["status"] = status

    payload = b"".join(app(environ, start_response)).decode("utf-8")
    return int(captured["status"].split()[0]), json.loads(payload)


def test_api_projects_list_and_detail(tmp_path):
    _project(tmp_path, "alpha")
    d = _project(tmp_path, "beta")
    ledger = d / store.LEDGER_REL
    ledger.parent.mkdir(parents=True)
    for i in range(30):
        ledger.write_text(
            (ledger.read_text() if ledger.exists() else "")
            + json.dumps({"ts": f"t{i}", "n": i}) + "\n", encoding="utf-8")
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)

    code, data = _call(api, "GET", "/projects")
    assert code == 200
    assert {p["name"] for p in data["projects"]} == {"alpha", "beta"}

    code, detail = _call(api, "GET", "/projects/beta")
    assert code == 200
    assert detail["manifest"]["renderfact"] == 1
    assert len(detail["history"]) == 20  # default limit

    code, detail = _call(api, "GET", "/projects/beta?limit=5")
    assert code == 200 and len(detail["history"]) == 5

    code, _ = _call(api, "GET", "/projects/does-not-exist")
    assert code == 404


def test_api_invalid_project_name_is_404(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    # an uppercase / traversal name does not match the route regex -> 404
    code, _ = _call(api, "GET", "/projects/NotASlug")
    assert code == 404
