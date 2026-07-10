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
render gate <files...> --stages vale,lychee,verapdf,uids,plainlang
```

Fail-closed: any finding fails, and a requested stage whose tool is not installed fails with exit 2.
Stages self-scope by file type. Exception: `plainlang` (repeated-phrase-across-sections scan, issue
#76) is report-only by default, since a hit is often legitimate repeated terminology rather than a
defect; add `--plainlang-fail-on-hits` once you have tuned `--plainlang-min-words` /
`--plainlang-min-count` for your corpus.

## Embed, inspect, or strip provenance

```bash
render provenance embed  <artifact.docx> --source <source.md>   # internal projections
render provenance extract <artifact.docx>                       # see what a file carries
render provenance strip  <artifact.docx>                        # external / publish projections
```

Strip is surgical: it only clears renderfact's own identifier, never a foreign DOI or an
organisation's document number.

## Draw a layered technology stack with interface boundaries

Author a plain YAML source (no ArchiMate/Archi dependency) and render it like any other diagram:

```bash
render diagram demo/diagrams/layered-stack-example.yaml
```

`render diagram` recognizes the archetype by content, not extension: any `.yaml`/`.yml` file whose
top level carries `archetype: layered-stack` is parsed, checked against the view-tier's element
budget, generated to D2 (styled from your brand tokens), and rendered through the normal D2 pipeline.
A `chains` entry in the `stack` list lays out N realizing chains side by side under one shared
interface (N=1 is an ordinary pass-through segment); see `demo/diagrams/layered-stack-example.yaml`
for a worked two-vendor example and `lint/layered_stack.py`'s module docstring for the full source
shape.

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

## Annotate a document's purpose and dossier role

Record WHY a paragraph or section exists, so a later prunability pass can tell "load-bearing" from
"true but not needed" without re-deriving intent from scratch:

```markdown
<!-- PURPOSE: states the tradeoff up front so a skimming reader gets the decision before the detail -->

## Cost vs lead time
...
```

The comment never reaches a reader (verified empirically against both the DOCX and PDF render
paths -- see [Explanation](../explanation/index.md#purpose-annotations-and-dossier-role)), so adding
one is zero render risk.

State what a whole document is FOR relative to its siblings in the same dossier, in frontmatter:

```yaml
---
title: Onboarding overview
dossier_role: the single-page entry point; every other document in this dossier goes deeper on one facet
---
```

Then, optionally, check which prominent blocks still lack a purpose comment (advisory only, never
fails):

```bash
render qa purpose onboarding.md --min-words 40
```

## Make your assistant renderfact-aware (harness mode)

```bash
render init-ai --assistant all
```

Installs instruction files (generated from each step's schema) into your own configured assistant, so a
harness can perform an LLM-touching step directly with no separate API call.
