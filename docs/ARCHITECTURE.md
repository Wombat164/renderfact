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
| `diagram` | mermaid / d2 rendering with pre-render lint, visual-QA metrics, and (issue #68) the `layered-stack` archetype generator | shipped |
| `tokens` | `brand.yaml` -> per-engine themes (mermaid JSON, marp CSS, pandoc profile, typst tokens) | shipped |
| `init-ai` | install D8 step instructions into the user's own assistant | shipped |
| `copy-paste` | run a D8 step with no harness: assemble a prompt, paste the reply back | shipped |
| `provenance` | embed / extract / adopt / retarget hidden source provenance across DOCX/XLSX/PPTX | shipped |
| `import-template` | derive a template profile (theme, fonts, geometry) from a branded DOCX, with an idempotency gate | shipped |
| `qa` | deterministic post-render gate (leaks / tables / paras / figs / purpose) | shipped |
| `gate` | fail-closed pre-publish QA gate chain (vale / lychee / verapdf / uids / plainlang) | shipped |
| `comprehension-review` | fresh-reader comprehension gate for a rendered text document (D16-gated, always escalates); the text peer of the diagram vision-review gate (issue #84) | shipped |
| `serve` | localhost HTTP API plus opt-in thin reference UI | shipped |
| `container` | raw passthrough to the OCI render wrapper | shipped |
| `doctor` | native version-drift check against `tools.lock` | stub, not built |
| `eml` | annotated markdown -> a plain-text, sendable RFC822 `.eml`, with a skin-supplied signature block (issue #95) | shipped |
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
| `TEMPLATE_PROFILE` | YAML consumed by the style post-processor; a top-level `toc: false` key also opts out of the table of contents (`--no-toc` is the flag form; either is sufficient, issue #99) | none (neutral defaults) |
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

The same shared string also pins `raw_attribute` (issue #96): the reader extension that turns a
fenced code block tagged ` ```{=openxml} ` into a genuine `RawBlock` AST node instead of an inert,
literal code block. This is a manual, advanced escape hatch, DONE and verified end-to-end into the
DOCX pipeline (a hand-authored ` ```{=openxml} ` block containing raw OOXML now reaches
`word/document.xml` verbatim), not a first-class markdown feature: authoring OOXML by hand is fragile
and requires no validation from the toolchain. It exists specifically because two structural gaps have
no markdown syntax at all today: Word content controls (`w:sdt` checkboxes/dropdowns) and
merged/spanned table cells (`gridSpan`). Native, ergonomic markdown syntax for either is
roadmap-only, tracked as a follow-up to #96, not part of this escape hatch. On the PDF/typst path the
same RawBlock is present in the AST but is silently dropped by the typst writer (it does not recognise
the `openxml` format tag), the same filtering pandoc already applies to an unrecognised `raw_html`
block, so the shared constant needs no path-specific carve-out.

A consumer keeps a thin wrapper that exports the variables it needs. There is no hardcoded host path
and no assumed tree layout: the pipeline is generic core, the wrapper is private skin.

**Table of contents opt-out (issue #99).** `--toc --toc-depth=2` used to be hardcoded into the pandoc
invocation with no way to turn it off, a fidelity problem for a short document (a one-to-two-page
template, say) that never had a table of contents in the original. `--no-toc` (CLI) and `toc: false`
(a top-level key in the `--template-profile` YAML) both disable it; either one is sufficient, the same
either-one-is-enough interaction as `QC_BLOCKING` / `--qc-blocking`. The default stays on (today's
behavior), so this is a pure opt-out: nothing already depending on the table of contents breaks.

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
  can be hand-written, or (roadmap C7) derived from an imported corporate template. A single global
  `font` key cannot represent a template that uses distinct fonts on distinct paragraph styles (issue
  #97), so the profile's optional `styles:` block carries per-named-style font overrides, falling back
  to `font` for any style not listed; a template that only ever uses one font derives an empty block
  and renders identically to before this key existed.
- **import-template's per-style font derivation (issue #97).** `derive_style_font_overrides` walks
  EVERY paragraph `w:style` definition's `w:rPr/w:rFonts` (the same one-level `basedOn` fallback
  `style_font_info` already applies to Normal/Heading), not just the handful of named styles C7 already
  special-cases, and keeps only the GENUINE overrides: a style whose resolved font differs from the
  derived global `font`. A style that happens to resolve to the same font as the global default is
  left out, keeping the derived profile minimal rather than padding it with redundant per-style
  entries. When no style differs, the generated profile carries a one-line note instead of an empty
  block, the same honesty-over-guessing posture the theme keys already follow.
- **Custom-style font fidelity (issue #98, D21).** The house body font/size pass respects a
  paragraph's own custom style by default: a paragraph carrying a style outside the built-in/default
  set (e.g. reached via a pandoc `::: {custom-style="X"} ... :::` fenced div) whose OWN `w:rPr`
  already defines a font/size is left with no direct-formatting run override, so it falls through to
  pure style inheritance instead of being stomped with the house look. Built-in categories
  (Title/Subtitle/Heading 1-4) and the generic default-body case are unaffected. The pre-#98 blanket
  override is available as an explicit opt-in: `--override-custom-style-fonts` (CLI) or
  `override_custom_style_fonts: true` (template-profile.yaml). Note (#97+#98 interaction): when a
  custom style is respected (this bullet), its own font wins outright; when it is NOT respected (the
  paragraph is in the known-non-custom set, or `--override-custom-style-fonts` forces it), the
  per-style `styles:` override above still applies to it if one is configured for that style name,
  falling back to the global `font` otherwise.
- **heading_numbering** injects field-based heading numbering AFTER pandoc, because pandoc regenerates
  the numbering part on every render and drops custom list definitions imported from a reference doc.
  It injects a multilevel list bound to Heading1..9 so the section numbers are Word FIELDS that
  renumber automatically on insert / reorder / delete. It is idempotent: re-running on an
  already-numbered document is a no-op. The source carries number-free headings.
- **Guidance-doc scan (issue #100).** A branded template often ships alongside a SEPARATE document
  (a policy/methodology paper explaining what each section is for, what's out of scope, how it fits
  the surrounding process) that `import-template` previously had no awareness of. `--guidance-doc
  <path>` (`.docx`/`.md`/`.markdown`/`.txt`) runs a MECHANICAL structural scan (`scan_guidance_doc`):
  heading count, body-paragraph count, and a capped heading-text preview, surfaced back to the
  operator as a pointer toward hand-seeding `editorial-doctrine.yaml` (issue #84's concept, not yet
  built) — deliberately not automated extraction, which is a judgment-heavy summarization task. When
  `--guidance-doc` is omitted, `import-template` prints a one-line reminder rather than a blocking
  stdin prompt (this CLI has no other interactive input, and a prompt would hang CI/scripted runs),
  at the one moment an operator has both artifacts in hand and is thinking about this template.

`render docx` (render-doc.sh) invokes `style_postprocess.py` directly as a subprocess for its own
house-style pass; that call path is unchanged. `render docstyle` (issue #74) is an additional,
directly documented entry point onto the same `main()`, for callers who want the post-processor's
capabilities (most notably `--table-widths`, which the `docx` pipeline does not pass through today)
without going through the full DOCX pipeline.

## Email output: `.eml` with a skin-supplied signature block (issue #95)

`mail/eml_backend.py` (`render eml`) is the email peer of the DOCX and PDF paths: a governed markdown
source becomes a directly-openable, plain-text RFC822 `.eml`, closing the gap where the actual
deliverable is an email rather than a rendered document (previously bridged by hand: copy the
rendered body into a mail client, re-add the signature, with no reconciliation path back to source
the way DOCX has `reingest`). See `docs/DECISIONS.md` D22 for why this is `.eml` (RFC822) rather than
the binary Outlook `.msg`/MAPI format or mail-client compose-window automation.

- **Body.** The markdown body is translated with pandoc's plain-text writer, over the same shared
  `pandoc_markdown.MARKDOWN_FROM` `--from` value every markdown-reading call site in this repo uses
  (issue #69: without `wikilinks_title_after_pipe` a `[[target|Display Text]]` link's display text
  never resolves). `--reference-links` keeps a link's URL from being silently dropped: pandoc's
  plain writer otherwise renders `[text](url)` as bare `text`; with the flag, the target lands in a
  trailing `[text]: url` reference list instead, plain-text-readable and lossless.
- **Signature-block config.** A skin's `signature.yaml` (see `mail/signature-example.yaml`, the
  worked, entirely fictional example) declares `lines:`, a freeform list of strings appended after
  the body, the same non-enum, freeform posture `dossier_role` (below) and the projection engine's
  clearance/distribution ladders use, rather than a rigid name/title/department/phone schema. It lives
  as its own file (the `docstyle/template-profile-example.yaml` / `projection/profiles-example.yaml`
  naming and loading pattern), not folded into `brand.yaml`: the signature block is CONTENT, and
  `brand.yaml` is DESIGN TOKENS consumed by a deep-merge generator pipeline with a fixed known-keys
  schema. The lines are joined onto the body after the sig-dash delimiter `-- ` alone on its own line
  (the long-standing plain-text-email convention mutt/Thunderbird/Gmail/Outlook all recognize to fold
  or strip a signature on reply): a different token from this repo's own prose "spaced double-hyphen"
  ban (CONTRIBUTING.md), which targets a dash used as sentence punctuation, not a stand-alone protocol
  marker with no text before or after it on its own line. `signature.yaml` MAY also declare `images:`,
  a list of PNG file paths (skin-relative, PNG-only, fail-closed on any other extension): each becomes
  its own `Content-Disposition: inline` `image/png` MIME part (`EmailMessage.add_attachment`, which
  promotes the message to `multipart/mixed` automatically on first use), so a logo genuinely travels
  embedded inside the `.eml` rather than as a hyperlink to a hosted image. No HTML part is generated in
  v1 (a `multipart/alternative` + `multipart/related` styled HTML signature is a materially larger,
  explicitly deferred extension (`docs/ROADMAP.md` Track J).
- **Frontmatter-to-header mapping.** `recipient:` (with `to:` as a synonym) maps to the `.eml`'s `To:`
  header; `subject:` (with the document's own `title:` as the natural fallback, and the source's
  filename stem as the last-resort default) maps to `Subject:`. Both are read via the same byte-
  preserving, read-only frontmatter idiom `roundtrip/dossier_role.read_dossier_role()` uses (locate
  the `---`-delimited block, `yaml.safe_load` one or two keys, never write anything back); an explicit
  `--recipient`/`--subject`/`--sender` on the command line wins over the frontmatter value. A missing
  recipient is advisory, not fatal: a WARNING to stderr, and an `.eml` with no `To:` header, useful
  for a draft written before the addressee is settled, the same "still produces a valid, honest
  artifact with less input" posture every optional skin-config flag in this repo takes.
- **Headers and tool reuse.** `Date:` and a deterministic, non-host-leaking `Message-ID:` (a fixed
  `renderfact.invalid` placeholder domain, RFC 2606 reserved, rather than `email.utils.make_msgid()`'s
  own default of this build machine's real hostname) are stamped on every render. Pandoc discovery
  reuses `pdf/typst_backend.find_pandoc()` directly (env override, then PATH, then known Windows
  install dirs) rather than re-implementing tool resolution a third time.
- **Out of scope, by design (this PR).** A binary `.msg`/MAPI writer, and driving a local mail
  client's compose window through a platform-specific automation interface: both are heavier,
  platform-specific follow-up work that would not add anything `.eml` does not already deliver for
  the "sendable, reconcilable email" need (`docs/DECISIONS.md` D22 has the full reasoning).

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

## Purpose annotations and dossier role

A purely annotative authoring convention (#77): a structural place to record WHY a paragraph, section,
or whole document exists, so a later editor (human or LLM) can tell "this is here on purpose, cutting
it loses something" from "this is here because it was true, not because it was needed." Neither piece
below is a new hard gate; both degrade to nothing for a consumer who ignores them, which is what makes
them safe to adopt gradually or not at all.

**Paragraph/section purpose comments.** An HTML comment stated immediately above the paragraph or
heading it explains:

```markdown
<!-- PURPOSE: states the tradeoff up front so a skimming reader gets the decision before the detail -->

## Cost vs lead time

...
```

Pandoc's markdown reader parses `<!-- ... -->` as a raw-HTML AST node that neither the DOCX writer nor
the typst writer (the PDF path's markdown-to-typst-markup step) ever emits: a raw HTML comment is
simply dropped. This is verified EMPIRICALLY, not assumed: `tests/test_purpose_annotations.py` drives
the real `render docx` pipeline (subprocess pandoc) and `pdf/typst_backend.md_to_typst` (the same
pandoc call the PDF backend makes; typst itself never parses the original markdown, so this is the
correct checkpoint) over a fixture containing the marker, and asserts it is absent from both outputs.
The same mechanism already backs D14's projection-provenance header stamp (`projector.py`'s
`<!-- projected: ... -->` line) -- this convention is the same trick, generalized from per-document
render metadata to per-block authoring intent. Zero render risk: a consumer who never adopts the
convention loses nothing, and an adopter's comments never reach a reader.

**Document-level dossier role.** A frontmatter field, `dossier_role:`, stating what a document
uniquely contributes relative to its siblings in a broader dossier/collection: what would be lost if
this document did not exist, that no sibling already covers.

```yaml
---
title: Onboarding overview
dossier_role: the single-page entry point; every other document in this dossier goes deeper on one facet
---
```

Freeform, consumer-defined text, not an enum -- the same non-enum posture as the projection engine's
clearance/distribution ladders: the engine ships no fixed dossier-role vocabulary of its own, so any
string is accepted verbatim. Read via `roundtrip/dossier_role.read_dossier_role()`, following the
repo's existing frontmatter-read idiom (the same regex-then-`yaml.safe_load` pattern as
`gates/run_gates.py`'s `run_uids` and `roundtrip/source_uid.py`) rather than a new parsing path:
locate the `---`-delimited body, read the one key, write nothing back.

**Optional advisory lint (`render qa purpose`).** Flags a paragraph or heading with no purpose comment
immediately above it, when a paragraph's word count is at or above `--min-words` (default 40) or the
block is a heading (a section boundary is always considered prominent). Report-only, the SAME
never-fails posture as `QC_SCRIPT`'s default (off/advisory, never blocking): the command always exits
0. This is a nudge, not a gate -- not every document needs this level of authoring rigor.

**Non-goals, by design.** No blocking enforcement of missing annotations (a document that never adopts
the convention pays no penalty), and no automatic purpose inference (e.g. an LLM summarization pass
over existing prose): the discipline's whole value is the author stating intent explicitly, which a
summarizer cannot reconstruct after the fact from text that was never written with that intent.

## Diagram archetypes

`lint/layered_stack.py` is the first entry in a diagram-archetype family (ROADMAP.md Track C1a):
a purpose-built generator for one recurring architecture shape, as opposed to a hand-drawn mermaid/d2
diagram. `render diagram` dispatches to it by CONTENT sniff, not a new subcommand: a `.yaml`/`.yml`
file whose top level carries `archetype: layered-stack` is parsed, validated, and rendered to D2
(then through the existing D2 -> svg -> pdf pipeline, unchanged); any other `.yaml`/`.yml` file is
skipped, the same as any unsupported extension.

- **Shape (issue #68, FR1-FR3):** an ordered technology stack, top to bottom, with an explicit,
  visually distinct INTERFACE boundary between adjacent layers (D2 `shape: oval`, a fixed status.info
  fill, and a thicker stroke - ArchiMate's ball-and-socket convention as the visual precedent,
  not drawn literally), and a `chains` segment supporting N parallel REALIZING CHAINS laid out side
  by side under one shared interface via a D2 `grid-columns` container (N=1 is the degenerate,
  default case: an ordinary pass-through segment of the stack). The source is plain, hand-authored
  renderfact YAML - no dependency on Archi or any ArchiMate file.
- **Styling:** brand.yaml ROLES (colour.brand.fill/primary/ink, colour.status.info, the colour.data
  Wong-8 categorical palette for distinguishing parallel chains) are resolved to literal D2
  `style.*` values at generation time - the same resolution pattern `tokens/gen/mermaid_theme.py`
  uses for Mermaid, adapted for D2's inline styling since D2 has no external theme-file injection
  mechanism to target the way `mmdc --configFile` does. D2's built-in renderer only ships a small
  fixed font set and rejects arbitrary family names outright, so `type.body_font` is deliberately NOT
  applied - documented as an engine limitation, the same honesty `mermaid_theme.py` already applies
  to its own theme-system gaps, rather than silently dropped.
- **NFR6 element budget:** the model's semantic element count (every layer box, interface marker, and
  per-chain layer box) is checked against `lint/element_budget.py`'s EXISTING tier budgets - the same
  table the generic `.d2`/`.mmd`/`.svg` line-count linter already enforces - and fails closed with an
  actionable "split this into multiple views" message before any D2 is generated.
- **Deliberately out of scope:** the issue's own FR4-FR7 (an optional ArchiMate Exchange-XML adapter:
  stdlib-only XML parsing, ArchiMate layer/element-type mapping, fail-closed on an unsupported
  construct, content-sniff dispatch alongside the plain-YAML source) is tracked as its own follow-up
  issue, not built here. The core archetype has zero ArchiMate awareness and no optional dependency of
  any kind.

**Text-delta normalization (issue #72).** `roundtrip/reingest.py`'s `## 4. Text delta` /
`## 5. Fast-forward plan` compare canonical-markdown lines against DOCX paragraph text, so any
pandoc source syntax that never renders as literal DOCX text must be stripped from the markdown
side first, or its absence reads as a false reviewer deletion. Two tiers: a pre-split, whole-block
regex pass in `md_plaintext()` (frontmatter, HTML comments, and raw-attribute OOXML blocks such as
a manual page break's ` ```{=openxml} ... ``` `, which spans multiple lines and cannot be stripped
per-line) and a per-line pass in `_norm()` (non-breaking spaces, list bullets, auto-numbered
headings, fenced-div `::: {...}` / `:::` lines, the blockquote `> ` marker). `render reingest
--strip-pattern <regex>` (repeatable) adds caller-supplied patterns at the same per-line tier, for
a project's own structural-noise conventions renderfact has no reason to special-case itself.

**Table-width apply path + page-break reporting (issue #73).** The `## 3. Table column widths`
section detects reviewer-applied column widths from the edited DOCX's `w:tblGrid`/`w:tcW` (twips),
but pipe-table markdown carries no width information pandoc will honor, so there is no markdown-side
apply. `render reingest --apply-widths <out.yaml>` instead emits a sidecar in the exact shape
`docstyle/style_postprocess.py`'s `_load_table_widths()` already parses: a top-level `tables:` list of
per-column-width lists in twips, matched to document tables by ordinal position on the next render
(the same ordinal `apply_table_widths()` uses). Each entry carries a YAML comment keyed by header text
+ row count + column count (per the issue's own suggestion: two tables can share an identical header)
for human/audit stability across re-ingestion runs; the comment is not part of the consumed shape, so
the sidecar stays directly compatible with the flag `--table-widths` already wires into `render
docstyle`, no new parallel format. Written unconditionally (not gated on FAST_FORWARD/DIVERGED like
`--apply`): it captures the reviewer's current widths, a fact about the returned DOCX, not an edit to
the canonical source.
Page breaks (the pandoc `\newpage` token or a raw-openxml `<w:br w:type="page"/>`) get their own `## 3b`
report section rather than folding into the generic manual-review list: `source_page_breaks()` scans
the canonical markdown text directly for both marker forms (line numbers), and `docx_page_breaks()`
walks the edited DOCX's body paragraphs directly for a literal `<w:br w:type="page"/>` (paragraph
offsets), deliberately excluding Word's own `w:lastRenderedPageBreak` (a layout-cache marker Word
regenerates on every open, not a deliberate edit). A page-break-only paragraph carries no visible text,
so `walk_structure()`'s existing text filter (`if not txt: continue`) already keeps it out of the
text-delta/manual-review path; the direct body walk is what makes it visible to a report at all.

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
- `tables <render.docx>`: per-table column-geometry ranking, content share vs width share. Reports
  two complementary per-table signals: pressure (a column squeezed under its content, the
  `squeezed-col`) and slack (a column over-allocated relative to its content, the `wasteful-col`,
  the inverse ratio). Pressure only scores columns clearing a content-share floor, so a genuinely
  tiny column (a row-number or ordinal column) never registers there; slack scores every column,
  so an over-allocated tiny-content column still gets flagged.
- `paras <render.docx>`: overweight-paragraph ranking (simplification candidates).
- `figs <source.md>`: figure inventory plus a low-contrast pre-filter.
- `purpose <source.md>`: prominent paragraphs/headings with no preceding `<!-- PURPOSE: ... -->`
  comment (#77). Read from SOURCE, not a rendered artifact -- purpose comments never survive
  rendering, by design. Report-only; never fails (see "Purpose annotations and dossier role" above).

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
  D20 for the recorded decision and why this is a legitimate D16 outcome, not a departure from it.
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
mail/        eml_backend.py: markdown -> plain-text RFC822 .eml + a skin signature block (issue #95)
api/         stdlib HTTP API (step contracts + projection over localhost) + thin reference UI
container/   OCI image (Containerfile) + render wrapper + render-doc.sh + bundle-annex-linux.py + verify-pins.sh
lint/        diagram render harness + pre-render linters + visual-QA metrics + the D8 step contract +
             render_qa + the diagram archetype family (layered_stack.py, issue #68)
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
