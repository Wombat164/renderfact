---
title: Reference
---

# Reference

## The `render` command surface

| Command | What it does |
|---|---|
| `render docx <src> --profile <p>` | Project one source to a governed DOCX for one audience profile. |
| `render diagram ...` | Render a diagram from its source. |
| `render gate <files> --stages ...` | Fail-closed QA gate chain (vale, lychee, verapdf, uids). |
| `render doctor [--json]` | Host tools vs `tools.lock`: report OK/DRIFT/MISSING; always exit 0. |
| `render provenance embed\|extract\|strip\|adopt\|retarget` | D11 provenance operations on DOCX/XLSX/PPTX/VSDX. |
| `render reingest <edited.docx> --source <md>` | Mechanical re-ingestion of an edited document. |
| `render drawio generate\|reingest` | Editable-diagram round-trip, draw.io adapter (C8.1). |
| `render vsdx generate\|reingest` | Editable-diagram round-trip, Visio adapter (C8.2; needs `vsdx`). |
| `render decision-capture --source <g> --reingest <j>` | Capture edit intent; deterministic first, LLM past the gate (C8.3). |
| `render copy-paste vision-review --image <svg>` | Gated visual-quality review of a diagram. |
| `render gate-stats` | D16 gate escalation-rate stats + storm detection. |
| `render init-ai [--assistant ...]` | Install renderfact-aware instruction files into your assistant. |
| `render copy-paste <step>` | Run one D8 step in copy-paste mode. |
| `render container <podman-args>` | Passthrough to the container render entry. |

Run any subcommand with `--help` for its flags.

## Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `RENDERFACT_VISION_THRESHOLD` | vision-review | D16 gate confidence threshold (default 0.6). |
| `RENDERFACT_DECISION_THRESHOLD` | decision-capture | D16 gate confidence threshold (default 0.6). |
| `RENDERFACT_GATE_LOG` | all gated steps | Path to the append-only gate decision log (opt-in). |
| `RENDERFACT_VALE_CONFIG` | gate (vale) | Override the built-in Vale config. |
| `RENDERFACT_LYCHEE_BIN` / `_VERAPDF_BIN` | gate | Native binary overrides. |
| `PROVENANCE=off` | render pipeline | Skip provenance embedding for a render. |

## Provenance schema (D11)

Embedded in the OOXML `dc:identifier` core property (and, for VSDX, `docProps/core.xml`) as
`renderfact:v1:<json>`:

| Field | Meaning |
|---|---|
| `source_uid` | Stable identity of the canonical source. |
| `source_version` | Content hash of the source at render time. |
| `rendered_at` | UTC render timestamp. |
| `tool_version` | renderfact's own git describe. |
| `source_commit` | The source repo's commit at render (`<sha>` or `<sha>-dirty`). |

## D16 gate contract (per step)

Every gated step exposes: `confidence(input) -> float`, `gate(input, threshold) -> (accept|escalate,
score)`, `deterministic_entry(input)` (the accept-path result), plus `MODE_FIELD` (the provenance field
naming which mode produced the output). See [Explanation](../explanation/index.md#the-d16-fuzzy-gate).
