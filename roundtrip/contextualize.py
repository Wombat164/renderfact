#!/usr/bin/env python3
"""contextualize.py: the document round-trip contextualize step (Track D 4.5).

The sibling of roundtrip/decision_capture.py for DOCUMENTS instead of diagrams:
`render reingest` mechanically re-ingests an edited DOCX and reports a `manual`
list of the reviewer edits it could not safely apply; this step turns that diff
into a decision-log entry -- DETERMINISTIC-FIRST with the D16 gate, escalating to
an LLM only past the confidence threshold. Per the plan, it reuses
decision-capture's shape near-verbatim rather than inventing a new heuristic;
the only genuinely new code is classifying reingest's `manual` tuples (which
carry no `kind` field) into the same descriptive-vs-intent buckets.

Confidence falls as edits shift from DESCRIPTIVE (a reworded line the template
states fully) toward INTENT-bearing (added/deleted content lines, heading
restructuring, shape-changing replacements -- the template says WHAT changed but
not WHY), scaled by edit volume and a DIVERGED verdict. Below threshold with no
escalation channel, the deterministic entry is still written, flagged
needs_review, so a capture is never lost.

Usage:
    render contextualize --source <canonical.md> --reingest <reingest.json>
        [--title TEXT] [--decision-log PATH] [--threshold F]
        [--escalate copy-paste] [--dry-run] [--json]

    # reingest.json is `render reingest --json`; pass '-' to read it from stdin.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))   # sibling modules: reingest, provenance
sys.path.insert(0, str(_ROOT))   # repo root: contracts.*

import provenance as prov_mod  # noqa: E402
from reingest import ADDED_MARKER, DELETED_MARKER, WHY_HEADING  # noqa: E402
from contracts.schema_utils import FieldSpec, validate  # noqa: E402

TASK_INTENT = (
    "A reviewer hand-edited a rendered document; the mechanical diff of the "
    "edits that could not be applied automatically is given below. Write the "
    "DECISION behind those edits: the one-line title and the rationale a future "
    "reader needs -- WHY the content changed, not merely what. Do not restate "
    "trivial rewording; focus on added/removed content, heading restructuring, "
    "and shape-changing replacements. Keep the change list factual and complete "
    "so the entry stands alone."
)

MODE_FIELD = "capture_mode"
HAS_OWN_GATE = True

# The change kinds the deterministic template states FULLY (what == why) vs the
# ones it can only describe, never justify (the reason lives in the reviewer's
# head): the split the confidence gate keys on. Same roles as decision-capture's
# relabel-vs-structural split, mapped onto reingest's manual-diff shapes.
_DESCRIPTIVE_KINDS = {"reword"}
_INTENT_KINDS = {"add", "delete", "replace", "heading"}

_SMALL_EDIT = 3
_DIVERGED_FACTOR = 0.7
DEFAULT_THRESHOLD = 0.6

_CHANGE_TEMPLATES = {
    "reword": "Reworded a line: '{old}' -> '{new}'.",
    "add": "Added a line: '{new}'.",
    "delete": "Deleted a line: '{old}'.",
    "replace": "Replaced content: '{old}' -> '{new}'.",
    "heading": "Edited a heading (structure change): '{old}' -> '{new}'.",
}


class ContextualizeError(RuntimeError):
    """A user-facing contextualize mistake: clean message, not a traceback."""


def classify(item: list) -> str:
    """Classify one reingest `manual` tuple (a JSON list) into a change kind.
    reingest emits [old, new] or [old, new, why]; it carries no `kind` field, so
    this is the one genuinely-new bit of logic (matches the named sentinels
    exported by reingest.py, not re-typed magic strings)."""
    old = item[0] if len(item) > 0 else ""
    new = item[1] if len(item) > 1 else ""
    why = item[2] if len(item) > 2 else None
    if why is not None:
        return "heading" if why == WHY_HEADING else "reword"
    if old == ADDED_MARKER:
        return "add"
    if new == DELETED_MARKER:
        return "delete"
    return "replace"  # unequal-length replace: content changed shape


# ------------------------------------------------------------------ schema --

_CHANGE_ITEM_SCHEMA: list[FieldSpec] = [
    FieldSpec("kind", str, required=True, description="The classified change kind."),
]

_PRIOR_ROUND_SCHEMA: list[FieldSpec] = [
    FieldSpec("round", int, required=True, description="1-indexed round number."),
    FieldSpec("title", str, required=True, description="That round's entry title."),
    FieldSpec("summary", str, required=True, description="That round's entry summary."),
]

INPUT_SCHEMA: list[FieldSpec] = [
    FieldSpec("task_intent", str, required=True,
              description="Instruction text -- TASK_INTENT, extended with prior-round context "
                          "when round > 1 (see _task_intent_for)."),
    FieldSpec("source_name", str, required=True,
              description="The canonical source the document was rendered from."),
    FieldSpec("doc_title", str, required=True,
              description="The document's title, for the decision entry heading."),
    FieldSpec("verdict", str, required=True, allowed_values=("FAST_FORWARD", "DIVERGED"),
              description="Whether the source evolved while the document was out for review."),
    FieldSpec("manual_changes", list, required=True,
              description="The classified manual-review diff items from the re-ingestion.",
              item_schema=_CHANGE_ITEM_SCHEMA),
    FieldSpec("round", int, required=False,
              description="1-indexed review round for this source_name in this decision log "
                          "(G8: multi-round narrative). Omitted/1 means first round."),
    FieldSpec("prior_rounds", list, required=False,
              description="Earlier rounds' title+summary for this source_name, oldest first "
                          "(G8). Empty/omitted means no prior rounds found.",
              item_schema=_PRIOR_ROUND_SCHEMA),
]

OUTPUT_SCHEMA: list[FieldSpec] = [
    FieldSpec("title", str, required=True, description="Short decision title (one line)."),
    FieldSpec("summary", str, required=True,
              description="The rationale/intent behind the edits -- WHY, not just what."),
    FieldSpec("changes", list, required=True,
              description="Factual, self-contained list of what changed (one string per change)."),
    FieldSpec("capture_mode", str, required=True,
              allowed_values=("deterministic", "harness", "copy-paste", "api"),
              description="How this entry was produced -- provenance, not a quality signal. "
                          "'api' = the D17 direct-API channel handled the escalation."),
]


def _task_intent_for(prior_rounds: list[dict]) -> str:
    """TASK_INTENT, extended with prior-round context when this is not round 1
    (G8). Deterministic string-building, zero LLM cost -- the same posture as
    every other input-assembly step in this file; only the ESCALATION path
    that eventually reads task_intent spends a token on it."""
    if not prior_rounds:
        return TASK_INTENT
    prior_desc = "; ".join(
        f"round {p['round']} ('{p['title']}'): {p['summary']}" for p in prior_rounds
    )
    return (
        TASK_INTENT
        + f" This document has gone out for review {len(prior_rounds)} time(s) before. Write "
          "this round's decision as a CONTINUATION of that narrative -- reference what earlier "
          "rounds already established rather than repeating it, and note what is NEW this round. "
          f"Prior rounds: {prior_desc}"
    )


def assemble_input(reingest_result: dict, source_name: str, doc_title: str,
                   prior_rounds: list[dict] | None = None) -> dict:
    """Deterministic input assembly from a `reingest --json` result. Classifies
    each `manual` tuple and keeps its old/new text for the template. Raises
    ContextualizeError if the assembled object would fail its own schema.

    prior_rounds (G8, multi-round narrative): earlier rounds' title+summary for
    this source_name, oldest first, from parse_prior_rounds() over the target
    decision log -- the caller's responsibility to supply (this function stays
    a pure assembler, no file I/O). Defaults to no prior rounds (round 1)."""
    prior_rounds = prior_rounds or []
    manual = reingest_result.get("manual", [])
    changes = []
    for item in manual:
        item = list(item)
        changes.append({
            "kind": classify(item),
            "old": item[0] if len(item) > 0 else "",
            "new": item[1] if len(item) > 1 else "",
        })
    obj = {
        "task_intent": _task_intent_for(prior_rounds),
        "source_name": source_name,
        "doc_title": doc_title,
        "verdict": reingest_result.get("verdict", "FAST_FORWARD"),
        "manual_changes": changes,
        "round": len(prior_rounds) + 1,
        "prior_rounds": prior_rounds,
    }
    errors = validate(obj, INPUT_SCHEMA)
    if errors:
        raise ContextualizeError(f"assembled input failed its own schema: {errors}")
    return obj


def validate_output(obj: dict) -> tuple[bool, list[str]]:
    """Validate a contextualize entry -- from ANY mode -- against the fixed schema."""
    errors = validate(obj, OUTPUT_SCHEMA)
    return len(errors) == 0, errors


# ------------------------------------------------------- deterministic path --

def _change_line(change: dict) -> str:
    tmpl = _CHANGE_TEMPLATES.get(change["kind"], "{kind}: '{old}' -> '{new}'.")
    return tmpl.format(kind=change.get("kind", ""),
                       old=change.get("old", ""), new=change.get("new", ""))


def confidence(input_obj: dict):
    """Confidence that the deterministic template alone captures the decision --
    the composed [0,1] score plus its NAMED sub-signals (G3). The decision-capture
    formula, over reingest's manual diff. Returns a confidence_gate.Confidence."""
    from contracts.confidence_gate import Confidence

    changes = input_obj.get("manual_changes", [])
    total = len(changes)
    verdict_factor = _DIVERGED_FACTOR if input_obj.get("verdict") == "DIVERGED" else 1.0
    if total == 0:
        # Nothing needed manual review: everything fast-forwarded. But a source
        # that DIVERGED while the document was out still needs reconciliation.
        score = round(1.0 * verdict_factor, 4)
        return Confidence(score, {"change_count": 0, "intent_ratio": 0.0,
                                  "volume_factor": 1.0, "verdict_factor": verdict_factor},
                          reason="no manual-review residue" + ("; source DIVERGED" if verdict_factor < 1 else ""))
    intent = sum(1 for c in changes if c.get("kind") in _INTENT_KINDS)
    intent_ratio = round(intent / total, 4)
    volume_factor = round(_SMALL_EDIT / max(_SMALL_EDIT, total), 4)
    score = round((1.0 - intent_ratio) * volume_factor * verdict_factor, 4)
    return Confidence(score, {"change_count": total, "intent_ratio": intent_ratio,
                              "volume_factor": volume_factor, "verdict_factor": verdict_factor},
                      reason=f"{intent}/{total} intent-bearing edits")


def _round_prefix(input_obj: dict) -> str:
    """'' for round 1, 'Round N: ' for round N>1 (G8). Mechanical prefixing
    applies only to the DETERMINISTIC entry's title -- an escalated (harness/
    copy-paste/api) entry's title is author-written with prior-round context
    already in its prompt (_task_intent_for), not force-prefixed here, to
    avoid a human or LLM title clashing with a second mechanical "Round N:"."""
    round_no = input_obj.get("round", 1)
    return f"Round {round_no}: " if round_no > 1 else ""


def deterministic_entry(input_obj: dict) -> dict:
    """Template every manual edit into a factual decision entry -- no LLM.
    capture_mode='deterministic'."""
    changes = input_obj.get("manual_changes", [])
    title = input_obj.get("doc_title", "document")
    diverged = input_obj.get("verdict") == "DIVERGED"
    prior_rounds = input_obj.get("prior_rounds") or []
    round_prefix = _round_prefix(input_obj)
    round_note = ""
    if prior_rounds:
        latest = prior_rounds[-1]
        round_note = (
            f" This is round {input_obj.get('round', len(prior_rounds) + 1)} of review for "
            f"{input_obj.get('source_name', 'this source')}; round {latest['round']} "
            f"('{latest['title']}') came before it."
        )

    if not changes:
        summary = ("The re-ingested edit was fully absorbed by the mechanical fast-forward; "
                   "no edit needed manual review. No content decision to narrate.") + round_note
        if diverged:
            summary += (" NB: the source evolved while the document was out (DIVERGED) -- "
                        "reconcile against the current source by hand.")
        return {
            "title": f"{round_prefix}{title}: no manual-review edits",
            "summary": summary,
            "changes": [],
            "capture_mode": "deterministic",
        }

    lines = [_change_line(c) for c in changes]
    n = len(changes)
    summary = (
        f"{n} reviewer edit{'s' if n != 1 else ''} needing manual review, captured "
        f"mechanically from a re-ingested edit of {input_obj.get('source_name', 'the source')}. "
        "Intent was not narrated (deterministic capture)."
    ) + round_note
    if diverged:
        summary += (" NB: the source evolved while the document was out (DIVERGED) -- "
                    "reconcile these edits against the current source by hand.")
    return {
        "title": f"{round_prefix}{title}: {n} reviewer edit{'s' if n != 1 else ''}",
        "changes": lines,
        "summary": summary,
        "capture_mode": "deterministic",
    }


def gate(input_obj: dict, threshold: float = DEFAULT_THRESHOLD) -> tuple[str, object]:
    """The D16 escalation gate: accept the deterministic entry at/above the
    threshold, else escalate. Shared comparison; per-step score."""
    from contracts import confidence_gate

    conf = confidence(input_obj)
    return confidence_gate.decide(conf.score, threshold), conf


# --------------------------------------------------------------------- sink --

def render_markdown(entry: dict, input_obj: dict, *, source_version: str | None = None,
                    needs_review: bool = False, rendered_at: str | None = None) -> str:
    """Format a validated entry as an appendable decision-log section."""
    meta = [f"- Source: {input_obj.get('source_name', '')}",
            f"- Verdict: {input_obj.get('verdict', '')}",
            f"- Capture: {entry.get('capture_mode', '')}"
            + ("  (NEEDS REVIEW: deterministic confidence below threshold)" if needs_review else "")]
    if source_version:
        meta.append(f"- Source version: {source_version}")
    if rendered_at:
        meta.append(f"- Captured at: {rendered_at}")
    parts = [f"## {entry.get('title', 'Document decision')}", "", *meta, "",
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
        log_path.write_text("# Document decision log\n\n", encoding="utf-8", newline="\n")
    existing = log_path.read_text(encoding="utf-8")
    sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    log_path.write_text(existing + sep + entry_md, encoding="utf-8", newline="\n")


def parse_prior_rounds(log_path: Path, source_name: str) -> list[dict]:
    """Parse an existing decision log (render_markdown's own '## title' + '- Source:
    x' + blank + summary shape, mechanically, no LLM) for entries belonging to
    source_name, returning {round, title, summary} oldest-first (G8, multi-round
    narrative). Missing file or zero matching entries returns [] -- round 1, no
    prior context -- never raises, since "no log yet" is the normal first-run case."""
    log_path = Path(log_path)
    if not log_path.exists():
        return []
    text = log_path.read_text(encoding="utf-8")
    # Split right before each level-2 heading; the file's own level-1 "# Document
    # decision log" heading never matches ("## " requires the second '#').
    sections = re.split(r"\n(?=## )", text)

    matches: list[dict] = []
    for section in sections:
        if not section.startswith("## "):
            continue
        lines = section.splitlines()
        title = lines[0][3:].strip()
        i = 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        this_source = None
        while i < len(lines) and lines[i].startswith("- "):
            meta = lines[i][2:]
            if meta.startswith("Source: "):
                this_source = meta[len("Source: "):].strip()
            i += 1
        if this_source != source_name:
            continue
        while i < len(lines) and not lines[i].strip():
            i += 1
        summary_lines: list[str] = []
        while i < len(lines) and lines[i].strip() and lines[i].strip() != "Changes:":
            summary_lines.append(lines[i])
            i += 1
        matches.append({"title": title, "summary": " ".join(summary_lines).strip()})

    return [{"round": idx + 1, **m} for idx, m in enumerate(matches)]


# --------------------------------------------------------------------- CLI --

def _load_reingest(raw: str) -> dict:
    if raw == "-":
        return json.loads(sys.stdin.read())
    p = Path(raw)
    if not p.exists():
        raise ContextualizeError(f"reingest result not found: {raw}")
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="render contextualize",
        description="Capture the decision behind a re-ingested document edit into a "
                    "decision log. Deterministic first; escalates to an LLM (D8 copy-paste) "
                    "only when confidence misses the threshold (D16).",
    )
    ap.add_argument("--source", type=Path, required=True,
                    help="the canonical markdown source the document was rendered from")
    ap.add_argument("--reingest", required=True,
                    help="a `render reingest --json` result file, or '-' for stdin")
    ap.add_argument("--title", default=None,
                    help="document title for the entry heading (default: source stem)")
    ap.add_argument("--decision-log", type=Path, default=None,
                    help="decision log to append to (default: <source-stem>.decisions.md)")
    ap.add_argument("--threshold", type=float,
                    default=float(os.environ.get("RENDERFACT_CONTEXTUALIZE_THRESHOLD", DEFAULT_THRESHOLD)),
                    help=f"confidence gate (default {DEFAULT_THRESHOLD}; env "
                         "RENDERFACT_CONTEXTUALIZE_THRESHOLD)")
    ap.add_argument("--escalate", choices=("copy-paste", "api"), default=None,
                    help="how to escalate when below threshold (default: none -- the "
                         "deterministic entry is written, flagged needs_review). 'api' "
                         "tries the D17 direct-API channel, falling back to copy-paste")
    ap.add_argument("--dry-run", action="store_true", help="print the entry, do not append")
    ap.add_argument("--json", action="store_true", help="emit the decision + gate as JSON")
    args = ap.parse_args(argv)

    try:
        if not args.source.exists():
            raise ContextualizeError(f"source not found: {args.source}")
        reingest = _load_reingest(args.reingest)

        title = args.title or args.source.stem
        # reproducible anchor: the source_version the artifact was rendered from
        source_version = (reingest.get("provenance") or {}).get("source_version")

        log_path = args.decision_log or args.source.with_suffix(".decisions.md")
        prior_rounds = parse_prior_rounds(log_path, args.source.name)
        input_obj = assemble_input(reingest, args.source.name, title, prior_rounds=prior_rounds)

        from contracts import confidence_gate, copy_paste, direct_api
        escalate = None
        if args.escalate == "copy-paste":
            def escalate():
                return copy_paste.run_copy_paste_step(
                    "contextualize", sys.modules[__name__], input_obj, scratch_dir=Path("."))
        elif args.escalate == "api":
            def escalate():
                return direct_api.api_then_copy_paste(
                    "contextualize", sys.modules[__name__], input_obj, scratch_dir=Path("."))
        try:
            entry, meta = confidence_gate.resolve(
                "contextualize", sys.modules[__name__], input_obj, args.threshold,
                escalate=escalate)
        except (confidence_gate.GateError, copy_paste.CopyPasteValidationError) as e:
            raise ContextualizeError(str(e))
        decision, score, needs_review = meta["decision"], meta["score"], meta["needs_review"]

        entry_md = render_markdown(entry, input_obj, source_version=source_version,
                                   needs_review=needs_review, rendered_at=prov_mod.now_iso())

        if args.json:
            print(json.dumps({"decision": decision, "confidence": score,
                              "threshold": args.threshold, "needs_review": needs_review,
                              "entry": entry, "round": input_obj["round"],
                              "log": str(log_path)}, indent=2))
        else:
            print(f"# contextualize: {args.source.name} (round {input_obj['round']})")
            print(f"confidence {score} vs threshold {args.threshold} -> {decision}"
                  + (" (escalated to copy-paste)" if decision == "escalate" and args.escalate else ""))
            print(f"capture mode: {entry['capture_mode']}"
                  + ("  [NEEDS REVIEW]" if needs_review else ""))
            print()
            print(entry_md.rstrip())

        if not args.dry_run:
            append_entry(log_path, entry_md)
            if not args.json:
                print(f"\nappended to {log_path}")
        return 0
    except ContextualizeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
