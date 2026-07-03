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
  post-render). lychee (B3b) and veraPDF-as-CLI-subprocess (B3c) are the next stages.
- **B4 - Visual-QA for all families.** NEXT.

## Track C - Add

- **C1 - VTOD executable (which content becomes a table, a formula, a diagram, a chart).** Two
  decision layers: form selection (prose / bullets / table / formula / diagram / chart) via
  deterministic signals first, then an optional dual-mode LLM step under the D8 contract for the
  ambiguous remainder; and visual-idiom plus notation selection once "visual" is chosen. `[imitate]`
  a deterministic shape-classifier rule base plus concept-graph converters. Exposes engine gaps that
  feed B1: PlantUML / C4-PlantUML, the Typst packages (fletcher / cetz / cetz-plot), a charting
  engine, and the poster mode.
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
  shared DrawingML theme extractor, derived template-profile with template provenance, and the
  probe-render style-diff idempotency gate). Remaining `[build]`: the PPTX and XLSX importers and
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

## Track D - Round-trip / draft reconciliation

Fully specified as D11: idempotent split-plus-embedded DOCX output, hidden provenance metadata,
diffable and contextualizing re-ingestion with a three-way conflict merge, git as inherent
infrastructure. **Provenance (part 2) is DONE**; the rest is specified, not built. Build order:
provenance first, then split-plus-embed dual output (parallel), then re-ingestion plus diff, then the
three-way conflict merge (hardest, build last), with git-commit wiring threading throughout.
Provenance is projection-aware per D14: internal profiles embed it, external / publish profiles strip
it; the strip mechanism still needs building before external renders are safe unscrubbed.

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
