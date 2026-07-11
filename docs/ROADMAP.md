# renderfact - Roadmap

The forward-looking plan: what to build, in what order, and what to adopt / imitate / build for each
item. `DECISIONS.md` is the record of WHY each architectural choice was made; `ARCHITECTURE.md` is
the system as it stands today. This document is what is next.

## How to read this

Each item carries an **[adopt / imitate / build]** tag:

- **adopt** = use the named dependency directly, do not reimplement.
- **imitate** = the pattern is proven elsewhere but not portable as a dependency (different source
  format, different ecosystem, or not mature enough to depend on): study it, build our own.
- **build** = no strong prior art surfaced; genuinely new design work.

DONE reflects code that exists and is tested; everything else is NEXT or specified-not-built.

---

## Track A - Consolidate (the single `render <mode>` entry point)

- **A1 - One token source.** `brand.yaml` -> generated per-engine themes. **[imitate]** Style
  Dictionary's transform-pipeline architecture as the reference for how the token-to-theme pipeline
  is structured; **[adopt]** the DTCG format module's `$value` / `$type` / `$description` plus
  alias syntax conventions for the schema. **DONE:** custom deep-merge generators (consumer values
  win, unspecified keys fall through to neutral defaults); no Style Dictionary runtime dependency.
- **A2 / A3 - The `render <mode>` single entry point.** **[imitate]** docling-serve's structure: a
  thin CLI/API layer wrapping existing engines, not a monolithic rewrite. **DONE:** `render.py`
  dispatches each mode to its unmodified pipeline.
- **A4 - Reconcile the diagram skills onto one token source.** **DONE:** both diagram skills consume
  A1-generated themes; no independent palettes remain.
- **A5 - Native deployment mode.** The execution of D10 (see Track B / D10). NEXT.
- **A6 - Remaining render pipelines to consolidate.** `[extract]` Additional live pipelines to bring
  into the toolchain: a poster pipeline (a Typst poster path plus an HTML/CSS print-to-PDF path,
  giving a `render poster` mode), a process-flow pipeline (one flow schema transformed into several
  output formats), a LikeC4 project workflow (the engine is already pinned; the project conventions
  are not), and a PlantUML / C4-PlantUML corpus (no PlantUML engine in `tools.lock` yet). Each gets
  the same treatment: generalize, de-couple from any consumer, land with tests, consumer keeps a
  thin wrapper.
- **A7 - One pandoc reader-extension source (#69).** Bracket wikilinks (`[[target|Display]]`)
  silently degrade to literal punctuation unless `wikilinks_title_after_pipe` is in the reader's
  `--from` string; `container/render-doc.sh` carries it, but every other pandoc invocation
  (the typst backend, any consumer copying an extension list from a sibling script) hand-rolls its
  own string and can silently drop one extension. The failure is doubly sneaky: a defensive Lua
  `Str`-filter fallback does NOT catch it, because the unparsed bracket run is fragmented across
  adjacent `Str`/`Space` inlines, so a single-token regex never sees the full pattern (verified in
  #69's repro). **[adopt]** pandoc's `wikilinks_title_after_pipe` extension as the mechanism (already
  elected); **[build]** the consolidation: one shared reader-extension constant that every in-repo
  pandoc call composes its `--from` from, plus a round-trip regression fixture (`[[x|y]]` through the
  REAL render invocation, asserting literal brackets never survive into output text runs). The
  existing `qa leaks` default probe for surviving `[[` brackets stays as the post-render backstop;
  this item removes the class at the source. NEXT.
- **A8 - Surface docstyle's real CLI (#74).** `docstyle/style_postprocess.py` has shipped, working
  capabilities: `--table-widths <yaml>` (`apply_table_widths()`, operator-fitted widths
  proportionally scaled to the section text width), `--cover-version` / `--cover-date`, `--profile`,
  `--template-profile`, that are invisible from `render --help` because the module keeps its own
  hand-rolled argv loop outside the `render.py` dispatcher, and `render-doc.sh` does not even pass
  `--table-widths` through (no env var, no flag), so NO current entry point reaches it. A consumer
  integrating via the Python API (a legitimate path per B3a/H2) demonstrably re-implemented
  `apply_table_widths` before finding the native one by reading module source. **[build]** three
  small moves: (1) wire the flags through the dispatcher (`render docx --table-widths/--cover-*`,
  render-doc.sh gains a `TABLE_WIDTHS` env var in the skin contract); (2) migrate the hand-rolled
  argv loop to argparse so `--help` is generated and complete (today's usage string omits half the
  real flags); (3) a generated Python-API reference for the modules the docs bless as integration
  surfaces (docstyle, projection, roundtrip), **[adopt]** pdoc-style docstring extraction rather
  than hand-maintained lists, landing with F6. NEXT.

## Track B - Optimize

- **B1 - Pins and drift.** **DONE** (typst / pandoc / marp / pypdf / docxcompose, extended with
  LikeC4). D10 adds a second axis: native-mode pin-drift WARNS, container-mode fails closed.
- **B2 - Caching.** NEXT, low priority; keys off the entry point.
- **B3 - Shared pre-render lint (hygiene plus budgets across all output families).** Do not build
  this bespoke. **[adopt]** Vale for text hygiene; **[adopt]** lychee for cross-reference / link
  integrity; **[adopt]** veraPDF for PDF/A plus PDF/UA conformance. **Licence election required:**
  veraPDF is dual GPL-3.0 / MPL-2.0; embedding it as a library under the GPL arm would contaminate
  the MIT claim, so either invoke it as a CLI subprocess or record the MPL-2.0 election explicitly,
  and ship a THIRD-PARTY-LICENSES / NOTICE inventory for every redistributed engine and font before
  the container image goes public. **[evaluate]** textlint and okflint per-check, not winner-take-all.
  **B3a DONE 2026-07-04:** `render gate` ships the fail-closed chain runner with the Vale stage:
  generic-core default config (repetition blocks, spelling warns; consumer overrides via
  RENDERFACT_VALE_CONFIG), vale 3.15.1 pinned in tools.lock + Containerfile + verify-pins.sh +
  doctor probes. Fail-closed means findings fail AND a requested-but-missing tool fails (exit 2):
  a gate that cannot run is not a gate that passed. Distinct from `render qa` (report-only,
  post-render). **B3b lychee DONE 2026-07-04:** offline-by-default link-integrity stage (relative file links
+ anchors; external URLs excluded so the verdict is deterministic and CI-safe; --online opts in);
lychee 0.24.2 pinned across lock/Containerfile/verify-pins/doctor; RENDERFACT_LYCHEE_BIN override
for hosts where the binary is not on PATH. Default chain is now vale,lychee.
**B3c veraPDF DONE 2026-07-04, B3 COMPLETE:** conformance stage on rendered PDFs, CLI
subprocess per the licence election; default validates each PDF against its DECLARED standard
(auto-detect: an undeclared PDF falls back to PDF/A-1b and fails, correct for an archival gate),
--pdf-flavour forces one (e.g. ua1). Exit codes verified against the real 1.30.2 CLI, including
that typst --pdf-standard a-2b output genuinely PASSES PDF/A-2b validation (the archival route
works end to end). veraPDF 1.30.2 + openjdk-17-jre-headless in the container image (headless
izpack install); RENDERFACT_VERAPDF_BIN override for native hosts. Default chain:
vale,lychee,verapdf,uids, each stage self-scoping by file type. The uids stage (added 2026-07-04,
operator requirement: multi-user organisations) detects DUPLICATE renderfact_uid values across a
source tree: uuid4 generation cannot collide, but a file copy duplicates identity and corrupts
every provenance-anchored round-trip downstream; dependency-free and deterministic.
**B3d PlainLanguage/plainlang DONE (issue #76):** the demo skin's Vale catalogue gained a distinct
concern from AiTells (authorial-tell detection): reader-facing plain-language/KISS quality.
**[build]** two of the three checks the issue asked for turned out Vale-expressible after all, so
they ship as a `PlainLanguage` Vale style package (`demo/skin/vale/styles/PlainLanguage/`), wired
into `BasedOnStyles` alongside `AiTells` the same way `GoldenRules` already is: `SentenceLength`
(`existence`, `scope: sentence`, a tunable word-count threshold suggesting a split at a coordinating
conjunction or semicolon) and `NominalisationDensity` (`occurrence`, `scope: paragraph`, English
suffix set `-tion`/`-ance`/`-ment`, structured so a Dutch sibling can be added later without
redesign). Both ship `level: warning`: advisory, not blocking, since both are tunable heuristics
that legitimately false-positive on complex-but-correct prose, unlike the fail-closed AiTells rules.
The third check (the same multi-word comparator/transition phrase recurring 3+ times across a
document) is a genuine Vale DSL limitation, not a modeling choice: every Vale rule type matches a
pattern fixed at authoring time, and this needs the document's own text as the source of the search
pattern. It ships instead as `docstyle/plain_language.py`, a dependency-free cheap n-gram/exact-match
scan, wired into `render gate` as a new `plainlang` stage. Default chain is now
vale,lychee,verapdf,uids,plainlang. plainlang is the one stage that does NOT fail-closed by default
(`--plainlang-fail-on-hits` opts in): a repeated phrase is very often a legitimately reused
programme/component name, so blocking-by-default would make it noise rather than signal, matching
`render qa leaks --fail-on-hits`'s existing report-only precedent rather than this track's usual
fail-closed default.
**B3e - The gate-hook contract for render-doc.sh, deliberately opposite defaults (issue #71, D18)
DONE:** `QC_SCRIPT` (pre-render, against the SOURCE markdown) stays advisory-only by default
(`QC_BLOCKING=1` / `--qc-blocking` opts a consumer into fail-closed); a new `POSTRENDER_GATE_SCRIPT`
(post-render, against the FINISHED `<docx>`, after style/numbering/provenance have all touched it)
defaults to BLOCKING, because its purpose is "does the artifact contain content it must never
contain", not a lint pass a human might skim past in scrollback (`POSTRENDER_GATE_ADVISORY=1` opts
back into report-only). `gates/content_scan.py` is the generic reference implementation a consumer
skin points either hook at: opens the DOCX with python-docx, regex-scans every paragraph and table
cell (recursively into nested tables), exits 1 on any hit. Ships with NO default pattern (the
regex is a required parameter via `--pattern`/`--pattern-file` or `RENDERFACT_GATE_PATTERN[_FILE]`
for zero-arg hook invocation), keeping the public core domain-neutral.
- **B4 - Visual-QA for all families.** NEXT. **Partial DONE (issue #90):** `render qa tables`
  (post-render, not the B3 pre-publish chain) gained a complementary `slack`/`wasteful-col` signal
  alongside the existing squeeze-`pressure`/`squeezed-col` one: the original scan only flagged
  under-allocated columns and excluded any column below a content-share floor from scoring at all, so
  an over-allocated column (a short ordinal/index column given generous width) never surfaced.
  `slack = wshare / max(cshare, floor)`, the inverse ratio, scored for every column with no
  eligibility cutoff, closes that blind spot without reintroducing false positives on genuinely
  proportional small columns.

## Track C - Add

- **C8 - Editable-diagram round-trip.** Operator ecosystem split (2026-07-04): .drawio is the
  LEAD adapter for the OSS/freeware ecosystem; .vsdx is the Microsoft-ecosystem adapter, and
  never a bridge between the two (draw.io removed VSDX export in v26.1.0). **C8.1 (drawio) DONE
  2026-07-04:** render drawio generate turns a YAML/JSON concept graph (concepts + relations with
  STABLE IDS, the round-trip anchor) into a .drawio carrying provenance attributes on the mxfile
  root; a separate ID-keyed layout file preserves hand-positioning across regenerations
  (Structurizr doctrine: stored positions win, the source stays authoritative for labels); render
  drawio reingest reads an edited .drawio, the compressed diagram format, or a .png carrying
  draw.io official full-source embed, verifies provenance (UID mismatch fails closed,
  FAST_FORWARD vs DIVERGED), and routes diffs ID-first: semantic (add/remove/relabel/regroup/
  rewire) reported for the canonical source, style strings reported for the template layer,
  geometry written to the layout file with --apply-layout. Rendering stays out of scope by
  design (the prior-art pass, docs/prior-art-diagram-roundtrip.md: headless drawio hard-requires
  Electron; the operator own draw.io app is the visual layer). Remaining: C8.2 vsdx adapter
  (adopt the vsdx Python lib + the OPC provenance embed), C8.3 decision-capture step (rides the
  D8 contract).

- **C1 - VTOD executable (which content becomes a table, a formula, a diagram, a chart).** Two
  decision layers: form selection (prose / bullets / table / formula / diagram / chart) via
  deterministic signals first, then an optional dual-mode LLM step under the D8 contract for the
  ambiguous remainder; and visual-idiom plus notation selection once "visual" is chosen. `[imitate]`
  a deterministic shape-classifier rule base plus concept-graph converters. Exposes engine gaps that
  feed B1: PlantUML / C4-PlantUML, the Typst packages (fletcher / cetz / cetz-plot), a charting
  engine, and the poster mode.
- **C1a - Diagram archetype family.** `[build]` Purpose-built diagram generators (a plain
  hand-authored renderfact YAML source -> D2, styled by resolving the brand-token system's roles at
  generation time) for common architecture shapes, as opposed to ad-hoc hand-drawn diagrams. **DONE:**
  `layered-stack` (issue #68, FR1-FR3) - an ordered technology stack with an explicit, visually
  distinct interface boundary between adjacent layers, and N parallel realizing chains laid out side
  by side under one shared interface (N=1 is the degenerate default). `lint/layered_stack.py`; wired
  into `render diagram` via content-sniff dispatch on `.yaml`/`.yml` (no new subcommand); NFR6
  element-budget discipline reuses `lint/element_budget.py`'s existing tier table. **ArchiMate
  Exchange-XML adapter (issue #86, FR4-FR6) DONE:** `lint/archimate_exchange.py` maps an Open Group
  Exchange File onto the SAME `StackModel` shape (stdlib `xml.etree.ElementTree` only, zero new
  dependency), reusing `render_d2()`/`check_element_budget()` unchanged; a fixed element-type
  allowlist, fail-closed (FR5) on anything outside it; `.xml` content-sniff dispatch alongside the
  existing `.yaml`/`.yml` path (FR6). v1 deliberately does not auto-detect N-parallel chains from
  ArchiMate relationships (every element renders as a plain Layer/Interface) or infer stack order
  from relationship topology (order = the Exchange File's own document order) - both documented
  scope decisions, not gaps found later. **NEXT (stretch, FR7):** fast re-render on a re-exported
  file, not started.
- **C2 - Projection / clearance gate for decks and diagrams (today the projection engine gates the
  DOCX path).** **[imitate]** Asciidoctor's `ifdef` / `ifndef` / `ifeval` preprocessor-level
  exclusion as the SECURITY model (excluded content never enters the parsed tree); **[imitate]**
  Quarto's profile system as the CONFIG-ergonomics model for how profiles compose. Neither is a
  drop-in dependency; both are adapted.
- **C3 - Typst-as-unifier spike.** NEXT.
- **C4 - render-all batch plus CI resumability.** **[imitate]** a checkpointed, resumable run-id
  model so a multi-stage gate chain resumes from a failed stage instead of restarting.
- **C5 - Tests.** Shadow each track as it lands, not at the end.
- **C6 - LLM design-assist (vision-QA gate first, then generative LLD).** **[adopt the pattern]** a
  harness-mode `init-ai` command that installs renderfact-aware instruction files into the user's own
  assistant, with zero new LLM-calling code of renderfact's own; **[build]** the copy-paste fallback
  (the generalized dual-mode identical-schema contract is a genuine gap, though **[imitate]** aider's
  clipboard round-trip UX for the low-level assemble-then-paste-back mechanism); **[imitate]**
  PaperBanana's prompt-scaffolding architecture
  (Retriever / Planner / Stylist / Critic separation, natural-language-color-not-hex rule,
  vision-plus-spec dual-context trick); **[study, do not adopt code]** PaperBanana's unsandboxed
  code-execution mistake as the negative example: LLM-generated content must render through pinned,
  isolated engines on TEXT the LLM produced, never `exec()`-run raw LLM code.
- **C7 - Template import.** DOCX style axis SHIPPED (`render import-template <corporate.docx>`:
  shared DrawingML theme extractor, derived template-profile with template provenance, the
  probe-render style-diff idempotency gate, and per-named-style font derivation, issue #97: a
  template that uses distinct fonts on distinct paragraph styles gets a `styles:` block in the derived
  profile carrying only the genuine overrides, not just the single global `font` key a template with
  one uniform font still gets). **Custom-style font fidelity (issue #98, D21) DONE alongside #97:**
  the house body font/size pass used to stamp itself onto every non-heading paragraph regardless of
  style, including one carrying a genuinely custom style whose OWN `w:rPr` already defines a font/size
  in `reference.docx`'s `styles.xml`: the paragraph got the right `w:pStyle` but a direct-formatting
  run override shadowed the style's own definition. The default now respects a custom style's own
  font/size (`is_custom_style_paragraph()`); the pre-#98 blanket override is an explicit opt-in
  (`--override-custom-style-fonts` / `override_custom_style_fonts: true`) for a consumer who genuinely
  wants one uniform house font regardless of custom styles. The two features compose: a per-style
  `styles:` override (#97) still applies whenever a style IS styled (built-in categories, or a custom
  style with the override flag forcing it); a respected custom style's own font (#98) wins outright
  when it is not. **Guidance-doc scan (issue #100) DONE:** `--guidance-doc <path>` runs a mechanical
  structural scan (heading/paragraph counts, heading preview) of a template's accompanying style/
  usage guide and surfaces it as a pointer toward hand-seeding `editorial-doctrine.yaml` (#84's
  concept); omitting the flag prints a one-line reminder instead of a blocking prompt. Remaining
  `[build]`: the PPTX and XLSX importers and
  the content-skeleton axis: derive the
  skin config FROM an imported branded template so the FIRST render is idempotent with the template's
  look (a shared OOXML DrawingML theme extractor plus per-format derivation, a derived
  template-profile carrying template provenance, and a probe-render style-diff idempotency gate). A
  second axis derives a source SCAFFOLD from the template's content skeleton (required section
  structure, author-guidance paragraphs, example text to replace). Prior-art tags: `[adopt]` the
  three existing Python libraries for styles / geometry / placeholders, and pandoc's reference-doc as
  the styling carrier plus its `docx+styles` reader for skeleton extraction; `[build]` the shared
  DrawingML theme parser (a maintainer-confirmed API gap in two of the three libraries), the scoped
  style-diff gate, and a structure-conformance gate modeled on markdownlint's MD043 semantics;
  `[imitate]` BrandDocs (its color-scheme resolution logic), docx4j's PropertyResolver cascade
  pattern, and mammoth's style-map DSL as the config syntax.
- **C9 - Purpose annotations and dossier role (#77).** `[build]` **DONE:** an annotative-only
  authoring convention, never a blocking gate (D19). `<!-- PURPOSE: ... -->` HTML comments above a
  paragraph/heading (verified empirically to be a no-op on both the DOCX and typst-PDF render paths,
  reusing the same pandoc raw-HTML-drop mechanism D14's provenance header stamp already relies on),
  a freeform `dossier_role:` frontmatter field (read via `roundtrip/dossier_role.py`, the same
  frontmatter-read idiom as `renderfact_uid`), and an optional advisory-only `render qa purpose` lint
  pass (never fails, same posture as `QC_SCRIPT`'s off-when-unset default).
- **C10 - OOXML raw-attribute escape hatch (#96).** `[build]` **DONE:** `pandoc_markdown.MARKDOWN_FROM`
  pins `raw_attribute`, so a hand-authored ` ```{=openxml} ` fenced block now reaches the DOCX writer
  as raw OOXML (verified end-to-end: a real `render docx` run puts the block's marker text into
  `word/document.xml` verbatim, and the negative control with the extension explicitly disabled
  confirms it stays an inert code block without it). This is deliberately the SMALL, mechanical half
  of the issue: it only unblocks the escape hatch, it does not add any native markdown syntax. **NEXT
  (separate follow-up issue, not this one):** purpose-built markdown syntax for the two gaps that
  motivated the escape hatch and that onboarding a real institutional form template surfaced -
  checkbox/dropdown Word content controls (`w:sdt`, currently unrepresentable in the AST at all) and
  merged/spanned table cells (`gridSpan`, pipe/grid tables have no colspan or rowspan support). Manual
  `{=openxml}` blocks remain the only path to either until that follow-up lands, and they are
  advanced/fragile by nature (hand-written OOXML, no toolchain validation), not the ergonomic answer.

## Track D - Round-trip / draft reconciliation

Fully specified as D11: idempotent split-plus-embedded DOCX output, hidden provenance metadata,
diffable and contextualizing re-ingestion with a three-way conflict merge, git as inherent
infrastructure. **Provenance (part 2) is DONE**; the rest is specified, not built. Build order:
provenance first, then split-plus-embed dual output (parallel), then re-ingestion plus diff, then the
three-way conflict merge (hardest, build last), with git-commit wiring threading throughout.
Provenance is projection-aware per D14: internal profiles embed it, external / publish profiles
strip it (the strip mechanism SHIPPED 2026-07-04 with the render-pipeline wiring: default renders
embed, strip-flagged projections scrub, PROVENANCE=off opts out).
**Chunk 4.4 (mechanical re-ingestion) DONE 2026-07-04:** render reingest anchors an edited DOCX to
its source via provenance (UID mismatch fails closed; FAST_FORWARD vs DIVERGED verdict), extracts
Word comments + tracked changes + structure + a normalized text delta (stdlib only, generalized
from a proven reverse-pipeline extractor), and is REPORT-ONLY by default: --apply back-ports just
the mechanically safe subset (1:1 reworded, markup-free, unique lines) and refuses on DIVERGED
(the three-way merge is chunk 4.6). Provenance also gained source_commit (D11 part 4 hardening):
every render records the source repo's exact commit, -dirty-suffixed when uncommitted.
Embedded objects are TRIAGED by provenance since 2026-07-04 (operator requirement): a
renderfact-tracked embedded OPC document (docx/xlsx/pptx/vsdx all share docProps/core.xml, read
generically) is routed to its own per-format path; an OOXML file without provenance is flagged
unknown-origin (adopt candidate); any other type is tried through markitdown (optional extra)
for a text preview. Embeddings are matched by path segment, covering XLSX/PPTX/VSDX hosts too.
**First consumer-side use of the whole loop (2026-07-10, a raw-pandoc + custom-Python pipeline, no
`render docx` involved) confirmed the bootstrap paths hold for externally-produced artifacts too:**
`provenance embed` anchors an existing source to a DOCX renderfact never rendered, `provenance
adopt` bootstraps a stub source for an externally-authored draft (issue #70's core round-trip ask
is validated by this; #70 itself stays open pending the GUI reconcile view the issue also asks for).
**Text-delta structural-noise fix (issue #72):** pandoc-specific structural syntax (fenced-divs,
raw-attribute OOXML blocks, blockquote markers) never renders as literal DOCX text, so the delta
used to show their absence as false-positive reviewer deletions. Fixed by stripping them from the
canonical-markdown side before the diff, at the same normalization tier as the pre-existing
list-bullet/auto-numbered-heading stripping (ordered-list markers were already handled correctly
and are unaffected). `render reingest --strip-pattern <regex>` (repeatable) lets a project add its
own structural-noise conventions without renderfact special-casing them.
**Table-width apply path + page-break reporting (issue #73) DONE:** the `## 3. Table column widths`
detection had no equivalent of the text delta's `--apply`, so `render reingest --apply-widths
<out.yaml>` now emits a table column-width sidecar in the exact shape `docstyle/style_postprocess.py`'s
`apply_table_widths()` / `--table-widths` already consume (ordinal-matched twips), keyed in a YAML
comment by header text + row count + column count for stability across re-ingestion runs. It never
touches the markdown source (pipe tables carry no width information pandoc will honor) and is written
regardless of the FAST_FORWARD/DIVERGED verdict, since it captures a fact about the returned DOCX, not
a source edit. Page-break adds/removals (the `\newpage` token or a raw-openxml `<w:br
w:type="page"/>`) previously surfaced only as generic manual-review noise (or not at all, since a
page-break-only paragraph carries no visible text); they now get a dedicated `## 3b. Page breaks`
section with source-line and DOCX-paragraph offsets, excluding Word's own `w:lastRenderedPageBreak`
layout-cache marker.
Remaining in Track D: 4.2 split-plus-embed dual output, 4.5 LLM contextualize (rides D8), 4.6
three-way merge, 4.7 git finalize.

## Track E - API and reference UI

- **E1 - Design the API around D8's per-step contracts**, not ahead of them. **DONE:** a stdlib WSGI
  app exposing the step contracts and the projection engine over localhost. **[imitate]**
  docling-serve's route shape and opt-in `/ui` mount.
- **E2 - Security posture.** **[imitate]** a read-server localhost-bind-plus-warn pattern, then
  harden past it (D15). **DONE:** loopback bind, non-localhost warning, rate limit, non-loopback Host
  rejection, browser cross-origin POST rejection, path jail, and a CSRF-token endpoint for the first
  mutating route.
- **E3 - Thin reference UI plus API docs.** **DONE:** opt-in `/ui`, a self-contained `/docs` page and
  a hand-authored `/openapi.json` (a bundled Swagger-UI build would be the first heavyweight frontend
  dependency; revisit only if the spec outgrows hand-authoring).
- **E4 - Progress reporting.** **[imitate]** a progress-event shape decoupled from pipeline logic,
  consumable identically by CLI, API, and UI. NEXT.
- **E5 - Optional MCP server on top of the API.** **[imitate]** a well-audited MCP hardening
  reference: off by default, every tool method permission-scoped, real input validation with size
  caps. Optional, last.
- **E6 - Dual-mode API/UI (container and native).** D10 applies here too. NEXT.
- **E7 / E7b / E7c - Structured source editor (from D12 / D12b / D12c).** `[build]` a three-pane
  markdown editor, a two-pane XLSX editor, and an as-text PPTX editor `[imitate]` marp-cli. Design
  spike DONE (see `ARCHITECTURE.md`); implementation sequenced behind Track F per D13.

## Track F - Release engineering

Packaging, CI, docs, and naming: what a repo needs to be installable, verifiable, and coherent for a
public audience.

- **F4 - Packaging.** `[build]` a `pyproject.toml` with declared and pinned Python dependencies
  (PyYAML, python-docx, openpyxl, python-pptx) and a `render` console entry point; `pytest` as a dev
  extra. `tools.lock` (engines) and the Python manifest are two separate, both-real artifacts.
  **DONE (editable install):** `pip install -e .` resolves dependencies and installs the entry point;
  full wheel packaging is the remainder.
- **F5 - CI.** `[build]` GitHub Actions: pytest on the container-pinned interpreter and the dev-host
  interpreter across Linux and Windows, container build plus `verify-pins.sh` in-image, and a demo
  smoke render. **DONE (skeleton):** the test matrix and hygiene gates run; container build and demo
  smoke render are the remainder.
- **F6 - Docs.** `[build]` a public docs set (this directory) that reflects the system as it is.
- **F8 - Naming unification.** `[build]` one public identity everywhere: `renderfact`, the container
  image `localhost/renderfact:latest`, a quickstart that works verbatim.
- **F9 - Demo chapters for the round-trip and template-import surfaces.** `[build]`. The Meridian
  demo showcases projection, tokens, the DOCX pipeline, Track H's financial PDF, and a consumer
  Vale skin, but NOTHING from Track D or C7: a new consumer evaluating renderfact sees no
  provenance, no reingest, no contextualize, and no `import-template` in the runnable showcase,
  which is exactly the surface a 2026-07-10 consumer session under-discovered (#74, G7). Two new
  demo steps, keeping the no-binary-fixtures rule (D4: the demo is the acceptance test): (5) a
  round-trip chapter that renders a Meridian source, simulates a reviewer edit programmatically
  (python-docx over the fresh render in demo/renders/, gitignored), then runs
  `reingest -> contextualize` and prints the decision-log entry; (6) a template-import chapter that
  builds a small "corporate" branded DOCX programmatically and derives a template profile from it
  via `render import-template`, closing with the probe-render idempotency gate. Each chapter skips
  with an honest message when its engine is missing, like the existing steps. NEXT.

---

## Track G - Fuzzy-gate consistency (deterministic-first, LLM only past a confidence gate)

Apply the D16 doctrine CONSISTENTLY to every LLM-touching step: run a deterministic result first,
score confidence, escalate only past a threshold. Motivated by tokenomics (most invocations need no
model) and by a prior-art sweep (FrugalGPT cascade, RouteLLM operating-point, oasdiff
deterministic-diff-authoritative, conformal-prediction calibration). Full sequenced plan, red-team
findings, and red-flag register: [`docs/2026-07-04-fuzzy-gate-architecture-plan.md`](2026-07-04-fuzzy-gate-architecture-plan.md).

- **G0 - worked example + hardening.** `[build]` **DONE (#14, #15):** decision-capture (C8.3) is the
  reference shape; its one correctness bug + two consistency debts fixed.
- **G1 - vision-review retrofit.** `[build]` **DONE:** gate the vision LLM on the deterministic
  svg_metrics/visual_quality verdict. U-shaped confidence (confident PASS 0.85 and confident BLOCK
  1.0 both accept metrics-only; the uncertain WARN band 0.4 and missing-signal 0.0 escalate), a
  canonical `assemble_metrics()` source, a `deterministic_entry()` synthesizing the review on the
  accept path (reviewer_mode='deterministic'), gate wired into `run_copy_paste` BEFORE prompt
  assembly with `--threshold`/`RENDERFACT_VISION_THRESHOLD` + `--force-review`. 19 tests.
- **G2 - gate telemetry + calibration log.** `[build]` **DONE:** `contracts/gate_telemetry.py` +
  `render gate-stats`. Opt-in append-only JSONL (via `RENDERFACT_GATE_LOG`) recording every gate
  decision (step / score / threshold / decision / channel / verdict); both gate consumers
  (vision-review, decision-capture) log; `gate-stats` reports overall + per-step escalation rate,
  recent-window storm detection, and the ~10-15% healthy-band note. Telemetry never breaks the gate.
- **G3 - confidence sub-signal refactor.** `[build]` **DONE:** `confidence()` now returns a
  `confidence_gate.Confidence` (score + named `signals` + reason), not a bare float. decision-capture
  exposes `change_count/intent_ratio/volume_factor/verdict_factor`; vision-review exposes
  `verdict/svg_severity/vq_status`. The signals ride into the gate telemetry event, so escalations
  are explainable and thresholds tunable per-signal. `resolve()` tolerates a legacy bare-float gate.
- **G4 - extract the thin gate primitive.** `[build]` **DONE:** `contracts/confidence_gate.py` with
  `decide(score, threshold)` (each step's `gate()` uses it) + `resolve(...)` (the shared
  gate->telemetry->accept/escalate/needs-review orchestration both CLIs were duplicating, with an
  `on_decision` hook so the verdict prints before an interactive prompt). Per-step `confidence()`
  heuristics stay local. decision-capture + vision-review both refactored onto it; adversarially
  subagent-reviewed for behavior-preservation.
- **G5 - model-config + optional direct-API channel (D17).** `[build]` **DONE:**
  `contracts/model_config.py` (`[models] llm/vlm` from a TOML file + env, `api_key` ENV-ONLY;
  `resolve_for_step()` routes text->llm / vision->vlm, falls the VLM back to the LLM when unset or
  unreachable, and degrades a vision step to copy-paste when no resolved model is vision-capable) plus
  `contracts/direct_api.py` (a stdlib-urllib OpenAI-compatible `/chat/completions` caller reusing the
  copy-paste prompt + validate_output, forcing `MODE_FIELD="api"`, attaching the rendered image as a
  base64 data URL for vision endpoints, and never logging the key). A third D8 escalation channel
  behind the same contract, off by default; `api_then_copy_paste()` falls back to copy-paste on
  no-config or any transport failure. Wired into `render copy-paste` (default on when configured,
  `--no-api` to force copy-paste) and `decision-capture` / `contextualize` (`--escalate api`). 39 tests.
- **G6 - Track D 4.5 contextualize on this shape.** `[build]` **DONE:** `roundtrip/contextualize.py`
  + `render contextualize`, mirroring decision-capture over reingest's `manual` diff. A `classify()`
  maps each reingest tuple (no `kind` field) to reword (descriptive) vs add/delete/replace/heading
  (intent-bearing) via reingest's now-exported sentinel constants; the confidence formula, gate,
  sink, and CLI are decision-capture's. Registered for harness exposure. 25 tests.
- **G7 - Comprehension gate for text documents, the first D16 step with no accept path (#84).**
  `[build]` **DONE:** `lint/comprehension_review_contract.py` + `render comprehension-review
  <docx-or-md>`, the text-document peer of the diagram vision-review gate (G1): chunks the document
  into reader-sized snippets at section (and, when needed, paragraph) boundaries and has an
  author-independent LLM read them in order via the same D8 contract machinery (harness / copy-paste
  / the D17 direct-API channel), reporting per-snippet purpose/confusion/fluff/cuttable content plus a
  whole-document synthesis. Report-only. `confidence()` returns a CONSTANT 0.0: comprehension has no
  deterministic sufficiency proxy the way vision-review's geometry/contrast numbers or
  decision-capture's change-kind taxonomy do, so the step always escalates unless an operator
  explicitly sets `--threshold <= 0` (an honest "not reviewed" stub, never a fabricated verdict). This
  was checked explicitly against the concrete plain-language signals that landed alongside it (issue
  #76: sentence-length, nominalisation density, repeated-phrase detection) and found NOT to
  substitute for a comprehension-confidence proxy either: a style finding is not a comprehension
  finding. Recorded as D20: a legitimate D16 outcome (the gate's own vision-review worked example
  already treats "no deterministic signal" as valid), not an exception to it, simply the first step
  where that is the PERMANENT case rather than one branch of a heuristic. 26 tests.
- **G8 - contextualize workflow surfacing + multi-round narrative.** `[build]`. Renumbered from G7
  during PR #67's main-branch merge-conflict resolution (2026-07-11): G7 collided with issue #84's
  comprehension gate, developed in parallel without either session aware of the other, the same class
  of collision D18/D19 already hit elsewhere in this repo's decision/roadmap numbering. A consumer
  session (2026-07-10) hand-wrote prose changelog entries for every back-ported reviewer edit, all
  session, without ever invoking `render contextualize`: the exact job G6 shipped for. Root cause is
  NOT render-help invisibility (contextualize is a registered mode with a real argparse `--help`,
  unlike A8's case); it is WORKFLOW invisibility plus one real functional gap. (1) Surfacing:
  `render reingest`'s report and CLI output never point at the next step, and its default
  human-readable report is not even the `--json` input contextualize requires; add a printed
  next-command hint after every reingest (**[imitate]** git's `advice.*` hint system and the
  clig.dev "suggest the next command" guideline) and a `reingest --contextualize` one-shot chaining
  flag so the two-command JSON plumbing disappears for the common case. (2) Multi-round narrative:
  contextualize is single-shot per reingest; it appends standalone entries and never reads the
  existing decision log, so a document that goes out for review three times gets three disconnected
  entries with no round numbering and no reference to what earlier rounds changed, while the
  consumer's real need was a cumulative changelog narrative referencing previous rounds. Make the
  step round-aware: read prior entries for the same source_uid from the log, stamp a round counter,
  and hand the previous rounds' titles/summaries to the escalation prompt as context
  (**[imitate]** towncrier's fragments-then-assemble model and reno's keep-fragments-forever
  philosophy: per-round entries stay the source of truth, the cumulative narrative is derived, so
  nothing is rewritten after the fact). NEXT.

---

## Track H - Layout PDF backend + governance/financial document primitives

Motivated by a real deliverable (Belgian VME general-assembly minutes + a financial statement, A4,
branded) that bypassed renderfact entirely and was hand-built in typst, because the DOCX->LibreOffice
path cannot reliably produce a layout-precise branded A4 PDF (page chrome, callout boxes, signature
grids, ledger rules). Filed as issues #31-#35; this track turns renderfact from "themed Word" into
"docs-as-code for print-quality deliverables".

- **H1 - PDF/layout backend (typst) as a peer of the DOCX path (#31).** `[build]` **DONE:**
  `pdf/typst_backend.py` + `pdf/theme/default.typ`, wired as `render pdf <src> [--engine typst]`.
  Markdown -> pandoc typst writer -> a brand-token-driven theme -> typst compile -> PDF; no OOXML, no
  LibreOffice, so the layout is typst's own. The default theme is generic-core (D3): A4, page
  header/footer rules, accent headings, title block, all derived from the existing `tokens.typ`
  generator (shared palette/fonts with every other engine); consumers override via `--theme` /
  `--brand`. Tools (pandoc + typst) are already probed by `render doctor`; missing either fails with an
  actionable message. 13 tests (unit + skipif-guarded real-compile).
- **H2 - Engine-agnostic theme descriptor (#32).** `[build]` **DONE:** the chrome + component layer
  (page margins, header/footer slots, heading/title/rule colour ROLES) is declared in `brand.yaml`'s
  `theme` section, with `base` + inheritable `variants` (a built-in `financial` restyles headings).
  `tokens/gen/theme_tokens.py` emits `chrome.typ` for the typst path; `pdf/theme/default.typ` is LAYOUT
  LOGIC that consumes `chrome.*` (roles resolved to colours at render time), selected by
  `render pdf --variant <name>`. **OOXML consumer:** `tokens/gen/pandoc_template_profile.py` now emits
  the FLAT `template-profile.yaml` that `docstyle/style_postprocess.apply_template_profile` actually
  consumes (font / accent / body / margin_cm / page_*_cm), sourced from the SAME descriptor + variant --
  so a variant recolours the DOCX headings + table headers exactly as it does the typst chrome. This
  also fixed a latent bug: the old generator emitted a nested shape the post-processor's flat-key reader
  ignored, so the generated DOCX profile was dead config. A round-trip test drives the generated profile
  through `apply_template_profile` and asserts the resolved colour. One descriptor, both engines. 14 tests.
- **H3 - First-class semantic blocks (#33).** `[build]` **DONE:** `pdf/filters/semantic-blocks.lua`
  maps the fenced divs `::: signatures` / `::: attendance` / `::: statement` (each a plain bullet list
  of pipe-delimited fields) to typst function calls, rendered by `pdf/theme/blocks.typ`: a
  hyphenation-safe signature card grid (bold name, muted role, reserved signature + date space), a
  present/proxy/quorum attendance callout, and a typed ledger (heading/item/subtotal/total/balance/rule
  rows, right-aligned amounts). Styling derives from the palette + theme roles, so a brand/variant
  restyles the blocks with everything else. The filter is a no-op for documents that use none. 10
  tests (wiring + per-block filter output + full-render integration).
- **H4 - Data-bound statement tables (#34).** `[build]` **DONE:** `pdf/statement_data.py` lets a
  `::: {.statement data="finance.yaml"}` block source its rows from YAML or CSV and COMPUTE its
  subtotals (section sums), totals/balances (a safe `+ - * /` formula over subtotal ids, or the running
  sum of all items). A computed row may also STATE an amount; if it disagrees with the computed value to
  the cent, the render FAILS with a reconciliation error - removing the silent-transcription error
  class. `expand_markdown` turns the data-bound block into a plain #33 `::: statement` with computed,
  formatted amounts before pandoc, so the entire render path is reused; all computation lives in tested
  Python. 30 tests. (Amount formatting is data-stated here; H5 makes it a project `locale`.)
- **H5 - Locale-driven formatting (#35).** `[build]` **DONE:** `pdf/locale_fmt.py` + `render pdf
  --locale <code>` (nl-BE / fr-BE / en / en-GB / en-US). A locale drives the statement number
  separators + currency placement (so a data file need only state `currency`, or nothing), the typst
  hyphenation language (`set text(lang: ...)`), and long-date formatting (a `--date` given as ISO
  `YYYY-MM-DD` renders as e.g. `15 februari 2025` / `15 février 2025` / `15 February 2025`). Stdlib-only
  and deterministic (month names tabled, not from the platform locale db); an unknown locale fails fast,
  before any tool/render work; an explicit `format` key in statement data still overrides the locale.
  15 tests. Completes the Track H financial-document surface.
- **H6 - Rich cover / title-page model.** `[build]` the block model, `[imitate]` the carriers. The
  native cover today is `docstyle/style_postprocess.build_reference_cover`: strip banners, drop the
  duplicate title H1, ONE version/date line, relocate the TOC (verified: no metadata table, no body
  content, no image support); the typst path has only the H1 title block. A real consumer cover
  needed an info/metadata table, a multi-paragraph pitch/rationale section, a pulled-quote
  blockquote, and an EMBEDDED IMAGE before the document body, and was hand-rolled entirely outside
  renderfact (an f-string building raw pandoc markdown with custom Title/Subtitle style divs).
  Prior art says metadata-driven rich covers are a solved pattern per engine: **[imitate]** the
  Eisvogel pandoc-LaTeX template's titlepage variable family (`titlepage-logo`,
  `titlepage-background`, rule/color variables, all plain document metadata), Quarto's
  `title-block-banner` (banner covers incl. an image) with its `title-block.html` partial as the
  full-custom escape hatch, and the typst-universe cover conventions (`modern-technique-report`,
  `bookly`: a title-page FUNCTION taking title/subtitle/logo/background/metadata parameters).
  None transfer as a dependency (LaTeX-, HTML-, and typst-template-bound respectively), and none
  is engine-agnostic, which is the actual requirement here: **[build]** one declarative cover
  schema (frontmatter `cover:` block or a `::: cover` semantic block in the H3 family: info table,
  pitch paragraphs, pull quote, image slot) rendered by BOTH engines: a typst cover function in the
  theme (H2 roles style it, variants restyle it) and a generated cover section on the DOCX path
  replacing the fixed `build_reference_cover` shape. Cover content must pass through the projection
  engine like body content (a pitch section can carry clearance/audience marks). C7's
  content-skeleton axis later derives the cover SCHEMA VALUES from an imported branded template;
  this item owns the render-side model. NEXT.

---

## Track I - Render-as-a-service (API + studio UI)

The API (`api/app.py`) and reference UI predate Track H: they exposed contract introspection +
projection but could not render. This track makes the whole pipeline reachable over HTTP and turns the
UI into an authoring surface. Filed as issues #42-#46.

- **I1 - Render endpoint `POST /render/pdf` (#42).** `[build]` **DONE:** a `BinaryResponse` type +
  `POST /render/pdf` rendering markdown (inline, <=512 KB, or a jailed `source` path) to
  `application/pdf` or a first-page `image/png` preview, with the same options as `render pdf`
  (title/subtitle/org/date/variant/locale/paper/brand). The typst backend gained `fmt='png'` (first
  page via a zero-padded page template), `ppi`, and a `data_root` jail so statement `data=` paths stay
  under the server root (source mode) or the render temp dir (inline mode) - an untrusted document
  cannot read server files. Origin/Host guard + path jail + size cap apply. OpenAPI + `/docs` extended.
  12 tests (validation/guard always-on + tool-gated real renders incl. the sandbox-escape check).
- **I2 - Studio UI live preview (#45).** `[build]` **DONE (core):** `api/ui.py` now leads with a render
  studio - markdown editor + debounced live PNG preview (`POST /render/pdf?format=png`, embedded
  same-origin) + variant/locale controls + PDF download - over the whole Track H pipeline. Still one
  self-contained page, vanilla JS, no build. (Remaining #45/#46 polish: block-scaffold buttons, a live
  statement-reconciliation panel over a future `POST /statement/check`, a doctor status badge.)
- **I2b - Render endpoint `POST /render/docx`.** `[build]` **DONE:** the DOCX peer of `/render/pdf`,
  wrapping `container/render-doc.sh` via `docstyle/docx_pipeline.render_docx()`. Markdown (inline or a
  jailed `source`) -> a styled DOCX with the generic house style; `profile` / `name` / `project` +
  `profiles` options. The source is rendered from a temp COPY so the pipeline's provenance-uid embed
  never mutates a server file (a test asserts the original is byte-identical); `RESOURCE_PATH` keeps
  relative images resolving. Studio gains a Download DOCX button. 9 tests.
- **I3 - `POST /statement/check` (#43).** `[build]` **DONE:** reconcile a statement spec (a YAML/JSON
  `data` string, a `spec` object, or a jailed `source` path) over HTTP with no render - computed rows
  out, or a 400 with the reconciliation error. An optional `locale` supplies default formatting. Lets
  CI gate financial correctness without typst.
- **I4 - Capability-discovery endpoints (#44).** `[build]` **DONE:** `GET /doctor` (tool availability +
  `render_pdf_ready`), `GET /locales` (codes + sample number/date), `GET /theme/variants` (from
  `brand.yaml`). The studio data-drives its variant/locale dropdowns and a backend-readiness badge off
  these.
- **I5 - Studio polish (#46).** `[build]` **DONE:** block-scaffold buttons (insert `::: attendance` /
  `statement` / `signatures` at the cursor), a live statement-reconciliation panel over
  `/statement/check`, a PDF-backend-ready badge, and data-driven variant/locale selects. 12 service +
  9 render API tests.

## Track J - Project workspace (registry, template library, live render, diff, auto-choose)

A NEW track (not a continuation of the Track E/I API surface or the 5.x editor thread), covering the
operator-facing project-workspace UI/UX: start a project, load a template, browse previous projects,
live-render output, live-edit input, see diffs, choose audience/doc-type/diagram-scaffolding manually
or let the app auto-choose. Full design in
`docs/2026-07-07-ui-ux-project-workspace-design-spike.md`; chunks numbered 6.x per that spike's
section 8 (placement rationale: most of this track is registry/library/diff/render plumbing, not
editor work, so it does not inherit the Track F freeze below -- only the final integration chunk 6.11
does). Buildable-now unless marked GATED; sequencing note: 6.1-6.6 are a coherent releasable arc
(workspace without any LLM and without the editor).

- **6.1 - Registry core (read side).** `[build]` **DONE:** `api/store.py` -- manifest schema + parser
  (fail-closed on unknown top-level keys, `x-skin` extension namespace, JSON-safe date coercion),
  depth-<=2 projects-root scan with an mtime cache, `.renderfact/renders.jsonl` ledger-tail reader,
  git facts via subprocess (no GitPython). `api/app.py` gains `GET /projects` and
  `GET /projects/{name}` (query folded into `body` so `?limit=` works over both real WSGI and the
  in-process test driver). CLI: `render projects list|show` (D9: CLI-proven before UI). 20 tests.
- **6.2 - Project creation + config mutation.** `[build]` **DONE:** `POST /projects` (slug validation,
  refuse-existing, scaffold the directory: manifest + a seeded source -- a real `templates/*.md` file
  when `template` names one, else a minimal stub -- + a `profiles.yaml` skeleton copied from
  `projection/profiles-example.yaml` + `.gitignore`; `git init` if not already inside a work tree;
  initial commit). `PUT /projects/{name}/config` mutates the mutable manifest fields
  (`default_profile`, `template`, `doc_type`, `diagram_scaffold`, `render`) with the same optimistic-
  concurrency shape as the (specified, not yet built) editor: request carries `base_hash`, 409 on
  staleness, one commit per diff-carrying change, required non-empty commit message
  (`sanitize_commit_message`: length cap + control-character stripping; a no-diff patch is a git-free
  no-op). These are the FIRST routes to enforce the full D15 mutating-endpoint guard set: a per-
  session CSRF token from `GET /session` (checked via `_require_csrf`, previously issued but checked
  by nothing), plus the existing Origin/Sec-Fetch-Site + Host guards extended from POST-only to also
  cover PUT. `GET /projects/{name}` now also returns `manifest_hash`, the concurrency token. CLI twin:
  `render projects new`. 24 tests (creation, template seeding incl. a real built-in template, config
  mutation, stale-hash conflict, immutable-key rejection, empty-message rejection, no-diff no-op,
  non-git-tree refusal, HTTP CSRF/cross-origin/409 coverage).
- **6.3 - Template library.** `[build]` **DONE:** `api/templates.py` -- a new directory convention,
  `<library-root>/<name>/` (`template.yaml` metadata + optional `scaffold.md` + optional
  `template-profile.yaml` + optional `reference.docx`), deliberately distinct from the pre-existing
  flat `templates/*.md` genre pack (untouched; still what `store.py`'s project-creation seed reads by
  filename). Two roots merge: built-in (`templates/library/`, ships `plain-report` + `plain-deck`) and
  a custom root (operator imports); a custom entry shadows a built-in of the same name. `GET
  /templates` (list, `[imitate]` the established I5 data-driven-select shape) + `GET /templates/{name}`
  (metadata + scaffold + profile). `POST /templates/import` `[adopt]`s the shipped `import-template`
  (C7) pipeline directly -- calls its `main()` in-process (stdout captured) rather than reimplementing
  derivation, including its `--check` idempotency gate (a DRIFT there does not delete the entry: the
  derivation succeeded, the gate is validation on top, reported via `idempotency_check_passed`).
  D15-hardened (writes into the library): CSRF required, same Origin/Host guards. CLI: `render
  templates list|show` (`new`/import stays API-only -- DOCX upload has no CLI-shaped one-shot form
  here). 18 tests.
- **6.4 - Profile discovery.** `[build]` **DONE:** `GET /projects/{name}/profiles` (a project's own
  `profiles.yaml`, resolved via its manifest + jailed to the project directory) and `GET
  /profiles?path=` (the same shape for any jailed path -- the wizard's profile-source step, before a
  project exists). Both reuse `projector.load_config` exactly (same fail-closed ladder validation a
  real render would hit) and resolve OQ11 as names+ranks: each profile's name, `clearance_ceiling` +
  its rank in the ladder, `releasable_to` + rank, `lang`, `audience`, `disclosure` -- not the raw
  ladder-keyed governance dict, so a private skin's full clearance vocabulary isn't handed out
  wholesale even on loopback. 7 tests.
- **6.5 - Dashboard + wizard UI (manual path only).** `[build]` **DONE:** the static-asset decision
  (D18) lands here -- `api/static/` (common.js + one CSS/JS pair per screen) served by an allowlisted
  `GET /ui/static/{name}` (cache-control headers, gated behind `--enable-ui`); the HTML shells stay
  small Python strings matching `render_docs_html`'s pattern. Projects Dashboard (`GET /ui/projects`:
  project cards from `GET /projects`, doctor badge); New Project wizard (`GET /ui/projects/new`:
  MANUAL template picker from `GET /templates` + doc_type + diagram_scaffold selects, create goes
  through the D15-hardened `POST /projects`, lands on the Dashboard -- the Project Workspace it will
  redirect to instead is chunk 6.6); Template Library (`GET /ui/templates`: cards + a `POST
  /templates/import` form). Auto mode is deferred to 6.7, so none of this ships any LLM machinery. 10
  new server-side tests (route gating, static-asset allowlist/content-type/cache-header, shell
  sanity); the client JS itself was verified with a real headless-browser click-through (full
  create-project flow end to end, zero console errors) rather than unit-tested, matching this repo's
  existing convention for embedded/served JS.
- **6.6 - Workspace shell + Render tab + History tab.** `[build]`. Project workspace page, render
  config panel (consumes 6.4), project-then-render flow, ledger writes, artifact links, `/doctor`-
  driven degradation. Interim whole-document Edit tab (studio pattern bound to project source, whole-
  file hash-guarded save). NEXT.
- **6.7 - Auto-choose.** `[build]` for the deterministic scorer + sub-signals, gated via
  `contracts/confidence_gate.py` (Track G's G4); escalation via the D8 dual-mode contract machinery
  `[imitate]` aider's clipboard-watch UX per the D8 spike. Telemetry log (G2 pattern). NEXT.
- **6.8 - Diff view, source mode.** `[adopt]` git via subprocess, `[build]` the hunk-JSON endpoint +
  colorizer UI. Depends only on 6.1/6.6. Also the natural home for #70's remaining GUI ask (a
  reconcile view over `reingest --json` output: comments, tracked changes, safe/manual split as
  reviewable hunks) once chunk 4.6's merge gives it an apply path; same endpoint shape, different
  hunk source. NEXT.
- **6.9 - Studio-workspace reconciliation polish.** `[build]`. Landing-page decision, scratchpad-to-
  project hand-off, keyboard-nav pass over all Track J screens. NEXT.
- **6.10 - Projected-diff mode.** `[build]`. `mode=projected`, difflib over two projections. NEXT.
- **6.11 - Three-pane editor integration.** GATED behind Track F (release readiness, D13) and behind
  the editor thread's own chunk 5.8. Mounts the D12 editor into the workspace Edit tab; the only
  chunk in this track that touches the editor contract.

---

## Track J - Sendable email output (`.eml`, plain-text signature block)

Filed as issue #95: closing the gap where the actual deliverable is an email rather than a rendered
document. Core-vs-adapter split (the same pattern issue #68's diagram-archetype work used): the
general core (`.eml`, plain text, stdlib-only) ships here; the narrower, heavier adapters (a binary
`.msg`/MAPI writer, mail-client compose-window automation) are named follow-ups, not built. See
`docs/DECISIONS.md` D22 for the full reasoning.

- **J1 - `.eml` backend with a skin signature block (#95).** `[build]` **DONE:**
  `mail/eml_backend.py`, wired as `render eml <src> [-o out.eml] [--signature <yaml>] [--recipient R]
  [--subject S] [--sender F]`. Markdown -> pandoc's plain-text writer (the shared
  `pandoc_markdown.MARKDOWN_FROM` `--from`, `--reference-links` so a link's URL survives instead of
  being silently dropped) -> an optional skin `signature.yaml` (freeform `lines:`, the sig-dash `-- `
  delimiter, PNG `images:` as inline `multipart/mixed` parts) -> a stdlib `email.message.EmailMessage`
  serialized to a valid RFC822 `.eml`. Frontmatter `recipient:`/`to:` and `subject:`/`title:` map to
  `To:`/`Subject:`; a missing recipient is advisory (a WARNING, no `To:` header), not fatal. `Date:`
  and a deterministic, non-host-leaking `Message-ID:` are stamped on every render. Pandoc discovery
  reuses `pdf/typst_backend.find_pandoc()` directly. 40 tests (unit + real end-to-end pandoc renders,
  parsed back with the stdlib `email` parser).
- **J2 - `.msg` (MAPI) writer.** `[build]` NEXT, not started. Deliberately deferred (D22): `.msg` is a
  binary Compound File Binary / MAPI property-stream format unrelated to the OOXML machinery
  `docstyle/style_postprocess.py` already has, and real-world producers lean on Windows COM automation
  or a native MAPI library, neither portable nor CI-testable the way this repo's other backends are.
  Worth doing only if a consumer's mail client genuinely cannot import `.eml` (rare in practice).
- **J3 - Mail-client compose-window automation.** `[build]` NEXT, not started. Deliberately deferred
  (D22): platform-specific (Outlook COM on Windows, AppleScript on macOS, no Linux equivalent),
  untestable in a cross-platform CI matrix, and couples the toolchain to a running, licensed desktop
  application, a different kind of dependency than anything else here. `.eml` already solves
  delivery (one double-click/import away from a compose window in every mail client tested).
- **J4 - MIME-multipart HTML signature.** `[build]` NEXT, not started. v1 (J1) ships plain text plus
  inline PNG image parts (a logo genuinely travels embedded in the `.eml`), but no HTML: a styled
  signature (coloured text, a clickable button, an inline-`cid:`-referenced logo sitting inside
  markup) needs a `multipart/alternative` + `multipart/related` structure and an HTML-authoring
  surface for the signature block this repo has no existing pattern for yet.
- **J5 - `.eml` reconciliation / reingest path.** `[build]` NEXT, not started. The issue's own framing
  named the DOCX `reingest` round-trip as the precedent an email deliverable currently lacks; J1 closes
  the FORWARD direction (source -> sendable email) but does not touch round-trip. A real reconciliation
  path (sent `.eml` back to a source diff, the way `roundtrip/reingest.py` does for an edited DOCX)
  is real, separable follow-up work, not a natural extension of J1's render-only scope.

---

## Open questions carried forward

- **OQ1 - schema-driven gate chain vs bespoke Python.** Should the gate chain move to a formally
  schematized validation layer (studying CALM's JSON meta-schema)? Deferrable: B3 adopts its
  dependencies regardless. It bites only when the first bespoke structural check would be written.
- **OQ3 - does the DTCG token-aliasing syntax transfer to governance metadata?** Does the alias syntax
  carry cleanly to audience / clearance / disclosure profiles, or does that layer need a materially
  different schema? Resolve before finalizing the clearance-profile schema; the visual-token schema
  proceeds regardless.
- **OQ4 - hermetic-container vs native-host install tension.** How do comparable docs-as-code
  toolchains handle this in their install tooling? No comparable pattern has surfaced yet; a targeted
  follow-up against their install docs precedes building the native install helper.
- **OQ7 - versioning policy.** Adopt semver tags as the primary `tool_version` source (commit hash as
  the dev-build fallback), and keep a CHANGELOG plus a deprecation policy from v0.1.0 onward.
- **OQ18 - source-authority demotion (from #70).** When a reviewer's hand-edits are predominantly
  FORMATTING (widths, breaks, spacing), does the render stay reproducible-from-source (in which case
  every such delta needs a source-side carrier, the 4.4c direction), or is there a supported mode
  where the hand-edited artifact becomes the new canonical file and the source is demoted to a
  content-only mirror kept for diffing and traceability? Today the toolchain implicitly assumes
  source-authoritative forever; the demotion route is unspecified (what happens to provenance, to
  the next render, to reingest verdicts against a demoted source). No strong prior art found either
  way; resolve before 4.6, because the three-way merge must know which side is allowed to win a
  formatting conflict.
