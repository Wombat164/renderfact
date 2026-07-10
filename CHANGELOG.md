# Changelog

Format: Keep a Changelog. Versioning: semver; v0.1.0 is tagged on the fresh
public history at the flip (pre-publish commits live in the private archive;
their hashes do not survive the history rewrite, see the publish protocol).
`tool_version` in embedded provenance follows `git describe --tags` and picks
up real tags from v0.1.0 onward, with bare-commit fallback for dev builds.

## [Unreleased]

### Added

- **`render qa tables` slack signal** (issue #90): the column-geometry scan reported only a single
  squeeze-pressure score per table (`squeezed-col`), and any column with 5% or less of a table's
  content share was excluded from that scoring entirely, so a genuinely tiny but over-allocated
  column (a row-number/ordinal column given generous width) never surfaced as a problem. `qa tables`
  now also reports a complementary `slack` ratio and `wasteful-col` (the inverse relationship,
  `wshare / max(cshare, floor)`, scored for every column with its own floor so proportionally-sized
  small columns are not flagged), printed alongside the existing pressure line, and both signals now
  drive which tables surface in the ranked top-N output.
- **`layered-stack` diagram archetype** (issue #68, FR1-FR3): a new diagram archetype for an ordered
  technology stack with an explicit, visually distinct interface boundary between adjacent layers, and
  support for N parallel realizing chains laid out side by side under one shared interface (N=1 is the
  degenerate default). Authored as a plain, hand-written renderfact YAML source - no dependency on
  Archi or any ArchiMate file. `render diagram <source.yaml>` dispatches to it by content-sniff (a
  `.yaml`/`.yml` file whose top level carries `archetype: layered-stack`), generates D2 styled via the
  existing brand-token system, and renders through the existing D2 -> svg -> pdf pipeline unchanged.
  Element counts are checked against `lint/element_budget.py`'s existing view-tier budgets before any
  D2 is generated, failing closed with an actionable message when a model needs splitting into multiple
  views. New: `lint/layered_stack.py`, `demo/diagrams/layered-stack-example.yaml`,
  `tests/test_layered_stack_archetype.py`. The issue's own optional ArchiMate Exchange-XML adapter
  (FR4-FR7) is deliberately out of scope for this change; see the follow-up issue.
- **PlainLanguage Vale style + `plainlang` gate stage** (issue #76): `render gate --stages vale` now
  also carries a reader-facing plain-language/KISS check, distinct from the existing `AiTells`
  authorial-tell detection. `demo/skin/vale/styles/PlainLanguage/`: `SentenceLength` (tunable
  word-count threshold, suggests a split at a coordinating conjunction or semicolon) and
  `NominalisationDensity` (English `-tion`/`-ance`/`-ment` suffix density per paragraph, suggests a
  verb-first rewrite); both `level: warning`, advisory rather than blocking. A third check
  (repeated multi-word comparator/transition phrase across a document) is not expressible as a Vale
  rule (the DSL cannot search for a pattern it does not know in advance) and ships instead as
  `docstyle/plain_language.py`, wired into `render gate` as a new `plainlang` stage; unlike the
  other gate stages this one is report-only by default (`--plainlang-fail-on-hits` opts in).
- **`render docstyle`** (issue #74): the house-style DOCX post-processor's standalone CLI surface
  (`--profile`, `--template-profile`, `--table-widths`, `--cover-version`, `--cover-date`) is now a
  documented top-level subcommand, in addition to being invoked internally by `render docx`. Fixes the
  discoverability gap where `apply_table_widths()` and its sibling flags were only findable by reading
  `docstyle/style_postprocess.py` source end to end.
- **Blocking QC hook** (issue #71): `render-doc.sh`'s pre-render `QC_SCRIPT` hook (`--qc`) stays
  advisory-only by default; `QC_BLOCKING=1` or `--qc-blocking` now makes a non-zero `QC_SCRIPT` exit
  stop the render instead of just printing a warning.
- **`POSTRENDER_GATE_SCRIPT` hook** (issue #71): a new post-render hook, called with the finished
  `<docx>` path (`--postrender-gate`), after render and before the completion summary. Defaults to
  BLOCKING, the opposite of `QC_SCRIPT`'s default, because its purpose is content-safety ("does the
  artifact contain content it must never contain"); `POSTRENDER_GATE_ADVISORY=1` opts back into
  advisory-only. See `docs/DECISIONS.md` D18 for the reasoning.
- **`gates/content_scan.py`**: the generic reference implementation of the "open docx with
  python-docx, regex over every paragraph and every table cell, exit 1 on hit" content-safety gate
  pattern. Ships with no default pattern; the regex is a required parameter (`--pattern` /
  `--pattern-file`, or `RENDERFACT_GATE_PATTERN` / `RENDERFACT_GATE_PATTERN_FILE` for zero-arg hook
  invocation), keeping the public core domain-neutral.
- **Purpose annotations and dossier role (#77, D19)**: an annotative-only authoring convention, never
  a blocking gate. `<!-- PURPOSE: ... -->` HTML comments stated above a paragraph or heading record
  why it exists, verified empirically to be a no-op on both the DOCX and typst-PDF render paths
  (`tests/test_purpose_annotations.py`). A freeform `dossier_role:` frontmatter field
  (`roundtrip/dossier_role.py`) states what a document uniquely contributes relative to its siblings
  in a dossier. `render qa purpose <source.md>` is an optional, advisory-only lint pass flagging a
  prominent block with no purpose comment above it; report-only, never fails.

### Fixed

- **Bracket wikilinks silently lost their display text (#69)**: `pdf/typst_backend.py` (the PDF path)
  built its pandoc `--from` value without `wikilinks_title_after_pipe`, so `[[target|Display Text]]`
  was read as literal punctuation, not a `Link` node, while `container/render-doc.sh` (the DOCX path)
  had the extension. Both paths now build `--from` from one shared constant,
  `pandoc_markdown.MARKDOWN_FROM`, so the extension cannot drop out of one sibling script while
  staying in another.
- **`render reingest` text-delta false positives (#72)**: pandoc-specific structural syntax (fenced-div
  `::: {...}` / `:::` lines, raw-attribute OOXML blocks such as a manual page break's ` ```{=openxml}
  ... ``` `, and the blockquote `> ` marker) never renders as literal text in the DOCX, but the `## 4.
  Text delta` / `## 5. Fast-forward plan` comparison used to treat their absence as a reviewer deletion.
  These are now stripped from the canonical-markdown side before the diff, at the same normalization
  tier as the existing list-bullet/auto-numbered-heading stripping. Ordered-list markers (`1.`, `2.`,
  ...) were already handled correctly by the fast-forward planner and are unaffected. Also adds a
  repeatable `render reingest --strip-pattern <regex>` flag so a project can strip its own
  structural-noise conventions (e.g. a custom heading-anchor sigil) without renderfact special-casing them.

## [0.4.0] - 2026-07-04

Completes render-as-a-service and rounds out onboarding. All additive over 0.3.0.

### Added

- **`POST /render/docx`**: the DOCX peer of `/render/pdf`, completing render-as-a-service. Markdown
  (inline or a jailed `source`) renders to a styled DOCX via the render-doc.sh pipeline, with
  `profile` / `name` / `project` + `profiles` options. The source is rendered from a temp copy so the
  pipeline's provenance-uid embed never mutates a server file. The studio gains a Download DOCX button.
- **Track H demo showcase**: `demo/source/agm-minutes.md` (Meridian AGM minutes) renders a branded
  governance/financial PDF exercising the attendance callout, a data-bound + reconciled statement, and
  the signature grid; `demo/render-demo.sh` gains a PDF step.

### Fixed

- Semantic-block UI labels (signature / date) were hard-coded Dutch even on non-Dutch documents; they
  now follow the render `--locale` (English default, `Handtekening`/`Datum` for `nl`).
- The getting-started tutorial referenced a non-existent demo file and a CLI flag that does not exist;
  rewritten around the real demo with a branded-PDF walkthrough.

## [0.3.0] - 2026-07-04

PDF-backend hardening and the governed-render path. All additive over 0.2.0.

### Added

- **Images in PDFs**: relative image paths (`![logo](logo.png)`, subfolders included) are resolved
  against the source directory and staged into the build so typst renders them; remote URLs pass
  through. Over the API an image resolving outside the server root is not staged (sandbox).
- **Governed PDFs** (`render pdf --project <profile> --profiles <config>`): compose the audience /
  clearance projection engine with the typst backend, so one full-candor source renders one branded
  PDF per profile. `--project all` renders every profile in one run (`<stem>-<profile>.pdf`). Also
  wired into `POST /render/pdf`.
- **Brand fonts** (`render pdf --font-path <dir>`, repeatable; env `RENDERFACT_FONT_PATH`): a brand can
  ship its own font for typst to use instead of relying on host install. API `font_paths` are jailed
  under the server root.
- **Multi-page studio preview**: `POST /render/pdf?format=png` takes a 1-indexed `page` and returns an
  `X-Total-Pages` header; the studio UI gains prev/next page navigation.
- **Descriptor-driven, variant-aware semantic-block styling**: the `::: attendance` callout (fill /
  border roles) and `::: statement` ledger (rule / heading roles) now take their colours from the
  `theme` descriptor, so a variant can restyle them (the built-in `financial` variant restyles the
  ledger section headings).

## [0.2.0] - 2026-07-04

Layout-native PDF, financial/governance documents, a consistent fuzzy-gated LLM pipeline, and
render-as-a-service. All additive over 0.1.0.

### Added

- **Layout-native PDF backend** (`render pdf`): markdown to a branded, layout-precise A4 PDF via
  pandoc's typst writer + a brand-token-driven theme + typst - a peer of the DOCX path, no OOXML and
  no LibreOffice. First-page PNG previews, `--paper`, and metadata (title/subtitle/org/date).
- **Engine-agnostic theme descriptor**: `brand.yaml [theme]` (page margins, header/footer slots,
  heading/title/rule colour ROLES) with a `base` + inheritable `variants` (built-in `financial`).
  Drives BOTH engines - the typst chrome (`chrome.typ`) and the DOCX house-style
  (`template-profile.yaml`); `render pdf --variant <name>`.
- **First-class semantic blocks** (fenced divs, rendered by the theme): `::: signatures` (hyphenation-
  safe signature card grid), `::: attendance` (present/proxy/quorum callout), `::: statement` (typed
  ledger with right-aligned amounts + rule lines).
- **Data-bound, self-reconciling statements**: a `::: {.statement data="finance.yaml"}` sources rows
  from YAML/CSV and COMPUTES subtotals/totals/balances (safe `+ - * /` formulas over subtotal ids); a
  stated total that diverges from its computed value FAILS the render - removing the silent-
  transcription error class from financial documents.
- **Project locale** (`render pdf --locale nl-BE|fr-BE|en|...`): number separators + currency
  placement, hyphenation language, and localized long dates (raw ISO in -> `15 februari 2025` out).
- **Fuzzy-gate LLM pipeline (D16)**: every LLM-touching step runs a deterministic result first, scores
  confidence, and escalates only past a threshold. Shared `confidence_gate` primitive, opt-in gate
  telemetry (`render gate-stats`), named confidence sub-signals, and an optional off-by-default
  direct-API escalation channel (D17, VLM/LLM) alongside the harness + copy-paste channels. Applied to
  vision-review, decision-capture, and the new document `contextualize` step.
- **Render-as-a-service HTTP API**: `POST /render/pdf` (PDF or PNG bytes, inline or jailed source),
  `POST /statement/check` (reconcile without rendering), and discovery endpoints `GET /doctor` /
  `/locales` / `/theme/variants`. The reference **studio** UI (`--enable-ui`) gains a live PNG preview,
  variant/locale controls, block-scaffold buttons, and a live reconciliation panel.

### Fixed

- `render <mode> --help` for the docx mode printed `source not found: --help` instead of usage.
- The generated DOCX `template-profile.yaml` used a nested shape the house-style post-processor's
  flat-key reader ignored - so brand/theme values never reached the DOCX render (dead config). Now
  emitted in the consumed flat schema.

### Security

- The API render/statement endpoints jail statement `data=` paths under the server root (source mode)
  or the render temp dir (inline mode); an untrusted inline document cannot read server files. Inline
  source size cap, plus the existing loopback bind + Host/Origin guard + rate limit.
- The direct-API channel's `api_key` is env-only and never written to a config file or any log line.

## [0.1.0] - 2026-07-04

### Capability set

- **Projection engine** (`render project`): one full-candor markdown source with profiled
  fenced-div blocks projects into one governed render per audience/clearance/disclosure
  profile; consumer-defined ladders; preprocessor-level exclusion; fail-closed on unknown
  labels; per-profile header-stamp suppression.
- **DOCX pipeline** (`render docx`): annotated markdown to styled DOCX (+ optional PDF) with a
  consumer-free shell: every consumer piece is env-configured, optional steps skip honestly;
  generic house style + field-based heading numbering ship as defaults (docstyle/).
- **Diagram pipeline** (`render diagram`): mermaid/d2 rendering with pre-render linting and
  visual-QA metrics (lint/).
- **Brand tokens** (`render tokens`): brand.yaml to per-engine themes (mermaid JSON, marp CSS,
  pandoc template profile, typst tokens).
- **D8 dual-mode LLM steps**: `render init-ai` (installs step instructions into the user's own
  assistant) and `render copy-paste` (no-harness fallback), one identical schema per step.
- **Provenance** (`render provenance embed|extract|adopt|retarget`): hidden source
  identity/version stamping across DOCX/XLSX/PPTX. The projection-aware POLICY is decided (full
  internal, stripped external) but the strip mechanism is NOT implemented yet: treat every
  externally-bound artifact as manually-scrub-required until it ships (top of the v0.2 queue).
- **Template import** (`render import-template`): derive a template profile (theme colors, fonts,
  page geometry) from a branded corporate DOCX, with template provenance in the derived config
  and a `--check` idempotency gate that probe-renders and diffs the derived properties.
- **Post-render QA gate** (`render qa`): leak scan on rendered text, table geometry pressure,
  overweight paragraphs, figure contrast pre-filter; probes config-driven; CI-gateable.
- **HTTP API + thin reference UI** (`render serve`): stdlib server exposing the step contracts
  and projection; loopback-only posture with anti-rebinding, origin checks, path jail, rate
  limiting; opt-in /ui; /openapi.json + /docs.
- **Demo**: a fictional railway-operator tender dossier exercising every projection gate, with
  profiles, brand skin, and a runner.
- **Container + native modes**: pinned-engine OCI image (tools.lock + verify-pins) and
  native-host execution.

### Roadmap formats not yet wired (annotated, not claimed)

Poster mode, deck mode, and the PDF/UA typst path are advertised directions with working
consumer-side precedents, not shipped modes; they land in v0.2.x.
