"""
Tests for the API service-surface endpoints: GET /doctor, /locales,
/theme/variants (#44) and POST /statement/check (#43). All are pure-Python
(no typst/pandoc), so they run everywhere.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from api import app as api_app  # noqa: E402


def call(api, method, path, body=None):
    app = api_app.make_wsgi_app(api)
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path,
               "HTTP_HOST": "127.0.0.1:8385", "REMOTE_ADDR": "127.0.0.1",
               "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
    captured = {}

    def start_response(status, headers):
        captured["status"] = status

    data = b"".join(app(environ, start_response)).decode("utf-8")
    return int(captured["status"].split()[0]), json.loads(data)


def api(**kw):
    kw.setdefault("root", REPO_ROOT)
    return api_app.RenderfactApi(**kw)


# ------------------------------------------------------------ discovery --

def test_doctor():
    code, data = call(api(), "GET", "/doctor")
    assert code == 200
    assert isinstance(data["tools"], list)
    assert set(data["backends"]) == {"typst", "pandoc"}
    assert isinstance(data["render_pdf_ready"], bool)


def test_locales():
    code, data = call(api(), "GET", "/locales")
    assert code == 200
    codes = {loc["code"]: loc for loc in data["locales"]}
    assert "nl-BE" in codes and "fr-BE" in codes
    assert codes["nl-BE"]["sample_number"] == "EUR 1.234.567,89"
    assert codes["nl-BE"]["sample_date"] == "15 februari 2025"


def test_theme_variants():
    code, data = call(api(), "GET", "/theme/variants")
    assert code == 200
    assert "base" in data["variants"] and "financial" in data["variants"]


def test_service_routes_advertised():
    _, info = call(api(), "GET", "/")
    for r in ("POST /statement/check", "GET /doctor", "GET /locales", "GET /theme/variants"):
        assert r in info["endpoints"]
    _, spec = call(api(), "GET", "/openapi.json")
    assert "/statement/check" in spec["paths"] and "/doctor" in spec["paths"]


# ------------------------------------------------- statement/check (#43) --

_OK_SPEC = {"format": {"currency": "EUR"}, "rows": [
    {"kind": "item", "label": "Dues", "amount": 8045.77},
    {"kind": "subtotal", "label": "Total", "id": "t"},
    {"kind": "total", "label": "Balance", "formula": "t"}]}


def test_check_spec_ok():
    code, data = call(api(), "POST", "/statement/check", {"spec": _OK_SPEC, "locale": "nl-BE"})
    assert code == 200 and data["reconciled"] is True
    assert data["rows"][-1]["amount"] == "EUR 8.045,77"


def test_check_reconciliation_failure_is_400():
    bad = {"rows": [{"kind": "item", "label": "A", "amount": 10},
                    {"kind": "subtotal", "label": "T", "amount": 999}]}
    code, data = call(api(), "POST", "/statement/check", {"spec": bad})
    assert code == 400 and "reconciliation failed" in data["error"]


def test_check_data_string_yaml():
    yaml_str = "rows:\n  - {kind: item, label: A, amount: 5}\n  - {kind: total, label: T}\n"
    code, data = call(api(), "POST", "/statement/check", {"data": yaml_str, "locale": "nl-BE"})
    assert code == 200 and data["rows"][-1]["amount"] == "5,00"


def test_check_source_path(tmp_path):
    (tmp_path / "s.yaml").write_text(
        "rows:\n  - {kind: item, label: A, amount: 3}\n  - {kind: total, label: T}\n", encoding="utf-8")
    code, data = call(api(root=tmp_path), "POST", "/statement/check", {"source": "s.yaml"})
    assert code == 200 and data["rows"][-1]["amount"] == "3.00"


def test_check_source_not_found(tmp_path):
    code, data = call(api(root=tmp_path), "POST", "/statement/check", {"source": "nope.yaml"})
    assert code == 404


def test_check_requires_exactly_one_input():
    assert call(api(), "POST", "/statement/check", {})[0] == 400
    assert call(api(), "POST", "/statement/check", {"spec": _OK_SPEC, "data": "x"})[0] == 400


def test_check_spec_without_rows_is_400():
    assert call(api(), "POST", "/statement/check", {"spec": {"format": {}}})[0] == 400


def test_check_bad_yaml_is_400():
    code, data = call(api(), "POST", "/statement/check", {"data": "rows: [unclosed"})
    assert code == 400


def test_check_unknown_locale_is_400():
    code, data = call(api(), "POST", "/statement/check", {"spec": _OK_SPEC, "locale": "xx-YY"})
    assert code == 400 and "unknown locale" in data["error"]
