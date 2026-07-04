"""
Tests for contracts/confidence_gate.py (Track G, item G4): the shared D16 gate
primitive extracted once decision-capture and vision-review both existed.

Covers decide() at the threshold boundary, and resolve() across its four paths:
accept -> deterministic (escalate never called); escalate with a channel ->
escalate() runs; escalate with no channel -> deterministic flagged needs_review;
and an invalid outcome -> GateError. Plus: telemetry is written when a log path
is set, and a telemetry failure never breaks resolve().
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from contracts import confidence_gate as cg  # noqa: E402
from contracts import gate_telemetry as gt  # noqa: E402


def _module(score, *, valid=True):
    """A minimal D16 step contract whose gate() returns a fixed Confidence."""
    conf = cg.Confidence(score, {"probe": round(score, 2)})
    return types.SimpleNamespace(
        gate=lambda input_obj, threshold: (cg.decide(score, threshold), conf),
        deterministic_entry=lambda input_obj: {"kind": "deterministic", "ok": valid},
        validate_output=lambda entry: (entry.get("ok", True), [] if entry.get("ok", True) else ["bad"]),
    )


# ------------------------------------------------------------------ decide --

def test_decide_boundary():
    assert cg.decide(0.6, 0.6) == "accept"      # inclusive
    assert cg.decide(0.59, 0.6) == "escalate"
    assert cg.decide(1.0, 0.6) == "accept"


# ----------------------------------------------------------------- resolve --

def test_accept_takes_deterministic_and_never_escalates():
    called = {"escalate": False}

    def escalate():
        called["escalate"] = True
        return {"kind": "llm"}

    entry, meta = cg.resolve("step", _module(0.9), {}, 0.6, escalate=escalate, log=False)
    assert entry["kind"] == "deterministic"
    assert meta == {"decision": "accept", "score": 0.9, "signals": {"probe": 0.9},
                    "needs_review": False, "channel": "deterministic"}
    assert called["escalate"] is False


def test_bare_float_gate_still_works():
    """resolve() tolerates a legacy gate() that returns a bare float (no signals)."""
    mod = types.SimpleNamespace(
        gate=lambda input_obj, threshold: (cg.decide(0.9, threshold), 0.9),
        deterministic_entry=lambda i: {"ok": True},
        validate_output=lambda e: (True, []))
    _, meta = cg.resolve("step", mod, {}, 0.6, log=False)
    assert meta["score"] == 0.9 and meta["signals"] == {}


def test_escalate_with_channel_runs_escalate():
    entry, meta = cg.resolve("step", _module(0.2), {}, 0.6,
                             escalate=lambda: {"kind": "llm", "ok": True}, log=False)
    assert entry["kind"] == "llm"
    assert meta["decision"] == "escalate" and meta["needs_review"] is False
    assert meta["channel"] == "copy-paste"


def test_escalate_without_channel_flags_needs_review():
    entry, meta = cg.resolve("step", _module(0.2), {}, 0.6, escalate=None, log=False)
    assert entry["kind"] == "deterministic"       # nothing lost
    assert meta["needs_review"] is True
    assert meta["channel"] == "needs-review"


def test_custom_escalate_channel_label():
    _, meta = cg.resolve("step", _module(0.1), {}, 0.6, escalate=lambda: {"ok": True},
                         channel_on_escalate="api", log=False)
    assert meta["channel"] == "api"


def test_invalid_outcome_raises_gate_error():
    with pytest.raises(cg.GateError, match="failed validation"):
        cg.resolve("step", _module(0.9, valid=False), {}, 0.6, log=False)


# --------------------------------------------------------------- telemetry --

def test_resolve_logs_to_gate_log(tmp_path, monkeypatch):
    log = tmp_path / "gate.jsonl"
    monkeypatch.setenv(gt.ENV_LOG, str(log))
    cg.resolve("mystep", _module(0.9), {}, 0.6, log=True)
    events = gt.read_events(log)
    assert len(events) == 1
    assert events[0]["step"] == "mystep"
    assert events[0]["decision"] == "accept"
    assert events[0]["channel"] == "deterministic"


def test_on_decision_fires_before_escalate():
    """The on_decision hook must fire the moment the gate decides, BEFORE the
    escalate callback runs -- so a caller can announce the verdict before an
    interactive paste prompt."""
    order = []
    cg.resolve("step", _module(0.2), {}, 0.6,
               escalate=lambda: order.append("escalate") or {"ok": True},
               on_decision=lambda d, s: order.append(f"announce:{d}"), log=False)
    assert order == ["announce:escalate", "escalate"]


def test_signals_reach_the_telemetry_event(tmp_path, monkeypatch):
    """G3 payoff: the named sub-signals are logged so thresholds can be tuned
    per-signal later."""
    log = tmp_path / "gate.jsonl"
    monkeypatch.setenv(gt.ENV_LOG, str(log))
    cg.resolve("step", _module(0.85), {}, 0.6, log=True)
    events = gt.read_events(log)
    assert events[0]["signals"] == {"probe": 0.85}


def test_telemetry_failure_never_breaks_resolve(monkeypatch):
    # a telemetry that raises must be swallowed
    import contracts.gate_telemetry as gtmod

    def boom(*a, **k):
        raise RuntimeError("telemetry down")

    monkeypatch.setattr(gtmod, "log_decision", boom)
    entry, meta = cg.resolve("step", _module(0.9), {}, 0.6, log=True)
    assert meta["decision"] == "accept"  # resolve completed despite telemetry blowing up
