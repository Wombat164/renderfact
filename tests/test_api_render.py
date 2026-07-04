"""
Tests for the API render endpoint POST /render/pdf (issue #42): render-as-a-
service over the same typst backend the CLI uses.

Validation + guard tests run everywhere (they 4xx before any render). The actual
render tests (real bytes out) are skipped without typst + pandoc, matching the
repo's tool-gated integration discipline.
"""

from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from api import app as api_app  # noqa: E402

HAVE_TYPST = shutil.which("typst") is not None
HAVE_PANDOC = shutil.which("pandoc") is not None
render_tools = pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")


def call_raw(api, method, path, body=None, extra=None):
    """Binary-aware WSGI call: returns (status_code, content_type, raw_bytes)."""
    app = api_app.make_wsgi_app(api)
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    environ = {
        "REQUEST_METHOD": method, "PATH_INFO": path,
        "HTTP_HOST": "127.0.0.1:8385", "REMOTE_ADDR": "127.0.0.1",
        "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
    }
    environ.update(extra or {})
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    data = b"".join(app(environ, start_response))
    code = int(captured["status"].split()[0])
    return code, captured["headers"].get("Content-Type", ""), data


def _err(data: bytes) -> str:
    return json.loads(data).get("error", "")


# ------------------------------------------------------- validation (always) --

def test_requires_exactly_one_source(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    assert call_raw(api, "POST", "/render/pdf", {})[0] == 400
    code, _, data = call_raw(api, "POST", "/render/pdf", {"markdown": "x", "source": "y"})
    assert code == 400 and "exactly one" in _err(data)


def test_bad_format_rejected(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, _, data = call_raw(api, "POST", "/render/pdf", {"markdown": "x", "format": "gif"})
    assert code == 400 and "pdf" in _err(data)


def test_oversize_inline_rejected(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    big = "#\n" + ("x" * (api.MAX_INLINE_BYTES + 1))
    code, _, data = call_raw(api, "POST", "/render/pdf", {"markdown": big})
    assert code == 413 and "size limit" in _err(data)


def test_source_not_found(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, _, data = call_raw(api, "POST", "/render/pdf", {"source": "nope.md"})
    assert code == 404 and "not found" in _err(data)


def test_brand_path_jail(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, _, data = call_raw(api, "POST", "/render/pdf",
                             {"markdown": "# x", "brand": "../../etc/brand.yaml"})
    assert code == 403 and "escapes" in _err(data)


def test_font_paths_must_be_list(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, _, data = call_raw(api, "POST", "/render/pdf",
                             {"markdown": "# x", "font_paths": "not-a-list"})
    assert code == 400 and "font_paths" in _err(data)


def test_font_path_jailed(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, _, data = call_raw(api, "POST", "/render/pdf",
                             {"markdown": "# x", "font_paths": ["../../etc/fonts"]})
    assert code == 403 and "escapes" in _err(data)


def test_cross_origin_render_rejected(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, _, data = call_raw(api, "POST", "/render/pdf", {"markdown": "# x"},
                             extra={"HTTP_ORIGIN": "http://evil.example"})
    assert code == 403 and "cross-origin" in _err(data)


def test_route_advertised():
    api = api_app.RenderfactApi(root=REPO_ROOT)
    _, _, data = call_raw(api, "GET", "/")
    assert "POST /render/pdf" in json.loads(data)["endpoints"]
    _, _, spec = call_raw(api, "GET", "/openapi.json")
    assert "/render/pdf" in json.loads(spec)["paths"]


# ------------------------------------------------------- render (tool-gated) --

@render_tools
def test_render_inline_pdf(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    md = "# Minutes\n\n::: attendance\n- present | A. Janssens\n:::\n"
    code, ctype, data = call_raw(api, "POST", "/render/pdf",
                                 {"markdown": md, "title": "T", "org": "VME", "locale": "nl-BE"})
    assert code == 200 and ctype == "application/pdf" and data[:5] == b"%PDF-"


@render_tools
def test_render_inline_png_preview(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, ctype, data = call_raw(api, "POST", "/render/pdf",
                                 {"markdown": "# Hi\n\nBody.\n", "format": "png"})
    assert code == 200 and ctype == "image/png" and data[:4] == b"\x89PNG"


def _png_call(api, body):
    """Like call_raw but also returns the X-Total-Pages header."""
    app = api_app.make_wsgi_app(api)
    raw = json.dumps(body).encode("utf-8")
    environ = {"REQUEST_METHOD": "POST", "PATH_INFO": "/render/pdf",
               "HTTP_HOST": "127.0.0.1:8385", "REMOTE_ADDR": "127.0.0.1",
               "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    cap = {}

    def start_response(status, headers):
        cap["status"] = status
        cap["headers"] = dict(headers)

    data = b"".join(app(environ, start_response))
    return int(cap["status"].split()[0]), cap["headers"], data


def test_png_page_out_of_range_rejected(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, _, _ = _png_call(api, {"markdown": "# Hi\n", "format": "png", "page": 0})
    assert code == 400


@render_tools
def test_png_multipage_navigation(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    md = "# One\n\n" + ("filler paragraph\n\n" * 60) + "# Two\n\nsecond page.\n"
    c1, h1, d1 = _png_call(api, {"markdown": md, "format": "png", "page": 1})
    c2, h2, d2 = _png_call(api, {"markdown": md, "format": "png", "page": 2})
    assert c1 == 200 and c2 == 200
    assert h1["X-Total-Pages"] == "2" and h2["X-Total-Pages"] == "2"
    assert d1 != d2 and d1[:4] == b"\x89PNG" and d2[:4] == b"\x89PNG"
    # a page past the end clamps to the last page (still 200)
    c3, _, d3 = _png_call(api, {"markdown": md, "format": "png", "page": 99})
    assert c3 == 200 and d3 == d2


@render_tools
def test_render_from_jailed_source(tmp_path):
    (tmp_path / "doc.md").write_text("# From file\n\nText.\n", encoding="utf-8")
    api = api_app.RenderfactApi(root=tmp_path)
    code, ctype, data = call_raw(api, "POST", "/render/pdf", {"source": "doc.md", "title": "T"})
    assert code == 200 and ctype == "application/pdf" and data[:5] == b"%PDF-"


@render_tools
def test_render_data_statement_reconcile_failure_is_400(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        "rows:\n  - {kind: item, label: A, amount: 10}\n"
        "  - {kind: subtotal, label: T, amount: 999}\n", encoding="utf-8")
    (tmp_path / "doc.md").write_text('::: {.statement data="bad.yaml"}\n:::\n', encoding="utf-8")
    api = api_app.RenderfactApi(root=tmp_path)
    code, _, data = call_raw(api, "POST", "/render/pdf", {"source": "doc.md"})
    assert code == 400 and "reconciliation failed" in _err(data)


@render_tools
def test_inline_statement_data_cannot_escape_to_server_files(tmp_path):
    # a secret under root that inline markdown must NOT be able to read via data=
    (tmp_path / "secret.yaml").write_text("rows:\n  - {kind: item, label: X, amount: 1}\n",
                                          encoding="utf-8")
    api = api_app.RenderfactApi(root=tmp_path)
    md = '::: {.statement data="secret.yaml"}\n:::\n'
    code, _, data = call_raw(api, "POST", "/render/pdf", {"markdown": md})
    # inline sources render in a temp dir, so the server-root file is not found
    assert code == 400 and "not found" in _err(data)
