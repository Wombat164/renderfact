# Changelog

Format: Keep a Changelog. Versioning: semver; v0.1.0 is tagged on the fresh
public history at the flip (pre-publish commits live in the private archive;
their hashes do not survive the history rewrite, see the publish protocol).
`tool_version` in embedded provenance follows `git describe --tags` and picks
up real tags from v0.1.0 onward, with bare-commit fallback for dev builds.

## [Unreleased]

## [0.5.0] - 2026-07-11

### Fixed

- **Demo dossier now actually passes its own skin's writing doctrine**: `tests/test_gates.py::
  test_demo_source_passes_its_own_skin_rules` (the dogfood invariant the demo README claims) was
  failing. Root cause was several genuine AiTells error-level findings in
  `demo/source/signalling-it-refresh.md` itself, not a dictionary gap: a colon-then-capitalized-word
  construction in the frontmatter title (`ColonUsage`), four instances of a comma-and/semicolon
  enumeration pattern the AI-tell heuristics treat as a giveaway (`VerbTricolon`, matched regardless
  of real part of speech), a formal-register word (`FormalRegister`: "implementation"), a deletable
  transition word (`FormalTransitions`: "accordingly"), and an empty modifier (`EmptyPadding`: "named
  accounts"). Fixed by rewriting the affected passages (several inline three-item enumerations became
  proper bullet lists, which also reads better) rather than weakening the rules or the fixture's
  content otherwise. Separately, `demo/skin/vale/vale.ini` gained a `TokenIgnores` entry for the
  fixture's own fictional proper nouns and established British-spelling technical terms, and a
  `BlockIgnores` pattern that skips the fixture's `lang="fr"` fenced-div block from `Vale.Spelling`
  entirely (real French, not a typo) instead of listing French words one at a time: `Vale.Spelling` is
  warning-level and was never the blocking cause, but the noise it produced obscured the real,
  blocking findings during triage.
- **Custom-style paragraphs now keep their own font/size instead of the house-style default** (issue
  #98, D21): `docstyle/style_postprocess.py`'s body-styling pass in `main()` called `set_para_font()`
  unconditionally on every non-Title/Subtitle/Heading paragraph, including one carrying a custom Word
  style (e.g. via a pandoc `::: {custom-style="X"} ... :::` fenced div) that already defines its own
  font and size in `reference.docx`'s `styles.xml`. The paragraph got the right `w:pStyle` but a
  direct-formatting run-level override shadowed the style's own definition. The default now respects a
  custom style's own font/size (new `is_custom_style_paragraph()` gate); the old blanket-override
  behaviour is available as an explicit opt-in via `--override-custom-style-fonts` (CLI, standalone
  `render docstyle`) or `override_custom_style_fonts: true` (`--template-profile` yaml). Built-in
  categories (Title/Subtitle/Heading 1-4) and the generic default-body case are unaffected: they still
  get the house font/size unconditionally, as before.

### Added

- **`render reingest --contextualize` chaining + multi-round narrative for `render contextualize`**
  (Track G8): a consumer session hand-wrote prose changelog entries for every back-ported reviewer
  edit without ever invoking `render contextualize`, the exact job G6 shipped for -- WORKFLOW
  invisibility, not render-help invisibility, plus one real functional gap. `render reingest` now
  prints a next-command hint whenever a run has manual-review residue or a DIVERGED verdict; new
  `--contextualize` flag chains the two commands in one process (`reingest.py` lazily imports
  `contextualize.py` at call time, never at module load, since `contextualize.py` already imports
  FROM `reingest.py` at its own load time), skipping the call entirely when nothing needs a decision
  rather than writing a redundant "nothing to narrate" entry. `contextualize.parse_prior_rounds()`
  mechanically parses an existing decision log (zero LLM cost) for entries belonging to the same
  source; `assemble_input()` gains optional `round`/`prior_rounds` fields, fully backward compatible
  (every existing caller still gets round 1, no prior context), reaching both the deterministic
  template (a mechanical "Round N:" title prefix, never applied to an escalated entry's
  author-written title) and the escalation prompt (told to continue the narrative referencing prior
  rounds, not repeat them). 14 new tests across `tests/test_reingest.py` (5) and
  `tests/test_contextualize.py` (9).
- **ArchiMate Exchange-XML adapter for the `layered-stack` diagram archetype** (issue #86, FR4-FR6
  of the #68 follow-up): `lint/archimate_exchange.py` transforms an Open Group ArchiMate Model
  Exchange File into the archetype's existing `StackModel` shape (stdlib `xml.etree.ElementTree`
  only, zero new dependency; Archi itself never enters renderfact's toolchain), reusing
  `render_d2()`/`check_element_budget()` completely unchanged. A fixed allowlist maps ArchiMate
  element types (Node/Device/SystemSoftware/ApplicationComponent-family -> Layer,
  TechnologyInterface/ApplicationInterface -> Interface) onto the archetype's roles; any element
  type outside the allowlist fails closed (FR5), naming the unsupported type and element rather than
  silently dropping content. `render diagram <model.xml>` recognizes an Exchange File by
  content-sniff (FR6), the same idiom the plain-YAML `.yaml`/`.yml` path already uses. Two
  deliberate v1 scope decisions, documented in the module rather than silently guessed around: stack
  order is the Exchange File's own `<elements>` document order (inferring vertical order from
  ArchiMate relationship topology is a separate, genuinely ambiguous problem); N-parallel-chain
  auto-detection from Serving/Realization relationships is not built (every element renders as a
  plain Layer/Interface, never a ChainsBlock). FR7 (fast re-render on a re-exported file) remains a
  separate stretch item. 20 new tests in `tests/test_archimate_exchange.py`: sniff (valid/unrelated/
  garbage/missing-file/non-ArchiMate-`<model>`), parsing + type mapping + document order, label
  fallback, fail-closed on an unsupported type/duplicate id/missing or empty `<elements>`/non-model
  root/malformed XML, D2 emission + NFR6 budget enforcement, and `lint/render.py`'s new `.xml`
  dispatch branch (skip-not-crash on non-ArchiMate XML, reject on an unsupported element, an
  end-to-end SVG render skip-guarded on the D2 CLI).
- **`import-template --guidance-doc`: mechanical structural scan of a template's accompanying
  style/usage guide** (issue #100): a branded template often ships alongside a SEPARATE document (a
  policy/methodology paper explaining what each section is for, what's out of scope, how it fits the
  surrounding process) that `import-template` previously had no awareness of, leaving that
  authoring-doctrine mining as a fully manual, easy-to-forget step done after the fact. New
  `--guidance-doc <path>` (`.docx`/`.md`/`.markdown`/`.txt`) runs `scan_guidance_doc()`: counts
  section headings and body paragraphs and previews the heading text, printed back as a pointer
  toward hand-seeding `editorial-doctrine.yaml` (issue #84's concept, not yet built) — deliberately
  not automated extraction, a judgment-heavy summarization task left to the operator. Omitting the
  flag prints a one-line reminder (not a blocking stdin prompt: this CLI has no other interactive
  input, and a prompt would hang CI/scripted runs) at the one moment an operator has both artifacts
  in hand and is thinking about this template. New tests in `tests/test_template_import.py` (10
  cases: `.docx`/`.md`/`.txt` scanning, heading-preview truncation, unsupported-extension error,
  report formatting, and three CLI-integration paths).
- **`render eml`: plain-text sendable email output with a skin signature block** (issue #95): closes
  the gap where the actual deliverable is an email, not a rendered document (previously bridged by
  hand: copy the rendered body into a mail client, re-add the signature, with no reconciliation path
  back to source the way DOCX has `reingest`). New `mail/eml_backend.py`, wired as `render eml <src>
  [-o out.eml] [--signature <yaml>] [--recipient R] [--subject S] [--sender F]`: markdown -> pandoc's
  plain-text writer (the shared `pandoc_markdown.MARKDOWN_FROM`, `--reference-links` so a link's URL
  survives instead of being dropped) -> an optional skin `signature.yaml` (freeform `lines:`, the
  sig-dash `-- ` delimiter, PNG `images:` as inline `multipart/mixed` parts) -> a valid RFC822 `.eml`
  via the stdlib `email` module. Frontmatter `recipient:`/`to:` and `subject:`/`title:` map to
  `To:`/`Subject:`; a missing recipient is advisory (a WARNING, no `To:` header), not fatal. New:
  `mail/eml_backend.py`, `mail/signature-example.yaml` (entirely fictional example data),
  `tests/test_eml_backend.py` (40 tests). A `.msg`/MAPI writer and mail-client compose-window
  automation are deliberately out of scope for this change (the issue's own two named alternatives to
  `.eml`); see `docs/DECISIONS.md` D22 and `docs/ROADMAP.md` Track J for the reasoning and the named
  follow-ups.
- **`import-template` per-style font derivation** (issue #97): the derived `template-profile.yaml`
  carried a single global `font` key, which structurally cannot represent a source template that
  defines distinct fonts on distinct paragraph styles (its `styles.xml` has multiple `w:style`
  definitions, each with its own `w:rPr/w:rFonts`). `import-template` now also walks EVERY paragraph
  style's `w:rPr/w:rFonts` (one level of `basedOn` fallback, same as the existing Normal/Heading
  derivation) and emits a `styles:` block in the derived profile carrying only the GENUINE overrides:
  a style whose resolved font differs from the derived global `font`. A style that resolves to the
  same font as the global default is left out, so the profile stays minimal and a template that only
  ever uses one font still derives an empty block (additive, no change to existing output). The
  consumer side, `docstyle/style_postprocess.py`'s `apply_template_profile` / `set_para_font`, now
  reads that block and applies the per-style font to a paragraph carrying that named style, falling
  back to the global font otherwise, so the derived data actually affects rendered output rather than
  being inert.
- **`--no-toc` / `toc: false` opt-out for `render-doc.sh`** (issue #99): `container/render-doc.sh`
  hardcoded `--toc --toc-depth=2` into the pandoc invocation unconditionally, with no flag, env var, or
  template-profile key to disable it, a fidelity problem for a short document (a one-to-two-page
  template, say) that never had a table of contents in the original. Two opt-out paths, either one
  sufficient: the `--no-toc` CLI flag, or a top-level `toc: false` key in the `--template-profile` YAML
  (the same either-one-is-enough interaction as `QC_BLOCKING` / `--qc-blocking`). Default stays on
  (today's behavior), so this is a pure opt-out. New:
  `tests/test_render_doc_toc_opt_out.py`.
- **OOXML `raw_attribute` escape hatch** (issue #96): `pandoc_markdown.MARKDOWN_FROM`, the one shared
  pandoc `--from` spec every markdown-reading call site builds on (DOCX via `container/render-doc.sh`,
  PDF via `pdf/typst_backend.py`), now pins the `raw_attribute` extension. A hand-authored
  ` ```{=openxml} ` fenced code block is read as a genuine `RawBlock` AST node instead of an inert,
  literal code block, so it now reaches the DOCX writer and lands in `word/document.xml` as raw OOXML
  verbatim: verified end-to-end through a real `render docx` run, plus a negative control with the
  extension explicitly disabled proving the fenced block really was inert before this change. On the
  PDF/typst path the same block is present in the AST but silently dropped by the typst writer (it
  does not recognise the `openxml` format tag), so the shared constant is safe for every call site
  without a path-specific carve-out. This is a manual, advanced escape hatch only, honestly not a new
  markdown feature: it does not add native syntax for Word content controls (checkbox/dropdown
  `w:sdt`) or merged/spanned table cells (`gridSpan`), both of which have no markdown representation
  today and remain a separate follow-up issue. New: `tests/test_raw_attribute_escape_hatch.py`, plus
  a regression test in `tests/test_typst_backend.py` confirming the PDF path drops the block cleanly.
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
- **`render comprehension-review`** (issue #84): a fresh-reader comprehension gate for rendered text
  documents (`.md` or `.docx`), the text peer of the diagram vision-review gate. Chunks the document
  into reader-sized snippets at section (and, when needed, paragraph) boundaries and has an
  author-independent LLM read them in order (harness / copy-paste / the D17 direct-API channel),
  reporting per-snippet purpose/confusion/fluff/cuttable content plus a whole-document synthesis.
  Report-only. The D16 gate is deliberately constant here: comprehension has no deterministic
  sufficiency proxy the way vision-review or decision-capture do, so `confidence()` always returns 0.0
  and the step always escalates unless `--threshold <= 0` -- see `docs/DECISIONS.md` D20.
- **`render reingest --apply-widths`** (issue #73): the `## 3. Table column widths` section already
  detected and reported reviewer-applied column-width changes; there was no apply path for them the
  way the text delta has `## 5. Fast-forward plan` / `--apply`. `--apply-widths <out.yaml>` now emits
  a table column-width sidecar, in the exact `tables: [[...], ...]` (twips, ordinal-matched) shape
  `docstyle/style_postprocess.py`'s `_load_table_widths()` / `apply_table_widths()` already consume via
  `--table-widths`, so the round trip is `render reingest --apply-widths spec.yaml` then
  `render docstyle --table-widths spec.yaml` on the next render. Does not touch the markdown source
  (pipe tables carry no width information pandoc will honor); each entry is commented with its header
  text + row count + column count for human/audit stability, since two tables can share an identical
  header. Written regardless of the FAST_FORWARD/DIVERGED verdict, unlike `--apply`: it captures the
  reviewer's current widths, not a canonical-source edit.
- **`render reingest` `## 3b. Page breaks` report section** (issue #73): manual page-break
  additions/removals (the pandoc `\newpage` token, or a raw-openxml `<w:br w:type="page"/>`) used to
  surface only as generic `(deleted in the edited DOCX)` / `(added in the edited DOCX)` lines in the
  manual-review list when they surfaced at all, indistinguishable from the structural noise issue #72
  fixed. They now get their own report section: counts in the canonical-markdown source vs the edited
  DOCX, plus source line numbers / DOCX paragraph offsets, so a reviewer moving a page break reads as a
  deliberate structural edit rather than noise. Word's own `w:lastRenderedPageBreak` layout-cache
  marker (regenerated on every open, not a deliberate edit) is never counted.
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
