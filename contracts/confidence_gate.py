"""confidence_gate.py -- the shared D16 gate primitive (Track G, item G4).

Extracted once a SECOND real consumer existed (decision-capture + vision-review),
per the trigger-gated-extraction discipline: diff the two, extract only what is
genuinely shared, leave the per-step `confidence()` heuristic where it belongs.

Two shared pieces, and only these:

  - `decide(score, threshold)` -- the thin accept/escalate comparison. Each
    step's own `gate()` computes its per-step score, then calls this so the
    comparison rule is identical everywhere.
  - `resolve(...)` -- the orchestration both step CLIs were duplicating: run the
    gate, log the decision to telemetry, then take the accept path (the
    deterministic result, zero tokens) or the escalate path (an LLM channel if
    one is supplied, else the deterministic result flagged `needs_review` so a
    result is never lost), and validate the outcome once.

The per-step `confidence()` heuristics stay in their own modules -- they are
inherently local (decision-capture keys on change kinds; vision-review is
U-shaped over the metrics verdict) and are NOT extracted here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Confidence:
    """A gate score plus the NAMED sub-signals that produced it (Track G, G3).

    The prior-art guidance for a rule-based (non-model) score: compose it from
    named, independently-inspectable sub-signals rather than one opaque number,
    and log each so an operator can see WHY a step escalated and tune thresholds
    per sub-signal later. `score` is the composed [0,1] value the gate compares;
    `signals` is a small {name: value} map (numbers or short verdict strings);
    `reason` is a one-line human summary.

    The sub-signal NAMES are the shared vocabulary; the per-step heuristic that
    computes them stays in each step's own module.
    """

    score: float
    signals: dict = field(default_factory=dict)
    reason: str = ""


class GateError(RuntimeError):
    """A resolved gate outcome failed its step's own validate_output()."""


def decide(score: float, threshold: float) -> str:
    """The D16 comparison: 'accept' the deterministic result at or above the
    threshold (zero tokens), else 'escalate'."""
    return "accept" if score >= threshold else "escalate"


def resolve(step, module, input_obj, threshold, *, escalate=None,
            channel_on_escalate: str = "copy-paste", log: bool = True,
            on_decision=None) -> tuple[dict, dict]:
    """Run the full D16 flow for one gated step and return (entry, meta).

    `module` must expose `gate(input_obj, threshold) -> (decision, score)`,
    `deterministic_entry(input_obj) -> dict`, and `validate_output(dict) ->
    (ok, errors)` -- the D16 step contract.

    `escalate` (optional): a zero-arg callable that produces the LLM result when
    the gate escalates (e.g. the copy-paste driver). When the gate escalates and
    no `escalate` is given, the deterministic result is emitted with
    `meta['needs_review'] = True` -- a result is never lost, only less rich.

    `on_decision` (optional): a callable(decision, score) fired the moment the
    gate decides, BEFORE any escalate() runs -- so a caller can surface the gate
    verdict to the operator before, not after, an interactive paste prompt.

    `meta` keys: decision ('accept'|'escalate'), score, needs_review, channel
    ('deterministic' | channel_on_escalate | 'needs-review').
    """
    decision, conf = module.gate(input_obj, threshold)
    # gate() returns (decision, Confidence); tolerate a bare float too so a
    # minimal/legacy step contract still works.
    score = conf.score if isinstance(conf, Confidence) else conf
    signals = conf.signals if isinstance(conf, Confidence) else {}

    if on_decision is not None:
        on_decision(decision, score)

    if decision == "accept":
        channel = "deterministic"
    elif escalate is not None:
        channel = channel_on_escalate
    else:
        channel = "needs-review"

    if log:
        try:
            from contracts import gate_telemetry

            gate_telemetry.log_decision(step, score, threshold, decision, channel,
                                        signals=signals or None)
        except Exception:
            pass  # telemetry must never break the gate

    needs_review = False
    if decision == "escalate" and escalate is not None:
        entry = escalate()
    else:
        entry = module.deterministic_entry(input_obj)
        needs_review = decision == "escalate"

    ok, errors = module.validate_output(entry)
    if not ok:
        raise GateError(f"{step}: gate result failed validation: {errors}")

    return entry, {"decision": decision, "score": score, "signals": signals,
                   "needs_review": needs_review, "channel": channel}
