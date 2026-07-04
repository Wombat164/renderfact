"""
Tests for pdf/statement_data.py (issue #34): data-bound, self-reconciling
statement ledgers.

Covers formatting, the safe formula evaluator, subtotal/total/balance
computation, reconciliation (stated vs computed), YAML + CSV loading, the
markdown expansion that feeds the #33 render path, and (skipif-guarded) a full
render that compiles on reconcile and fails the render on divergence.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "pdf"))

import statement_data as sd  # noqa: E402

HAVE_TYPST = shutil.which("typst") is not None
HAVE_PANDOC = shutil.which("pandoc") is not None

NL = {"currency": "EUR", "thousands": ".", "decimal": ","}


# ---------------------------------------------------------------- format --

@pytest.mark.parametrize("value,fmt,expected", [
    (8045.77, NL, "EUR 8.045,77"),
    (45.7, NL, "EUR 45,70"),
    (1234567.5, NL, "EUR 1.234.567,50"),
    (-100.0, NL, "-EUR 100,00"),
    (1234.56, {}, "1234.56"),
    (1000.0, {"decimal": "."}, "1000.00"),
])
def test_format_amount(value, fmt, expected):
    assert sd.format_amount(value, fmt) == expected


# ------------------------------------------------------------ safe eval --

def test_eval_arithmetic():
    assert sd._safe_eval("a - b", {"a": 10.0, "b": 3.0}) == 7.0
    assert sd._safe_eval("(a + b) * 2", {"a": 1.0, "b": 2.0}) == 6.0


def test_eval_unknown_id_raises():
    with pytest.raises(sd.StatementError, match="unknown subtotal id"):
        sd._safe_eval("a + missing", {"a": 1.0})


def test_eval_rejects_calls():
    with pytest.raises(sd.StatementError):
        sd._safe_eval("__import__('os').system('x')", {})


def test_eval_invalid_syntax():
    with pytest.raises(sd.StatementError, match="invalid formula"):
        sd._safe_eval("a +", {"a": 1.0})


# --------------------------------------------------------- compute rows --

def _spec(rows, fmt=None):
    return {"format": fmt or NL, "rows": rows}


def test_subtotal_sums_section_items():
    rows = sd.compute_rows(_spec([
        {"kind": "item", "label": "A", "amount": 8000.0},
        {"kind": "item", "label": "B", "amount": 45.77},
        {"kind": "subtotal", "label": "Total"},
    ]))
    assert rows[-1] == {"kind": "subtotal", "label": "Total", "amount": "EUR 8.045,77"}


def test_heading_resets_the_group():
    rows = sd.compute_rows(_spec([
        {"kind": "item", "label": "A", "amount": 100.0},
        {"kind": "heading", "label": "New"},
        {"kind": "item", "label": "B", "amount": 5.0},
        {"kind": "subtotal", "label": "Sub"},
    ]))
    assert rows[-1]["amount"] == "EUR 5,00"  # only B, not A


def test_total_formula_over_subtotals():
    rows = sd.compute_rows(_spec([
        {"kind": "item", "label": "A", "amount": 8045.77},
        {"kind": "subtotal", "id": "inc", "label": "Income"},
        {"kind": "item", "label": "B", "amount": 6535.24},
        {"kind": "subtotal", "id": "exp", "label": "Expenses"},
        {"kind": "total", "label": "Balance", "formula": "inc - exp"},
    ]))
    assert rows[-1]["amount"] == "EUR 1.510,53"


def test_total_without_formula_sums_all_items():
    rows = sd.compute_rows(_spec([
        {"kind": "item", "label": "A", "amount": 10.0},
        {"kind": "subtotal", "label": "S1"},
        {"kind": "item", "label": "B", "amount": 5.0},
        {"kind": "total", "label": "Grand"},
    ]))
    assert rows[-1]["amount"] == "EUR 15,00"


def test_reconciliation_passes_when_stated_matches():
    rows = sd.compute_rows(_spec([
        {"kind": "item", "label": "A", "amount": 8000.0},
        {"kind": "item", "label": "B", "amount": 45.77},
        {"kind": "subtotal", "label": "Total", "amount": 8045.77},
    ]))
    assert rows[-1]["amount"] == "EUR 8.045,77"


def test_reconciliation_fails_when_stated_diverges():
    with pytest.raises(sd.StatementError, match="reconciliation failed"):
        sd.compute_rows(_spec([
            {"kind": "item", "label": "A", "amount": 8000.0},
            {"kind": "subtotal", "label": "Total", "amount": 9999.99},
        ]))


def test_non_number_amount_raises():
    with pytest.raises(sd.StatementError, match="not a number"):
        sd.compute_rows(_spec([{"kind": "item", "label": "A", "amount": "lots"}]))


def test_unknown_kind_raises():
    with pytest.raises(sd.StatementError, match="unknown statement row kind"):
        sd.compute_rows(_spec([{"kind": "grand-poobah", "label": "X"}]))


# ------------------------------------------------------------ load_spec --

def test_load_yaml(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("rows:\n  - {kind: item, label: A, amount: 10}\n", encoding="utf-8")
    assert sd.load_spec(p)["rows"][0]["label"] == "A"


def test_load_csv(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("kind,label,amount\nitem,A,10\nsubtotal,Total,\n", encoding="utf-8")
    spec = sd.load_spec(p)
    assert spec["rows"][0] == {"kind": "item", "label": "A", "amount": "10"}
    assert spec["rows"][1] == {"kind": "subtotal", "label": "Total"}  # empty amount dropped


def test_load_missing_raises(tmp_path):
    with pytest.raises(sd.StatementError, match="not found"):
        sd.load_spec(tmp_path / "nope.yaml")


def test_load_unsupported_ext(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(sd.StatementError, match="unsupported"):
        sd.load_spec(p)


def test_load_yaml_without_rows(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("format: {currency: EUR}\n", encoding="utf-8")
    with pytest.raises(sd.StatementError, match="rows"):
        sd.load_spec(p)


# ----------------------------------------------------- to_block_markdown --

def test_to_block_markdown_shape():
    md = sd.to_block_markdown([
        {"kind": "heading", "label": "H"},
        {"kind": "item", "label": "A", "amount": "EUR 10,00"},
        {"kind": "rule"},
        {"kind": "total", "label": "T", "amount": "EUR 10,00"},
    ])
    assert md.splitlines() == [
        "- heading | H",
        "- item | A | EUR 10,00",
        "- rule",
        "- total | T | EUR 10,00",
    ]


# ------------------------------------------------------- expand_markdown --

def _data_file(tmp_path):
    p = tmp_path / "fin.yaml"
    p.write_text(
        "format: {currency: EUR, thousands: '.', decimal: ','}\n"
        "rows:\n"
        "  - {kind: item, label: Dues, amount: 8045.77}\n"
        "  - {kind: subtotal, label: Total}\n",
        encoding="utf-8")
    return p


def test_expand_replaces_data_block(tmp_path):
    _data_file(tmp_path)
    md = '# Fin\n\n::: {.statement data="fin.yaml"}\n:::\n'
    out = sd.expand_markdown(md, tmp_path)
    assert "::: statement" in out
    assert "- item | Dues | EUR 8.045,77" in out
    assert "- subtotal | Total | EUR 8.045,77" in out
    assert "data=" not in out


def test_expand_leaves_plain_statement_untouched(tmp_path):
    md = "::: statement\n- item | Hand typed | EUR 1,00\n:::\n"
    assert sd.expand_markdown(md, tmp_path) == md


def test_expand_leaves_other_divs_untouched(tmp_path):
    md = "::: {.attendance}\n- present | A\n:::\n"
    assert sd.expand_markdown(md, tmp_path) == md


def test_expand_propagates_reconciliation_failure(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        "rows:\n"
        "  - {kind: item, label: A, amount: 10}\n"
        "  - {kind: subtotal, label: T, amount: 999}\n",
        encoding="utf-8")
    with pytest.raises(sd.StatementError, match="reconciliation failed"):
        sd.expand_markdown('::: {.statement data="bad.yaml"}\n:::\n', tmp_path)


# ---------------------------------------------------- render integration --

@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_render_data_bound_statement_compiles(tmp_path):
    import typst_backend as tb

    _data_file(tmp_path)
    md = tmp_path / "fin.md"
    md.write_text('# Fin\n\n::: {.statement data="fin.yaml"}\n:::\n', encoding="utf-8")
    out = tb.render_pdf(md, tmp_path / "fin.pdf", title="Fin")
    assert out.read_bytes()[:5] == b"%PDF-"


@pytest.mark.skipif(not (HAVE_TYPST and HAVE_PANDOC), reason="needs typst + pandoc")
def test_render_fails_on_divergent_total(tmp_path):
    import typst_backend as tb

    p = tmp_path / "bad.yaml"
    p.write_text(
        "rows:\n  - {kind: item, label: A, amount: 10}\n"
        "  - {kind: subtotal, label: T, amount: 999}\n", encoding="utf-8")
    md = tmp_path / "bad.md"
    md.write_text('::: {.statement data="bad.yaml"}\n:::\n', encoding="utf-8")
    with pytest.raises(tb.TypstBackendError, match="reconciliation failed"):
        tb.render_pdf(md, tmp_path / "bad.pdf", title="Bad")
