"""
Tests for the Track J workspace screens (chunk 6.5 / D23): Projects Dashboard,
New Project wizard, Template Library, and the GET /ui/static/{name} asset
route. Server-side plumbing only (route gating behind --enable-ui, the
static-asset allowlist/content-type/cache header, and that each HTML shell
correctly references its static files) -- the client-side JS logic itself was
verified by hand with a real headless-browser click-through (dashboard load,
wizard template-card selection, full create-project flow, template-library
listing), matching this repo's existing convention of not unit-testing
embedded/served JS (api/ui.py's UI_HTML has none either).

Uses the same in-process WSGI environ builder as test_api.py/test_store.py.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from api import app as api_app  # noqa: E402


def _call(api, method, path, extra=None):
    app = api_app.make_wsgi_app(api)
    environ = {
        "REQUEST_METHOD": method, "PATH_INFO": path, "HTTP_HOST": "127.0.0.1:8385",
        "REMOTE_ADDR": "127.0.0.1", "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""),
    }
    for k, v in (extra or {}).items():
        environ[k] = v
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app(environ, start_response))
    code = int(captured["status"].split()[0])
    return code, captured["headers"], body


def _api(tmp_path, enable_ui=True):
    return api_app.RenderfactApi(root=tmp_path, enable_ui=enable_ui,
                                 projects_root=tmp_path / "projects",
                                 templates_root=tmp_path / "templates")


# ---------- page gating + shell sanity ----------

def test_dashboard_gated_behind_enable_ui(tmp_path):
    code, _, _ = _call(_api(tmp_path, enable_ui=False), "GET", "/ui/projects")
    assert code == 404


def test_dashboard_served_and_references_its_static_files(tmp_path):
    code, headers, body = _call(_api(tmp_path), "GET", "/ui/projects")
    assert code == 200
    assert headers["Content-Type"].startswith("text/html")
    html = body.decode("utf-8")
    assert "/ui/static/common.js" in html
    assert "/ui/static/dashboard.js" in html
    assert "/ui/static/dashboard.css" in html
    assert "New project" in html


def test_wizard_gated_and_served(tmp_path):
    code, _, _ = _call(_api(tmp_path, enable_ui=False), "GET", "/ui/projects/new")
    assert code == 404
    code, _, body = _call(_api(tmp_path), "GET", "/ui/projects/new")
    assert code == 200
    html = body.decode("utf-8")
    assert "/ui/static/wizard.js" in html
    assert "w-templates" in html  # the manual template-picker mount point
    # manual path only (chunk 6.7 defers auto-choose): no auto-mode controls yet
    assert "auto-choose" not in html.lower()


def test_template_library_gated_and_served(tmp_path):
    code, _, _ = _call(_api(tmp_path, enable_ui=False), "GET", "/ui/templates")
    assert code == 404
    code, _, body = _call(_api(tmp_path), "GET", "/ui/templates")
    assert code == 200
    html = body.decode("utf-8")
    assert "/ui/static/templates-library.js" in html
    assert "Import" in html  # the import form


# ---------- static asset route (D23) ----------

def test_static_asset_gated_behind_enable_ui(tmp_path):
    code, _, _ = _call(_api(tmp_path, enable_ui=False), "GET", "/ui/static/common.js")
    assert code == 404


def test_static_asset_served_with_correct_content_type_and_cache_header(tmp_path):
    code, headers, body = _call(_api(tmp_path), "GET", "/ui/static/common.js")
    assert code == 200
    assert headers["Content-Type"] == "text/javascript; charset=utf-8"
    assert "max-age" in headers.get("Cache-Control", "")
    assert b"jsonFetch" in body

    code, headers, _ = _call(_api(tmp_path), "GET", "/ui/static/dashboard.css")
    assert code == 200
    assert headers["Content-Type"] == "text/css; charset=utf-8"


def test_static_asset_matches_file_on_disk(tmp_path):
    code, _, body = _call(_api(tmp_path), "GET", "/ui/static/dashboard.js")
    assert code == 200
    on_disk = (REPO_ROOT / "api" / "static" / "dashboard.js").read_bytes()
    assert body == on_disk


def test_static_asset_404_for_unlisted_name(tmp_path):
    """Not just missing-on-disk -- a name outside STATIC_ALLOWLIST is refused
    before any filesystem read is attempted (no path-jail arithmetic needed,
    per D23: the allowlist itself makes traversal impossible)."""
    code, _, _ = _call(_api(tmp_path), "GET", "/ui/static/../../../../etc/passwd")
    assert code == 404
    code, _, _ = _call(_api(tmp_path), "GET", "/ui/static/not-a-real-asset.js")
    assert code == 404


def test_static_asset_404_when_missing_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(api_app, "STATIC_ALLOWLIST",
                        api_app.STATIC_ALLOWLIST | {"ghost.js"})
    code, _, data = _call(_api(tmp_path), "GET", "/ui/static/ghost.js")
    assert code == 404
    assert b"missing on disk" in data


# ---------- OpenAPI / info surface stay in sync ----------

def test_info_lists_workspace_routes(tmp_path):
    code, _, body = _call(_api(tmp_path), "GET", "/")
    data = json.loads(body)
    endpoints = data["endpoints"]
    assert "GET /projects" in endpoints
    assert "GET /templates" in endpoints
    assert "GET /profiles" in endpoints
