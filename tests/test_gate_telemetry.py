"""
Tests for contracts/gate_telemetry.py (Track G, item G2): the D16 gate decision
log + calibration stats.

Covers: opt-in logging (no-op unless a path is set, and telemetry I/O errors
never raise); the event schema; read_events tolerating blank/corrupt lines; the
stats aggregation (overall + per-step escalation rate, recent-window rate); storm
detection; the healthy-band note; the CLI (empty log, human + JSON report); and
that the render.py gated steps actually log to RENDERFACT_GATE_LOG.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from contracts import gate_telemetry as gt  # noqa: E402

RENDER_PY = REPO_ROOT / "render.py"


# ---------------------------------------------------------- opt-in logging --

def test_logging_is_opt_in_noop(monkeypatch, tmp_path):
    monkeypatch.delenv(gt.ENV_LOG, raising=False)
    # no env, no explicit path -> no-op, returns False, writes nothing
    assert gt.log_decision("s", 0.5, 0.6, "escalate", "copy-paste") is False
    assert list(tmp_path.iterdir()) == []


def test_logging_writes_when_path_set(tmp_path):
    log = tmp_path / "g.jsonl"
    assert gt.log_decision("vision-review", 0.85, 0.6, "accept", "deterministic",
                           verdict="OK", log_path=log) is True
    events = gt.read_events(log)
    assert len(events) == 1
    e = events[0]
    assert e["step"] == "vision-review" and e["decision"] == "accept"
    assert e["score"] == 0.85 and e["channel"] == "deterministic" and e["verdict"] == "OK"
    assert "ts" in e


def test_logging_never_raises_on_bad_path(tmp_path):
    # a path whose parent is a FILE (cannot mkdir) must not raise
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    assert gt.log_decision("s", 0.5, 0.6, "accept", "deterministic",
                           log_path=afile / "sub" / "g.jsonl") is False


def test_read_events_tolerates_corrupt_lines(tmp_path):
    log = tmp_path / "g.jsonl"
    log.write_text('{"step":"a","decision":"accept"}\n\nnot json\n{"step":"b","decision":"escalate"}\n',
                   encoding="utf-8")
    events = gt.read_events(log)
    assert [e["step"] for e in events] == ["a", "b"]


# ------------------------------------------------------------------ stats --

def _events(pairs):
    # pairs: list of (step, decision)
    return [{"step": s, "decision": d, "score": 0.0, "threshold": 0.6} for s, d in pairs]


def test_stats_overall_and_per_step():
    ev = _events([("vision-review", "accept"), ("vision-review", "accept"),
                  ("decision-capture", "escalate"), ("decision-capture", "accept")])
    s = gt.stats(ev)
    assert s["total"] == 4
    assert s["escalation_rate"] == 0.25
    assert s["per_step"]["vision-review"] == {"total": 2, "escalations": 0, "rate": 0.0}
    assert s["per_step"]["decision-capture"] == {"total": 2, "escalations": 1, "rate": 0.5}


def test_storm_detection_flags_recent_spike():
    calm = _events([("s", "accept")] * 40)
    storm = _events([("s", "escalate")] * 20)
    s = gt.stats(calm + storm, window=20)
    assert s["storm_suspected"] is True
    assert s["recent_escalation_rate"] == 1.0
    # a calm recent window is not a storm
    assert gt.stats(calm, window=20)["storm_suspected"] is False


def test_band_note():
    assert gt._band_note(0.10) == "healthy"
    assert "LOW" in gt._band_note(0.01)
    assert "HIGH" in gt._band_note(0.9)


# --------------------------------------------------------------------- CLI --

def _cli(args, env=None):
    return subprocess.run([sys.executable, str(RENDER_PY), "gate-stats", *args],
                          capture_output=True, text=True, encoding="utf-8",
                          cwd=str(REPO_ROOT), env=env)


def test_cli_empty_log_is_graceful(tmp_path, monkeypatch):
    import os
    env = dict(os.environ)
    env.pop(gt.ENV_LOG, None)
    r = _cli(["--log", str(tmp_path / "nope.jsonl")], env=env)
    assert r.returncode == 0
    assert "no gate events" in r.stderr


def test_cli_json_report(tmp_path):
    log = tmp_path / "g.jsonl"
    for s, d in [("vision-review", "accept"), ("decision-capture", "escalate")]:
        gt.log_decision(s, 0.5, 0.6, d, "x", log_path=log)
    r = _cli(["--log", str(log), "--json"])
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["total"] == 2
    assert payload["escalation_rate"] == 0.5


# ------------------------------------------------- render.py integration --

def test_render_steps_log_to_env_path(tmp_path):
    import os
    # drive a decision-capture accept (relabel) with the log enabled
    graph = tmp_path / "g.yaml"
    graph.write_text("title: T\nconcepts:\n  - {id: a, label: A}\n", encoding="utf-8")
    reingest = tmp_path / "r.json"
    reingest.write_text(json.dumps({"verdict": "FAST_FORWARD", "semantic": [
        {"kind": "relabel-node", "id": "a", "old": "A", "new": "B"}]}), encoding="utf-8")
    log = tmp_path / "gate.jsonl"
    env = dict(os.environ, **{gt.ENV_LOG: str(log)})
    r = subprocess.run(
        [sys.executable, str(RENDER_PY), "decision-capture", "--source", str(graph),
         "--reingest", str(reingest), "--decision-log", str(tmp_path / "d.md"), "--json"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT), env=env)
    assert r.returncode == 0, r.stderr
    events = gt.read_events(log)
    assert len(events) == 1
    assert events[0]["step"] == "decision-capture"
    assert events[0]["decision"] == "accept"
    assert events[0]["channel"] == "deterministic"
