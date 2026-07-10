---
title: How-to recipes
---

# How-to recipes

Task-oriented recipes. Each assumes `render` is installed (see
[Getting started](../tutorials/getting-started.md)).

## Render a source to DOCX for one audience

```bash
render docx <source.md> --profile <profile>
```

The profile decides the disclosure rules, the brand skin, and whether provenance is embedded (internal)
or stripped (external / publish).

## Fit table columns and set a cover version/date on a DOCX

```bash
cat > widths.yaml <<'YAML'
tables:
  - [3000, 6000]   # table 0: two columns (twips), proportions preserved, scaled full-width
YAML
render docstyle draft.docx styled.docx --profile reference \
  --table-widths widths.yaml --cover-version 1.2 --cover-date "2026-07-10"
```

This is the standalone entry point to the same house-style post-processor `render docx` calls
internally; use it to restyle a DOCX directly, or to apply just `--table-widths` without a full
`render docx` pass.

## Gate artifacts before publishing

```bash
render gate <files...> --stages vale,lychee,verapdf,uids
```

Fail-closed: any finding fails, and a requested stage whose tool is not installed fails with exit 2.
Stages self-scope by file type.

## Embed, inspect, or strip provenance

```bash
render provenance embed  <artifact.docx> --source <source.md>   # internal projections
render provenance extract <artifact.docx>                       # see what a file carries
render provenance strip  <artifact.docx>                        # external / publish projections
```

Strip is surgical: it only clears renderfact's own identifier, never a foreign DOI or an
organisation's document number.

## Round-trip an editable diagram

Generate an editable diagram from a concept graph, hand-edit it in the app, then re-ingest:

```bash
# draw.io (the OSS lead adapter)
render drawio generate <graph.yaml> -o diagram.drawio
# ... hand-edit in the draw.io app ...
render drawio reingest diagram.drawio --source <graph.yaml>

# Visio (the Microsoft-side adapter; needs the optional `vsdx` lib)
render vsdx generate <graph.yaml> -o diagram.vsdx
render vsdx reingest diagram.vsdx --source <graph.yaml>
```

Re-ingest classifies each hand-edit: geometry -> the layout file (auto), style -> the template layer,
and semantic changes (added/removed/relabeled/rewired nodes) -> reported for the canonical source.

## Capture the decision behind a diagram edit

Turn a re-ingestion's semantic diff into a decision-log entry -- deterministic first, LLM only if the
edit is intent-heavy enough to miss the confidence gate:

```bash
render drawio reingest diagram.drawio --source <graph.yaml> --json \
  | render decision-capture --source <graph.yaml> --reingest -
```

Add `--escalate copy-paste` to narrate the intent via a chat LLM when the gate escalates; otherwise the
deterministic entry is written, flagged `needs_review`.

## Review a diagram's visual quality (gated)

```bash
render copy-paste vision-review --tier operator-handoff --image diagram.svg
```

The deterministic svg-metrics / visual-quality verdict runs first; the vision LLM is only invoked past
the confidence threshold. Tune it with `--threshold` / `RENDERFACT_VISION_THRESHOLD`, or force the
review with `--force-review`.

## Watch the gates' behaviour over time

```bash
export RENDERFACT_GATE_LOG=~/.renderfact/gate.jsonl   # opt in to logging
# ... run gated steps ...
render gate-stats                                     # escalation rate + storm detection
```

## Make your assistant renderfact-aware (harness mode)

```bash
render init-ai --assistant all
```

Installs instruction files (generated from each step's schema) into your own configured assistant, so a
harness can perform an LLM-touching step directly with no separate API call.
