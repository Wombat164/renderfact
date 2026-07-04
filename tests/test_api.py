"""
Tests for api/app.py, the stdlib HTTP API (chunk 5.1 / E1 + E2/D15 guards).

Most tests drive the WSGI app in-process via a tiny environ builder (no
socket); one test runs a real wsgiref server on an ephemeral port and talks
HTTP through urllib, matching the repo's one-real-transport-test discipline.

Covers: service info, step listing + schema introspection (nested item_schema
included), validate-output happy/invalid paths, projection through the API
against the real demo source (gate held), the D15 guard set (non-loopback Host
rejected, cross-origin POST rejected, same-origin POST allowed, non-browser
POST without Origin allowed, path jail rejection), rate limiting, UI gating
behind --enable-ui, and openapi/docs availability.
"""

from __future__ import annotations

import io
import json
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from api import app as api_app  # noqa: E402


def make_api(**kwargs) -> api_app.RenderfactApi:
    kwargs.setdefault("root", REPO_ROOT)
    return api_app.RenderfactApi(**kwargs)


def call(api, method, path, body=None, host="127.0.0.1:8385", extra=None):
    app = api_app.make_wsgi_app(api)
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "HTTP_HOST": host,
        "REMOTE_ADDR": "127.0.0.1",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
    }
    for k, v in (extra or {}).items():
        environ[k] = v
    status_headers = {}

    def start_response(status, headers):
        status_headers["status"] = status
        status_headers["headers"] = dict(headers)

    chunks = app(environ, start_response)
    payload = b"".join(chunks).decode("utf-8")
    code = int(status_headers["status"].split()[0])
    ctype = status_headers["headers"].get("Content-Type", "")
    data = json.loads(payload) if ctype.startswith("application/json") else payload
    return code, data


def test_info_lists_endpoints():
    code, data = call(make_api(), "GET", "/")
    assert code == 200
    assert data["service"] == "renderfact-api"
    assert "POST /project" in data["endpoints"]
    assert "GET /ui" not in data["endpoints"]  # UI off by default


def test_steps_listing_and_schema_introspection():
    api = make_api()
    code, data = call(api, "GET", "/steps")
    assert code == 200 and "vision-review" in data["steps"]
    code, schema = call(api, "GET", "/steps/vision-review")
    assert code == 200
    out_fields = {f["name"]: f for f in schema["output_schema"]}
    assert "findings" in out_fields
    assert out_fields["findings"]["item_schema"]  # nested shape exposed, not opaque
    code, _ = call(api, "GET", "/steps/nope")
    assert code == 404


def test_validate_output_happy_and_invalid():
    api = make_api()
    good = {"status": "OK", "findings": [], "summary": "Clean.", "reviewer_mode": "copy-paste"}
    code, data = call(api, "POST", "/steps/vision-review/validate-output", body=good)
    assert code == 200 and data["valid"] is True
    code, data = call(api, "POST", "/steps/vision-review/validate-output",
                      body={"status": "NOT-A-STATUS"})
    assert code == 400 and "error" in data


def test_project_through_api_gate_held():
    api = make_api()
    code, data = call(api, "POST", "/project", body={
        "source": "demo/source/signalling-it-refresh.md",
        "profiles": "demo/profiles.yaml",
        "profile": "public-tender",
    })
    assert code == 200, data
    assert data["blocks_dropped"] > 0
    assert "Internal context" not in data["text"]
    code, data = call(api, "POST", "/project", body={
        "source": "demo/source/signalling-it-refresh.md",
        "profiles": "demo/profiles.yaml",
        "profile": "not-a-profile",
    })
    assert code == 400 and "unknown profile" in data["error"]


def test_non_loopback_host_rejected():
    code, data = call(make_api(), "GET", "/", host="evil.example:80")
    assert code == 403 and "Host" in data["error"]


def test_cross_origin_post_rejected_same_origin_allowed():
    api = make_api()
    body = {"source": "x", "profiles": "y", "profile": "z"}
    code, data = call(api, "POST", "/project", body=body,
                      extra={"HTTP_ORIGIN": "http://evil.example"})
    assert code == 403 and "cross-origin" in data["error"]
    code, _ = call(api, "POST", "/project", body=body,
                   extra={"HTTP_ORIGIN": "http://127.0.0.1:8385"})
    assert code != 403  # passes the guard (fails later on missing files, not on origin)
    code, data = call(api, "POST", "/project", body=body,
                      extra={"HTTP_SEC_FETCH_SITE": "cross-site"})
    assert code == 403


def test_non_browser_post_without_origin_passes_guard():
    code, data = call(make_api(), "POST", "/steps/vision-review/validate-output",
                      body={"status": "OK", "findings": [], "summary": "s",
                            "reviewer_mode": "harness"})
    assert code == 200


def test_path_jail_rejects_escape():
    code, data = call(make_api(), "POST", "/project", body={
        "source": "../outside.md", "profiles": "demo/profiles.yaml", "profile": "x"})
    assert code == 403 and "escapes" in data["error"]


def test_rate_limit_returns_429():
    api = make_api(rate_limit=3)
    for _ in range(3):
        code, _ = call(api, "GET", "/")
        assert code == 200
    code, data = call(api, "GET", "/")
    assert code == 429


def test_ui_gated_behind_flag():
    code, _ = call(make_api(), "GET", "/ui")
    assert code == 404
    code, html = call(make_api(enable_ui=True), "GET", "/ui")
    assert code == 200 and "renderfact reference UI" in html


def test_openapi_and_docs_served():
    api = make_api()
    code, spec = call(api, "GET", "/openapi.json")
    assert code == 200 and spec["openapi"].startswith("3.")
    assert "/project" in spec["paths"]
    code, html = call(api, "GET", "/docs")
    assert code == 200 and "renderfact API" in html


def test_real_http_roundtrip_on_ephemeral_port():
    from urllib.request import urlopen
    from wsgiref.simple_server import make_server

    api = make_api()
    httpd = make_server("127.0.0.1", 0, api_app.make_wsgi_app(api))
    port = httpd.server_port
    t = threading.Thread(target=httpd.handle_request, daemon=True)
    t.start()
    try:
        with urlopen(f"http://127.0.0.1:{port}/steps", timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        assert "vision-review" in data["steps"]
    finally:
        t.join(timeout=10)
        httpd.server_close()
