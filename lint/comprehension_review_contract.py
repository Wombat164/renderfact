"""
comprehension_review_contract.py -- D8 I/O contract for the comprehension-review
step (issue #84), the TEXT-document peer of lint/vision_review_contract.py's
diagram vision-review gate.

Deterministic gates (Vale, the plain-language work) catch phrasing patterns; the
diagram vision-review gate already established that a fresh, author-independent
LLM read catches what pattern-matching cannot -- for a diagram, subjective
layout quality. This module is the same idea for a rendered TEXT document: does
a reader who has never seen this understand what each snippet is for, and where
does the flow break down. That is a comprehension question, downstream of style,
and needs an actual fresh read.

Both modes (harness via `render init-ai`, copy-paste via `render copy-paste`,
and the D17 direct-API channel) call assemble_input() for the same deterministic
context and validate_output() against the same schema -- the D8 doctrine this
step reuses rather than reinvents.

**The D16 gate decision for THIS step (read before touching confidence()).**
Every other gated step in this repo has a deterministic proxy for "the model's
judgment probably is not needed here": vision-review has hard geometry/contrast
numbers; decision-capture and contextualize have a change-kind taxonomy
splitting descriptive edits (the template states them fully) from intent-bearing
ones (the template can describe but not justify). Comprehension has no
equivalent. Document length, section count, sentence length and similar
structural signals predict REVIEW COST, not comprehension risk, in either
direction: one dense paragraph can bury its point as badly as a long,
well-structured document reads cleanly. Inventing a confidence formula from
those signals would dress up a coin flip as a measurement, which is worse than
being honest that none exists -- and the whole reason this gate exists is to
catch exactly what the deterministic gates (Vale, plain-language, render_qa's
zero-LLM probes) structurally cannot. So confidence() below is pinned at 0.0,
UNCONDITIONALLY: this step always escalates. That is not a departure from D16;
D16 already treats "no deterministic signal" as a legitimate outcome
(vision-review's own confidence() returns 0.0 when neither of its two metrics
fired) -- this is simply the first step where that is the PERMANENT case, not
one branch of a heuristic. See docs/DECISIONS.md D19 for the recorded decision.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from contracts.schema_utils import FieldSpec, validate

TASK_INTENT = (
    "You are reading this document for the FIRST TIME: no authoring context, no "
    "memory of any other document, nothing but what is on the page. Read the "
    "numbered snippets below IN ORDER, exactly as a first-time reader would "
    "encounter them. For EACH snippet, report: what you infer its purpose to be, "
    "what (if anything) is hard to follow without context you do not have yet, "
    "what reads as fluff (padding that adds no information), and what could be "
    "cut without losing meaning. Then, having read the whole document, write a "
    "closing synthesis: what the document as a whole is FOR, which snippet "
    "breaks your reading flow worst (name it by its heading, or 'none' if "
    "nothing breaks), and what a length-budget cut would remove FIRST. This is a "
    "comprehension read, not a style or grammar check -- deterministic gates "
    "already caught phrasing issues; judge only whether a cold reader follows "
    "the content and its argument. Report findings only. Do not rewrite the "
    "document or propose exact replacement text; that decision belongs to a "
    "human."
)

# The provenance field the D8 copy-paste driver forces (contracts/copy_paste.py
# reads MODE_FIELD explicitly). Same name as vision-review's ("reviewer_mode"):
# both are review steps, and the two modules never collide.
MODE_FIELD = "reviewer_mode"

# This step's CLI takes a document path plus chunking/gate flags, nothing like
# vision-review's tier/image/metrics shape -- it is not driven from the generic
# `render copy-paste <step>` CLI. A DECLARED flag, not a duck-typed proxy (same
# convention as decision-capture / contextualize).
HAS_OWN_GATE = True

DEFAULT_THRESHOLD = 0.6
DEFAULT_TARGET_WORDS = 250  # approx a reader half-page, per the issue's ask


class ComprehensionReviewError(RuntimeError):
    """A user-facing comprehension-review mistake: clean message, not a traceback."""


# --------------------------------------------------------------- chunking --
# Fence-aware ATX heading split: the same LEAF SECTION rule the (design-spike-
# only, not yet built) structured-editor spike settled on for its own section
# granularity (docs/2026-07-03-editor-design-spike.md S1.1) -- applied fresh
# here in actual code, since E7 itself has not landed. A '#' line inside a ```
# code fence or a ::: div fence is content, not a boundary, the same fence
# discipline projection/projector.py's own ::: parser applies to its blocks.

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_CODE_FENCE_RE = re.compile(r"^```+")
_DIV_FENCE_RE = re.compile(r"^:::+")
_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n.*?\n---[ \t]*\n?", re.S)


def _strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block, if present. Comprehension is about
    the READER's experience of the body; frontmatter is metadata, not prose."""
    if text.startswith("---"):
        m = _FRONTMATTER_RE.match(text)
        if m:
            return text[m.end():]
    return text


def _split_leaf_sections(text: str) -> list[tuple[str, str]]:
    """Fence-aware ATX heading split. Returns [(heading_label, body_text), ...]
    in document order; text before the first heading is labeled "(preamble)"
    and dropped entirely if blank. A malformed/unmatched fence degrades to
    "headings stop being recognized for the rest of the document" rather than
    crashing -- an honest degradation, not a silent misparse."""
    lines = text.split("\n")
    sections: list[list] = [["(preamble)", []]]
    in_code = False
    in_div = False
    for line in lines:
        is_code_fence_line = bool(_CODE_FENCE_RE.match(line)) and not in_div
        is_div_fence_line = bool(_DIV_FENCE_RE.match(line)) and not in_code
        if not in_code and not in_div and not is_code_fence_line and not is_div_fence_line:
            m = _HEADING_RE.match(line)
            if m:
                sections.append([m.group(2).strip() or "(untitled heading)", []])
                continue
        sections[-1][1].append(line)
        if is_code_fence_line:
            in_code = not in_code
        if is_div_fence_line:
            in_div = not in_div

    out: list[tuple[str, str]] = []
    for heading, body_lines in sections:
        body = "\n".join(body_lines).strip("\n")
        if heading == "(preamble)" and not body.strip():
            continue
        out.append((heading, body))
    return out


def _split_by_paragraphs(body: str, target_words: int) -> list[str]:
    """Sub-split one leaf section into reader-sized snippets at paragraph
    (blank-line) boundaries, never mid-paragraph -- a single paragraph over
    budget stays whole (render_qa.py's own `paras` check already flags
    overweight paragraphs deterministically; this gate is not the place to
    slice one open)."""
    paras = [p for p in re.split(r"\n[ \t]*\n", body.strip("\n")) if p.strip()]
    if not paras:
        return [""]
    chunks: list[str] = []
    cur: list[str] = []
    cur_words = 0
    for p in paras:
        w = len(p.split())
        if cur and cur_words + w > target_words:
            chunks.append("\n\n".join(cur))
            cur, cur_words = [], 0
        cur.append(p)
        cur_words += w
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def chunk_document(text: str, target_words: int = DEFAULT_TARGET_WORDS) -> list[dict]:
    """Chunk a rendered document into reader-sized snippets, IN DOCUMENT ORDER,
    split first at section boundaries and then (only if a section runs long) at
    paragraph boundaries within it. Never merges across headings: a tiny section
    stays its own snippet, so each snippet's heading label stays precise."""
    text = _strip_frontmatter(text)
    leaves = _split_leaf_sections(text)
    chunks: list[dict] = []
    idx = 0
    for heading, body in leaves:
        for i, part in enumerate(_split_by_paragraphs(body, target_words)):
            label = heading if i == 0 else f"{heading} (cont.)"
            chunks.append({"index": idx, "heading": label, "text": part})
            idx += 1
    if not chunks:
        chunks.append({"index": 0, "heading": "(empty document)", "text": ""})
    return chunks


# ---------------------------------------------------------- text extraction --

def extract_text(path: Path) -> str:
    """Read a rendered document into markdown-ish text with ATX headings, so
    chunk_document() runs unmodified over either input format. .md/.txt are
    read as-is; .docx paragraphs are walked with python-docx (already a repo
    dependency) and Heading-N / localized Kop-N styles (the same Word style
    names render_qa.py's own table/paragraph scans recognize) are rewritten to
    '#'*N headings."""
    path = Path(path)
    if path.suffix.lower() == ".docx":
        return _extract_docx_text(path)
    return path.read_text(encoding="utf-8")


_DOCX_HEADING_RE = re.compile(r"^(?:Heading|Kop)\s*([1-6])$")


def _extract_docx_text(path: Path) -> str:
    from docx import Document  # python-docx

    doc = Document(str(path))
    lines: list[str] = []
    for p in doc.paragraphs:
        style_name = (p.style.name if p.style is not None else "") or ""
        text = p.text.strip()
        m = _DOCX_HEADING_RE.match(style_name)
        if not text:
            continue
        if m:
            level = int(m.group(1))
            lines.append("")
            lines.append(f"{'#' * level} {text}")
            lines.append("")
        else:
            lines.append(text)
            lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ schema --

_CHUNK_SCHEMA: list[FieldSpec] = [
    FieldSpec("index", int, required=True,
              description="Position in document order, matching the input chunk."),
    FieldSpec("heading", str, required=True,
              description="The chunk's section heading, or '(preamble)'."),
    FieldSpec("text", str, required=True, description="The snippet's raw text."),
]

INPUT_SCHEMA: list[FieldSpec] = [
    FieldSpec("task_intent", str, required=True,
              description="Fixed instruction text (see TASK_INTENT)."),
    FieldSpec("doc_title", str, required=True,
              description="The document's title (filename stem, or an explicit --title)."),
    FieldSpec("chunks", list, required=True,
              description="Reader-sized snippets, IN DOCUMENT ORDER, split at section "
                          "boundaries (and, only when a section runs long, paragraph "
                          "boundaries within it).",
              item_schema=_CHUNK_SCHEMA),
]

_FINDING_SCHEMA: list[FieldSpec] = [
    FieldSpec("index", int, required=True, description="Which input chunk this finding is about."),
    FieldSpec("purpose", str, required=True,
              description="Inferred purpose of this snippet, one sentence."),
    FieldSpec("confusing", str, required=True,
              description="What is hard to follow without later context; '' if nothing."),
    FieldSpec("fluff", str, required=True,
              description="What reads as padding; '' if nothing."),
    FieldSpec("cuttable", str, required=True,
              description="What could be cut without losing meaning; '' if nothing."),
]

OUTPUT_SCHEMA: list[FieldSpec] = [
    FieldSpec("status", str, required=True, allowed_values=("OK", "WARN", "BLOCK"),
              description="OK: a cold reader follows throughout. WARN: some snippets "
                          "cause friction. BLOCK: reading flow breaks down badly somewhere."),
    FieldSpec("chunk_findings", list, required=True,
              description="One entry per input chunk, in the same order.",
              item_schema=_FINDING_SCHEMA),
    FieldSpec("doc_purpose", str, required=True,
              description="What the document as a whole is FOR, from a cold read."),
    FieldSpec("worst_snippet", str, required=True,
              description="Which snippet (by heading) breaks reading flow worst, or 'none'."),
    FieldSpec("cut_first", str, required=True,
              description="What a length-budget cut would remove first."),
    FieldSpec("summary", str, required=True, description="One-paragraph whole-document verdict."),
    FieldSpec("reviewer_mode", str, required=True,
              allowed_values=("harness", "copy-paste", "api", "deterministic"),
              description="Which mode produced this output -- provenance, not a quality "
                          "signal. 'deterministic' = the D16 gate's unreviewed stub, no LLM "
                          "ran. 'api' = the D17 direct-API channel ran the escalation."),
]


def assemble_input(chunks: list[dict], doc_title: str) -> dict:
    """Deterministic input assembly -- identical regardless of which mode
    consumes it. Raises ComprehensionReviewError if the assembled object would
    fail its own schema."""
    obj = {"task_intent": TASK_INTENT, "doc_title": doc_title, "chunks": chunks}
    errors = validate(obj, INPUT_SCHEMA)
    if errors:
        raise ComprehensionReviewError(f"assembled input failed its own schema: {errors}")
    return obj


def validate_output(obj: dict) -> tuple[bool, list[str]]:
    """Validate a comprehension-review result -- from ANY mode -- against the
    fixed output schema."""
    errors = validate(obj, OUTPUT_SCHEMA)
    return len(errors) == 0, errors


# --------------------------------------------------------------- D16 gate --
# See the module docstring for why confidence() is pinned at 0.0 unconditionally
# (docs/DECISIONS.md D19): comprehension has no deterministic sufficiency proxy,
# so this step always escalates rather than pretending a structural heuristic
# could stand in for a fresh read.

def confidence(input_obj: dict):
    """Confidence that a comprehension read can be skipped -- ALWAYS 0.0 (see
    the module docstring for the full reasoning). The composed score plus its
    named sub-signals (G3): chunk_count and word_count are reported for
    telemetry/operator visibility, not because they feed the score. Returns a
    contracts.confidence_gate.Confidence."""
    from contracts.confidence_gate import Confidence

    chunks = input_obj.get("chunks", [])
    signals = {
        "chunk_count": len(chunks),
        "word_count": sum(len(c.get("text", "").split()) for c in chunks),
    }
    return Confidence(
        0.0, signals,
        reason="comprehension has no deterministic sufficiency proxy; always escalate (D19)")


def gate(input_obj: dict, threshold: float = DEFAULT_THRESHOLD) -> tuple[str, object]:
    """The D16 comparison, run for consistency with every other gated step.
    Since confidence() is pinned at 0.0, this escalates for any threshold > 0 --
    every sane default. threshold<=0 accepts the unreviewed stub deliberately:
    the same escape hatch every other gated step's threshold already offers,
    made explicit rather than accidental."""
    from contracts import confidence_gate

    conf = confidence(input_obj)
    return confidence_gate.decide(conf.score, threshold), conf


def deterministic_entry(input_obj: dict) -> dict:
    """The accept-path stub -- reached only when the gate escalates with no
    escalation channel available (confidence_gate.resolve()'s needs_review
    fallback), or when an operator sets --threshold <= 0. Honestly states that
    no fresh read happened rather than fabricating findings; reviewer_mode
    ='deterministic'."""
    chunks = input_obj.get("chunks", [])
    return {
        "status": "WARN",
        "chunk_findings": [],
        "doc_purpose": "not analyzed (no comprehension read was performed)",
        "worst_snippet": "not analyzed",
        "cut_first": "not analyzed",
        "summary": (
            f"No fresh-reader comprehension read was performed ({len(chunks)} snippet(s) "
            "were prepared but not reviewed). This step has no deterministic fallback for a "
            "judgment-based comprehension question -- run with --escalate copy-paste or "
            "--escalate api, or drive it through a harness (render init-ai), to get real "
            "findings."
        ),
        "reviewer_mode": "deterministic",
    }


# --------------------------------------------------------------------- CLI --

def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="render comprehension-review",
        description="Fresh-reader comprehension gate for a rendered text document (.md or "
                    ".docx): chunk it into reader-sized snippets by section boundary, and "
                    "have a fresh-context LLM (harness, copy-paste, or the D17 direct-API "
                    "channel) read them in order, reporting per-snippet purpose/confusion/"
                    "fluff/cuttable content plus a whole-document synthesis. Report-only -- "
                    "it never rewrites the document. Comprehension has no deterministic "
                    "accept path (docs/DECISIONS.md D19): this always escalates unless "
                    "--threshold <= 0.",
    )
    ap.add_argument("path", type=Path, help="rendered document to review (.md or .docx)")
    ap.add_argument("--title", default=None,
                    help="document title for the report (default: filename stem)")
    ap.add_argument("--target-words", type=int, default=DEFAULT_TARGET_WORDS,
                    help=f"approx words per reader-sized snippet (default {DEFAULT_TARGET_WORDS}, "
                         "~half a page)")
    ap.add_argument("--threshold", type=float,
                    default=float(os.environ.get("RENDERFACT_COMPREHENSION_THRESHOLD", DEFAULT_THRESHOLD)),
                    help=f"D16 gate (default {DEFAULT_THRESHOLD}; env "
                         "RENDERFACT_COMPREHENSION_THRESHOLD). Confidence is always 0.0 (D19), "
                         "so any positive threshold always escalates; <= 0 accepts the "
                         "unreviewed stub.")
    ap.add_argument("--escalate", choices=("copy-paste", "api"), default=None,
                    help="how to escalate (default: none -- the unreviewed stub is emitted, "
                         "flagged needs_review). 'api' tries the D17 direct-API channel, "
                         "falling back to copy-paste")
    ap.add_argument("--json", action="store_true", help="emit the full result as JSON")
    args = ap.parse_args(argv)

    try:
        if not args.path.exists():
            raise ComprehensionReviewError(f"document not found: {args.path}")
        text = extract_text(args.path)
        chunks = chunk_document(text, target_words=args.target_words)
        title = args.title or args.path.stem
        input_obj = assemble_input(chunks, title)

        from contracts import confidence_gate, copy_paste, direct_api
        escalate = None
        if args.escalate == "copy-paste":
            def escalate():
                return copy_paste.run_copy_paste_step(
                    "comprehension-review", sys.modules[__name__], input_obj, scratch_dir=Path("."))
        elif args.escalate == "api":
            def escalate():
                return direct_api.api_then_copy_paste(
                    "comprehension-review", sys.modules[__name__], input_obj, scratch_dir=Path("."))

        def announce(decision, score):  # before any interactive paste prompt
            print(f"[D16 gate] confidence {score} vs threshold {args.threshold} -> {decision}",
                  file=sys.stderr)

        try:
            entry, meta = confidence_gate.resolve(
                "comprehension-review", sys.modules[__name__], input_obj, args.threshold,
                escalate=escalate, on_decision=announce)
        except (confidence_gate.GateError, copy_paste.CopyPasteValidationError) as e:
            raise ComprehensionReviewError(str(e))

        if args.json:
            print(json.dumps({"decision": meta["decision"], "confidence": meta["score"],
                              "threshold": args.threshold, "needs_review": meta["needs_review"],
                              "chunk_count": len(chunks), "entry": entry}, indent=2))
        else:
            print(f"# comprehension-review: {args.path.name}  ({len(chunks)} snippet(s))")
            print(f"confidence {meta['score']} vs threshold {args.threshold} -> {meta['decision']}")
            print(f"mode: {entry['reviewer_mode']}"
                  + ("  [NEEDS REVIEW]" if meta["needs_review"] else ""))
            print(f"status: {entry['status']}")
            print()
            print(f"Document purpose:   {entry['doc_purpose']}")
            print(f"Worst-flow snippet: {entry['worst_snippet']}")
            print(f"Cut first:          {entry['cut_first']}")
            print()
            print(entry["summary"])
            if entry["chunk_findings"]:
                print("\nPer-snippet findings:")
                for f in entry["chunk_findings"]:
                    idx = f.get("index", -1)
                    heading = chunks[idx]["heading"] if 0 <= idx < len(chunks) else "?"
                    print(f"\n[{idx}] {heading}")
                    print(f"  purpose:   {f['purpose']}")
                    if f["confusing"]:
                        print(f"  confusing: {f['confusing']}")
                    if f["fluff"]:
                        print(f"  fluff:     {f['fluff']}")
                    if f["cuttable"]:
                        print(f"  cuttable:  {f['cuttable']}")
        return 0
    except ComprehensionReviewError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
