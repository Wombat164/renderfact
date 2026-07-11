# Design spike: the project-workspace UI/UX (Track J)

> **What this is.** A design pass, in the discipline of the 5.7 editor spike, for growing the
> thin reference UI (D9) into a full project-workspace UI: project lifecycle, template library,
> render history, audience selection, live render, live edit, and diffs, all still Python-first,
> locally served, and consistent with generic-core/private-skin. It makes decisions with
> rationale, gives worked examples, and carries an honest open-question list. It does NOT
> relitigate resolved D-numbered decisions (D8, D9, D12/b/c, D13, D15) or the fuzzy-gate
> doctrine; where a decision here touches one, the constraint is cited and honored. Per D13,
> everything editor-shaped stays design-only until Track F clears; this spike marks each roadmap
> chunk buildable-now or gated. Governs-relationship: this document proposes; DECISIONS.md
> disposes. Any decision below that the operator ratifies should be promoted to a D-number.

## 1. Audit: what the 8 asks already have, and what is genuinely new

The operator's eight asks, mapped against D9/D12, the shipped api/app.py (662 lines) and
api/ui.py (265 lines), and the Track I studio. Verdicts: COVERED, PARTIAL, or NEW.

### 1.1 Start a project - NEW

Nothing in the codebase persists anything. The API holds only an in-memory CSRF token set and
a rate limiter; there is no store module, no /projects route, no project concept anywhere in
api/app.py's route table (app.py:127-166) or the hand-authored /openapi.json (app.py:510).
A projects registry is greenfield: it needs a store (section 3), routes, and jail/guard
integration with the existing `_jail()` (app.py:114) and `_guard()` (app.py:97).

### 1.2 Load a template - NEW (backend half-exists as a CLI mode)

`render import-template <corporate.docx>` (ARCHITECTURE.md, `import-template` mode; chunk C7)
already derives template profiles with provenance and an idempotency gate, but it is CLI-only:
no API route lists or serves template profiles, and the studio textarea is hardcoded to one
sample Notulen document (ui.py:34-84). The three insert-block buttons (ui.py, BLOCKS at
L183-187) are client-side canned `:::` snippets, not server templates. "Load a template" needs
a listing endpoint, a library location convention, and wiring into project creation (section 4).

### 1.3 See previous projects / history - NEW

No database, no file-store, no history of any kind. Renders are synchronous
request-to-response in a tempdir (POST /render/pdf at app.py:336, POST /render/docx at
app.py:399) and leave no trace server-side. Provenance stamps live in the artifacts themselves,
not in any queryable index. Fully new scope (sections 3 and 5.1).

### 1.4 Live-render output - COVERED for the single-pane case, design-integrated for the rest

The shipped studio already IS a live-render preview: `schedulePreview()` debounces 600 ms and
POSTs /render/pdf with format:png, swapping the preview `<img>` via createObjectURL
(ui.py:175-181), with a pager driven by the X-Total-Pages header. What it is not: push-based,
projection-aware (it renders the raw textarea, never through /project), or connected to the
D12 three-pane preview split (live-approximate client-side vs exact-on-demand server-side,
editor spike section 1.2). Section 6 decides how these compose.

### 1.5 Live-edit input - PARTIAL (2-pane shipped, 3-pane specified-not-built)

The studio gives a two-pane source|preview editor for one whole document. The D12 three-pane
editor (outline | raw section | live preview) is fully specified (editor spike sections
1.1-1.4; DECISIONS.md L174-236) with a complete API contract (GET /editor/doc, GET
/editor/section, POST /editor/render-fragment, PUT /editor/section) but zero implementation:
no editor code exists, and per D13 implementation is frozen behind Track F. This spike treats
the D12 contract as fixed input and designs the workspace to receive it (section 5.3).

### 1.6 See diffs - NEW (but the substrate is already mandated)

No diff endpoint, no diff UI. However D12's save model (exactly one git commit per
diff-carrying save, server refuses non-git work trees, editor spike section 1.3 L59-70) means
the substrate - a linear per-project commit history whose messages are decision-intent entries
- is already a hard requirement of the editor. The diff view (section 7) is a thin read-only
consumer of that substrate and is buildable before the editor itself.

### 1.7 Audience menu - PARTIAL (backend yes, discovery and UI no)

POST /project (app.py:212, F1) accepts source+profiles+profile and returns
{profile, blocks_dropped, text}; the projector's gate semantics (clearance no-read-up,
distribution coverage, disclosure ladder, fail-closed on unknown labels) are shipped
(projection/projector.py, ARCHITECTURE.md `project` mode). But the UI exposes this as three
freeform text inputs (ui.py:113-119), and critically NO endpoint enumerates the profile names
defined in a profiles YAML the way GET /theme/variants (app.py:274) enumerates brand variants.
An audience MENU needs a profile-listing endpoint (section 5.4) plus select-driven UI.

### 1.8 Doc-type and diagram scaffolding, manual or auto - NEW

Manual today means: two download buttons (PDF vs DOCX) and three block-snippet buttons. There
is no doc-type concept in the API, no diagram backend on the API surface (d2/mermaid/likec4
render only inside the CLI pipelines), and no auto-choice of anything. The auto-choose feature
is new scope and is exactly the shape the fuzzy-gate plan was written for
(2026-07-04-fuzzy-gate-architecture-plan.md, worked example "auto-choose template"); section 4
designs it deterministic-first with D8-degradable escalation.

### 1.9 Audit summary table

| Ask | Verdict | Existing anchor |
| --- | --- | --- |
| 1 start project | NEW | none (greenfield store) |
| 2 load template | NEW (CLI mode exists) | import-template / C7 |
| 3 project history | NEW | provenance stamps only, in artifacts |
| 4 live render | COVERED (single-pane) | ui.py schedulePreview, app.py /render/pdf png |
| 5 live edit | PARTIAL | studio 2-pane shipped; D12 3-pane specified |
| 6 diffs | NEW (substrate mandated) | D12 commit-per-save |
| 7 audience menu | PARTIAL | POST /project shipped; no listing endpoint |
| 8 doc-type/diagram auto | NEW | fuzzy-gate plan + confidence_gate.py (G4) |

One staleness observation surfaced during the audit: ARCHITECTURE.md L29 still lists pdf/deck/
poster as "roadmap v0.2.x, not wired" while ROADMAP Track H/I record `render pdf` DONE and a
shipped studio. Carried as OQ9, not treated as current.

## 2. Requirements

### 2.1 The eight operator asks, restated in system vocabulary

- **FR-1 (project lifecycle).** The workspace can create a renderfact project: a git work tree
  containing a profiled markdown source, a profiles YAML, a template reference, and a manifest
  (section 3), scaffolded from a template-library entry, via a D15-hardened mutating route.
- **FR-2 (template load).** The workspace lists the template library (built-ins plus
  import-template C7 outputs under the server root) and applies a chosen template profile at
  project creation or retarget time; import of a new corporate DOCX is invocable from the UI as
  a thin wrapper over the existing import-template pipeline, idempotency gate included.
- **FR-3 (registry / history).** A projects dashboard lists all projects under a projects
  root with status, last render, and per-render history (profile used, blocks_dropped, artifact
  path, timestamp, source commit), rebuildable from on-disk truth (section 3.4).
- **FR-4 (live render).** The workspace shows a rendered preview that updates as work
  progresses, honoring the D12 two-quality split: live-approximate client-side for orientation,
  exact server-side on demand for sign-off (section 6).
- **FR-5 (live edit).** The workspace hosts the D12/D12b/D12c editors as specified (leaf-
  section unit, hash concurrency token, commit-per-save, CSRF on PUT /editor/section); this
  spike adds composition only, no contract changes (section 5.3).
- **FR-6 (diff).** The workspace shows git-based diffs between any two commits of a project's
  source, defaulting to previous-vs-current, rendered in the UI, via a read-only endpoint over
  `git diff` plumbing (section 7).
- **FR-7 (audience menu).** Audience/clearance/disclosure targeting is a menu, not freeform
  text: a profile-listing endpoint enumerates profile names (and optionally ladder metadata,
  OQ11) from the project's profiles YAML, mirroring the GET /theme/variants pattern; the render
  panel projects through POST /project before rendering, and surfaces blocks_dropped.
- **FR-8 (doc-type/diagram choice, manual or auto).** An explicit manual-vs-auto toggle. Manual:
  operator picks doc-type (report, deck, poster, sheet) and diagram scaffolding (none, mermaid,
  d2) from data-driven selects. Auto: deterministic rule-based choice, confidence-gated per the
  fuzzy-gate doctrine, escalating to an LLM step only past the threshold and only through a D8
  dual-mode (harness or copy-paste) step; never a silent guess (section 4).

### 2.2 Added functional requirements (interpreted, grounded)

- **FR-9 (profile discovery endpoint).** GET /projects/{name}/profiles (and a project-less
  GET /profiles?path= for the studio) returning profile names plus enough metadata to build the
  menu. Grounding: the audit gap in 1.7; the /theme/variants precedent (app.py:274); I5's
  "data-driven selects" pattern already shipped for variants and locales.
- **FR-10 (render history with provenance linkage).** Every workspace-initiated render appends
  a ledger entry (section 3.4) carrying the projection profile, gate parameters, dropped-block
  count, and the source git commit when the tree is clean. Grounding: the `project` mode header
  stamp already computes exactly these fields; the editor spike's chunk 4.4 hand-off (optional
  Provenance.source_commit) gives the clean-tree rule.
- **FR-11 (capability-aware degradation).** Every UI affordance that needs an optional engine
  (typst for PDF, d2/likec4 for exact diagram previews) consults GET /doctor (app.py:242) and
  degrades to a labeled disabled state ("d2 not installed - exact preview unavailable"), never
  a dead button or a raw 500. Grounding: /doctor and the render_pdf_ready badge already exist
  (I4); D12's placeholder-card rule for server-only fences.
- **FR-12 (needs_review surfacing).** Anything the fuzzy-gate doctrine flags needs_review
  (auto-choice below threshold with no escalation channel, or an escalation that itself came
  back low) appears in the workspace as a confirm-required badge on the affected setting, with
  the deterministic partial and its sub-signals visible. Grounding: fuzzy-gate plan rule 5
  ("never lost") and the plan's own auto-choose worked example.
- **FR-13 (project portability).** A project is a plain directory: copying it (or cloning its
  git repo) to another machine with renderfact installed reproduces the full workspace view
  with zero import step. Grounding: generic-core/private-skin and docs-as-code; falls out of
  the section 3 manifest decision, but stated as a requirement so a future cache never becomes
  load-bearing.
- **FR-14 (copy-paste-degradable everywhere an LLM appears).** The only LLM-touching workspace
  feature (auto-choose escalation) must run in both D8 modes from the same UI: harness when
  configured, otherwise the UI presents the assembled prompt for copy-out and a paste-back box
  validated against the identical OUTPUT_SCHEMA. Grounding: D8 verbatim; no UI feature may be
  harness-only.

### 2.3 Non-functional requirements

- **NFR-1 (offline, no required network).** Every workspace function works with no network
  interface beyond loopback. The only network-optional path is a configured LLM harness, and D8
  guarantees a no-network substitute (copy-paste via a human). No CDN assets, no font
  fetches: the D12 vendored-only client-JS rule (one markdown renderer + KaTeX + mermaid.js,
  nothing else) extends to every new screen.
- **NFR-2 (no phone-home telemetry).** The workspace emits no outbound analytics of any kind.
  Explicit distinction: the fuzzy-gate calibration log - the local (score, decision,
  later-correct?) record used to tune thresholds (fuzzy-gate plan, G2) - is a LOCAL file under
  the server root, never transmitted, and is NOT prohibited telemetry; it is required by the
  doctrine and stays.
- **NFR-3 (data locality).** All project data lives on the local filesystem inside the --root
  jail, versioned by git. No component may require a daemon, service, or store outside the
  project tree plus an optional disposable cache (section 3.3).
- **NFR-4 (stdlib-first backend).** New backend code follows E1: pure stdlib WSGI, hand-rolled
  routes in the existing route() if-chain, lazy imports of CLI-internal modules, no framework,
  no ORM. sqlite3, subprocess, json, hashlib are in bounds because they are stdlib.
- **NFR-5 (D15 on every new mutating route).** Every route this spike adds that writes
  anything (POST /projects, POST /templates/import, PUT /projects/{name}/config, plus the D12
  editor routes when they land) enforces the full D15 set: Origin/Sec-Fetch-Site allowlist,
  per-session CSRF token from GET /session, loopback-only Host, path jail. This spike's 6.2 is
  the first route that actually enforces the currently-unused /session token (app.py:130-133).
  LLM free-text destined for commit messages or the decision log gets length caps,
  control-char stripping, and human confirm before write.
- **NFR-6 (localhost-trust posture unchanged).** No user authentication is introduced; bind
  127.0.0.1 default, stderr warning on wider bind, rate limiting - all per D9/E2 as shipped.
- **NFR-7 (keyboard accessibility).** The workspace, and especially the three-pane editor, is
  fully keyboard-operable: pane focus cycling, outline navigation by arrow keys, save and
  render-exact as chorded shortcuts, visible focus rings, and no interaction reachable only by
  pointer. Grounding: single-operator power-user tool; the editor's middle pane is a text
  surface where hands stay on the keyboard.
- **NFR-8 (single-maintainer buildability).** Every roadmap chunk in section 8 is
  independently shippable by one person in one sitting-to-few-sittings, with no chunk blocking
  more than its declared dependencies. No build step for the client (no npm, no bundler);
  first-party JS stays hand-written vanilla.
- **NFR-9 (graceful engine absence).** Same as FR-11 but as a posture: a missing optional
  engine degrades a feature, never the workspace. /doctor is the single source of capability
  truth; no endpoint probes tools ad hoc.
- **NFR-10 (egress caution).** The server initiates no outbound connections. The one
  exception, a configured harness call, is explicit operator configuration, and the UI labels
  when a click will cause an LLM call versus staying fully local. Grounding: the same caution
  that made D8 dual-mode mandatory; consumers may run this inside networks where silent egress
  is a policy violation.
- **NFR-11 (scale honesty).** Design targets: tens to low hundreds of projects, sources up to
  the existing 512 KB request cap, render round-trips of a few seconds. The registry must stay
  responsive by design at 200 projects (section 3.3 sizes the scan); anything beyond that is
  explicitly out of scope for v1 (OQ12).

## 3. The project concept and data model

### 3.1 What a renderfact project IS

**Decision.** A project is a git work tree (or a subdirectory of one) under the projects root
containing: (a) exactly one manifest file `renderfact.yaml` at its top level, which is the
source of truth for everything the workspace knows about the project; (b) the profiled
markdown source(s) and profiles YAML the manifest points at; (c) a `.renderfact/` operational
directory for derived, rebuildable data (render ledger, auto-choose telemetry). Identity is
the directory name (slug); there is no opaque ID.

**Why.** This is the docs-as-code answer: the project travels as files, diffs as text, and
needs no import/export machinery (FR-13). It also composes with two hard constraints for free:
D12's server-refuses-non-git-trees rule (a project that wants editor saves is already a git
tree) and the `_jail()` path discipline (everything the API touches resolves under --root).

### 3.2 Manifest as source of truth: flat file, not database

**Decision.** The registry's source of truth is the per-project `renderfact.yaml` manifest,
git-tracked. There is NO central database of record. Discovery is a scan of the projects root
(default `<root>/projects`, overridable with --projects-root) for directories containing a
manifest, depth-limited to 2 to keep the scan bounded.

**Why flat-file wins here.** Three arguments, in strength order. First, generic core, minimal
deps and NFR-4: yaml is already a dependency of the projection engine (profiles YAML), json is
stdlib; a manifest costs zero new dependencies, while making SQLite the truth would put the
project's most important metadata in a binary blob that neither git nor a human can diff -
directly against the commit-per-save philosophy where the git history IS the record. Second,
D9 API-first: routes stay thin readers of files, the same files the CLI can read, so every
workspace feature remains scriptable without the server. Third, crash-consistency for free:
a manifest write is a single atomic file replace (write temp + os.replace), and if it ever
tears, git checkout restores it. A database of record would need its own backup story.

**Why not SQLite-as-truth at all.** sqlite3 being stdlib makes it tempting, but truth in
SQLite breaks FR-13 (copy a dir, lose its registry row), breaks human-diffability, and gives
nothing at NFR-11 scale: parsing 200 small YAML files is single-digit milliseconds territory
and the server already lazy-imports far heavier modules per request.

### 3.3 SQLite as a disposable read-cache: deferred

**Decision.** v1 ships scan-only with an in-process cache keyed on (path, mtime) per manifest,
invalidated per request by a cheap os.stat sweep. A SQLite index file at
`<projects-root>/.renderfact-index.sqlite` is specified as a REBUILDABLE cache only - delete
it and the next scan recreates it, it is never written except from manifest truth, and it is
gitignored - but it is NOT built in v1. It gets built only if a real dashboard latency problem
appears (OQ12 records the trigger condition: sustained scan time over ~250 ms at the
operator's real project count).

**Why.** The strong steer is correct and the numbers back it: at target scale the cache buys
nothing, and every cache is a second source of truth waiting to lie. Specifying its contract
now (disposable, rebuildable, never authoritative) costs one paragraph and prevents a future
implementer from promoting it.

### 3.4 The render ledger

**Decision.** Render history is an append-only JSONL file `.renderfact/renders.jsonl` per
project, one object per workspace-initiated render, written by the server after each
successful POST that produced an artifact for this project. It is untracked by default
(listed in the scaffolded .gitignore): git tracks intent (source + manifest + commit
messages); the ledger tracks operations, and the durable render record remains the provenance
stamp inside each artifact, per the editor spike's no-provenance-refresh-on-save reasoning.
Operators who want the ledger versioned can remove the gitignore line; nothing breaks. OQ14
carries the tracked-by-default question in case field use says otherwise.

Ledger entry shape:

```json
{"ts": "2026-07-07T14:03:22Z", "action": "render", "format": "pdf",
 "profile": "partner-contextual", "blocks_dropped": 7,
 "template": "acme-report", "doc_type": "report",
 "source_commit": "b41c9e2", "source_dirty": false,
 "artifact": "out/notulen-partner.pdf", "duration_ms": 2140,
 "engine": {"typst": "0.15.0"}, "ok": true}
```

`source_commit` is stamped only when the tree is clean, exactly the chunk 4.4 rule the editor
spike handed forward; `source_dirty: true` with no commit is the honest alternative, never a
guessed commit.

### 3.5 The manifest schema (concrete)

```yaml
# renderfact.yaml - project manifest, source of truth, git-tracked
renderfact: 1              # manifest schema version, integer
name: q3-partner-briefing  # display name; directory slug is identity
created: 2026-07-07
source: src/briefing.md    # relative, jailed under the project dir
profiles: profiles.yaml    # relative; the consumer-defined ladders live here
default_profile: partner-contextual

template:
  ref: acme-report         # name in the template library (section 4.1)
  mode: manual             # manual | auto
  # when mode: auto, the last gate outcome is recorded for audit:
  chosen_by: deterministic # deterministic | llm | operator
  confidence: 0.87
  needs_review: false

doc_type: report           # report | deck | poster | sheet
diagram_scaffold: mermaid  # none | mermaid | d2

render:
  formats: [pdf, docx]     # what the render panel offers by default
  locale: nl-BE
  variant: default         # brand.yaml variant, as GET /theme/variants
  paper: a4

# free-form consumer extension point; the core never interprets keys here
x-skin: {}
```

Rules: unknown top-level keys are rejected (fail-closed, same spirit as the projector's
unknown-label rule); `x-skin` is the single sanctioned extension namespace so private skins
can annotate without forking the schema. All paths are validated through `_jail()` relative
to the project directory. The manifest is small on purpose: anything derivable (last render,
history) lives in the ledger, not here, so manifest diffs stay meaningful.

### 3.6 Discovery routes

- GET /projects - scan projects root, return
  `[{name, path, doc_type, template, default_profile, last_render}]` (last_render from the
  ledger tail; null if none). Read-only, existing guard only.
- GET /projects/{name} - manifest (parsed), ledger tail (bounded, ?limit= default 20), git
  facts (current branch, head commit, dirty flag) via subprocess git.
- POST /projects - create: validate slug, refuse existing, scaffold directory (manifest,
  seeded source from template, profiles YAML skeleton, .gitignore), `git init` if not already
  inside a work tree, initial commit "renderfact: create project <name>". Full D15 set
  enforced (NFR-5); this is deliberately the first consumer of the /session CSRF token.
- PUT /projects/{name}/config - mutate manifest fields (profile, template ref, doc_type,
  render defaults) with the same optimistic-concurrency shape as the editor: the request
  carries the manifest's content hash as base_hash, 409 on staleness, one git commit per
  diff-carrying change with a required non-empty message. Same mechanics as PUT
  /editor/section on purpose: one concurrency idiom across the API.

## 4. Template loading and auto-choose

### 4.1 The template library

**Decision.** The template library is a directory convention, not a store:
`<root>/templates/<name>/` containing a template profile (the C7 import-template output
format: theme, fonts, geometry, provenance) plus optional `scaffold.md` (seed source for new
projects) and `template.yaml` metadata:

```yaml
name: acme-report
doc_type: report          # what this template is FOR; drives auto-choose candidates
description: Corporate A4 report, derived from acme-corporate.docx
derived_from: acme-corporate.docx   # provenance, from import-template
diagram_scaffolds: [mermaid, d2]    # scaffolds this template styles well
```

Routes: GET /templates (list, [imitate] the established E1 route shape - same discipline as
/theme/variants and /locales, data-driven selects per I5); GET /templates/{name} (metadata +
profile summary); POST /templates/import (thin wrapper over the shipped import-template
pipeline, C7 idempotency gate included, D15-hardened since it writes into the library). The
core ships two or three domain-neutral built-in templates (plain report, plain deck, plain
sheet); everything branded arrives via import-template - generic core, private skin.

### 4.2 Manual-vs-auto toggle

**Decision.** The toggle is a per-project manifest field (`template.mode`), surfaced in the
New Project wizard and the Render Config panel as an explicit two-state control labeled
"Choose template and doc-type myself" / "Let renderfact choose (you confirm)". Auto NEVER
silently commits a choice the operator has not seen: the wizard always shows the chosen
template + doc-type + diagram scaffold with the confidence score and fired sub-signals, and
the needs_review path (4.4) requires an explicit confirm click. Manual mode never invokes the
chooser at all - zero compute, zero tokens, per the fuzzy-gate accept-is-free principle.

### 4.3 Auto-choose: deterministic first, gated, D8-degradable

The chooser follows the fuzzy-gate pipeline exactly, reusing the shared primitive being
extracted to contracts/confidence_gate.py (G4).

**Step 1 - deterministic_template_choice(source, library).** Pure rules, always runs, always
produces a schema-valid result with MODE_FIELD "deterministic". Rule table, first match wins
within each facet:

- doc_type: frontmatter `doc_type:` key (explicit declaration) > filename conventions
  (`*-deck.md`, `slides/` parent, marp directives present -> deck; `*-poster.md` -> poster;
  tabular YAML source -> sheet) > structural signals (slide-separator lines `---` at column 0
  between content blocks -> deck; heading depth <= 2 with heavy table density -> report) >
  catch-all: report.
- template: manifest/frontmatter `template:` key > unique library template whose
  template.yaml doc_type matches the chosen doc_type > most-recently-used template for that
  doc_type in this projects root (from ledgers) > catch-all: the built-in plain template for
  the doc_type.
- diagram_scaffold: fences present in source (```mermaid -> mermaid, ```d2 -> d2) > template's
  declared diagram_scaffolds first entry > none.

**Step 2 - confidence(input) from named sub-signals**, per the doctrine: never a bare float.

- coverage: fraction of facets (doc_type, template, scaffold) decided by a non-catch-all rule.
  All three explicit = 1.0; all three catch-all = 0.0.
- specificity: rank of the strongest fired rule (explicit declaration 1.0, filename 0.7,
  structural 0.5, catch-all 0.15). A catch-all firing is intrinsically low confidence for
  free, exactly the doctrine's point.
- ambiguity: 1 minus the normalized margin between the top-2 doc_type candidates' rule scores;
  a document that pattern-matches both deck and report scores high ambiguity.
- novelty: share of fence languages and frontmatter keys in the source that appear in no rule;
  an intent-opaque source cannot be confidently classified by rules (this is also the
  escalation FLOOR class: novelty above 0.6 caps the composite below the accept threshold
  regardless of other signals, guarding the confidently-wrong-specific-rule red flag).
- volume: penalty outside template norms (a 3-line source or a 400 KB source both reduce
  confidence in structural signals).

Composite: weighted mean, weights externalized next to the threshold. Worked example, a file
`notulen-2026-07.md` with frontmatter `doc_type: report`, two mermaid fences, no marp
directives, library containing acme-report (doc_type report) and plain-deck:

```
coverage    = 1.00  (doc_type explicit, template unique-match, scaffold from fences)
specificity = 1.00  (explicit frontmatter declaration)
ambiguity   = 0.05  (report 0.95 vs deck 0.10, wide margin)
novelty     = 0.00  (all fences and keys known)
volume      = 0.90  (14 KB, in range)
composite   = 0.93  -> above threshold 0.75 -> ACCEPT deterministic
result: template=acme-report, doc_type=report, scaffold=mermaid, zero tokens
```

Counter-example, an untitled paste with no frontmatter, `---` separators, and one unknown
```vega fence: coverage 0.33, specificity 0.15 (catch-alls), ambiguity 0.72, novelty 0.45 ->
composite 0.31 -> below threshold -> escalate.

**Step 3 - gate(score, threshold).** Threshold externalized per-step
(auto_choose.threshold, initial 0.75, OQ13), calibrated later from the local (score, decision,
later-correct?) log written to `.renderfact/autochoose-telemetry.jsonl` (this is the NFR-2
local-only calibration log, G2 pattern). Healthy escalation band target 10-15 percent; the
telemetry file is what proves or disproves it.

**Step 4 - escalation, D8 dual-mode.** Above-threshold-of-doubt (composite below threshold)
escalates to an LLM step defined like every other step contract: assemble_input packs the
deterministic candidate, the sub-signal values, the source outline (headings + fence
languages, NOT full text - keeps the prompt small and the copy-paste mode humane), and the
library metadata; OUTPUT_SCHEMA is `{template, doc_type, diagram_scaffold, rationale}`,
identical in harness and copy-paste modes, validated by the same validator, bounded retry ~3,
reviewer_mode stamped. The deterministic partial is ALWAYS passed as context and ALWAYS
recoverable: if the LLM answer fails validation out of retries, the deterministic result
stands, flagged needs_review.

**Step 5 - no channel.** No harness configured and operator declines copy-paste: the
deterministic result is used, flagged needs_review, and FR-12 surfaces it as a
confirm-required badge in the wizard ("renderfact guessed plain-report with low confidence
(0.31) - confirm or change"). Never lost, never silent.

### 4.4 Where the choice lands

The confirmed choice writes template.mode/chosen_by/confidence/needs_review into the manifest
(3.5) via the same PUT /projects/{name}/config mechanics, producing one audited git commit.
The gate outcome is thereby in the decision record without any new persistence machinery.

## 5. Information architecture

Six screens/panes, all served the existing way (HtmlResponse wrapper, app.py:445, behind
--enable-ui), composing with rather than replacing the shipped studio and the specified D12
editor. One structural decision first.

**Decision (static assets).** The one-monolithic-UI_HTML-string pattern ends at the workspace
boundary. First-party JS/CSS for the new screens ship as package data files under
api/static/, served by a new GET /ui/static/{name} route with a hard allowlist (exact
filenames, no directory traversal possible by construction) and long-cache headers. The
vendored D12 libraries (markdown renderer, KaTeX, mermaid.js) ship the same way. UI_HTML and
the shipped studio stay exactly as they are.

**Why.** KaTeX and mermaid.js are megabyte-class; as Python string literals they would be
unreviewable and would bloat every import of api.ui. Package data + importlib.resources is
pure stdlib, keeps the no-build/no-npm rule (NFR-8), and the allowlisted route keeps the D15
posture (no filesystem reads outside the package). This is the "real architectural decision"
the extension-seam audit flagged; it is made here and carried to DECISIONS.md if ratified
(OQ8 records the ratification question).

### 5.1 Projects Dashboard (GET /ui/projects)

Purpose: the answer to "what have I got and what happened last". Elements: project cards/rows
from GET /projects (name, doc_type badge, template, default profile, last render outcome +
timestamp, dirty-tree indicator); a New Project button; a Template Library link; a doctor
strip reusing the existing PDF-ready banner pattern, extended per FR-11 to all engines.
Composes: this becomes the natural landing page when --enable-ui is set (the current /ui
studio remains reachable, linked as "Scratchpad studio"; whether / ui default flips to the
dashboard is cosmetic and decided at build time).

### 5.2 New Project wizard (dashboard modal or /ui/projects/new)

Purpose: FR-1 + FR-2 + FR-8 in one flow. Steps: (1) name/slug; (2) the manual-vs-auto toggle
(4.2); manual -> template picker (from GET /templates, cards with doc_type badges and
derived-from provenance) + doc_type + scaffold selects; auto -> paste-or-pick source first,
then the chooser result panel with confidence, sub-signals, and confirm/override controls,
including the copy-paste escalation surface (assembled prompt textarea + paste-back box) when
no harness is configured; (3) profile source: scaffold a skeleton profiles YAML or point at an
existing one; (4) create -> POST /projects -> land in the Project Workspace. Every mutating
click goes through the D15-hardened routes.

### 5.3 Project Workspace (GET /ui/projects/{name})

Purpose: the working screen; everything about one project. Layout: a header (project name,
doc_type, template, git head + dirty flag), a left rail (Edit / Render / History / Diff
tabs), and the main area per tab.

Edit tab: this is WHERE the D12 three-pane editor mounts when 5.8 lands - the workspace does
not respecify it; it provides the frame (project-scoped path parameter into GET /editor/doc
and friends, which already take path=). Until 5.8 exists, the Edit tab shows the interim
whole-document editor: the shipped studio's textarea+preview pattern pointed at the project's
source file instead of the hardcoded sample, with save going through a project-scoped
whole-file save route that reuses the PUT /editor/section mechanics at doc granularity
(base_hash on the whole file, commit message required). This interim surface is explicitly
disposable: it exists so the workspace is useful before Track F clears, and the 3-pane editor
replaces it in place.

**Decision (studio vs editor relationship).** Coexist, one embeds the other's pattern: the
Track I studio remains as the project-less scratchpad (quick ad-hoc render, no persistence,
exactly what it is today); the workspace Edit+Render tabs embed the same preview mechanics
bound to project state; the D12 editor replaces the Edit tab's interim surface when built.
Nothing is unified into one mega-screen and nothing shipped is thrown away.

**Why.** The studio's job (prove the render API, fast ad-hoc use) and the editor's job
(section-scoped governed editing with commit-per-save) are different jobs with different
state models (none vs git). Forcing them into one surface would either give the scratchpad
unwanted save ceremony or give the editor an escape hatch around commit-per-save.

### 5.4 Render Config panel (workspace Render tab)

Purpose: FR-7 + FR-8 at render time. Elements: profile select fed by GET
/projects/{name}/profiles (FR-9); variant/locale/paper selects (existing endpoints);
format buttons (from manifest render.formats, gated by /doctor per FR-11); a projection
preview strip showing blocks_dropped and the would-be header stamp BEFORE committing to a
full render (a dry call to POST /project); the render button, which runs project-then-render
server-side and appends the ledger entry (3.4). The fail-closed rule is surfaced honestly:
a ProjectionError (unknown clearance/distribution label) renders as the error card with the
offending label, never a fallback render - a gate that guesses is not a gate, and neither is
a UI that hides the gate.

### 5.5 Diff view (workspace Diff tab)

Section 7 in full. Elements: two commit pickers (default: previous save vs working head),
the commit-message-as-decision-intent list from git log (this is D11 part 4 paying rent:
the history reads as a decision journal), unified diff pane, and a projected-diff toggle
(7.4, later chunk).

### 5.6 Template Library (GET /ui/templates)

Purpose: FR-2 standalone. Elements: template cards (metadata from 4.1, provenance line
"derived from acme-corporate.docx on 2026-06-30"), an Import Template flow (upload/point at a
DOCX path under the root jail, run C7, show the idempotency-gate style-diff verdict), and a
"use in new project" shortcut into the wizard. The import flow is the second consumer of the
mutating-route hardening.

### 5.7 History view (workspace History tab)

Purpose: FR-3/FR-10 per project. Elements: ledger table (time, action, profile,
blocks_dropped, format, artifact link, source commit, ok/fail), each row expandable to the
full ledger JSON; artifact links served through a jailed GET /projects/{name}/artifact?path=
read-only route. Cross-links: source_commit jumps to the Diff tab pinned at that commit.

## 6. Live render integration

### 6.1 The two-quality split extends cleanly

D12's rule stands: live-approximate is client-side and vendored-only (orientation, not
sign-off); exact is server-side through real engines on demand. The workspace adds a third
distinguishable render intent - the committed artifact render (Render tab, writes ledger) -
and the design keeps all three visually distinct: the editor right pane (approximate, free,
instant), the exact-preview button (server round-trip, no ledger entry), and the Render
button (server round-trip, ledger entry, artifact on disk). Blurring approximate preview
and sign-off render is the failure mode D12 explicitly named; three labeled intents prevent
it.

### 6.2 Transport: keep the synchronous round-trip, no SSE, no websocket

**Decision.** The live-render mechanism stays the shipped one: debounced client POST
/render/pdf format:png, response bytes swapped into the preview img. Render-on-save in the
workspace = the save success handler triggers the same call. No server push is added in this
track.

**Why.** Three reasons, one decisive. Decisive: the stdlib wsgiref server handles requests
serially; a long-lived SSE or websocket connection would starve every other route for its
lifetime, so push transport is not an incremental add, it forces a threading/server rework
that belongs to its own decision (and websockets are not WSGI at all). Supporting: renders at
target document sizes complete in low seconds, inside comfortable synchronous UX territory;
and the debounce+refetch pattern is already proven in the shipped studio, zero new failure
modes. E4's [imitate] progress-event shape is honored at the SCHEMA level, not the transport
level: the render routes gain an optional events list in error responses now
({"events": [{"stage": "typst", "level": "error", "msg": ...}]}), so when an async job
model ever arrives (bigger docs, decks with heavy diagram farms), the event vocabulary is
already fixed and CLI/API/UI already parse it. Polling GET /jobs/{id}/events over that same
shape is the designated future path; it is out of scope here and noted, not built.

### 6.3 Preview scope in the workspace

The Edit tab previews the SOURCE (full-candor, un-projected) because that is what the
operator is editing; the Render tab previews the PROJECTION for the selected profile
(server-side project-then-render), because that is what the audience will see, with
blocks_dropped displayed alongside so the difference between the two previews is explained
rather than mysterious. This split resolves what the shipped studio fudges today (it renders
raw text and /project is a separate disconnected panel).

## 7. Diff view design

### 7.1 Substrate and plumbing

**Decision.** Diffs come from the project's own git history via subprocess calls to the git
binary - `git log --format=...`, `git diff <from> <to> -- <source>`, `git show` - with a
fixed argv (never shell=True), cwd pinned to the project directory, and commit refs validated
against `git rev-parse --verify` before use. No GitPython, no dulwich: the server already
depends on git being present (D12 refuses to operate outside a work tree), subprocess is
stdlib (NFR-4), and [adopt] git itself is the diff engine - there is no better-tested one.

### 7.2 Endpoint shape

- GET /projects/{name}/history?limit= - `[{commit, ts, message, files}]` from git log; the
  message column is the decision-intent journal (D11 part 4).
- GET /projects/{name}/diff?from=&to=&mode=source - default from=previous-commit-of-source,
  to=HEAD (or WORKING for the uncommitted tree). Response:

```json
{"from": "b41c9e2", "to": "WORKING", "mode": "source",
 "message_from": "tighten partner-facing risk wording",
 "files": [{"path": "src/briefing.md", "hunks": [
   {"header": "@@ -42,7 +42,9 @@", "lines": [
     {"op": " ", "text": "## Risk posture"},
     {"op": "-", "text": "The risk is acceptable."},
     {"op": "+", "text": "The residual risk is acceptable under condition R3."}
 ]}]}]}
```

Structured JSON rather than raw patch text so the client stays a dumb colorizer (no vendored
diff-parsing JS, preserving the D12 vendored-only budget). Read-only, existing guard,
both endpoints live under /projects/{name}/ so the path jail and slug validation are shared
with the rest of the registry. The D12 editor's future needs are covered by the same routes
(a per-section diff is just the whole-file diff filtered client-side by the section's line
range from GET /editor/doc).

### 7.3 UI rendering

**Decision.** Unified view is the default; a split (side-by-side) toggle is offered but
implemented as pure CSS/JS over the same hunk JSON (two columns from op - / op +), no second
endpoint. Raw-source diff is the v1 semantic: it is exact, cheap, and matches what the
commit actually recorded.

### 7.4 Rendered-projection diff (later, separate chunk)

The genuinely interesting question "what changed in what the PARTNER sees" is answerable with
shipped parts: project both commits' source through the projector with the same profile, diff
the two projected texts (difflib, stdlib), present with the same hunk JSON. It is
deliberately its own chunk (6.10): it multiplies compute (two projections per view), needs
care around fail-closed errors on historical revisions (an old commit may contain labels the
current profiles YAML no longer defines - surfaced as an honest error, never skipped), and
must NOT be confused with the source diff in the UI (explicit mode badge). mode=projected on
the same endpoint, additive.

## 8. Phased build roadmap

**Decision (track placement).** This work is a NEW track, Track J (project workspace), with
chunks numbered 6.x, not a continuation of the 5.x editor thread.

**Why.** Two reasons. First, honesty about D13: the 5.x thread (5.8/5.9/5.10) is editor
implementation, frozen behind Track F; most of this track is registry/library/diff/render
plumbing that is NOT editor work and is buildable now - numbering it 5.11+ would either
falsely inherit the freeze or, worse, blur what the freeze covers. Second, the dependency
shape is different: Track J depends on shipped Track E/I surfaces plus G4, and only its final
integration chunk touches the editor contract. The editor remains the 5.x thread; Track J
consumes it when it lands.

Chunks, in dependency order. Buildable-now unless marked GATED.

- **6.1 Registry core** [build]. Manifest schema + parser (fail-closed unknown keys), projects
  root scan with mtime cache, GET /projects, GET /projects/{name}, ledger reader. Pure
  read-side; no UI. Ships with a `render projects list` CLI subcommand so the API-first rule
  (D9: CLI-proven before UI) is satisfied for the read path.
- **6.2 Project creation + config mutation** [build]. POST /projects (scaffold, git init,
  initial commit), PUT /projects/{name}/config (hash-guarded, commit-per-change). FIRST
  enforcement of the /session CSRF token plus the full D15 set on both routes; includes the
  free-text caps/strip/confirm rules for commit messages. CLI twin: `render projects new`.
- **6.3 Template library** [build] for the library convention and GET /templates,
  [imitate] existing E1/I5 route+data-driven-select shape for listing; POST /templates/import
  wraps the shipped C7 pipeline [adopt] (own prior work). Ships the built-in plain templates.
- **6.4 Profile discovery** [build]. GET /projects/{name}/profiles and GET /profiles?path=,
  names + minimal metadata (OQ11 decides depth). Small, unblocks the audience menu.
- **6.5 Dashboard + wizard UI (manual path only)** [build]. Static-asset route +
  vendored/package-data decision from section 5 lands here; Projects Dashboard, New Project
  wizard with MANUAL template/doc_type/scaffold selection, Template Library screen. Auto mode
  is deferred to 6.7 so the wizard ships without any LLM machinery.
- **6.6 Workspace shell + Render tab + History tab** [build]. Project workspace page, render
  config panel with profile menu (consumes 6.4), project-then-render flow, ledger writes
  (render history, FR-10), artifact links, /doctor-driven degradation (FR-11). Interim
  whole-document Edit tab (studio pattern bound to project source, whole-file hash-guarded
  save). E4 event-shape stub in render error responses.
- **6.7 Auto-choose** [build] for the deterministic scorer and sub-signals; gate via
  contracts/confidence_gate.py (depends on G4 from the fuzzy-gate track); escalation step via
  the D8 dual-mode contract machinery [imitate] aider --copy-paste clipboard-watch UX for the
  paste-back surface, as already resolved by the D8 spike. Telemetry log (G2 pattern).
  needs_review badge + confirm flow (FR-12). Wizard grows the auto path.
- **6.8 Diff view, source mode** [adopt] git via subprocess for plumbing, [build] for the
  hunk-JSON endpoint and the dumb-colorizer UI. GET .../history and GET .../diff, unified +
  split toggle. Depends only on 6.1/6.6.
- **6.9 Studio-workspace reconciliation polish** [build]. Landing-page decision, cross-links
  (scratchpad "save as project" hand-off into the wizard with the scratch content as seed),
  keyboard-nav pass over all Track J screens (NFR-7 audit as a checklist item, not a vibe).
- **6.10 Projected-diff mode** [build]. mode=projected per section 7.4, difflib over two
  projections, honest historical-label error handling.
- **6.11 Three-pane editor integration** - GATED behind Track F per D13 and behind chunk 5.8
  itself. Mounts the D12 editor into the workspace Edit tab (project-scoped paths into the
  already-specified /editor routes), removes the interim whole-document surface, wires the
  per-section diff filter (7.2). This chunk is integration only; if 5.8's implementation
  wants contract changes, those are 5.x decisions, not Track J ones.

Sequencing note for the single maintainer: 6.1 through 6.6 are a coherent releasable arc
(workspace without any LLM and without the editor) and none of it touches the Track F freeze;
6.7 requires G4 to exist; 6.11 is the only chunk that waits on the editor thread.

## 9. Open questions

**OQ8 - ratify the static-asset decision. RESOLVED (chunk 6.5): D23.** Package-data files under
`api/static/` + an allowlisted `GET /ui/static/{name}`, plain `Path` reads (not
`importlib.resources` -- consistency with every other bundled-asset convention in this repo).
See DECISIONS.md D23 for the full rationale.

**OQ9 - ARCHITECTURE.md L29 staleness.** L29 lists pdf/deck/poster as roadmap-not-wired while
Track H/I record `render pdf` and the studio as DONE. Doc-only fix, but it is the
front-page architecture file; should be corrected in whichever chunk next touches docs.

**OQ10 - Track J lettering and placement.** Section 8 argues Track J / chunks 6.x over 5.11+.
If the operator instead reads the workspace as an extension of Track E (API+UI), the chunks
renumber but nothing else changes. Confirm before ROADMAP.md is edited.

**OQ11 - profile-listing schema depth. RESOLVED (chunk 6.4): names+ranks**, per the leaning
above. `GET /projects/{name}/profiles` / `GET /profiles?path=` return each profile's name,
`clearance_ceiling` value + its numeric rank in the ladder, `releasable_to` value + rank,
`lang`, `audience`, `disclosure` -- enough for tooltips and ordering in the audience menu,
without exposing the raw ladder-keyed dict (a private skin's full governance vocabulary).
Full ladders behind a config flag was not built; revisit only if a real UI need surfaces.

**OQ12 - SQLite read-cache trigger.** Deferred per 3.3 with a stated trigger (sustained scan
over ~250 ms at real project count). Needs a real-world number: how many projects does the
operator actually expect within a year? If the honest answer is under 50, delete the cache
paragraph entirely at the next spike revision.

**OQ13 - auto-choose initial threshold and weights.** 0.75 and the sub-signal weights in 4.3
are engineering guesses pending the calibration log (G2). Also open: whether the telemetry
JSONL lives per-project (.renderfact/) as specified or per-root (one log calibrates faster);
per-root leaks cross-project filenames into one file, which a multi-tenant-ish root might
mind.

**OQ14 - render ledger tracked vs untracked.** 3.4 defaults untracked (operations are not
intent). Counter-argument: a consumer whose audit posture wants render operations in the
versioned record just deletes the gitignore line, but maybe that should be a manifest flag
instead so the choice is declared, not implied. Small, decide when 6.6 is built.

**OQ15 - out-of-root project registration.** v1 discovery is scan-only under the projects
root, consistent with the path jail. Registering an existing project living elsewhere on
disk would need either a symlink convention (jail implications need thought) or a pointers
file, both deferred. Does the operator actually have out-of-root projects today?

**OQ16 - deck engine still open (inherited).** D12c's Marp-vs-typst-touying bench is still
unresolved and scoped inside its own chunk. Track J touches it only in one place: the
doc_type auto-choose rules for decks (marp-directive detection in 4.3) assume Marp-flavored
canonical source per D12c. If the bench picks typst-touying, the rule table needs one row
updated; noted so the coupling is explicit.

**OQ17 - whole-file interim save route.** 5.3's interim Edit tab needs a whole-document save
with editor-grade mechanics (hash guard, commit message, one commit). Options: a dedicated
PUT /projects/{name}/source route (clean, but a second save contract to maintain and then
delete), or shipping GET /editor/doc + a doc-granularity PUT early (touches the frozen editor
surface, arguably violating the D13 freeze's spirit even though it is not the three-pane
editor). The dedicated disposable route is the safer reading of D13; flagging because the
alternative is cheaper and an operator may judge it inside the letter of the freeze.
