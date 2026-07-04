#!/usr/bin/env python3
"""decision_capture.py: the editable-diagram round-trip decision-capture step
(C8, chunk C8.3), and renderfact's worked example of the fuzzy-gate doctrine
(D16): run a DETERMINISTIC template first, score its confidence, and hand off
to an LLM (harness or copy-paste, the D8 dual-mode contract) ONLY when the
score misses a threshold. Most captures cost zero tokens.

The last of the three round-trip routes (drawio.py / visio.py classify a
re-ingested hand-edit into semantic / style / layout; layout is auto-applied,
style is reported, and the SEMANTIC changes -- the human's model edits -- are
the ones whose INTENT belongs in a decision log). This step turns that semantic
diff into a decision-log entry.

The tokenomics gate (D16). The prior-art pass confirmed the open ground:
"nothing combines model diffs with intent generation", and oasdiff proves a
deterministic structured-diff-to-changelog fallback works. So:

  1. deterministic_entry() templates every change into a factual entry -- no
     LLM, always available. For a pure relabel or a couple of layout tweaks
     that IS the whole decision ("renamed X to Y"): the WHAT is the WHY.
  2. confidence() scores whether the template is likely sufficient. It drops
     as the edit shifts from descriptive changes (relabels: the template
     states them fully) toward intent-bearing changes (added/removed/rewired
     nodes and edges: the template can say WHAT changed but not WHY), scaled
     down by edit volume and by a DIVERGED verdict (a source that evolved
     since generation needs reconciliation reasoning).
  3. gate() compares the score to a threshold. At or above -> the deterministic
     entry stands (zero tokens). Below -> escalate to the LLM via the SAME D8
     contract vision-review uses; if no escalation channel is offered, the
     deterministic entry is still written, flagged needs_review, so a capture
     is never lost -- only sometimes less richly narrated.

This module is BOTH a D8 step contract (TASK_INTENT / INPUT_SCHEMA /
OUTPUT_SCHEMA / assemble_input / validate_output, so contracts/init_ai.py can
expose it to a harness and contracts/copy_paste.py can drive the escalation)
AND the deterministic engine + gate + sink behind the `render decision-capture`
CLI.

Usage:
    render decision-capture --source <graph.yaml> --reingest <reingest.json>
        [--decision-log PATH] [--threshold F] [--escalate copy-paste]
        [--dry-run] [--json]

    # reingest.json is the output of `render {drawio,vsdx} reingest --json`;
    # pass '-' to read it from stdin (pipe the two commands together).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))   # sibling modules: drawio, provenance
sys.path.insert(0, str(_ROOT))   # repo root: contracts.*

import drawio  # noqa: E402  the lead adapter owns the shared concept-graph contract
import provenance as prov_mod  # noqa: E402
from contracts.schema_utils import FieldSpec, validate  # noqa: E402

TASK_INTENT = (
    "A human hand-edited a generated diagram; the mechanical diff of their "
    "model changes (added/removed/relabeled/rewired nodes and edges) is given "
    "below. Write the DECISION behind those edits: the one-line title and the "
    "rationale a future reader needs -- WHY the model changed, not merely what. "
    "Do not restate layout or styling; those are cosmetic and handled "
    "elsewhere. Keep the change list factual and complete so the entry stands "
    "alone."
)

# Change kinds the deterministic template states FULLY (what == why, low
# intent-gap) vs kinds it can only describe, never justify (the reason lives in
# the human's head): the split the confidence gate keys on.
# The provenance field the D8 copy-paste driver forces (contracts/copy_paste.py
# reads this so it stays generic across step contracts; vision-review uses
# "reviewer_mode").
MODE_FIELD = "capture_mode"

# This step owns a richer CLI with its own D16 gate (`render decision-capture`),
# so the vision-shaped `render copy-paste` CLI redirects rather than mis-driving
# it. A DECLARED flag, not a duck-typed absence-of-VALID_TIERS proxy.
HAS_OWN_GATE = True

_DESCRIPTIVE_KINDS = {"relabel-node", "relabel-edge"}
_INTENT_KINDS = {
    "add-node", "remove-node", "add-edge", "remove-edge",
    "rewire-edge", "regroup-node",
}

_SMALL_EDIT = 3           # up to this many semantic changes stay easy to summarize
_DIVERGED_FACTOR = 0.7    # a source that moved since generation wants narrative
DEFAULT_THRESHOLD = 0.6

_CHANGE_TEMPLATES = {
    "relabel-node": "Renamed node '{id}' from '{old}' to '{new}'.",
    "relabel-edge": "Relabeled edge '{id}' from '{old}' to '{new}'.",
    "regroup-node": "Moved node '{id}' from group '{old}' to '{new}'.",
    "rewire-edge": "Rewired edge '{id}' from {old} to {new}.",
    "add-node": "Added node '{id}' ({new}).",
    "remove-node": "Removed node '{id}' (was '{old}').",
    "add-edge": "Added edge '{id}': {new}.",
    "remove-edge": "Removed edge '{id}' (was {old}).",
}


class DecisionCaptureError(RuntimeError):
    """A user-facing decision-capture mistake: clean message, not a traceback."""


# ------------------------------------------------------------------ schema --

_CHANGE_ITEM_SCHEMA: list[FieldSpec] = [
    FieldSpec("kind", str, required=True, description="The classified change kind."),
    FieldSpec("id", str, required=True, description="The concept/edge id the change touched."),
]

INPUT_SCHEMA: list[FieldSpec] = [
    FieldSpec("task_intent", str, required=True,
              description="Fixed instruction text (see TASK_INTENT)."),
    FieldSpec("source_name", str, required=True,
              description="The canonical source the diagram was generated from."),
    FieldSpec("diagram_title", str, required=True,
              description="The diagram's title, for the decision entry heading."),
    FieldSpec("verdict", str, required=True, allowed_values=("FAST_FORWARD", "DIVERGED"),
              description="Whether the source evolved since the diagram was generated."),
    FieldSpec("semantic_changes", list, required=True,
              description="The classified semantic diff items from the re-ingestion.",
              item_schema=_CHANGE_ITEM_SCHEMA),
]

OUTPUT_SCHEMA: list[FieldSpec] = [
    FieldSpec("title", str, required=True,
              description="Short decision title (one line)."),
    FieldSpec("summary", str, required=True,
              description="The rationale/intent behind the edits -- WHY, not just what."),
    FieldSpec("changes", list, required=True,
              description="Factual, self-contained list of what changed (one string per change)."),
    FieldSpec("capture_mode", str, required=True,
              allowed_values=("deterministic", "harness", "copy-paste"),
              description="How this entry was produced -- provenance, not a quality signal."),
]


def assemble_input(reingest_result: dict, source_name: str, diagram_title: str) -> dict:
    """Deterministic input assembly from a `reingest --json` result -- identical
    regardless of which mode consumes it. Raises DecisionCaptureError if the
    assembled object would fail its own schema."""
    semantic = reingest_result.get("semantic", [])
    obj = {
        "task_intent": TASK_INTENT,
        "source_name": source_name,
        "diagram_title": diagram_title,
        "verdict": reingest_result.get("verdict", "FAST_FORWARD"),
        "semantic_changes": [{"kind": s.get("kind", ""), "id": str(s.get("id", "")),
                              "old": s.get("old", ""), "new": s.get("new", "")}
                             for s in semantic],
    }
    errors = validate(obj, INPUT_SCHEMA)
    if errors:
        raise DecisionCaptureError(f"assembled input failed its own schema: {errors}")
    return obj


def validate_output(obj: dict) -> tuple[bool, list[str]]:
    """Validate a decision entry -- from ANY mode -- against the fixed schema."""
    errors = validate(obj, OUTPUT_SCHEMA)
    return len(errors) == 0, errors


# ------------------------------------------------------- deterministic path --

def _change_line(change: dict) -> str:
    tmpl = _CHANGE_TEMPLATES.get(change["kind"])
    if tmpl is None:
        return f"{change['kind']} '{change.get('id', '')}'."
    return tmpl.format(id=change.get("id", ""),
                       old=change.get("old", ""), new=change.get("new", ""))


def confidence(input_obj: dict) -> float:
    """Fuzzy score in [0, 1]: how likely the deterministic template alone
    captures the decision. 1.0 when there is nothing whose intent needs
    narrating; lower as intent-bearing changes, edit volume, and a DIVERGED
    verdict accumulate. The gate (D16) escalates below the threshold."""
    changes = input_obj.get("semantic_changes", [])
    total = len(changes)
    verdict_factor = _DIVERGED_FACTOR if input_obj.get("verdict") == "DIVERGED" else 1.0
    if total == 0:
        # Cosmetic-only edit: no model change to narrate. But a source that
        # DIVERGED while the diagram was out still needs a human to notice and
        # reconcile, so the verdict factor applies here too -- an empty diff on
        # a moved source is NOT full confidence (bug fixed 2026-07-04: it used
        # to short-circuit to 1.0 and silently skip both escalation and the
        # DIVERGED note).
        return round(1.0 * verdict_factor, 4)
    intent = sum(1 for c in changes if c.get("kind") in _INTENT_KINDS)
    intent_ratio = intent / total
    volume_factor = _SMALL_EDIT / max(_SMALL_EDIT, total)
    return round((1.0 - intent_ratio) * volume_factor * verdict_factor, 4)


def deterministic_entry(input_obj: dict) -> dict:
    """Template every change into a factual decision entry -- no LLM. The
    harness-free baseline that always works (oasdiff-style, per the prior-art
    pass); capture_mode='deterministic'."""
    changes = input_obj.get("semantic_changes", [])
    title = input_obj.get("diagram_title", "diagram")
    diverged = input_obj.get("verdict") == "DIVERGED"

    if not changes:
        summary = ("A re-ingested edit changed only layout or styling; no model "
                   "(node/edge) changes were made. No design decision to narrate.")
        if diverged:
            summary += (" NB: the source had evolved since this diagram was generated "
                        "(DIVERGED) -- even though this edit is cosmetic, reconcile the "
                        "diagram against the current source by hand.")
        return {
            "title": f"{title}: layout/style refinements only",
            "summary": summary,
            "changes": [],
            "capture_mode": "deterministic",
        }

    lines = [_change_line(c) for c in changes]
    n = len(changes)
    summary = (
        f"{n} model change{'s' if n != 1 else ''} captured mechanically from a "
        f"re-ingested edit of {input_obj.get('source_name', 'the source')}. "
        "Intent was not narrated (deterministic capture)."
    )
    if diverged:
        summary += (" NB: the source had evolved since this diagram was generated "
                    "(DIVERGED) -- reconcile these edits against the current source by hand.")
    return {
        "title": f"{title}: {n} model change{'s' if n != 1 else ''}",
        "changes": lines,
        "summary": summary,
        "capture_mode": "deterministic",
    }


def gate(input_obj: dict, threshold: float = DEFAULT_THRESHOLD) -> tuple[str, float]:
    """The D16 escalation gate: 'accept' the deterministic entry when the
    confidence is at or above the threshold, else 'escalate' to an LLM."""
    score = confidence(input_obj)
    return ("accept" if score >= threshold else "escalate"), score


# --------------------------------------------------------------------- sink --

def render_markdown(entry: dict, input_obj: dict, *, source_version: str | None = None,
                    needs_review: bool = False, rendered_at: str | None = None) -> str:
    """Format a validated decision entry as an appendable decision-log section.
    Anchored on the content version (reproducible), not a wall-clock time;
    rendered_at is optional and secondary (the CLI supplies it)."""
    meta = [f"- Source: {input_obj.get('source_name', '')}",
            f"- Verdict: {input_obj.get('verdict', '')}",
            f"- Capture: {entry.get('capture_mode', '')}"
            + ("  (NEEDS REVIEW: deterministic confidence below threshold)" if needs_review else "")]
    if source_version:
        meta.append(f"- Source version: {source_version}")
    if rendered_at:
        meta.append(f"- Captured at: {rendered_at}")
    parts = [f"## {entry.get('title', 'Diagram decision')}", "", *meta, "",
             entry.get("summary", "")]
    changes = entry.get("changes", [])
    if changes:
        parts += ["", "Changes:", *[f"- {c}" for c in changes]]
    return "\n".join(parts) + "\n"


def append_entry(log_path: Path, entry_md: str) -> None:
    """Append a decision entry to the log, creating it with a heading if new."""
    log_path = Path(log_path)
    if not log_path.exists():
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("# Diagram decision log\n\n", encoding="utf-8", newline="\n")
    existing = log_path.read_text(encoding="utf-8")
    sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    log_path.write_text(existing + sep + entry_md, encoding="utf-8", newline="\n")


# --------------------------------------------------------------------- CLI --

def _load_reingest(raw: str) -> dict:
    if raw == "-":
        return json.loads(sys.stdin.read())
    p = Path(raw)
    if not p.exists():
        raise DecisionCaptureError(f"reingest result not found: {raw}")
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="render decision-capture",
        description="Capture the decision behind a re-ingested diagram edit into a "
                    "decision log. Deterministic first; escalates to an LLM (D8 "
                    "copy-paste) only when confidence misses the threshold (D16).",
    )
    ap.add_argument("--source", type=Path, required=True,
                    help="the canonical concept-graph source the diagram was generated from")
    ap.add_argument("--reingest", required=True,
                    help="a `render {drawio,vsdx} reingest --json` result file, or '-' for stdin")
    ap.add_argument("--decision-log", type=Path, default=None,
                    help="decision log to append to (default: <source-stem>.decisions.md)")
    ap.add_argument("--threshold", type=float,
                    default=float(os.environ.get("RENDERFACT_DECISION_THRESHOLD", DEFAULT_THRESHOLD)),
                    help=f"confidence gate (default {DEFAULT_THRESHOLD}; env "
                         "RENDERFACT_DECISION_THRESHOLD)")
    ap.add_argument("--escalate", choices=("copy-paste",), default=None,
                    help="how to escalate when below threshold (default: none -- the "
                         "deterministic entry is written, flagged needs_review)")
    ap.add_argument("--dry-run", action="store_true", help="print the entry, do not append")
    ap.add_argument("--json", action="store_true", help="emit the decision + gate as JSON")
    args = ap.parse_args(argv)

    try:
        if not args.source.exists():
            raise DecisionCaptureError(f"source not found: {args.source}")
        reingest = _load_reingest(args.reingest)

        # title + content version from the source itself (reproducible anchor)
        graph = drawio.load_graph(args.source)
        title = graph.get("title", args.source.stem)
        source_version = drawio._content_version(args.source)

        input_obj = assemble_input(reingest, args.source.name, title)
        decision, score = gate(input_obj, args.threshold)

        needs_review = False
        if decision == "escalate" and args.escalate == "copy-paste":
            from contracts import copy_paste
            entry = copy_paste.run_copy_paste_step(
                "decision-capture", sys.modules[__name__], input_obj,
                scratch_dir=Path("."),
            )
        else:
            entry = deterministic_entry(input_obj)
            needs_review = decision == "escalate"

        ok, errors = validate_output(entry)
        if not ok:
            raise DecisionCaptureError(f"decision entry failed validation: {errors}")

        entry_md = render_markdown(entry, input_obj, source_version=source_version,
                                   needs_review=needs_review, rendered_at=prov_mod.now_iso())

        log_path = args.decision_log or args.source.with_suffix(".decisions.md")

        if args.json:
            print(json.dumps({"decision": decision, "confidence": score,
                              "threshold": args.threshold, "needs_review": needs_review,
                              "entry": entry, "log": str(log_path)}, indent=2))
        else:
            print(f"# decision-capture: {args.source.name}")
            print(f"confidence {score} vs threshold {args.threshold} -> {decision}"
                  + (" (escalated to copy-paste)" if decision == "escalate"
                     and args.escalate else ""))
            print(f"capture mode: {entry['capture_mode']}"
                  + ("  [NEEDS REVIEW]" if needs_review else ""))
            print()
            print(entry_md.rstrip())

        if not args.dry_run:
            append_entry(log_path, entry_md)
            if not args.json:
                print(f"\nappended to {log_path}")
        return 0
    except (DecisionCaptureError, drawio.DrawioError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
