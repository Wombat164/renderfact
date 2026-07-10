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

## Escape into raw OOXML for anything markdown can't express

```markdown
Some ordinary paragraph.

```{=openxml}
<w:p/>
```

More ordinary paragraph.
```

`raw_attribute` (issue #96) lets a fenced code block tagged `{=openxml}` pass through verbatim into
the docx writer as raw OOXML, instead of being read as an inert, literal code block. This is a manual,
advanced escape hatch, not new markdown syntax -- reach for it only when nothing else in this guide
covers your case (a genuinely empty spacer paragraph, a one-off structure no fenced div expresses). It
does **not** give you native syntax for Word content controls (checkboxes/dropdowns) or merged/spanned
table cells; both remain open gaps (see the tracking issues) because a hand-authored raw block for
either is fragile enough that it needs its own worked recipe, not a one-liner. Malformed XML here fails
at the pandoc step with a clear error, not a silent corrupt docx.

## Insert a genuinely empty paragraph (spacer)

```markdown
Title text.

```{=openxml}
<w:p/>
```

## First heading
```

Plain markdown has no way to author a genuinely empty paragraph: consecutive blank lines are pure
block separators (they produce zero extra paragraphs, not spacers), and common workarounds like a
lone `&nbsp;` or a trailing `\` both leave a residual character behind rather than a true empty `<w:p>`
-- usually invisible on screen, but a real mismatch if you're reproducing an existing document's exact
layout (e.g. matching a corporate template's own spacer paragraphs paragraph-for-paragraph). The raw
OOXML block above is the tested, working pattern (see `tests/test_raw_attribute_escape_hatch.py` and
`tests/test_empty_paragraph_recipe.py`) -- reach for it specifically when paragraph-count fidelity to
a reference document matters, not as a general substitute for markdown's own blank-line spacing.

## Render a governed source to a sendable .eml

```bash
cat > signature.yaml <<'YAML'
from_email: "jane.doe@example.com"
lines:
  - "Jane Doe"
  - "Product Manager, Engineering"
  - "+1-555-0100"
  - "https://example.com/directory/jane-doe"
# images:
#   - "logo.png"   # optional; PNG only, resolved relative to this file's own directory
YAML

cat > status-update.md <<'MD'
---
title: "Q3 status update"
recipient: "Alex Rivera <alex.rivera@example.com>"
---

# Status

Hello Alex, the dashboard is live.
MD

render eml status-update.md --signature signature.yaml
# -> renders/status-update.eml, ready to open/import in any mail client
```

`recipient:`/`to:` and `subject:`/`title:` frontmatter map to the `.eml`'s `To:`/`Subject:` headers;
`--recipient`/`--subject`/`--sender` on the command line override them. A missing recipient is
advisory, not fatal: a WARNING to stderr, and an `.eml` with no `To:` header, useful for a draft
written before the addressee is settled. See
[Explanation](../explanation/index.md#eml-vs-msg-a-core-vs-adapter-split) for why this is `.eml`
rather than `.msg` or mail-client automation.

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
