"""gate_telemetry.py -- D16 gate decision logging + calibration stats (Track G, item G2).

Every fuzzy-gate decision (decision-capture, vision-review, and future gated
steps) can be logged to an append-only JSONL so that:

  1. thresholds become EVIDENCE-BASED. The prior-art sweep's conformal-prediction
     guidance is "log (score, decision, later-verified-correct?) tuples and pick
     the threshold from that log", not hand-set a magic number. This is that log.
  2. escalation STORMS are caught. A systemic input change (a new diagram theme,
     a format bump) can make every step miss the gate at once -- a cost spike and
     rate-limit amplifier. A recent-window escalation-rate check flags it.
  3. the healthy operating band (~10-15% escalation, from HITL-triage deployments)
     is observable rather than assumed.

OPT-IN by construction: logging is a no-op unless RENDERFACT_GATE_LOG (a file
path) is set, so no gate call ever writes a file by surprise, and a telemetry I/O
error never breaks the gate.

CLI: `render gate-stats [--log PATH] [--window N] [--json]`.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ENV_LOG = "RENDERFACT_GATE_LOG"

# Healthy escalation band (fraction), from the HITL-triage prior art: below this
# the gate rarely fires (maybe too loose / deterministic path over-trusted);
# above it, inputs are genuinely hard or the threshold is too strict.
HEALTHY_BAND = (0.05, 0.30)
_STORM_RATE = 0.6  # recent-window escalation fraction that suggests a storm


def _resolve(explicit: "str | Path | None") -> "Path | None":
    p = explicit if explicit is not None else os.environ.get(ENV_LOG)
    return Path(p) if p else None


def log_decision(step: str, score: float, threshold: float, decision: str, channel: str,
                 *, verdict: "str | None" = None, signals: "dict | None" = None,
                 log_path: "str | Path | None" = None, extra: "dict | None" = None) -> bool:
    """Append one gate decision to the JSONL. No-op (returns False) unless a log
    path is set via arg or RENDERFACT_GATE_LOG. Never raises -- telemetry must not
    break the gate.

    channel: the path actually taken -- 'deterministic' (accepted, zero tokens),
    'copy-paste' / 'harness' / 'api' (escalated to an LLM), or 'needs-review'
    (escalated but no channel available, deterministic result flagged)."""
    path = _resolve(log_path)
    if path is None:
        return False
    event = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "step": step,
        "score": round(float(score), 4),
        "threshold": float(threshold),
        "decision": decision,
        "channel": channel,
    }
    if verdict is not None:
        event["verdict"] = verdict
    if signals:
        # the named sub-signals behind the score (G3) -- for per-signal calibration
        event["signals"] = signals
    if extra:
        event.update(extra)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return True
    except OSError:
        return False


def read_events(log_path: "str | Path | None" = None) -> list[dict]:
    path = _resolve(log_path)
    if path is None or not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a corrupt line must not sink the whole read
    return out


def stats(events: list[dict], *, window: int = 50) -> dict:
    """Aggregate escalation rates overall + per step, plus a recent-window storm
    check. Pure function of the event list, so it is trivially testable."""
    total = len(events)
    escalations = sum(1 for e in events if e.get("decision") == "escalate")
    per_step: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [total, escalations]
    for e in events:
        row = per_step[e.get("step", "?")]
        row[0] += 1
        if e.get("decision") == "escalate":
            row[1] += 1
    recent = events[-window:]
    recent_esc = sum(1 for e in recent if e.get("decision") == "escalate")
    recent_rate = recent_esc / len(recent) if recent else 0.0
    storm = len(recent) >= max(5, window // 2) and recent_rate >= _STORM_RATE
    return {
        "total": total,
        "escalation_rate": round(escalations / total, 4) if total else 0.0,
        "per_step": {k: {"total": v[0], "escalations": v[1],
                         "rate": round(v[1] / v[0], 4) if v[0] else 0.0}
                     for k, v in sorted(per_step.items())},
        "recent_window": len(recent),
        "recent_escalation_rate": round(recent_rate, 4),
        "storm_suspected": storm,
    }


def _band_note(rate: float) -> str:
    lo, hi = HEALTHY_BAND
    if rate < lo:
        return "LOW -- the gate rarely fires; the deterministic path may be over-trusted"
    if rate > hi:
        return "HIGH -- inputs are hard or the threshold is too strict"
    return "healthy"


def main(argv: "list[str] | None" = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="render gate-stats",
        description="Report D16 gate escalation rates + storm detection from the "
                    f"append-only gate log (set {ENV_LOG} or pass --log to populate it).",
    )
    ap.add_argument("--log", type=Path, default=None,
                    help=f"gate JSONL log (default: ${ENV_LOG})")
    ap.add_argument("--window", type=int, default=50, help="recent-window size for storm detection")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    events = read_events(args.log)
    if not events:
        print(f"no gate events yet. Set {ENV_LOG}=<path> (or pass --log) so gated steps "
              "log their decisions, then re-run.", file=sys.stderr)
        return 0

    s = stats(events, window=args.window)
    if args.json:
        print(json.dumps(s, indent=2))
        return 0

    print(f"gate decisions: {s['total']} | overall escalation {s['escalation_rate'] * 100:.1f}%"
          + (f"  ({_band_note(s['escalation_rate'])})" if s['total'] >= 10 else ""))
    print(f"recent {s['recent_window']}: {s['recent_escalation_rate'] * 100:.1f}% escalated"
          + ("   [!] STORM SUSPECTED -- a systemic input change may be missing the gate en masse"
             if s['storm_suspected'] else ""))
    for step, v in s['per_step'].items():
        print(f"  {step}: {v['escalations']}/{v['total']} escalated ({v['rate'] * 100:.1f}%)")
    if s['total'] >= 10:
        print(f"target band ~10-15% escalation (healthy {int(HEALTHY_BAND[0]*100)}-"
              f"{int(HEALTHY_BAND[1]*100)}%). Recalibrate thresholds on any ruleset/input-format change.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
