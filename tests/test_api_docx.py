"""
Tests for POST /render/docx (the DOCX peer of /render/pdf) and the
docstyle/docx_pipeline.py wrapper over render-doc.sh.

Validation + guard tests run everywhere. The real DOCX renders need pandoc + bash
(and python-docx, a dep), so they are skipped when pandoc/bash are absent, per
the repo's tool-gated integration discipline.
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
from docstyle import docx_pipeline  # noqa: E402

HAVE_PANDOC = shutil.which("pandoc") is not None
HAVE_BASH = docx_pipeline.find_bash() is not None
docx_tools = pytest.mark.skipif(not (HAVE_PANDOC and HAVE_BASH), reason="needs pandoc + bash")

DOCX_CTYPE = api_app.RenderfactApi.DOCX_CTYPE


def call_raw(api, body=None, path="/render/docx", extra=None):
    app = api_app.make_wsgi_app(api)
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    environ = {"REQUEST_METHOD": "POST", "PATH_INFO": path,
               "HTTP_HOST": "127.0.0.1:8385", "REMOTE_ADDR": "127.0.0.1",
               "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    environ.update(extra or {})
    cap = {}

    def start_response(status, headers):
        cap["status"] = status
        cap["headers"] = dict(headers)

    data = b"".join(app(environ, start_response))
    return int(cap["status"].split()[0]), cap["headers"].get("Content-Type", ""), data


def _err(data):
    return json.loads(data).get("error", "")


# ---------------------------------------------------- pipeline unit --

def test_pipeline_missing_source(tmp_path):
    with pytest.raises(docx_pipeline.DocxBackendError, match="source not found"):
        docx_pipeline.render_docx(tmp_path / "nope.md", tmp_path / "out")


# ------------------------------------------------- validation (always) --

def test_requires_exactly_one_source(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    assert call_raw(api, {})[0] == 400
    assert call_raw(api, {"markdown": "x", "source": "y"})[0] == 400


def test_oversize_inline_rejected(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, _, data = call_raw(api, {"markdown": "#\n" + "x" * (api.MAX_INLINE_BYTES + 1)})
    assert code == 413


def test_source_not_found(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    assert call_raw(api, {"source": "nope.md"})[0] == 404


def test_profiles_path_jailed(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, _, data = call_raw(api, {"markdown": "# x", "project": "p", "profiles": "../../etc/p.yaml"})
    assert code == 403 and "escapes" in _err(data)


def test_cross_origin_rejected(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, _, _ = call_raw(api, {"markdown": "# x"}, extra={"HTTP_ORIGIN": "http://evil.example"})
    assert code == 403


def test_route_advertised():
    api = api_app.RenderfactApi(root=REPO_ROOT)
    app = api_app.make_wsgi_app(api)

    def get(path):
        cap = {}
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "HTTP_HOST": "127.0.0.1:8385",
                   "REMOTE_ADDR": "127.0.0.1", "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b"")}
        data = b"".join(app(environ, lambda s, h: cap.setdefault("s", s)))
        return json.loads(data)

    assert "POST /render/docx" in get("/")["endpoints"]
    assert "/render/docx" in get("/openapi.json")["paths"]


# ------------------------------------------------- render (tool-gated) --

@docx_tools
def test_render_inline_docx(tmp_path):
    api = api_app.RenderfactApi(root=tmp_path)
    code, ctype, data = call_raw(api, {"markdown": "# Report\n\nBody **text**.\n", "name": "t"})
    assert code == 200 and ctype == DOCX_CTYPE and data[:2] == b"PK"


@docx_tools
def test_render_from_source_does_not_mutate_original(tmp_path):
    src = tmp_path / "doc.md"
    original = "# From file\n\nText.\n"
    src.write_text(original, encoding="utf-8")
    api = api_app.RenderfactApi(root=tmp_path)
    code, ctype, data = call_raw(api, {"source": "doc.md", "name": "t"})
    assert code == 200 and data[:2] == b"PK"
    # the pipeline embeds a provenance uid into its input's frontmatter; we render
    # a COPY, so the server's original file must be byte-for-byte unchanged.
    assert src.read_text(encoding="utf-8") == original
