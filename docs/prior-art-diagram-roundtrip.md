# Prior art: editable-diagram round-trip (C8)

> Verification-disciplined research pass, 2026-07-04 (six parallel sub-searches; claims verified
> against primary sources fetched in-session; refuted claims listed). Feeds C8's tags in
> `ROADMAP.md`. The loop under study: generate .drawio/.vsdx from canonical source -> human
> hand-edits in the visual editor -> re-ingest, diff, route (semantic -> source, layout/style ->
> template layer, intent -> decision log).

## Top-line verdicts

1. **No OSS tool does the full generate-edit-reingest-reconcile loop.** Ten candidates checked
   from their own repos: Cisco's Network Sketcher explicitly disclaims sync-back in its README
   (two disjoint one-way pipelines); clab-io-draw (closest) is two LOSSY one-way converters with
   no diff/merge; Structurizr CLI merges LAYOUT between workspace JSONs only. The loop is this
   framework's own contribution: D11's doctrine applied to diagrams.
2. **Lead with .drawio; vsdx is a second adapter, never a bridge.** draw.io REMOVED its VSDX
   export in v26.1.0 (2025; last version with it 26.0.16, jgraph discussion 5173) after
   documented quality problems: any "author in drawio, deliver as Visio" architecture is dead.
   Import (.vsdx -> drawio) still exists.
3. **The XML-in-image embed is official and lossless** (drawio docs: full source XML in the PNG
   zTXt chunk; "retains all of the data necessary to continue working on it"): rendered artifact
   and re-editable source in ONE file, surviving mail/sharing, dying only on image-resampling
   services. Excalidraw has the same idiom (exportEmbedScene), so the pattern is an industry
   norm, not a quirk. Extraction is plain PNG-chunk parsing; no library needed.

## Per-capability findings and tags

- **Generation, drawio: [adopt drawpyo or thin build].** drawpyo (MIT, v0.2.5, 2025-12,
  write-only) covers shapes/style-strings/multi-page; the format is simple enough to emit
  directly if it constrains. N2G (MIT) reads AND writes drawio but is stale (2023). Format has
  no canonical schema ("edit at your own risk" per drawio's own FAQ); jgraph's drawio-mcp repo
  now ships an mxfile.xsd + style reference seemingly written for LLM consumption: the format
  owner is preparing for machine-generated diagrams.
- **Generation, vsdx: [adopt the `vsdx` Python lib]** (BSD-3-Clause, v0.6.1, 2026-01, active):
  read pages/shapes/text, WRITE, and a first-class template workflow documented verbatim in its
  README (open a template .vsdx, jinja-render the context, save as new): exactly the
  scaffolding-from-template mechanism C8 wants. libvisio is read-only; no other OSS writer
  exists; COM automation needs licensed Visio.
- **Provenance embed, vsdx: [adopt our existing OOXML code].** Microsoft's own file-format
  introduction confirms .vsdx is ZIP + OPC with docProps/core.xml: the dc:identifier embed
  should carry over unchanged (byte-level verification on a real file is the first
  implementation task). For .drawio: custom attributes on the mxfile root.
- **Semantic diff: [imitate EMF Compare, build the implementation].** The mature model-diff
  prior art: match by identifier first, content-similarity fallback, two-way AND three-way with
  a common ancestor. Transfer: ancestor = last-generated file, left = fresh regeneration, right
  = hand-edited file. No semantic merge driver exists for mxGraph XML (only a git textconv for
  readable diffs); the niche is empty.
- **Layout-vs-model routing: [imitate Structurizr, build the router].** Structurizr keeps manual
  layout OUT of the DSL in a separate JSON, merged back on regeneration via pluggable matching
  (name-first, ID-fallback); layout survives renames only if identity stays stable. GraphML/yEd
  is the counter-example (geometry in the same file, no separation). Consequence for C8: give
  every generated cell the canonical node ID from the concept-graph JSON, keep a layout file
  keyed by those IDs, and classify diffs by attribute (cell/edge/label/parent = semantic;
  mxGeometry/style = layout).
- **Decision capture: [build].** Gap confirmed: EMF Compare emits fixed sentence templates, not
  narrative; nothing combines model diffs with intent generation. oasdiff (Apache-2.0,
  rule-classified OpenAPI changelogs) proves the deterministic structured-diff-to-changelog
  fallback works; the LLM-contextualize step under the existing D8 dual-mode contract is the
  novel-but-precedented answer, with the oasdiff-style template as the harness-free fallback.
- **Stencils: style-string referencing works without shipping assets.** A generated file can
  reference bundled sets by style string (e.g. shape=mxgraph.cisco19...) and the drawio app
  renders them with no library import: the generator needs a style-string catalogue only.
  Licence caution: drawio CODE is Apache-2.0 but bundled icon sets are carved out (Cisco shapes
  CC-BY-4.0 per maintainer; AWS/Azure icons under vendor terms): a catalogue that NAMES styles
  is fine, redistributing icon assets is not. Python .vssx stencil parsing: nothing exists.
- **Headless drawio export requires Electron/Chromium, no exceptions** (drawio-desktop CLI flags
  are real but undocumented in its README; official position on Docker: declined; the
  drawio-export wrapper automates xvfb, does not remove the dependency). Consequence: RENDERING
  drawio to PNG/SVG stays a heavyweight engine (tools.lock already knows: drawio-desktop
  BROKEN); the round-trip itself needs no rendering: generate + re-ingest are pure XML, and the
  operator's own draw.io app does the visual part.

## Recommended architecture (condensed from the research)

Generate mxGraphModel XML with stable canonical IDs; provenance as root attributes (drawio) or
the OPC embed (vsdx); layout in a separate ID-keyed file consumed at generation (stored positions
win, Sugiyama for new nodes); distribute as .drawio or .drawio.png (zTXt embed); re-ingest via
three-way ID-first/similarity-fallback matching; attribute-whitelist classification; route
semantic patches to source with operator confirm, layout to the layout file automatically,
unclassifiable to a quarantine list; decision entry via the dual-mode contextualize step with a
deterministic template fallback.

## Refuted and unverifiable (kept per discipline)

REFUTED: drawio exports vsdx (removed v26.1.0); drawpyo reads existing files (write-only).
UNVERIFIED: the exact SVG embed attribute (PNG zTXt is the primary-verified path); byte-level
dc:identifier in a real .vsdx; EMF Compare's SPDX (EPL-2.0 vs Apache-2.0 conflict between
sub-searches: check the LICENSE file before citing); GCP icon licence; whether drawio-mcp's XSD
validates the real product.
