# Fuzzy-gate architecture plan: deterministic-first, LLM-only-past-a-gate, consistently

> **What this is.** The augmented roadmap + sequenced implementation plan for applying the D16
> doctrine (deterministic result first, escalate to an LLM only past a confidence gate) CONSISTENTLY
> across every LLM-touching step in renderfact. Produced 2026-07-04 from a prior-art sweep (LLM
> cascades, confidence routing, deterministic-first tooling) + a red-team of the codebase's current
> D16 compliance. Governs D8 (harness/copy-paste), D16 (the gate), and D17 (the optional VLM/LLM
> direct-API channel). `docs/DECISIONS.md` holds the decisions; this doc sequences the work.

## 1. The doctrine, sharpened by the prior-art

D16 states the shape: (1) deterministic result first, (2) a confidence score in [0,1], (3) a gate on
a threshold -- accept below cost, escalate above uncertainty; below threshold with no channel, emit
the deterministic result flagged `needs_review` so a result is never lost. The prior-art sweep
confirms this is a well-trodden pattern and sharpens five points:

- **Cascade, cheapest-first (FrugalGPT).** Run the cheap/deterministic path, score reliability,
  escalate only on a low score. Published cost cuts up to ~98% at frontier-parity. Our deterministic
  path is the "cheap model"; the gate is the reliability score.
- **One tunable operating point per step (RouteLLM), not a hardcoded magic number.** Expose the
  threshold as a single slider per step and pick the cost/quality knee from data, not taste.
- **Deterministic diff is authoritative; the LLM only narrates the residue (oasdiff).** The
  fact-of-change is never an LLM's to decide -- only the prose wording is. decision-capture already
  embodies this; every future step must too.
- **Confidence for a RULE-BASED path comes from structure, not logprobs.** Compose the score from
  named sub-signals: rule-coverage (did every field resolve without a fallback rule firing),
  rule-specificity (a precise rule vs a catch-all), ambiguity-count (tied candidate outputs),
  input-novelty (distance from the input shapes the rules were written for). "A fallback/catch-all
  rule fired" is intrinsically low-confidence, for free.
- **Calibrate with conformal prediction, not training.** Log `(score, sub-signals, decision,
  later-verified-correct?)` tuples from real runs; pick each threshold for a formal coverage
  guarantee against that log. Target operating band from HITL-triage deployments: ~10-15% of
  invocations escalating is healthy.

## 2. Current-state compliance (red-team findings, 2026-07-04)

| Step | File | D16 status | Note |
|---|---|---|---|
| decision-capture (C8.3) | `roundtrip/decision_capture.py` | FOLLOWS (hardened) | The worked example. Empty-diff/DIVERGED bug + MODE_FIELD/HAS_OWN_GATE fixed (#15). |
| vision-review | `lint/vision_review_contract.py` + `render.py` | **VIOLATES** | Contract has D8 dual-mode but no `confidence()`/`gate()`/`deterministic_entry()`. The LLM runs the moment the step is invoked; the deterministic svg_metrics/visual_quality verdict is fed as prompt CONTEXT but never gates the call. The single highest-value retrofit. |
| Track D 4.5 contextualize | `roundtrip/reingest.py` (not built) | N/A yet | Must ship in the C8.3 shape, not bolted on. reingest's `manual` list is already the deterministic partial -- 4.5 is "score confidence over `manual`, then gate." |
| gate chain (`render gate`) | `gates/run_gates.py` | N/A | Deterministic-only by design (Track B3), pre-dates D16. A sibling, not a consumer. |
| render QA (`render qa`) | `lint/render_qa.py` | N/A | Deterministic-only. |

## 3. The canonical step shape (what "consistent" means)

Every LLM-touching (or could-be-deterministic-first) step must expose, in this order:

1. `deterministic_<result>(input_obj) -> dict` -- the always-available baseline (template/rules),
   schema-valid, carrying `MODE_FIELD = "<field>": "deterministic"`.
2. `confidence(input_obj) -> ConfidenceResult` -- returns **named sub-signals + a composed score +
   a human-readable reason**, not a bare float (prior-art B). Per-step heuristic; the sub-signal
   NAMES are shared vocabulary (coverage / specificity / ambiguity / novelty / volume / verdict).
3. `gate(input_obj, threshold) -> ("accept" | "escalate", ConfidenceResult)` -- the trivial
   comparison; identical across steps (extraction candidate, see G4).
4. Escalation ALWAYS passes the deterministic partial as context to the LLM (never a blank slate),
   and ALWAYS keeps the deterministic result recoverable (prior-art C, D16 rule).
5. Below threshold with no channel -> deterministic result, flagged `needs_review`.
6. Contract declarations: `MODE_FIELD` (required; the driver raises if absent), and `HAS_OWN_GATE`
   when the step owns a richer CLI than the vision-shaped `render copy-paste`.
7. Telemetry: every gate decision logged for calibration (G2).

## 4. Sequenced implementation plan

Dependency-ordered, PR-sized. Each item is independently shippable and testable.

### G0 -- worked example + hardening. DONE (#14, #15).
decision-capture is the reference implementation; the red-team's one correctness bug and two
consistency debts are fixed. Everything below copies this shape.

### G1 -- vision-review retrofit. DONE.
The step D16 names by name, and its deterministic inputs already exist and are already wired as
prompt context. Scope:
- `lint/vision_review_contract.py`: add `confidence(deterministic_metrics)` keyed on the EXISTING
  svg_metrics `PASS/WARN/BLOCK` + visual_quality `OK/WARN/BLOCK` verdicts. Clean PASS/OK, zero WARN
  -> high (little subjective risk when the geometry is clean). Any BLOCK -> LOW (the compositional
  WHY is exactly what geometry cannot judge -- escalate to the eye). WARN-heavy/borderline -> mid.
- add `deterministic_entry(input_obj)` synthesizing the `status/findings/summary` OUTPUT_SCHEMA from
  the metrics when confidence is high; extend the `reviewer_mode` enum with `"deterministic"`
  (mirrors capture_mode).
- gate BEFORE prompt assembly (must spend zero tokens below threshold -- gate ahead of
  compose_prompt, not just ahead of parsing the reply).
- wire the gate into both `render.py:run_copy_paste` (interactive) and the harness path.
- tests: confidence over each verdict combination; the "clean metrics -> deterministic OK entry, no
  LLM" path; the "BLOCK -> escalate" path.

### G2 -- gate telemetry + calibration log. DONE.
Enables evidence-based thresholds and catches the anti-patterns before they become incidents.
- a JSONL sink (append-only) recording per decision: step, sub-signals, score, threshold, decision,
  channel, and (when later known) outcome-correct. Location + schema are the design work.
- a `render gate-stats` (or doctor extension) reporting escalation rate per step-type and flagging
  **escalation storms** (a spike across steps in a window = a systemic input change; backpressure).
- documents the recalibrate-on-ruleset-change rule as an operational checklist.

### G3 -- confidence sub-signal refactor. DONE.
With two real consumers (decision-capture + vision-review), make `confidence()` return the named
sub-signal breakdown across both, not a bare float. This is the shared VOCABULARY; the heuristics
stay per-step. Depends on G1 (needs the second instance to design the shared shape from two data
points, not one).

### G4 -- extract the thin shared gate primitive. DONE. (Trigger: G1's second consumer.)
Per this repo's trigger-gated-extraction discipline (only after a second real consumer), extract
ONLY the two-line `gate(score, threshold)` comparison + the escalate-with-context +
needs_review-flagging helper into `contracts/confidence_gate.py` (NOT `gate.py` -- the name is
already triple-booked: `gates/run_gates.py`, `scripts/generic_gate.py`, and D16's gate). The
per-step `confidence()` heuristic is inherently local and stays put.

### G5 -- model-config layer + optional direct-API channel (D17). Sequenced last.
The largest surface and the only one touching the D8 trust boundary; off by default.
- `[models]` config: `llm` + optional `vlm`; `vlm` falls back to `llm` when unset or its key
  fails a cheap reachability probe; route by step image-modality; degrade a vision step to
  copy-paste if the resolved model is not vision-capable.
- a fourth escalation channel behind the SAME D8 contract; `MODE_FIELD` enum gains `"api"`; the API
  result is validated by the same validate_output(); an unreachable endpoint falls back to
  copy-paste, never fails the step.
- all D15 hardening (no secrets in logs) and the grens-doctrine egress caution (defence consumers:
  Defence content never leaves local machines) apply.

### G6 -- Track D 4.5 contextualize. DONE.
The mechanical re-ingest (`roundtrip/reingest.py`) already produces the deterministic partial (its
`manual` list). 4.5 = compute confidence over that list (size + kind: pure rewording vs add/delete
lines) reusing the C8.3 `confidence()`/`gate()` shape and the extracted primitive, then narrate only
past the gate. Do NOT invent a new heuristic; copy decision-capture's near-verbatim.

## 5. Red-flag register (design constraints, threaded through every item)

- **Confidently-wrong specific rule.** A precise (non-fallback) rule can still be wrong on an unseen
  edge case; a naive score reads "specific rule fired" as high and never escalates. Mitigation: keep
  an escalation FLOOR for change classes known to be intent-opaque regardless of rule specificity
  (decision-capture already does this: any `add-node` scores toward escalation).
- **Static threshold drift.** A threshold tuned against an old ruleset silently rots. Mitigation:
  recalibrate on any rule/input-format change; G2's log makes drift visible.
- **Gating on completion, not correctness.** "The rule produced output" is not "the output is
  right." Mitigation: score correctness-proxies (coverage/ambiguity), never mere completion.
- **Escalation storms.** A systemic input change makes every step miss the gate at once -> cost
  spike + rate-limit + retry amplification. Mitigation: G2 storm detection + backpressure.
- **Gate overhead.** If scoring re-parses or re-runs partial rules, a cheap gate can cost more than
  it saves. Mitigation: budget gate cost; reuse already-computed deterministic artifacts as score
  inputs (vision-review reuses the metrics it already has).
- **Losing the deterministic partial on escalation.** Always pass it as context and keep it
  recoverable; this also yields a free running eval set for G2 calibration.

## 6. Cross-project note

This doctrine is not renderfact-specific. The same deterministic-first-then-gated-handoff shape was
applied the same day to a separate vault-hygiene tool's tag-governance loop (an independent second
instance). Where the pattern recurs across tools, the vocabulary here (sub-signal names, the gate
verbs accept/escalate, the needs_review fallback, the calibration log schema) should be kept
aligned so operators reason about one pattern, not many.
