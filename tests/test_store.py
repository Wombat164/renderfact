"""
Tests for api/store.py, the project registry (Track J): read side (chunk 6.1)
and write side, project creation + config mutation (chunk 6.2).

Unit tests drive the ProjectStore / manifest parser directly against temporary
project trees; integration tests drive the store through the HTTP API in-process
via the same environ builder as test_api.py (no socket).

Covers (6.1): manifest parse happy path, fail-closed validation (missing file, non-
mapping, bad/missing version, unknown top-level key rejected, x-skin accepted,
date coercion to a JSON-safe string), depth-limited scan (finds projects at
depth 1 and 2, never descends into a project or a hidden dir), a broken manifest
surfaced as an error row without aborting the scan, the mtime cache (a stale
cache entry is refreshed when the file changes), render-ledger tail (limit,
tolerance of a torn line, missing ledger), git facts (real repo vs non-repo),
slug validation / traversal rejection, and the GET /projects + GET /projects/{name}
routes (list shape, detail shape, ?limit fold, 404 on unknown/invalid name).

Covers (6.2): sanitize_commit_message (control-char stripping, empty/oversized
rejected), create() happy path (manifest + seeded source + profiles.yaml +
.gitignore + git init + initial commit), refuse-existing, invalid slug, seeding
from a real built-in template; update_config() happy path (patch merge, one
commit, hash changes), 409 on stale base_hash, unknown/immutable key rejected,
empty message rejected on a diff-carrying patch, no-diff patch is a git-free
no-op, refusal on a non-git-tree project; and the D15 guard set on the two new
HTTP routes (CSRF required, cross-origin PUT rejected, 409 propagates over HTTP).
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


def _isolated_git_env(monkeypatch):
    """Deterministic git identity + no ambient global/system config, so these
    tests behave the same on a bare CI runner as on a developer machine with
    its own git config (same isolation test_git_facts_real_repo already uses,
    extended with AUTHOR/COMMITTER env vars since create()/update_config()
    commit inside one call -- there is no window to inject local config
    between `git init` and `git commit`)."""
    import os

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "Test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "t@example.com")

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


# ---------- commit-message sanitization (chunk 6.2, D15 free-text rule) ----------

def test_sanitize_strips_control_chars_and_trims():
    assert store.sanitize_commit_message("  hello\x07 world\x1b  ") == "hello world"


def test_sanitize_rejects_empty_after_stripping():
    with pytest.raises(store.CommitMessageError):
        store.sanitize_commit_message("\x00\x01   ")


def test_sanitize_rejects_non_string():
    with pytest.raises(store.CommitMessageError):
        store.sanitize_commit_message(None)


def test_sanitize_rejects_oversized():
    with pytest.raises(store.CommitMessageError):
        store.sanitize_commit_message("x" * (store.MAX_COMMIT_MESSAGE_BYTES + 1))


# ---------- project creation (chunk 6.2) ----------

def test_create_happy_path(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    st = store.ProjectStore(tmp_path)
    detail = st.create("demo-project", title="Demo Project", doc_type="deck",
                       diagram_scaffold="mermaid", formats=["pdf", "docx"])

    project_dir = tmp_path / "demo-project"
    assert project_dir.is_dir()
    assert (project_dir / store.MANIFEST_NAME).is_file()
    assert (project_dir / "profiles.yaml").is_file()
    assert (project_dir / "src.md").is_file()
    assert ".renderfact/" in (project_dir / ".gitignore").read_text(encoding="utf-8")

    assert detail["manifest"]["name"] == "Demo Project"
    assert detail["manifest"]["doc_type"] == "deck"
    assert detail["manifest"]["diagram_scaffold"] == "mermaid"
    assert detail["manifest"]["render"]["formats"] == ["pdf", "docx"]
    assert detail["manifest"]["template"] == {"ref": "none", "mode": "manual"}
    assert "manifest_hash" in detail

    facts = detail["git"]
    assert facts["git"] is True
    assert facts["dirty"] is False  # initial commit left a clean tree
    log = subprocess.run(["git", "-C", str(project_dir), "log", "--format=%s"],
                         capture_output=True, text=True, check=True)
    assert "renderfact: create project demo-project" in log.stdout


def test_create_refuses_existing_project(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    st = store.ProjectStore(tmp_path)
    st.create("demo")
    with pytest.raises(store.ProjectExistsError):
        st.create("demo")


def test_create_rejects_invalid_slug(tmp_path):
    st = store.ProjectStore(tmp_path)
    with pytest.raises(store.ManifestError):
        st.create("Not A Slug")
    with pytest.raises(store.ManifestError):
        st.create("../escape")


def test_create_seeds_from_a_real_builtin_template(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    st = store.ProjectStore(tmp_path)
    detail = st.create("pitch", template="pitch-1pager")
    seeded = (tmp_path / "pitch" / "src.md").read_text(encoding="utf-8")
    real_template = (REPO_ROOT / "templates" / "pitch-1pager.md").read_text(encoding="utf-8")
    assert seeded == real_template
    assert detail["manifest"]["template"]["ref"] == "pitch-1pager"


def test_create_falls_back_to_stub_for_unknown_template(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    st = store.ProjectStore(tmp_path)
    st.create("mystery", template="no-such-template", title="Mystery Doc")
    seeded = (tmp_path / "mystery" / "src.md").read_text(encoding="utf-8")
    assert "Mystery Doc" in seeded
    assert "[Start writing here.]" in seeded


def test_create_root_created_if_missing(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    root = tmp_path / "does" / "not" / "exist"
    st = store.ProjectStore(root)
    st.create("demo")
    assert (root / "demo" / store.MANIFEST_NAME).is_file()


# ---------- config mutation (chunk 6.2) ----------

def test_update_config_happy_path(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    st = store.ProjectStore(tmp_path)
    created = st.create("demo")
    base_hash = created["manifest_hash"]

    result = st.update_config("demo", {"doc_type": "deck"}, base_hash, "switch to deck")
    assert result["changed"] is True
    assert result["manifest_hash"] != base_hash
    assert result["commit"]

    detail = st.get("demo")
    assert detail["manifest"]["doc_type"] == "deck"
    assert detail["manifest_hash"] == result["manifest_hash"]

    log = subprocess.run(["git", "-C", str(tmp_path / "demo"), "log", "--format=%s"],
                         capture_output=True, text=True, check=True)
    assert "switch to deck" in log.stdout


def test_update_config_nested_merge_preserves_siblings(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    st = store.ProjectStore(tmp_path)
    created = st.create("demo", template="acme-report")
    result = st.update_config(
        "demo", {"template": {"mode": "auto"}}, created["manifest_hash"], "flip to auto")
    detail = st.get("demo")
    assert detail["manifest"]["template"] == {"ref": "acme-report", "mode": "auto"}
    assert result["changed"] is True


def test_update_config_stale_hash_is_conflict(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    st = store.ProjectStore(tmp_path)
    created = st.create("demo")
    st.update_config("demo", {"doc_type": "deck"}, created["manifest_hash"], "first change")
    with pytest.raises(store.StaleManifestError):
        # base_hash is now stale: a second change was already committed
        st.update_config("demo", {"doc_type": "poster"}, created["manifest_hash"], "second change")


def test_update_config_rejects_immutable_key(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    st = store.ProjectStore(tmp_path)
    created = st.create("demo")
    with pytest.raises(store.ManifestError):
        st.update_config("demo", {"source": "elsewhere.md"}, created["manifest_hash"], "nope")


def test_update_config_empty_message_rejected_on_real_diff(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    st = store.ProjectStore(tmp_path)
    created = st.create("demo")
    with pytest.raises(store.CommitMessageError):
        st.update_config("demo", {"doc_type": "deck"}, created["manifest_hash"], "   ")


def test_update_config_no_diff_is_noop_no_commit(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    st = store.ProjectStore(tmp_path)
    created = st.create("demo", doc_type="report")
    before = subprocess.run(["git", "-C", str(tmp_path / "demo"), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout
    # patch says the same value the manifest already has, and an empty message
    # would normally be rejected -- but a no-diff save never reaches that check
    result = st.update_config("demo", {"doc_type": "report"}, created["manifest_hash"], "")
    assert result == {"changed": False, "manifest_hash": created["manifest_hash"]}
    after = subprocess.run(["git", "-C", str(tmp_path / "demo"), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout
    assert before == after  # no new commit


def test_update_config_refuses_non_git_project(tmp_path):
    # a project scaffolded by hand (not via create()) has no git work tree
    d = _project(tmp_path, "handmade")
    st = store.ProjectStore(tmp_path)
    with pytest.raises(store.ManifestError):
        st.update_config("handmade", {"doc_type": "deck"},
                         store.manifest_hash_of(d), "message")


# ---------- HTTP API integration: create + config mutation (chunk 6.2) ----------

def _call_with_headers(api, method, path, body=None, extra=None):
    app = api_app.make_wsgi_app(api)
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    environ = {
        "REQUEST_METHOD": method, "PATH_INFO": path, "HTTP_HOST": "127.0.0.1:8385",
        "REMOTE_ADDR": "127.0.0.1", "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
    }
    for k, v in (extra or {}).items():
        environ[k] = v
    captured = {}

    def start_response(status, headers):
        captured["status"] = status

    payload = b"".join(app(environ, start_response)).decode("utf-8")
    return int(captured["status"].split()[0]), json.loads(payload)


def _get_csrf_token(api):
    _, data = _call_with_headers(api, "GET", "/session")
    return data["csrf_token"]


def test_api_post_projects_requires_csrf(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    code, data = _call_with_headers(api, "POST", "/projects", {"name": "demo"})
    assert code == 403
    assert "CSRF" in data["error"]
    assert not (tmp_path / "demo").exists()


def test_api_post_projects_with_csrf_creates(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    token = _get_csrf_token(api)
    code, data = _call_with_headers(
        api, "POST", "/projects", {"name": "demo", "doc_type": "report"},
        extra={"HTTP_X_CSRF_TOKEN": token})
    assert code == 200
    assert data["manifest"]["name"] == "demo"
    assert (tmp_path / "demo" / store.MANIFEST_NAME).is_file()


def test_api_post_projects_duplicate_is_409(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    token = _get_csrf_token(api)
    _call_with_headers(api, "POST", "/projects", {"name": "demo"},
                       extra={"HTTP_X_CSRF_TOKEN": token})
    code, _ = _call_with_headers(api, "POST", "/projects", {"name": "demo"},
                                 extra={"HTTP_X_CSRF_TOKEN": token})
    assert code == 409


def test_api_post_projects_cross_origin_rejected_even_with_csrf(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    token = _get_csrf_token(api)
    code, _ = _call_with_headers(
        api, "POST", "/projects", {"name": "demo"},
        extra={"HTTP_X_CSRF_TOKEN": token, "HTTP_ORIGIN": "https://evil.example"})
    assert code == 403


def test_api_put_config_requires_csrf(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    token = _get_csrf_token(api)
    _call_with_headers(api, "POST", "/projects", {"name": "demo"},
                       extra={"HTTP_X_CSRF_TOKEN": token})
    _, detail = _call_with_headers(api, "GET", "/projects/demo")
    code, data = _call_with_headers(
        api, "PUT", "/projects/demo/config",
        {"patch": {"doc_type": "deck"}, "base_hash": detail["manifest_hash"], "message": "x"})
    assert code == 403
    assert "CSRF" in data["error"]


def test_api_put_config_cross_origin_rejected(tmp_path, monkeypatch):
    """Extends the D15 guard set (test_api.py's cross-origin coverage was
    POST-only) to PUT, the verb chunk 6.2 introduces."""
    _isolated_git_env(monkeypatch)
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    token = _get_csrf_token(api)
    _call_with_headers(api, "POST", "/projects", {"name": "demo"},
                       extra={"HTTP_X_CSRF_TOKEN": token})
    _, detail = _call_with_headers(api, "GET", "/projects/demo")
    code, _ = _call_with_headers(
        api, "PUT", "/projects/demo/config",
        {"patch": {"doc_type": "deck"}, "base_hash": detail["manifest_hash"], "message": "x"},
        extra={"HTTP_X_CSRF_TOKEN": token, "HTTP_ORIGIN": "https://evil.example"})
    assert code == 403


def test_api_put_config_happy_path_and_stale_conflict(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    token = _get_csrf_token(api)
    _call_with_headers(api, "POST", "/projects", {"name": "demo"},
                       extra={"HTTP_X_CSRF_TOKEN": token})
    _, detail = _call_with_headers(api, "GET", "/projects/demo")
    base_hash = detail["manifest_hash"]

    code, result = _call_with_headers(
        api, "PUT", "/projects/demo/config",
        {"patch": {"doc_type": "deck"}, "base_hash": base_hash, "message": "to deck"},
        extra={"HTTP_X_CSRF_TOKEN": token})
    assert code == 200
    assert result["changed"] is True

    # the stale base_hash from before the change now 409s
    code, _ = _call_with_headers(
        api, "PUT", "/projects/demo/config",
        {"patch": {"doc_type": "poster"}, "base_hash": base_hash, "message": "to poster"},
        extra={"HTTP_X_CSRF_TOKEN": token})
    assert code == 409


# ---------- profile discovery (chunk 6.4) ----------

def test_api_project_profiles_names_and_ranks(tmp_path, monkeypatch):
    """A freshly created project's seeded profiles.yaml (copied from
    projection/profiles-example.yaml by store.create()) is real, valid
    config -- no extra fixture needed."""
    _isolated_git_env(monkeypatch)
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    token = _get_csrf_token(api)
    _call_with_headers(api, "POST", "/projects", {"name": "demo"},
                       extra={"HTTP_X_CSRF_TOKEN": token})

    code, data = _call_with_headers(api, "GET", "/projects/demo/profiles")
    assert code == 200
    assert data["ladders"]["clearance"] == ["public", "internal", "confidential", "secret"]
    names = {p["name"] for p in data["profiles"]}
    assert {"internal-full", "partner-brief", "public-release"} <= names
    public = next(p for p in data["profiles"] if p["name"] == "public-release")
    assert public["clearance_rank"] == 0  # lowest ceiling in the ladder
    internal = next(p for p in data["profiles"] if p["name"] == "internal-full")
    assert internal["clearance_rank"] == 3  # highest (secret)
    # only names + minimal metadata, not the raw ladder-keyed governance dict
    assert "disclosure" in public and "audience" in public


def test_api_project_profiles_404_unknown_project(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    code, _ = _call_with_headers(api, "GET", "/projects/nope/profiles")
    assert code == 404


def test_api_project_profiles_400_when_manifest_field_missing(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    token = _get_csrf_token(api)
    _call_with_headers(api, "POST", "/projects", {"name": "demo"},
                       extra={"HTTP_X_CSRF_TOKEN": token})
    # config-PUT cannot remove 'profiles' (it is not in MUTABLE_MANIFEST_KEYS);
    # simulate the missing-field case directly on the manifest on disk
    manifest_path = tmp_path / "demo" / store.MANIFEST_NAME
    text = manifest_path.read_text(encoding="utf-8").replace("profiles: profiles.yaml\n", "")
    manifest_path.write_text(text, encoding="utf-8")
    code, data = _call_with_headers(api, "GET", "/projects/demo/profiles")
    assert code == 400
    assert "profiles" in data["error"]


def test_api_standalone_profiles_by_path(tmp_path):
    example = REPO_ROOT / "projection" / "profiles-example.yaml"
    rel = example.relative_to(REPO_ROOT)
    api = api_app.RenderfactApi(root=REPO_ROOT, projects_root=tmp_path)
    code, data = _call_with_headers(api, "GET", f"/profiles?path={rel.as_posix()}")
    assert code == 200
    assert any(p["name"] == "public-release" for p in data["profiles"])


def test_api_standalone_profiles_missing_path_param(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    code, data = _call_with_headers(api, "GET", "/profiles")
    assert code == 400


def test_api_standalone_profiles_path_jail(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    code, data = _call_with_headers(api, "GET", "/profiles?path=../outside.yaml")
    assert code == 403
    assert "escapes" in data["error"]


def test_api_project_profiles_400_on_broken_config(tmp_path, monkeypatch):
    _isolated_git_env(monkeypatch)
    api = api_app.RenderfactApi(root=tmp_path, projects_root=tmp_path)
    token = _get_csrf_token(api)
    _call_with_headers(api, "POST", "/projects", {"name": "demo"},
                       extra={"HTTP_X_CSRF_TOKEN": token})
    (tmp_path / "demo" / "profiles.yaml").write_text("not: {a: valid, profiles: config}\n",
                                                      encoding="utf-8")
    code, _ = _call_with_headers(api, "GET", "/projects/demo/profiles")
    assert code == 400
