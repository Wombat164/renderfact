"""
Tests for pdf/locale_fmt.py (issue #35): project-locale number/date/hyphenation
formatting, plus its composition with the #34 statement formatter and the render
backend.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pdf"))

import locale_fmt as lf  # noqa: E402
import statement_data as sd  # noqa: E402


# ------------------------------------------------------------- resolve --

def test_resolve_known():
    assert lf.resolve("nl-BE")["lang"] == "nl"


def test_resolve_none_is_none():
    assert lf.resolve(None) is None and lf.resolve("") is None


def test_resolve_unknown_raises():
    with pytest.raises(lf.LocaleError, match="unknown locale"):
        lf.resolve("xx-YY")


def test_number_format_and_lang():
    nl = lf.resolve("nl-BE")
    assert lf.number_format(nl) == {"thousands": ".", "decimal": ",", "currency_before": True}
    assert lf.number_format(None) == {}
    assert lf.lang(nl) == "nl" and lf.lang(None) == "en"


# --------------------------------------------------------------- dates --

@pytest.mark.parametrize("loc,expected", [
    ("nl-BE", "15 februari 2025"),
    ("fr-BE", "15 février 2025"),
    ("en", "15 February 2025"),
])
def test_format_date_iso(loc, expected):
    assert lf.format_date("2025-02-15", lf.resolve(loc)) == expected


def test_format_date_passthrough_non_iso():
    assert lf.format_date("15 februari 2025", lf.resolve("nl-BE")) == "15 februari 2025"


def test_format_date_passthrough_invalid():
    assert lf.format_date("2025-13-40", lf.resolve("nl-BE")) == "2025-13-40"


def test_format_date_no_locale_passthrough():
    assert lf.format_date("2025-02-15", None) == "2025-02-15"
    assert lf.format_date(None, lf.resolve("nl-BE")) is None


# ------------------------------------------ compose with statement (#34) --

def test_locale_drives_separators_without_format_block():
    # spec omits `format`; locale supplies separators
    rows = sd.compute_rows(
        {"rows": [{"kind": "item", "label": "A", "amount": 8045.77}]},
        default_format=lf.number_format(lf.resolve("nl-BE")))
    assert rows[0]["amount"] == "8.045,77"


def test_spec_format_overrides_locale():
    # spec states currency; locale states separators -> compose
    rows = sd.compute_rows(
        {"format": {"currency": "EUR"}, "rows": [{"kind": "item", "label": "A", "amount": 8045.77}]},
        default_format=lf.number_format(lf.resolve("nl-BE")))
    assert rows[0]["amount"] == "EUR 8.045,77"


def test_currency_after_placement():
    rows = sd.compute_rows(
        {"format": {"currency": "EUR"}, "rows": [{"kind": "item", "label": "A", "amount": 1510.53}]},
        default_format=lf.number_format(lf.resolve("fr-BE")))
    # fr-BE: currency after, nbsp thousands, comma decimal
    assert rows[0]["amount"] == "1 510,53 EUR"


# --------------------------------------------------------------- backend --

def test_render_pdf_unknown_locale_fails_fast(tmp_path):
    # resolves before any tool lookup, so this raises even without typst/pandoc
    import typst_backend as tb

    md = tmp_path / "d.md"
    md.write_text("# Hi\n", encoding="utf-8")
    with pytest.raises(tb.TypstBackendError, match="unknown locale"):
        tb.render_pdf(md, tmp_path / "x.pdf", locale="xx-YY")


def test_compose_main_includes_lang():
    import typst_backend as tb

    main = tb.compose_main("body", title=None, subtitle=None, org=None, date=None,
                           paper="a4", lang="nl")
    assert 'lang: "nl"' in main
