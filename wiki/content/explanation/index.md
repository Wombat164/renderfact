---
title: Explanation
---

# Explanation: why renderfact is shaped this way

The decisions behind the architecture are recorded as numbered entries in
[`docs/DECISIONS.md`](https://github.com/Wombat164/renderfact/blob/main/docs/DECISIONS.md); this page
explains the load-bearing ones.

## Generic core, private skin

The engine is domain-agnostic and OSS. Anything organisation-specific -- house style, terminology,
disclosure rules, brand tokens -- lives in a private "skin" the engine consumes. This is what lets the
same tool serve a public tender, a bidder-confidential annex, and an internal evaluation from ONE
source: the profile selects the skin and the disclosure rules. The demo ships a fictional skin so the
public repo has zero real-world coupling.

## Source vs render: one full-candor background, many governed projections

There is exactly one full-candor source. Everything shipped is a PROJECTION of it for a named audience,
produced by applying that audience's profile (disclosure gating, styling, provenance policy). You never
maintain parallel copies; you maintain one truth and govern its outputs.

## The D8 harness-optional contract

Every LLM-touching step has a fixed input/output contract validated identically no matter who produced
the output:

- **harness mode** -- your own configured assistant, given renderfact-aware instruction files.
- **copy-paste mode** -- a human pasting the assembled prompt into any chat LLM and pasting the reply
  back.
- **(D17, opt-in) direct-API mode** -- a configured model, with a VLM endpoint separate from the LLM
  that falls back to the LLM when unset or unreachable.

No step is locked to a vendor, and renderfact ships no LLM-calling code unless you opt into D17. The
same `validate_output()` accepts or rejects a result from any mode.

## The D16 fuzzy-gate

An LLM-touching step is an **escalation, not a default**. Each such step:

1. produces a **deterministic** result first (template / rules / a metrics verdict),
2. computes a **confidence** score in [0, 1] for whether that result suffices, and
3. **gates** on a threshold: at or above, the deterministic result stands (zero tokens); below,
   escalate to a model. With no escalation channel, the deterministic result is still emitted, flagged
   `needs_review` -- a result is never lost.

The confidence heuristic is per step and lives in code, not the model. Two worked examples:

- **decision-capture** scores lower as diagram edits shift from descriptive (relabels, which the
  template states fully) toward intent-bearing (added/removed/rewired nodes, whose WHY the template
  cannot supply).
- **vision-review** is **U-shaped**: a confident PASS and a confident BLOCK both stand on the metrics
  alone; the vision LLM is spent only on the uncertain WARN band, where the eye adds the most.
- **comprehension-review** (issue #84) is the one step whose confidence is a CONSTANT 0.0: it always
  escalates. Document length, section count, and similar structural signals predict review COST, not
  comprehension risk, in either direction -- a single dense paragraph can bury its point as badly as a
  long, well-structured document reads cleanly. There is no deterministic proxy for "a cold reader will
  follow this" the way there is for diagram geometry or an edit's descriptive-vs-intent split, so the
  gate says so rather than dressing up a guess as a measurement. See `docs/DECISIONS.md` D19.

This is the FrugalGPT cascade / RouteLLM operating-point pattern, tuned per step, with an append-only
log (`render gate-stats`) so thresholds become evidence-based rather than hand-set. Full plan:
[`docs/2026-07-04-fuzzy-gate-architecture-plan.md`](https://github.com/Wombat164/renderfact/blob/main/docs/2026-07-04-fuzzy-gate-architecture-plan.md).

## Round-trip and provenance

Editable artifacts (DOCX, and diagrams via draw.io / Visio) carry hidden provenance -- what source,
what version, when, by what tool, at what commit. That is what makes a hand-edited file re-ingestable:
the mechanical diff is verified against the exact source it came from, semantic changes are routed back
to the source, and the human intent is captured to a decision log. External / publish projections have
provenance STRIPPED (projection-aware provenance, D14): stamping internal source identity into files
that leave the building would contradict the disclosure gating that is the tool's whole point.
