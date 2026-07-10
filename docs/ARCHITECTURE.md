# renderfact - Architecture

The system as it stands today: what each piece IS and how the pieces fit. `DECISIONS.md` is the WHY
behind these shapes; `ROADMAP.md` is what is next. This document is current-state reference, and it
is honest about what is shipped versus specified.

renderfact takes one full-candor source and produces governed projections (per audience, clearance,
or disclosure) rendered to several formats, with provenance and QA gates, from one pinned toolchain.

## Render modes

`render <mode>` is a thin dispatcher: each mode invokes its own, unmodified pipeline underneath. Per-
mode argument parsing and path resolution still live in each pipeline; a shared library is future work.

| Mode | What it does | Status |
|---|---|---|
| `project` | one profiled source -> one governed render per audience/clearance/disclosure profile | shipped |
| `docx` | annotated markdown -> styled DOCX (plus optional PDF) | shipped |
| `docstyle` | standalone house-style DOCX post-processor (font/heading/table styling, `--table-widths`, `--cover-version`/`--cover-date`); the same engine `docx` calls internally, exposed directly (issue #74) | shipped |
| `diagram` | mermaid / d2 rendering with pre-render lint and visual-QA metrics | shipped |
| `tokens` | `brand.yaml` -> per-engine themes (mermaid JSON, marp CSS, pandoc profile, typst tokens) | shipped |
| `init-ai` | install D8 step instructions into the user's own assistant | shipped |
| `copy-paste` | run a D8 step with no harness: assemble a prompt, paste the reply back | shipped |
| `provenance` | embed / extract / adopt / retarget hidden source provenance across DOCX/XLSX/PPTX | shipped |
| `import-template` | derive a template profile (theme, fonts, geometry) from a branded DOCX, with an idempotency gate | shipped |
| `qa` | deterministic post-render gate (leaks / tables / paras / figs) | shipped |
| `gate` | fail-closed pre-publish QA gate chain (vale / lychee / verapdf / uids / plainlang) | shipped |
| `comprehension-review` | fresh-reader comprehension gate for a rendered text document (D16-gated, always escalates); the text peer of the diagram vision-review gate (issue #84) | shipped |
| `serve` | localhost HTTP API plus opt-in thin reference UI | shipped |
| `container` | raw passthrough to the OCI render wrapper | shipped |
| `doctor` | native version-drift check against `tools.lock` | stub, not built |
| `pdf` / `deck` / `poster` | typst archival/tagged PDF, marp decks, A2 posters | roadmap (v0.2.x), not wired |

The advertised-but-unwired formats are annotated, not claimed: the README carries a
shipped-vs-roadmap capability matrix stating exactly what runs today.

## Generic core, private skin

The toolchain is domain-neutral. Any organisation supplies its own private SKIN (brand token values,
reference templates, audience personas, classification markings) and its content; the public core
never contains domain content.

```
your private config (skin)         renderfact (this repo, generic)
  brand.yaml values  ------------>  tokens/     (mechanism + neutral defaults)
  reference.docx     ------------>  container/  (engines, pinned)
  audience personas  ------------>  render <mode>  (one entry point)
  source corpus      ------------>  lint/ + QA gates -> governed artifacts
```

**The skin contract is environment variables.** `container/render-doc.sh` is the generic DOCX
pipeline: it assumes no consumer directory layout. Every consumer-supplied piece is plugged in via an
environment variable, and each step SKIPS with an honest message when its piece is not configured.
The pipeline itself (projection, pandoc conversion, optional PDF) runs with zero consumer config.

| Variable | Purpose | Default |
|---|---|---|
| `SKIN_DIR` | convenience root: the vars below default into it when set | unset |
| `TEMPLATE_DOCX` | pandoc `--reference-doc` | pandoc built-in style |
| `FILTERS_DIR` | directory of pandoc lua filters, applied in name order | none |
| `TEMPLATE_PROFILE` | YAML consumed by the style post-processor | none (neutral defaults) |
| `STYLE_POSTPROCESS` | house-style DOCX post-processor | `docstyle/style_postprocess.py` (in-repo) |
| `HEADING_NUMBERING` | field-based numbering injector | `docstyle/heading_numbering.py` (in-repo) |
| `PROJECTION_CONFIG` | ladders-plus-profiles YAML for `--project` | `projection/profiles-example.yaml` |
| `QC_SCRIPT` / `NLQA_DIR` / `PAGECHECK_SCRIPT` | optional pre/post checks | off when unset |
| `QC_BLOCKING` | `1` makes a `QC_SCRIPT` finding stop the render (`--qc-blocking` is the flag form) | `0` (advisory) |
| `POSTRENDER_GATE_SCRIPT` | post-render gate, called with the finished `<docx>` (`--postrender-gate`) | off when unset |
| `POSTRENDER_GATE_ADVISORY` | `1` makes a `POSTRENDER_GATE_SCRIPT` finding advisory instead of blocking | `0` (blocking) |
| `PDF_CONVERTER_PS1` | Windows Word-COM converter; otherwise LibreOffice is used when present | LibreOffice fallback |
| `OUTPUT_DIR` / `RESOURCE_PATH` / `PANDOC` / `PYTHON` | output, image root, tool overrides | `./renders`, source dir, PATH |

**One shared markdown-reader extension string.** Every call site that reads a renderfact markdown
source into pandoc's AST (`container/render-doc.sh` for DOCX, `pdf/typst_backend.py` for PDF) builds
its `--from` value from `pandoc_markdown.MARKDOWN_FROM` (Python callers import it; `render-doc.sh`
shells out to `python pandoc_markdown.py`) instead of hand-rolling its own extension list. This is a
single source of truth for `wikilinks_title_after_pipe`, the extension that makes
`[[target|Display Text]]` bracket links resolve to their display text: without it, pandoc's plain
`markdown` reader treats the brackets as literal punctuation rather than a `Link` node (issue #69).

A consumer keeps a thin wrapper that exports the variables it needs. There is no hardcoded host path
and no assumed tree layout: the pipeline is generic core, the wrapper is private skin.

**The gate-hook contract (D18).** `render-doc.sh` has two fail-closed hook points, and they default
OPPOSITE ways on purpose:

- `QC_SCRIPT` runs pre-render, against the SOURCE markdown, and defaults to ADVISORY (findings print;
  the render continues). This is the more common case for lint-shaped pre-render checks, so it stays
  the default; `QC_BLOCKING=1` / `--qc-blocking` opts a consumer into fail-closed.
- `POSTRENDER_GATE_SCRIPT` runs post-render, against the FINISHED `<docx>` (after style, numbering,
  and provenance have all touched it, before the completion summary), and defaults to BLOCKING (a
  non-zero exit stops the run). Its purpose is "does the artifact contain content it must never
  contain", not a lint pass a human might skim past in scrollback; a silently-advisory default would
  undermine the one property the hook exists to guarantee. `POSTRENDER_GATE_ADVISORY=1` opts back into
  advisory-only for a consumer that wants report-only behaviour.

`gates/content_scan.py` is the generic reference implementation a consumer skin points
`POSTRENDER_GATE_SCRIPT` at: it opens the DOCX with python-docx and regex-scans every paragraph and
every table cell (recursively into nested tables) for a caller-supplied pattern, exiting 1 on any hit.
It ships with NO default pattern (D3: the pattern is a required parameter, supplied via `--pattern`,
`--pattern-file`, or the `RENDERFACT_GATE_PATTERN` / `RENDERFACT_GATE_PATTERN_FILE` env vars for
zero-arg hook invocation) so the public core stays domain-neutral.

## The projection engine

`projection/projector.py` (the `render project` mode) turns one SOURCE with profiled fenced-div
blocks into one governed RENDER per PROFILE. It implements conditional processing at the PREPROCESSOR
level: excluded content never enters any downstream parse tree, which is the correct, harder boundary
for a genuine no-read-up clearance gate (excluded content is gone before pandoc or any engine sees it).

Blocks are pandoc fenced divs:

```
::: {.block clearance="secret" releasable="partners" detail="true" lang="en" audience="reviewer"}
...content...
:::
```

**Gate semantics**, per block, against the active profile:

- **clearance (no-read-up):** the block's clearance rank must be less than or equal to the profile's
  ceiling. An unlabelled block is the lowest rank.
- **distribution:** the block's allowed extent must cover how far this render travels. An unlabelled
  block is the widest extent.
- **disclosure posture** (full > contextual > minimal): `detail="true"` blocks appear only in the
  full posture; `variant="abstract"` blocks REPLACE detail in non-full postures; `softspot="true"`
  blocks drop below the contextual posture.
- **language select:** keep blocks matching the profile language or language-neutral ones.
- **audience:** a per-block allow-list (`audience=`) and deny-list (`hide=`).
- **gloss-inject:** an optional term bank glosses the first body occurrence of terms the profile's
  audience does not already know.

**Ladders are consumer-defined.** The clearance and distribution vocabularies are ORDERED lists in
the profiles YAML (rank equals list position). The engine ships no classification vocabulary of its
own; the `profiles-example.yaml` ladders are an illustration, not a standard.

**Fail-closed rule.** A block or profile using a clearance or distribution value that is absent from
the configured ladder raises `ProjectionError` rather than being ranked lowest. A gate that guesses is
not a gate. This is a deliberate hardening over the reference implementation, which treated unknown
values as most-permissive.

**Header stamping (D14-aware).** The projected output carries an HTML comment stamping the profile
name, gate parameters, and dropped-block count. Profiles for externally-bound renders set
`stamp_header: false` to suppress it, the same audience-awareness principle as the provenance rule.

## docstyle: the template-profile mechanism

`docstyle/style_postprocess.py` and `docstyle/heading_numbering.py` are the default style and
numbering steps of the DOCX pipeline: with zero consumer config they render a styled, field-numbered
document out of the box, and consumers override with `--template-profile`.

- **style_postprocess** applies a neutral default house style (font, heading sizes and accent colour,
  table borders and header fill, A4 page geometry, header/footer handling). Everything
  organisation-specific (palette, font, geometry, marking-text replacements, cover labels,
  punctuation normalization) is plain data in an optional profile YAML. The profile mechanism is
  purely additive: with no profile the neutral defaults apply and no marking edits are made. A profile
  can be hand-written, or (roadmap C7) derived from an imported corporate template.
- **heading_numbering** injects field-based heading numbering AFTER pandoc, because pandoc regenerates
  the numbering part on every render and drops custom list definitions imported from a reference doc.
  It injects a multilevel list bound to Heading1..9 so the section numbers are Word FIELDS that
  renumber automatically on insert / reorder / delete. It is idempotent: re-running on an
  already-numbered document is a no-op. The source carries number-free headings.

`render docx` (render-doc.sh) invokes `style_postprocess.py` directly as a subprocess for its own
house-style pass; that call path is unchanged. `render docstyle` (issue #74) is an additional,
directly documented entry point onto the same `main()`, for callers who want the post-processor's
capabilities (most notably `--table-widths`, which the `docx` pipeline does not pass through today)
without going through the full DOCX pipeline.

## The D8 dual-mode step contract

Every LLM-touching step has an IDENTICAL input/output contract whether it runs through an agentic
harness or a human copy-pasting into a chat LLM (D8). The same validator accepts or rejects output
from either source with no special-casing.

- `contracts/schema_utils.py` is the shared, domain-agnostic validator: a `FieldSpec` (name, type,
  required, allowed-values, and a nested `item_schema` for list-of-object fields, carried as DATA so a
  doc generator can introspect the nested shape, not as an opaque closure only the validator can run).
- `lint/vision_review_contract.py` is the first concrete step: a fixed task intent, an input schema
  (task intent, rendered-image path, tier, and deterministic metrics: the vision-plus-spec
  dual-context idea, handing the reviewer both the image and hard numbers, never vision alone), and an
  output schema (a status vocabulary, a findings list, a summary, and a reviewer-mode field used for
  provenance only, never as a quality signal).
- `contracts/init_ai.py` (`render init-ai`) is harness mode: it installs renderfact-aware instruction
  files into the user's OWN assistant, with zero LLM-calling code of renderfact's own. Every
  instruction is GENERATED from the step contract's field list, never hand-typed, so the code wins if
  the file and the code ever disagree.
- `contracts/copy_paste.py` (`render copy-paste`) is the no-harness fallback: it composes the same
  prompt, delivers it (stdout, a scratch file, and a best-effort clipboard copy with no new pip
  dependency), captures the pasted reply over stdin, parses it (JSON, then fence-stripped JSON, then
  YAML), and validates it against the same contract in a bounded retry loop.

## Provenance and round-trip

`roundtrip/provenance.py` and `roundtrip/source_uid.py` embed hidden provenance in every rendered
editable Office document.

- **Mechanism:** a single JSON blob in the OOXML core property `dc:identifier` (`docProps/core.xml`),
  the SAME schema across DOCX / XLSX / PPTX. One property, not one per fact, because every other core
  property has native Office meaning a user might set. SVG/PNG (visual, not round-trippable) and PDF
  (a flattened archival format) are deliberately excluded.
- **What it records:** the source's stable UID (persisted once in the source's own frontmatter,
  without reformatting it), a content version (a hash of the source at render time, separate from
  identity), the render timestamp, and the tool version.
- **Operations:** `embed`, `extract`, `adopt` (bootstrap a minimal honest stub source for an
  externally-authored artifact with no source yet), and `retarget` (carry provenance onto a
  differently-formatted artifact of the same content). Both `adopt` and `retarget` refuse the ways a
  caller could silently lose history.

**Projection-aware policy (D14):** provenance is a function of the projection profile. Internal
profiles embed full provenance (round-trip intact); external / publish profiles strip it entirely. An
opaque-token mode is a documented future extension. Until the strip mechanism is implemented, every
externally-bound artifact is treated as manually-scrub-required.

**The out-for-review three-way merge (the reason provenance is not refreshed on edit).** Source V1 is
rendered and sent for comments. The operator edits the source to V2 in the meantime. The commented
DOCX returns: its provenance still records hash(V1), while the current source hashes to V2. That
MISMATCH is exactly what routes re-ingestion into a three-way conflict merge, with V1 as the common
ancestor, V2 as the local branch, and the commented DOCX as the remote branch, rather than a silent
overwrite in either direction. Refreshing provenance on a source edit would FORGE the render record:
the returning DOCX would claim V2 ancestry, re-ingestion would fast-forward, and the V1-to-V2 edits
would be silently stomped. So the editor and any save-path never refresh provenance; only a real
`render` or `retarget` stamps it. A `source_commit` field, stamped at render time only when the
source sits in a clean git work tree, makes ancestor recovery a direct `git show`.

## Pre-publish QA gate chain (B3)

`gates/run_gates.py` (`render gate`) is the fail-closed sibling to the post-render `qa` gate below:
findings fail the run, AND a requested stage whose tool is not installed also fails the run (exit 2):
a gate you cannot execute is not a gate you passed. Every stage is a deterministic CLI subprocess
or dependency-free Python, no LLM anywhere. Default chain: `vale,lychee,verapdf,uids,plainlang`,
each stage self-scoping by file type so one `render gate <dir>` run applies each stage to the files
it understands.

- `vale`: text hygiene on markdown sources (errata-ai/vale). The generic-core default
  (`gates/vale/vale.ini`) ships only Vale's built-in checks (repetition blocks, spelling warns);
  a consumer's writing doctrine is private-skin config (`--vale-config` / `RENDERFACT_VALE_CONFIG`).
  The demo skin (`demo/skin/vale/vale.ini`) is the worked example: `GoldenRules` (the deterministic
  slice of a house writing style), `AiTells` (vendored authorial-AI-tell detection: filler phrases,
  hedging, formal register, and so on), and `PlainLanguage` (issue #76: reader-facing plain-language
  quality, a distinct concern from AiTells: sentence length and nominalisation density, both
  warning-level advisory rather than blocking, since both are tunable heuristics rather than
  clear-cut defects). `BeNl` (BE-NL lexical checks) is opt-in via a separate `vale.be-nl.ini`.
- `lychee`: link integrity on markdown sources (lycheeverse/lychee), offline by default (relative
  file links and anchors only, so the verdict is deterministic); `--online` opts into checking
  external URLs.
- `verapdf`: PDF/A and PDF/UA conformance on rendered PDFs (veraPDF, invoked as a CLI subprocess per
  the dual GPL/MPL licence election). Validates against each PDF's declared standard by default;
  `--pdf-flavour` forces one.
- `uids`: duplicate `renderfact_uid` detection across a source tree. A file copy duplicates identity
  (uuid4 generation cannot collide, but a fork or template carrying an existing uid claims the
  original's lineage), which corrupts every provenance-anchored round-trip at organisational scale.
  Dependency-free.
- `plainlang`: repeated-phrase-across-sections scan (issue #76), a cheap n-gram/exact-match scan
  over markdown sources (`docstyle/plain_language.py`) for the same multi-word phrase recurring
  near-verbatim 3+ times in one document. The one PlainLanguage check that is NOT a Vale rule: Vale's
  rule types all match a pattern fixed at authoring time, and this check needs the document's own
  text as the source of the pattern to search for, which the DSL cannot express. UNLIKE every other
  stage here, a finding does not fail the run by default (`--plainlang-fail-on-hits` opts in): a
  repeated phrase is very often legitimate (a programme or component name used consistently), so
  fail-closed-by-default would make it noise rather than signal, in the same
  `render qa leaks --fail-on-hits` report-only shape used below.

## Post-render QA gate

`lint/render_qa.py` (`render qa`) is a deterministic, zero-LLM gate over rendered artifacts, run
BEFORE any vision/LLM pass (hard numbers accompany every subjective review):

- `leaks <full.txt>`: an audience-leak scan on rendered text for internal remnants that should never
  survive projection. Consumer-specific probes (codenames, internal paths) come from a `--probes`
  config merged over generic defaults.
- `tables <render.docx>`: per-table column-geometry pressure (content share vs width share).
- `paras <render.docx>`: overweight-paragraph ranking (simplification candidates).
- `figs <source.md>`: figure inventory plus a low-contrast pre-filter.

Report-only by default; `leaks --fail-on-hits` exits non-zero for CI gating.

## Comprehension gate: a fresh reader for text documents (issue #84)

`lint/comprehension_review_contract.py` (`render comprehension-review`) is the TEXT-document peer of
`lint/vision_review_contract.py`'s diagram vision-review gate. Where `render qa` above is deterministic
and zero-LLM by design, and Vale/AiTells catch phrasing patterns, neither can answer "does a reader who
has never seen this document understand what each section is for, and where does the flow break down."
That is a comprehension question, downstream of style and structure, and needs an actual fresh read --
the same author-independence principle the diagram gate already relies on for its own review to mean
anything.

- **Chunking.** The rendered document (`.md` or `.docx`, python-docx extracts the latter into the same
  markdown-ish shape) is split into reader-sized snippets, first at ATX heading (leaf-section) boundaries
  and only then, when a section runs long, at paragraph boundaries within it -- fence-aware, so a `#`
  inside a code fence or a `:::` block is never mistaken for a boundary. A single paragraph over budget
  stays whole rather than being cut mid-sentence; `render qa paras` already flags it deterministically.
- **The D8 contract.** One INPUT_SCHEMA (task intent, doc title, the ordered chunk list) and one
  OUTPUT_SCHEMA (a status, one finding per chunk -- purpose / confusing / fluff / cuttable -- plus a
  whole-document synthesis: doc purpose, worst-flow snippet, what a length-budget cut removes first),
  identical across harness, copy-paste, and the D17 direct-API channel, reusing
  `contracts/schema_utils.py` / `contracts/copy_paste.py` / `contracts/init_ai.py` exactly as vision-review
  does.
- **The D16 gate, with no accept path.** Every other gated step (vision-review, decision-capture,
  contextualize) has a deterministic proxy for "the model's judgment probably is not needed here."
  Comprehension does not: document length, section count, and similar structural signals predict review
  COST, not comprehension risk, in either direction. `confidence()` is therefore pinned at a CONSTANT
  0.0 rather than dressing up a guess as a measurement -- this step always escalates unless an operator
  explicitly sets `--threshold <= 0`, in which case an honest "not reviewed" stub is emitted
  (`reviewer_mode: deterministic`, `status: WARN`), never a fabricated verdict. See `docs/DECISIONS.md`
  D19 for the recorded decision and why this is a legitimate D16 outcome, not a departure from it.
- **Report-only.** Findings are printed (or emitted as JSON); nothing is rewritten. The cut/rewrite
  decision stays with a human, per the same propose-only contract every gated step in this repo follows.

## API security posture

`api/app.py` (`render serve`) is a stdlib WSGI app exposing the D8 step contracts (list, introspect,
validate) and the projection engine over HTTP: the same code paths the CLI uses. The reference UI is
one deliberately thin client, mounted at an opt-in `/ui`; `/openapi.json` and a self-contained `/docs`
page describe the surface.

The guard set (D9 hardened past a read-server posture per D15) runs on every request:

- binds `127.0.0.1` by default; binding wider prints an explicit runtime warning that the server has
  NO authentication or authorization controls;
- rejects any non-loopback `Host` header with 403 (DNS-rebinding protection);
- on every POST, rejects browser-signaled cross-origin requests (an `Origin` or `Sec-Fetch-Site`
  allowlist; non-browser clients that carry neither header pass);
- jails every request-named filesystem path under `--root` (default: the working directory at start);
- applies a fixed-window per-client rate limit (429 when exceeded);
- issues a per-session CSRF token from `/session`, ready for the first truly-mutating route.

Current routes are compute/read-only; the CSRF mechanism exists for the editor's write endpoints.

## Structured source editor (specified, not built)

The editor is a reference client of the API and a direct-edit (third D8) mode. The design is settled;
implementation is sequenced behind the release-engineering track (D13).

- **Markdown (three panes):** the edit unit is the LEAF section, an ATX heading plus everything up to
  the next heading of any level; the nav tree still shows the full hierarchy. The splitter is
  fence-aware (a `#` inside a code fence or a `:::` block is content, not a boundary). Frontmatter is
  section 0. Each section carries a content hash, which is the concurrency token (not the index).
- **Right-pane preview is hybrid:** live-approximate client-side (a vendored markdown renderer, KaTeX,
  mermaid.js) for orientation; exact server-side on demand through the real engines (`d2` / `typst` /
  `likec4` are server-only, since no faithful client equivalent exists).
- **Save is explicit or on navigate-away.** A save with a detected diff REQUIRES a non-empty commit
  message, enforced server-side, and produces exactly one git commit whose message becomes the
  decision-intent entry. The write route (`PUT /editor/section`) is the first CSRF-required mutating
  route and 409s on a stale base hash.
- **XLSX (two panes):** a canonical YAML source, dense row-major with one row per line so a row insert
  or a cell edit is a one-line git diff (cell-address-keyed maps were rejected: one insert renumbers
  the whole sheet). Formula cells are `{f, v}` mappings; there is no formula recompute in v1 (a stale
  badge instead). Formatting is out of scope for the canonical source; presentation is render-side.
- **PPTX:** the canonical source is slide-level Marp-flavored markdown; shape-level pixel positioning
  is declined as a canonical-source feature (coordinate soup fails the human-readable bar). The
  deck-engine choice is resolved by a small bench inside the PPTX implementation, not unilaterally here.

## Layout

```
render.py    single entry point: render <mode> [args...]
projection/  the projection engine: profiled blocks -> one governed render per profile
docstyle/    generic DOCX house-style post-processor + field-based heading numbering
api/         stdlib HTTP API (step contracts + projection over localhost) + thin reference UI
container/   OCI image (Containerfile) + render wrapper + render-doc.sh + bundle-annex-linux.py + verify-pins.sh
lint/        diagram render harness + pre-render linters + visual-QA metrics + the D8 step contract + render_qa
tokens/      brand.yaml token mechanism + per-engine generators (tokens/gen/)
contracts/   the generic D8 I/O-contract validator + harness-mode installer + copy-paste fallback
gates/       fail-closed QA gate chain (run_gates.py, B3) + content_scan.py, the generic
             post-render content-safety regex-scan gate (D18)
roundtrip/   provenance embed/extract/adopt/retarget + stable source UID (named to avoid shadowing python-docx)
demo/        a fictional railway-operator tender dossier exercising every projection gate
docs/        DECISIONS + ROADMAP + ARCHITECTURE + CONTRIBUTING + SECURITY
tests/       fixture-based tests, built programmatically (no binary fixtures)
tools.lock   pinned engine versions (single source of truth)
pyproject.toml  Python dependency manifest + `render` console entry point
```
