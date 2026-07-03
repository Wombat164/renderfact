"""
Tests for doctor.py: the native-mode version-drift check (chunk 1.5, A5/D10).

Covers: tools.lock parsing against the REAL committed lock (pins present,
comments stripped); the segment-prefix version-match rule including the
3.1-vs-3.10 false-prefix trap; probe behaviour with injected which/runner
fakes (found, missing, unparseable output); the full check() verdict matrix
(OK / OK unpinned / DRIFT / MISSING / SKIP incl. the BROKEN entry); that
main() ALWAYS exits 0 on the real host regardless of what is installed
(report-only is the D10 contract); and the JSON output mode.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import doctor  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"


# ---- lock parsing ----

def test_parse_real_lock_extracts_pins_and_strips_comments():
    pins = doctor.parse_lock()
    assert pins["pandoc"] == "3.10"
    assert pins["typst"] == "0.15.0"
    assert pins["python-docx"] == "installed"
    assert pins["drawio-desktop"] == "DROPPED"  # resolved by C8: round-trip needs no rendering
    assert all("#" not in v for v in pins.values())


# ---- version matching ----

def test_versions_match_segment_prefix_rule():
    assert doctor.versions_match("3.10", "3.10")
    assert doctor.versions_match("3.10", "3.10.1")
    assert not doctor.versions_match("3.1", "3.10")  # the false-prefix trap
    assert not doctor.versions_match("0.15.0", "0.15.1")
    assert not doctor.versions_match("3.10.1", "3.10")  # pin more specific than found


# ---- probing with fakes ----

def _fake_runner(stdout: str):
    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    return runner


def test_probe_cli_parses_version_from_output():
    found = doctor.probe_cli(
        ("sometool",), ("--version",), r"sometool\s+v?([0-9][0-9.]*)",
        which=lambda name: "/usr/bin/sometool",
        runner=_fake_runner("sometool 1.2.3 (build abc)"),
    )
    assert found == "1.2.3"


def test_probe_cli_returns_none_when_absent():
    assert doctor.probe_cli(
        ("sometool", "sometool.cmd"), ("--version",), r"([0-9.]+)",
        which=lambda name: None,
        runner=_fake_runner("never called"),
    ) is None


def test_probe_cli_returns_none_on_unparseable_output():
    assert doctor.probe_cli(
        ("sometool",), ("--version",), r"sometool\s+([0-9][0-9.]*)",
        which=lambda name: "/usr/bin/sometool",
        runner=_fake_runner("no version here"),
    ) is None


# ---- verdict matrix ----

def test_check_verdict_matrix():
    pins = {
        "base-image": "debian:bookworm-slim",   # SKIP (container scope)
        "drawio-desktop": "BROKEN",             # SKIP (lock says broken)
        "pandoc": "3.10",                       # OK (fake says 3.10.1)
        "typst": "0.15.0",                      # DRIFT (fake says 0.16.0)
        "d2": "0.7.1",                          # MISSING (fake which finds nothing)
        "python-docx": "installed",             # OK unpinned
        "mystery-tool": "9.9",                  # SKIP (no native probe defined)
    }
    versions = {"pandoc": "pandoc 3.10.1", "typst": "typst 0.16.0"}

    def which(name):
        base = name.replace(".cmd", "")
        return f"/usr/bin/{base}" if base in ("pandoc", "typst") else None

    def runner(cmd, **kwargs):
        tool = Path(cmd[0]).name
        return subprocess.CompletedProcess(cmd, 0, stdout=versions.get(tool, ""), stderr="")

    results = {r.tool: r for r in doctor.check(
        pins, which=which, runner=runner, py_probe=lambda dist: "1.2.0",
    )}
    assert results["base-image"].status == "SKIP"
    assert results["drawio-desktop"].status == "SKIP"
    assert "BROKEN" in results["drawio-desktop"].note
    assert results["pandoc"].status == "OK"
    assert results["typst"].status == "DRIFT"
    assert results["typst"].found == "0.16.0"
    assert results["d2"].status == "MISSING"
    assert results["python-docx"].status == "OK unpinned"
    assert results["mystery-tool"].status == "SKIP"


def test_check_python_package_missing(tmp_path):
    results = {r.tool: r for r in doctor.check(
        {"pypdf": "6.14.2"},
        which=lambda name: None,
        runner=None,
        py_probe=lambda dist: None,
    )}
    assert results["pypdf"].status == "MISSING"


# ---- the D10 contract: report-only, exit 0, on the REAL host ----

def test_main_exits_zero_whatever_the_host_has(capsys):
    rc = doctor.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "doctor:" in out
    assert "never fails closed" in out


def test_main_json_mode_is_machine_readable(capsys):
    rc = doctor.main(["--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    tools = {entry["tool"] for entry in payload}
    assert {"pandoc", "typst", "pypdf"} <= tools
    assert all(entry["status"] in ("OK", "OK unpinned", "DRIFT", "MISSING", "SKIP")
               for entry in payload)


def test_render_entrypoint_dispatches_doctor(tmp_path):
    result = subprocess.run(
        [sys.executable, str(RENDER_PY), "doctor"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "doctor:" in result.stdout
