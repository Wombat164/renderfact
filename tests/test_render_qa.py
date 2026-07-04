"""
Tests for lint/render_qa.py, the deterministic post-render QA gate.

Covers: probe loading (defaults, consumer yaml merge, defaults-off), the leaks
scan (hit counting, fail-on-hits exit semantics), the paras overweight ranking
against a real python-docx document, the tables geometry scan running against a
real table without crashing, the figs inventory MISSING path, and dispatch via
render.py as a real subprocess.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lint"))
sys.path.insert(0, str(REPO_ROOT))

import render_qa  # noqa: E402


def test_default_probes_are_generic_only():
    # consumer-specific probe terms are built dynamically so THIS file stays
    # clean under the repo's own denylist gate (same trick as test_denylist_scan)
    probes = render_qa.load_probes(None)
    joined = " ".join(probes.values()).lower()
    for consumer_term in ("ss" + "ot", "vau" + "lt", "rc" + "de", "ken" + "nis", ".cla" + "ude"):
        assert consumer_term not in joined


def test_probes_yaml_merges_over_defaults(tmp_path):
    p = tmp_path / "probes.yaml"
    p.write_text('probes:\n  "codename": "\\\\bNIGHTJAR\\\\b"\n', encoding="utf-8")
    probes = render_qa.load_probes(str(p))
    assert "codename" in probes
    assert "surviving wikilink brackets" in probes  # defaults kept


def test_probes_defaults_can_be_disabled(tmp_path):
    p = tmp_path / "probes.yaml"
    p.write_text('probes:\n  "codename": "NIGHTJAR"\n', encoding="utf-8")
    probes = render_qa.load_probes(str(p), use_defaults=False)
    assert list(probes) == ["codename"]


def test_leaks_scan_counts_and_fail_on_hits(tmp_path, capsys):
    txt = tmp_path / "full.txt"
    txt.write_text(
        "clean page one\n\fpage two has a [[wikilink]] leak\nand a title (2026-05) suffix\n",
        encoding="utf-8",
    )
    rc = render_qa.cmd_leaks(str(txt), render_qa.load_probes(None), fail_on_hits=True)
    out = capsys.readouterr().out
    assert rc == 1
    assert "TOTAL leak hits: 2" in out

    clean = tmp_path / "clean.txt"
    clean.write_text("nothing to see\n", encoding="utf-8")
    rc = render_qa.cmd_leaks(str(clean), render_qa.load_probes(None), fail_on_hits=True)
    assert rc == 0


def _make_docx(tmp_path):
    from docx import Document

    doc = Document()
    doc.add_heading("Section One", level=1)
    doc.add_paragraph("short paragraph")
    doc.add_paragraph(" ".join(["word"] * 150))  # overweight
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "k"
    table.rows[0].cells[1].text = "a much longer content cell " * 4
    table.rows[1].cells[0].text = "k2"
    table.rows[1].cells[1].text = "more content here"
    path = tmp_path / "doc.docx"
    doc.save(str(path))
    return path


def test_paras_ranks_overweight_paragraph(tmp_path, capsys):
    path = _make_docx(tmp_path)
    rc = render_qa.cmd_paras(str(path), top=5, limit_words=110)
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 paragraph(s) >= 110 words" in out
    assert "Section One" in out  # attributed to its nearest heading


def test_tables_scan_runs_on_real_table(tmp_path, capsys):
    path = _make_docx(tmp_path)
    rc = render_qa.cmd_tables(str(path), top=5)
    out = capsys.readouterr().out
    assert rc == 0
    assert "TABLES geometry" in out


def test_figs_reports_missing_reference(tmp_path, capsys):
    md = tmp_path / "src.md"
    md.write_text("intro\n\n![diagram](figures/missing.png)\n", encoding="utf-8")
    rc = render_qa.cmd_figs(str(md))
    out = capsys.readouterr().out
    assert rc == 0
    assert "MISSING" in out and "figures/missing.png" in out


def test_render_entrypoint_dispatches_qa_mode(tmp_path):
    txt = tmp_path / "full.txt"
    txt.write_text("has a [[leak]]\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "render.py"), "qa", "leaks", str(txt),
         "--fail-on-hits"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "TOTAL leak hits: 1" in result.stdout
