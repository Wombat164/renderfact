# Decisions

Architecture decisions for renderfact, with the reasoning that informed each. This is the
historical record of WHY the toolchain is shaped the way it is; `ROADMAP.md` is what is next and
`ARCHITECTURE.md` is the system as it stands today.

Decisions are recorded as they are taken and are not rewritten when later decisions build on them;
a superseding note is added instead. Two consumer-neutrality conventions run throughout: the public
core carries no domain content, and any organisation that drives the toolchain with its own private
config is referred to only as "a private consumer" or "the reference consumer".

## D1 - Home and boundary: a standalone toolchain, migrated into incrementally

The toolchain is a standalone repo that owns the render engines, the shared logic, the token
mechanism, and the unified `render <mode>` entry point. Consumers keep only their content and their
config and call in as thin private consumers. Logic migrates out of any pre-existing in-consumer
pipeline opportunistically, never in one big-bang move. Why: reuse, CI, and OSS publishability;
decoupling from any single consumer's read-only or sensitivity constraints; the engine layer was
already effectively standalone.

## D2 - A dedicated repo

The toolchain lives in its own repo, not grown inside a pre-existing diagram-schema sandbox repo.
Why: a clean identity that is separately publishable, and a sandbox that keeps its own unrelated
R and D.

## D3 - Fully OSS and public; generic core, private skin

The public repo is architected to be domain-neutral. Private config (brand token values, reference
templates, audience personas, classification markings) and all content stay with the consumer and
never enter this repo. Why: publishability, and a proven precedent that a generic tool ships public
while its private config stays out.

## D4 - Generalize the structured-document pipeline and ship a demo

The most domain-specific pipeline (a regulated, annex-heavy procurement dossier) is generalized
into a domain-neutral governed-structured-document pipeline: cover / title-page generator, section
model, field-numbered headings, annex bundling, and source-vs-render projection. A fictional demo
dossier ships public as the showcase; any real domain config stays private with the consumer. Why:
a governed docs-as-code framework is a genuine gap, so this is the highest-value OSS surface, and
the demo is also the acceptance test that the generic-core / private-skin split actually holds with
zero domain content.

## D5 - Token format

`brand.yaml` is the single token source (the mechanism plus neutral defaults in this repo). It
generates the per-engine themes (mermaid JSON, deck CSS, pandoc template profile, typst tokens). A
consumer's palette VALUES are private config that overrides the defaults. One token source, many
generated themes.

## D6 - Delivery-mode boundary

Two delivery modes, kept separate but sharing one spine (tokens, source, diagrams): ARTIFACTS (this
toolchain: DOCX / PDF / posters / decks) versus a LIVE HTML wiki (a separate gitops consumer). They
do not merge. An optional `html` projection mode for artifact-to-wiki parity is deferred.

## D7 - Publish identity: name and licence

Name: renderfact (a double meaning: render plus artefact, what it produces, and render factory,
what it is). Licence: MIT, chosen for consistency across the maintainer's portfolio rather than a
per-repo re-litigation.

## D8 - Harness-optional accessibility: every LLM-touching step must degrade to copy-paste

Every step in this toolchain that calls an LLM (content generation, persona review, visual review,
critique, and so on) must work TWO ways, not one:

1. **Through a harness** (an agentic CLI): the harness calls the model directly, no manual
   copy-paste, fully automated. The fast path.
2. **Standalone, no harness available.** The script prompts the human for input and intent,
   assembles all the scaffolding / context / schema itself, and prints ONE detailed, self-contained
   prompt to paste into any chat-based LLM the human has access to (deliberately provider-agnostic).
   The human pastes it in, gets back structured output (JSON or YAML), and pastes THAT back into the
   script, which parses it and continues the pipeline.

Why: not every user has an agentic harness wired up with API access; some have only chat-UI access
to an LLM (for example a locked-down corporate seat with no API-key issuance). The tool should never
be useless to that user. This applies uniformly to every LLM-touching step, not just content
generation.

**Design implication:** every such step needs a clean I/O contract (a fixed input schema the script
assembles from local context, and a fixed output schema the script can parse) that is IDENTICAL
whether the LLM call happens in-process (harness mode) or out-of-band (copy-paste mode). Do not
design the schema around one mode and bolt the other on afterwards.

## D9 - API-first, thin reference UI, sequenced behind D8

The toolchain exposes a small HTTP API wrapping the same per-step I/O contracts D8 requires anyway.
A basic reference UI ships as one client of that API, built deliberately thin and undecorated so it
is obvious how to swap in a different UI: the API is the product, the reference UI is a proof it
works, not the intended end-state front end.

**Security posture:** small route surface; bind to `127.0.0.1` by default; if an operator ever binds
beyond localhost, print an explicit runtime warning to the server's own logs rather than staying
silent; rate-limit the real endpoints. A materially stronger default than a silently-exposed server
for roughly the same amount of code.

**Sequencing:** build AFTER D8's per-step contracts exist and have been proven via the CLI path
(harness mode and copy-paste mode both working end to end for at least one real step). The API's job
is then just "same contract, HTTP instead of copy-paste"; it has nothing honest to expose until the
contracts it wraps are real.

## D10 - Dual deployment mode: container is not the only path, native host Python is a real audience

A container-only default is wrong for a real chunk of the likely audience: anyone on a workstation
without a container runtime set up, or who simply does not want the container-management overhead for
a single render.

**Evidence this is a real cost, not a theoretical one:** on Windows workstations, rendering through a
containerized engine can require standing up a container machine, then working around path-translation
limits when the source lives on a cloud-synced drive (staging files through a local scratch directory
instead), path mangling on bind-mount arguments, and browser-version mismatches inside the image. The
SAME diagrams rendered through native `typst` plus `d2` already on PATH hit none of these and produced
a cleaner result. That is the general shape of container-vs-native friction on this platform.

**Decision:** support BOTH modes as first-class, not container-primary with native as an afterthought:

1. **Container mode** (current): hermetic, exact `tools.lock` versions guaranteed, best for CI and
   for anyone who wants no engines on their host at all. `verify-pins.sh` fails closed on drift.
2. **Native mode**: `render <mode>` invokes whatever engines are already on the host's PATH. A native
   equivalent of `verify-pins.sh` checks installed versions against `tools.lock` and WARNS, rather
   than failing closed, on drift (native mode cannot guarantee hermeticity the way the container can;
   that is the tradeoff the user accepts by choosing it). A native install helper installs pinned
   versions where the package managers can pin exactly, and clearly reports where they cannot.

Why this matters for D8/D9 too: the harness-optional / API-optional principles only pay off if the
underlying render step works without heavyweight infrastructure. Native mode is the deployment-layer
analog of the same accessibility goal.

## D11 - Round-trip and draft reconciliation, fully specified

Generalizes a pattern already proven in a private consumer's own reverse-pipeline (a DOCX back-port
workflow that reads reviewer-edited renders back into the canonical source plus a decision log) into
a first-class, domain-neutral capability. Four parts:

**1. Split AND embedded annex output, both available, not mutually exclusive.** `render docx`
produces a main-body DOCX plus one DOCX per annex by default; a flag also produces a merged variant
with the same annex content embedded inline. The annex content is generated once and projected
twice (standalone file plus embedded section): the one-source-many-projections principle applied
recursively at the annex level.

**2. Every render artifact carries hidden provenance metadata.** Every DOCX (main, annex,
embedded-variant) embeds, via document properties rather than the visible body, the canonical
source's stable UID, its content-hash-or-version at render time, the render timestamp, and the
render-tool version. Without this, a re-ingested DOCX cannot be checked against "what source was
this actually rendered from."

**3. Re-ingestion is idempotent, diffable, and CONTEXTUALIZING, not merely mechanical.** Feeding a
previously-rendered DOCX back into the tool extracts the hidden provenance, every tracked change /
comment / revision entry, and the current literal text; then compares the CURRENT canonical source
against the render-time-recorded version:
   - **Unchanged since render** -> clean fast-forward: apply the human's edits back onto the source.
   - **Source evolved in the meantime** (someone edited the source while the DOCX was out for review)
     -> **three-way conflict merge**: render-time source (common ancestor), current source, and the
     human-edited DOCX (the branch), same shape as a git merge conflict, never a silent overwrite in
     either direction.
   It does not merely diff: it summarizes what changed and, where inferable, why. It produces THREE
   outputs: the updated literal canonical source, a new decision-intent / justification entry
   capturing the reasoning behind the change, and confirmation that re-rendering from the updated
   source reproduces a DOCX matching what was ingested (a round-trip validation; a mismatch is a bug
   in the ingest step, not an acceptable outcome).

**4. Git is inherent infrastructure, not optional.** Every canonical-source version is a real commit.
Every render's provenance UID must trace to an exact commit (or tag) of the source it came from.
Re-ingestion produces a new commit whose message is the contextualized change summary, so the full
history (what changed, when, why, and whether it round-tripped cleanly or needed a merge) is auditable
via `git log` / `git blame` directly.

**Status: part 2 (provenance) is implemented; the rest is specified, not yet built.** Natural build
order: provenance-embed first, then split-plus-embed dual output (parallel), then mechanical
re-ingestion plus diff (single-source-unchanged case first), then the three-way conflict merge
(hardest, build last), with git-commit wiring threading through all of it.

## D12 - Structured source editor: three-pane browser UI, direct-edit mode, mandatory commit message

A browser-based UI for editing a canonical source section by section:

- **Left pane:** a navigation skeleton (the structural outline of the source), so the operator
  browses by section rather than scrolling one long document.
- **Middle pane:** the selected section's raw content, editable directly by the human.
- **Right pane:** a live rendered visualization of that section's special content: tables render as
  tables, images show inline, formulas render, diagram and Mermaid blocks render as actual diagrams
  rather than code fences.

**A third D8 mode: direct human edit.** A way to SKIP the LLM round-trip (both harness and copy-paste
modes) when the operator already knows what to write. D8 originally specified two modes for every
LLM-touching step; this adds a third path that bypasses the LLM entirely for direct source editing
(not for judgment steps like vision-review, which this editor does not replace).

**Save semantics:** an explicit Save button, or an implicit save when the operator navigates away
from a section that has unsaved edits.

**Mandatory commit-message-on-diff, feeding the decision log.** If save detects an actual content
change, the operator MUST supply a commit message before the save/commit completes: not optional,
not skippable. That message IS the decision-intent entry D11 part 3 describes, authored directly by
the human at edit time rather than LLM-inferred from tracked changes after the fact. This editor is a
second, more direct route to the same decision-log destination.

**Relationship to existing infrastructure:** it requires the HTTP API (D9) as its backend (there is
no other sane way to serve section content, accept edits, and run git operations from a browser);
each save-with-diff is a git-native commit (D11 part 4); and it complements, not replaces, the
LLM-contextualize step, which still exists for the DOCX-round-trip path where no human typed a
message in the moment.

**UI-over-API is load-bearing.** The minimal stdlib-plus-vanilla-JS frontend is ONE reference client
of the API, not the product. The API surface (list sections, get a section's content plus rendered
preview, save a section with a mandatory commit message, get a diff) must be fully usable and
documented independent of that reference frontend, so anyone can build a nicer editor (a React/Vue
SPA, a desktop app, whatever dependencies THEY want) against the same API with zero backend changes.

**D12b - the XLSX case gets a two-pane editor, not the three-pane layout.** A spreadsheet's rendered
table IS its natural edit surface; there is no meaningful "raw source" distinct from the table the
way markdown prose differs from its preview. So: left pane navigates SHEETS; right pane is a
simplified table view where cells are edited directly in place (the visualization pane and the edit
surface are the same pane). Same save / diff / commit-message mechanics as D12. Directionally, for a
spreadsheet the metasource (the provenance plus the mandatory-commit-message decision log) is likely
weighted MORE heavily than for prose: the cell values are just data, while the WHY behind a formula
or a structural change is what is worth tracking rigorously. This does NOT mean there is no literal
source: a faithful, machine-exact canonical source is still required precisely so nothing is lossily
paraphrased on the way in. Format: YAML or JSON, explicitly NOT CSV (CSV collapses formulas to their
last-computed value, loses multi-sheet structure, and re-infers weak types). A strict structural
export can hold multiple named sheets, per-cell value AND formula as distinct fields, and real types.

**D12c - the same cross-cutting principle extends to PPTX.** Across all three formats, the canonical
literal source must be a faithful, structured, human-readable, git-diffable TEXT representation, never
a lossy narrative retelling. For decks, slide structure and formatting need their own as-text
representation. Real prior art already in this repo: `marp-cli` is a pinned engine, and Marp's own
per-slide directive syntax already captures a meaningful slice of "layout and formatting as text",
directly extendable rather than a bespoke format. This is coupled to a pre-existing tooling question
(the deck-engine choice) that changes what the canonical source looks like, so the source-format
decision is resolved together with the engine choice, not independently.

**Status: specified, not implemented.** No editor code exists yet. The design questions are resolved
in the editor design spike (see `ARCHITECTURE.md`, "Structured source editor"). Editor implementation
is sequenced behind the release-engineering work per D13.

## D13 - Release readiness is its own workstream

Publish readiness is tracked as a first-class workstream with its own plan (ROADMAP Track F:
packaging, CI, docs, naming), rather than being treated as a byproduct of feature work. The project
carries TWO parallel critical paths: the FEATURE path (Track D's conflict-merge as its tail) and the
RELEASE path (packaging and CI and docs). Editor implementation is frozen until the release-track
items are clear, to keep single-maintainer focus on the release blockers.

## D14 - Projection-aware provenance

D11's provenance embed is audience-blind: every DOCX/XLSX/PPTX, including artifacts rendered for
external recipients, carries source UID, source content-hash, render timestamp, and tool version in
the OOXML `dc:identifier` property, unencrypted and trivially extractable (it is hidden from the
casual Word UI, not secure). For a tool whose core value is no-read-up disclosure gating, stamping
internal source identity and tooling state into files that leave the building is a self-contradiction
and a real metadata channel.

**Rule: profile-driven full/none.** Provenance is a function of the projection profile. Internal
profiles embed full provenance (round-trip intact); external / publish profiles strip it entirely. An
opaque-token third mode (an encrypted/keyed blob, meaningless externally but internally resolvable,
which would enable round-trip with OUTSIDE parties) is documented as a future extension, not built
now: in the reference workflow, round-trip happens with internal reviewers while truly external sends
are terminal and never re-ingested, so strip costs nothing today. Which profiles count as external
ties into the projection profile schema. Until the strip mechanism is implemented in code, every
externally-bound artifact is treated as manually-scrub-required.

## D15 - API hardening beyond a read-server posture for state-changing endpoints

D9's posture (localhost bind, warn on wider bind, rate limits) is a READ-server posture. The D12
editor makes the API a WRITER: it saves files and creates git commits from a browser. Localhost
binding alone does not stop CSRF (any website the operator visits can POST to `127.0.0.1`) or DNS
rebinding.

**Decision: on every mutating endpoint additionally require:**
1. an `Origin` / `Sec-Fetch-Site` allowlist check (browser-signaled cross-origin POSTs rejected;
   non-browser clients that carry neither header are unaffected);
2. a per-session CSRF token;
3. rejection of non-loopback `Host` headers (anti-rebinding);
4. a source-path allowlist / root-jail so render and save endpoints cannot address arbitrary
   filesystem paths.

Additionally, before any path writes LLM free-text into decision-log entries and git commit messages:
define the write-path validation (length caps, control-character stripping, human-confirm before
commit). Schema validation only protects enumerated fields, not free text.

## D16 - Fuzzy-gate before handoff: deterministic first, LLM only past a confidence threshold

Every LLM-touching step defined under D8 (harness or copy-paste) is an escalation, not a default.
D8 made the two LLM modes interchangeable and gave each step a deterministic fallback; D16 makes the
deterministic path the FIRST-CLASS path and the LLM path conditional on a measured confidence gate.
Motivated by tokenomics: most invocations of these steps do not need a model, and paying for one is
waste plus latency plus a data-egress surface.

**Rule.** An LLM-touching step must:
1. produce a deterministic result first (template / rules / structured transform), and
2. compute a confidence score in [0, 1] for whether that deterministic result is sufficient, and
3. gate on a configurable threshold: at or above -> the deterministic result stands (zero tokens);
   below -> escalate to the LLM via the D8 contract. If no escalation channel is available, the
   deterministic result is still emitted, flagged `needs_review`, so a result is never lost -- only
   sometimes less rich.

The confidence heuristic is per step and lives in code (not the LLM): it keys on how far the input
sits from what the deterministic path handles well. Worked example (C8.3 decision-capture): score
falls as diagram edits shift from descriptive changes the template states fully (relabels) toward
intent-bearing changes it can describe but not justify (added/removed/rewired nodes), scaled by edit
volume and a DIVERGED verdict; default threshold 0.6, env/flag overridable.

**Scope: this is architecture-wide, not one step.** Existing and future LLM-touching or
could-be-deterministic steps are expected to adopt the same shape (deterministic result + confidence
+ gate): vision-review (deterministic svg_metrics/visual_quality already exist -- the vision LLM
should be gated on their verdict, not run unconditionally), Track D 4.5 contextualize (the same
diff-to-narrative shape as C8.3), and any later generative step. The gate primitive is kept inline
per step until a second consumer justifies extracting a shared `contracts/gate.py` (trigger-gated,
per this repo's build-when-needed discipline). The consistency sweep that maps every current step
onto this doctrine and sequences the retrofits is its own workstream (see the augmented roadmap).

## D17 - Optional direct-API escalation channel, with a VLM endpoint separate from the LLM (VLM defaults to the LLM)

D8 made every LLM-touching step degrade across two modes: harness (the user's own configured
assistant, via `render init-ai`) and copy-paste (a human pasting into any chat LLM). Both keep
renderfact free of LLM-calling code and of a new trust boundary. D16 then made those modes an
ESCALATION taken only past a confidence gate. This decision adds a THIRD, OPTIONAL escalation
channel and the model-config layer it needs -- kept off by default so the D8 posture is unchanged
for anyone who does not opt in.

**The model-config layer.** An optional `[models]` config (file + env overrides) declares up to two
endpoints: `llm` (the main text model) and `vlm` (a vision-language model for steps that must look at
a rendered image -- vision-review, and any image-attach step). Resolution rules:
1. A step routes to `vlm` if its input carries an image (declared in its INPUT_SCHEMA, e.g.
   `rendered_image_path`), else to `llm`.
2. **`vlm` DEFAULTS TO `llm`** when no `vlm` is configured, or when the configured `vlm` has no
   working API key / fails a cheap reachability probe. One configured model therefore serves both
   text and vision; you only set `vlm` when you deliberately want a different vision model.
3. If the resolved model is not vision-capable for a vision step (e.g. the fallback `llm` is
   text-only), the step degrades to copy-paste -- the human attaches the image to a chat VLM
   themselves. A vision step is NEVER silently run text-only.

**Direct-API is opt-in and off by default.** Configuring `[models]` is what turns the direct-API
channel on. With no config, escalation remains harness-or-copy-paste exactly as D8 defined; the
deterministic-first D16 path is unchanged in all cases (most invocations never escalate at all).
When on, the same D8 step contract (assemble_input/validate_output, MODE_FIELD provenance) governs
the API result identically to a harness or pasted one -- a fourth provenance value `MODE_FIELD in
{deterministic, harness, copy-paste, api}` records which channel produced it. The API result is
validated by the same validate_output() as every other mode; a failing/unreachable endpoint falls
back to copy-paste rather than failing the step.

**Why now, why optional.** The operator wants an unattended escalation path (deterministic gate
misses -> call a model directly) without the human-in-the-loop of copy-paste, and a cheaper/faster
vision model distinct from the main reasoning model. That is a real need, but it reintroduces the
LLM-calling code and the network/egress/cost surface D8 deliberately avoided -- so it is strictly
opt-in, disabled unless configured, and every hardening rule from D15 (no secrets in logs, egress is
a sovereignty concern per the grens-doctrine for defence consumers) and D16 (telemetry, storm
backpressure) applies to it. Implementation is sequenced last in the fuzzy-gate plan
(docs/2026-07-04-fuzzy-gate-architecture-plan.md, item G5) because it is the largest surface and the
only one that touches the D8 trust boundary.

## D18 - The gate-hook contract: QC_SCRIPT advisory-by-default, POSTRENDER_GATE_SCRIPT blocking-by-default, generic regex-scan as a real gates/ module

Issue #71: a consumer with a hard content-safety requirement (its own example: a render must never
carry a currency figure once it is bound for an external vendor, because disclosing an internal
budget ceiling to a counterparty is a real negotiating-leverage risk) found two gaps in
`render-doc.sh`'s hook set, and contributed the fix upstream rather than keeping it private.

**1. `QC_SCRIPT` gains an opt-in blocking mode, default unchanged.** `QC_SCRIPT` (`--qc`) has always
run pre-render, against the source markdown, with its exit code print-and-continue: `"$PYTHON"
"$QC_SCRIPT" "$SOURCE" || echo "(advisory, not blocking)"`. That default stays: a pre-render lint pass
being advisory is the common case (a consumer runs a stricter check without every finding gating every
draft render), so backward compatibility for existing skins matters here. `QC_BLOCKING=1` (or the
equivalent `--qc-blocking` flag, which also implies `--qc`) turns a non-zero `QC_SCRIPT` exit into a
build failure, for the consumer that specifically wants pre-render fail-closed behaviour.

**2. A new hook, `POSTRENDER_GATE_SCRIPT`, called with the finished `<docx>` path, same calling
convention as `PAGECHECK_SCRIPT`** (a path in, run after render and before the completion summary),
but distinct in purpose: `PAGECHECK_SCRIPT` is page-economy-focused and already advisory
(`|| true`); `POSTRENDER_GATE_SCRIPT` is content-safety-focused, and scans the ARTIFACT rather than
the source, which matters because a reference template, a lua filter, or the house-style
post-processor can inject content that never existed in the markdown source `QC_SCRIPT` saw.

**Decision: `POSTRENDER_GATE_SCRIPT` defaults to BLOCKING, the opposite of `QC_SCRIPT`.** These two
hooks are not the same shape wearing different names; they earn different defaults:

- `QC_SCRIPT` is a pre-render LINT: findings are advice a human can act on before the artifact even
  exists, so the more common posture is "print it and let the author decide", matching every other
  advisory hook already in this script (`--lint`, `--page-check`).
- `POSTRENDER_GATE_SCRIPT` is a post-render GATE whose entire reason to exist is "does the artifact
  contain content it must never contain." A gate with that job description that defaults to
  advisory-only is close to useless: the whole point is that a human should not have to notice a
  finding in scrollback for the guarantee to hold. Defaulting it to fail-closed is what makes it a
  gate rather than a second linter with a different name. `POSTRENDER_GATE_ADVISORY=1` is the escape
  hatch for a consumer that genuinely wants report-only behaviour instead, kept symmetric with
  `QC_BLOCKING` so both hooks are governed the same way (an env var or flag that inverts the default),
  just inverted in which direction is the default.

**3. The generic regex-scan pattern ships as `gates/content_scan.py`, pattern-as-parameter, never a
built-in default.** The issue's own reference implementation ("open the DOCX with python-docx, regex
over every paragraph and every table cell, `raise SystemExit(1)` on any hit") is domain-neutral
already; the only domain-specific part was the currency regex the issue used to motivate the ask. Per
D3 (generic core, private skin), the pattern is a REQUIRED parameter (`--pattern` / `--pattern-file`,
or `RENDERFACT_GATE_PATTERN` / `RENDERFACT_GATE_PATTERN_FILE` for the zero-arg hook-invocation case,
since `render-doc.sh` calls every hook with only its target path, no extra flags): this module never
ships a currency regex, a codename list, or any other example as a default. A consumer skin points
`POSTRENDER_GATE_SCRIPT` at this script directly (via the env-var pattern) or through a thin wrapper
that hardcodes its own pattern; either way the "open docx, scan every paragraph and cell, exit 1 on
hit" mechanics stop being re-implemented per consumer, which was the issue's actual complaint.

## D19 - Purpose annotations and dossier role: annotative-only, never a gate

A specific editorial discipline ("everything in this document should be prunable, as long as its
stated purpose is still achieved") has no way to be checked mechanically, or even by inspection
months later, without an explicit record of what each paragraph, section, or document was FOR. An
author (human or LLM) ends up including detail because it is true and available, not because it is
load-bearing for the document's actual goal, and a later editor has no record of which paragraphs
were serving which purpose to safely decide what to cut (issue #77).

**Rule: two structurally separate, purely annotative mechanisms, neither a hard gate.**
1. Paragraph/section purpose: an HTML comment, `<!-- PURPOSE: ... -->`, stated immediately above the
   block it explains.
2. Document-level dossier relation: a frontmatter field, `dossier_role:`, stating what a document
   uniquely contributes relative to its siblings in a broader dossier/collection.

**Why HTML comments are safe.** Pandoc's markdown reader parses `<!-- ... -->` as a raw-HTML AST node
that neither the DOCX writer nor the typst writer (the PDF path's markdown-to-typst-markup step, the
only step that touches the original markdown -- typst itself never parses it) emits. Verified
empirically (`tests/test_purpose_annotations.py` drives the real pandoc/typst subprocess pipelines
and asserts the marker is absent from both outputs), not assumed. This is the SAME mechanism D14's
projection-provenance header stamp already relies on (`projector.py`'s `<!-- projected: ... -->`
line): #77 generalizes it from per-document render metadata, stamped by the tool, to per-block
authoring intent, stated by the author.

**Why `dossier_role` is freeform, not an enum.** The projection engine's clearance/distribution
ladders already establish the precedent that this repo's engine ships no fixed classification
vocabulary of its own (`profiles-example.yaml`'s ladders are an illustration, not a standard);
`dossier_role` follows the same posture. Read via the repo's existing frontmatter-read idiom
(`gates/run_gates.py`'s `run_uids`, `roundtrip/source_uid.py`), not a new parsing path.

**Why this is explicitly NOT a D16 fuzzy-gate step.** D16 governs LLM-touching steps: deterministic
result first, confidence score, gate past a threshold. Purpose annotation is deliberately outside
that doctrine because it is not LLM-touching at all -- the issue's stated non-goal is exactly that an
LLM summarization pass CANNOT substitute for the author stating intent explicitly (a summarizer
reconstructs what a paragraph SAYS, not what it is FOR, and the whole point is capturing the latter
before it is lost). The optional lint pass (`render qa purpose`) that flags an unannotated prominent
block is a plain deterministic pattern match, not a confidence-gated step, and it never fails a run:
the same never-fails posture as `QC_SCRIPT`'s off-when-unset default (`container/render-doc.sh`), not
the fail-closed posture of `render gate`. Not every document needs this level of authoring rigor, and
a document that never adopts the convention pays no penalty -- the issue explicitly rules out both a
blocking enforcement gate and automatic purpose inference.

## D20 - Comprehension gate for text documents, and a D16 gate that legitimately never accepts

Issue #84: the diagram vision-review gate (chunk 3.1, D8/D16) already establishes that a fresh,
author-independent LLM read catches subjective failures a deterministic pass structurally cannot. No
equivalent existed for rendered TEXT documents -- Vale and the plain-language work catch phrasing
patterns, but neither can answer "does a reader who has never seen this understand what each section is
for, and where does the flow break down." This decision adds `lint/comprehension_review_contract.py`
(`render comprehension-review`) as that peer, reusing the SAME D8 contract machinery
(`contracts/schema_utils.py`, `contracts/copy_paste.py`, `contracts/init_ai.py`) rather than inventing
parallel plumbing: one INPUT_SCHEMA (an ordered list of reader-sized snippets, chunked at section
boundaries), one OUTPUT_SCHEMA (per-snippet purpose/confusion/fluff/cuttable findings plus a
whole-document synthesis), identical across harness, copy-paste, and the D17 direct-API channel.

**The D16 gate decision, made explicit.** D16 requires every LLM-touching step to produce a
deterministic result first, score confidence that it suffices, and gate on a threshold. Every existing
gated step has a real deterministic proxy to score: vision-review has hard geometry/contrast/a11y
numbers; decision-capture and contextualize have a change-kind taxonomy splitting edits the template
states fully (descriptive) from edits it can describe but not justify (intent-bearing). Comprehension has
no such proxy. Document length, section count, sentence length, and similar structural signals predict
review COST, not comprehension risk, in either direction: a single dense paragraph can bury its point as
badly as a long, well-structured document reads cleanly. Building a confidence formula from those
signals anyway would dress up a coin flip as a measurement -- and the entire reason this gate exists is
to catch exactly what deterministic checks (Vale, plain-language, `render qa`'s zero-LLM probes)
structurally cannot reach. So `comprehension_review_contract.confidence()` returns a CONSTANT 0.0: this
step always escalates.

**Concretely, against the signals that actually exist (issue #76, landed alongside this one).**
`demo/skin/vale/styles/PlainLanguage/` ships `SentenceLength` (word-count threshold per sentence) and
`NominalisationDensity` (`-tion`/`-ance`/`-ment` suffix density per paragraph); `docstyle/plain_language.py`
adds a repeated-phrase-across-sections scan. All three are real, useful, deterministic, and were
considered as a confidence input. All three were rejected for the same reason: a long sentence, a dense
paragraph, or a repeated phrase is a STYLE finding a reader can often work around; whether the reader
loses the thread entirely is a different question these checks do not and cannot answer (a document with
zero PlainLanguage hits can still bury its point, and a document flagged throughout can still read
clearly to a patient reader). Wiring any of them into `confidence()` would make the gate's escalation
depend on a signal that does not measure what the gate exists to check.

**This is a D16 outcome, not an exception to it.** D16's own vision-review worked example already
treats "no deterministic signal" as valid (confidence 0.0 when neither of its two metrics fired); this
step is simply the first where that is the PERMANENT case rather than one branch of a heuristic. The gate
mechanics stay identical: `gate()` still compares the score to a threshold via the shared
`contracts/confidence_gate.decide()`, so an operator who explicitly sets `--threshold <= 0` still gets
the accept path -- an honest "not reviewed" stub (`status: WARN`, empty findings, `reviewer_mode:
deterministic`), never a fabricated verdict. That is the same `needs_review` fallback every gated step
already offers when no escalation channel is available; here it is also reachable by deliberate choice,
not only by channel absence. Report-only throughout: the step never rewrites the document, matching the
propose-only contract every gated step in this repo follows.

**Scope note for future gated steps.** A step with a genuinely judgment-based question and no
deterministic proxy should follow this pattern rather than inventing a superficial heuristic to satisfy
D16's shape: state the absence explicitly, pin confidence at 0.0, and record the reasoning in a decision
entry (this one). D16's "Scope" paragraph already anticipated this kind of retrofit; this is the first
step in the repo where it applies to the step's ENTIRE lifetime, not a transitional phase.

## D21 - Custom-style fonts win by default over the house-style body pass

Issue #98: `docstyle/style_postprocess.py`'s per-paragraph body-styling loop in `main()` called
`set_para_font()` unconditionally on every paragraph that was not Title/Subtitle/Heading 1-4, including
one carrying a genuinely custom Word style (reached via a pandoc `::: {custom-style="X"} ... :::` fenced
div) that already defines its OWN font and size in `reference.docx`'s `styles.xml`. The paragraph came
out with the right `w:pStyle` (pandoc resolves the style name correctly) but a direct-formatting
run-level `w:rFonts`/`w:sz` override, injected by the post-processor, shadowed the style's own
definition: a Word-rendering fact (direct run formatting always outranks paragraph-style formatting),
not a pandoc writer bug. Confirmed by reproduction: a fixture `reference.docx` with a `PullQuote` style
set to Georgia 16pt in its own `w:rPr`, run through the real pandoc + style_postprocess pipeline,
produced a `PullQuote`-styled paragraph whose runs carried Arial at the house body size instead.

**The default changes: a custom style's own font/size now wins.** `is_custom_style_paragraph()` treats a
paragraph as template-fidelity-worthy when its style name falls outside a known built-in/default-body
set (Title, Subtitle, Heading 1-4, Normal, Body Text, and similar) AND that style's own `w:rPr` (not an
inherited base style; python-docx's `Font` getters only read a style's own direct properties) explicitly
sets `w:rFonts` and/or `w:sz`. For such a paragraph, the body-styling loop now skips `set_para_font()`
entirely, leaving the run with no direct formatting so it falls through to pure Word style inheritance.
Chosen as the default rather than an opt-in because "apply style X" reasonably means "look like style
X": a caller who references a custom style by name is expressing a template-fidelity intent, and silently
overriding it with the house look is the surprising behaviour, not the other way round. Built-in
categories (Title/Subtitle/Heading 1-4) and the generic default-body case (Normal / no style) are
UNCHANGED: they still get the house font/size unconditionally, matching renderfact's primary use case
(an opinionated house typography over otherwise-plain source content).

**The old blanket-override behaviour is kept as an explicit opt-in**, for callers who genuinely want one
uniform house font everywhere regardless of any custom style a source paragraph names: a CLI flag
(`--override-custom-style-fonts`, standalone `render docstyle` surface, same shape as `--table-widths` /
`--cover-version`) and a `template-profile.yaml` key (`override_custom_style_fonts: true`, same shape as
`normalize_punctuation`) both set the same module-level gate; the CLI flag wins when both are present.
Scope note: this is narrower than the issue's own follow-up comment, which also flagged built-in styles
(Title, numbered headings) as unconditionally overridden. That is true but out of scope here by design:
overriding a BUILT-IN category is exactly the documented primary use case (a consistent house look over
plain content), so changing that default would break the common case to fix an uncommon one. A future
issue can add a broader `preserve_reference_styles` escape hatch (skip ALL font/size injection, not only
for custom styles) if a template-fidelity use case needs the built-in categories left alone too; this
decision deliberately does not reach for that yet.

## D22 - Sendable email output is `.eml` (RFC822), not `.msg` (MAPI) or mail-client automation

Issue #95: the pipeline had `docx`/`pdf` body-output modes plus diagram-only modes, but no mode for
rendering a governed markdown source directly to a sendable email, so a real deliverable that is
"an email" rather than "a document" was bridged manually: copy the rendered body into a mail client,
re-add the signature by hand, with no reconciliation path back to source the way `docx` has
`reingest`. The issue's own framing named three candidate shapes: (1) declare a signature block in
skin config, (2) map frontmatter fields to headers, and (3) produce a `.msg`/`.eml` file OR drive a
local mail client's compose window through its automation interface, and noted the project's
existing OOXML-manipulation infrastructure (`docstyle/style_postprocess.py`) as a possible `.msg`
building block, since `.msg` is also an Office/MAPI-family binary format.

**This decision, following the same core-vs-adapter split issue #68 used for the layered-stack
diagram archetype (ship the general core, name the narrower adapter as an explicit follow-up rather
than build it now):** the core of this change is `.eml` (RFC822, plain text, stdlib `email` module),
NOT `.msg`, and NOT mail-client automation.

- **`.eml` is the right primary deliverable.** It is a portable, openly documented, dependency-free
  format that essentially every mail client (Outlook included) can open or import directly, so it
  solves the actual "sendable email with a reconciliation path" need without touching a binary
  format at all. It needs no optional dependency (the stdlib `email` module both builds and parses
  it), which makes it directly testable the same way every other backend in this repo is tested: a
  fixture in, a real parse of the artifact out, asserted against.
- **`.msg` (MAPI) is explicitly deferred, not built here.** Unlike DOCX (OOXML, a documented open
  zip-of-XML format `python-docx` already reads/writes), `.msg` is Microsoft's binary Compound File
  Binary / MAPI property-stream format: heavier to write correctly, platform-adjacent in practice
  (real-world producers overwhelmingly lean on Windows COM automation or a native MAPI library,
  neither of which is portable or testable in CI the way this repo's other backends are), and it
  buys nothing `.eml` does not already deliver for the "sendable, reconcilable email" goal an
  organisation actually has. `docstyle/style_postprocess.py`'s OOXML-manipulation experience does not
  transfer the way the issue speculated: OOXML and CFB/MAPI are unrelated container formats sharing
  only the "Microsoft Office binary" label, not any parsing machinery.
- **Mail-client automation is explicitly deferred, not built here.** Driving a compose window through
  a platform automation interface (Outlook COM on Windows, AppleScript on macOS, no equivalent at all
  on Linux) is inherently platform-specific, untestable in a cross-platform CI matrix the way this
  repo's other modes are (`render eml` runs the same on every OS `render pdf` does), and adds a
  different kind of coupling (to a running, licensed desktop application) than anything else in this
  toolchain. A `.eml` file already solves delivery: it is one double-click (or one drag-and-drop, or
  one `mailto:`-adjacent import) away from a compose window in every mail client tested.
- **Signature-block config is freeform text lines**, the same non-enum, freeform posture `dossier_role`
  (D19) and the projection engine's clearance/distribution ladders already use, rather than a rigid
  structured name/title/department/phone schema: a consumer's own house style for a sign-off varies
  too much for the generic core to usefully constrain, and a list of strings is trivially sufficient.
  It lives in its own `mail/signature-example.yaml` (the `docstyle/template-profile-example.yaml` /
  `projection/profiles-example.yaml` naming and loading pattern), not folded into `brand.yaml`: the
  signature block is CONTENT (a name, a role, a phone number, a directory link), and `brand.yaml` is
  DESIGN TOKENS (colour, type, geometry) consumed by a deep-merge generator pipeline with a fixed
  known-keys schema: mixing the two would either force the token generators to tolerate an
  arbitrary freeform key they do not otherwise need to understand, or force the signature block into
  an enum-shaped shell it does not need.
- **v1 is plain text, with PNG image(s) riding along as inline MIME parts, not HTML.** The signature
  block's text is rendered as a plain-text block, appended after a plain-text body (pandoc's plain
  writer over the same shared `pandoc_markdown.MARKDOWN_FROM` `--from` every markdown-reading call
  site in this repo already uses), in a single `text/plain` MIME part. A signature MAY also declare
  `images:` (PNG only, resolved skin-relative): each becomes its own `Content-Disposition: inline`
  `image/png` part (`EmailMessage.add_attachment`, which promotes the message to `multipart/mixed`
  automatically), so a logo genuinely travels embedded inside the .eml rather than as a hyperlink to
  a hosted image. This is deliberately NOT the `multipart/alternative` + `multipart/related` shape a
  styled HTML signature (coloured text, a clickable button, an inline-`cid:`-referenced logo sitting
  inside markup) would need: no HTML part is generated, so an attached image is not laid out or
  positioned by anything, it simply rides along as a real embedded part most mail clients show inline
  or as a thumbnail near the body. A full HTML signature remains a real, useful, materially larger
  extension (a second content type, an HTML-authoring surface for the signature block, and layout
  decisions this repo has no existing pattern for), tracked as a roadmap follow-up
  (`docs/ROADMAP.md` Track J), not built here.
- **Frontmatter-to-header mapping** follows the field-naming style already established by `dossier_role`
  and `renderfact_uid`: `recipient:` (with `to:` accepted as a synonym) maps to the eml's `To:`
  header, and `subject:` (with the document's own `title:` as the natural fallback, the same
  subject-equivalent field a document already carries) maps to `Subject:`. Both are read-only over
  the source, the same posture `roundtrip/dossier_role.read_dossier_role()` uses: nothing is
  generated or persisted back into frontmatter. A missing recipient is advisory, not fatal (a WARNING
  to stderr, an eml with no `To:` header): the same "still produces a valid, honest artifact with
  less input" posture optional `--theme`/`--brand`/`--signature` flags take across every backend in
  this repo, useful for a draft written before the addressee is settled.

## D23 - Workspace static assets: package-data files + GET /ui/static/{name}, not string literals

The monolithic-`UI_HTML`-string pattern (api/ui.py, D9) ends at the Track J workspace boundary
(design spike `docs/2026-07-07-ui-ux-project-workspace-design-spike.md` section 5, OQ8). First-party
JS/CSS for the Dashboard/wizard/Template Library screens (chunk 6.5 onward) ship as real files under
`api/static/`, served by a new `GET /ui/static/{name}` route: an exact-filename allowlist (no
directory traversal possible by construction, no path-jail arithmetic needed), long-cache headers,
gated behind `--enable-ui` like every other `/ui*` route. The HTML shell each screen returns stays a
small Python string (matching `render_docs_html`'s existing pattern) that only assembles structure
and links to the static files; the substantial JS/CSS logic lives in reviewable, cacheable files, not
string literals.

**Why now.** The extension-seam audit that produced the design spike flagged this as a genuine fork,
not a mechanical continuation: `UI_HTML` as one string already works for a single studio page, but a
multi-screen workspace (Dashboard, wizard, Template Library, and later the vendored D12 editor
libraries, which are megabyte-class) would make every new screen bloat `api.ui`'s single string
further and make diffs unreviewable. Splitting now, before chunk 6.5's first new screen, costs one
small route and an allowlist; deferring it would mean rewriting three screens' worth of inline string
literals later instead of one.

**Why a plain filesystem read, not `importlib.resources`.** OQ8's own text floated
`importlib.resources` for pip-installed-package portability; this repo's every other bundled-asset
convention (the template library's `templates/library/`, the flat `templates/*.md` pack, `tools.lock`,
`container/`) already reads via a `REPO_ROOT`-relative `Path`, with no `importlib.resources` usage
anywhere in the codebase. Consistency with that established convention wins over anticipating a
packaging concern no other module here has needed to solve yet; revisit if/when renderfact actually
ships as a wheel with `api/static/` needing to travel inside it.

**Renumbered from D18 to D23 during PR #67's main-branch merge-conflict resolution** (2026-07-11):
D18 was independently assigned to two decisions developed in parallel without either session aware
of the other (issue #71's gate-hook contract, merged first) -- the same class of collision D19
(comprehension gate vs #77's purpose-annotations) already hit and was renumbered for earlier in this
same file. D22 (sendable email output) was the highest number on `main` at merge time, so this
decision becomes D23, immediately after it; content and reasoning are otherwise unchanged from the
original PR #67 draft.

## D24 - Custom document properties: reverse D11's docProps/custom.xml avoidance, reimplement (not share) the OPC-part registration technique, declaration and display kept as separate concerns

Issue #105's sibling feature (alongside dropdown/checkbox content controls, developed in a parallel
branch that may land before or after this one -- if D24 is already taken when these merge, this
becomes the next free number, the same renumbering this file already has precedent for, see D23
above): named, typed custom document properties, visible in Word via `[ ]{.docproperty name="..."}`
bound `{ DOCPROPERTY }` field references.

**Reverses roundtrip/provenance.py's own D11 decision to avoid `docProps/custom.xml`.** That module's
docstring gives its reasoning: "none of the three libraries has native support for it, and
hand-rolling the OOXML content-types + relationship registration carries real corruption risk... for
no functional gain over the core_properties approach at this stage." That reasoning is sound for D11's
own use case -- one opaque, machine-only JSON blob, for which `dc:identifier` (a core property) was a
genuinely adequate substitute. It does not hold here: this feature needs multiple, independently
NAMED and TYPED values a human opens File > Info > Properties > Advanced to read or edit, and Word's
`DOCPROPERTY` field mechanism can only bind to a real custom property, never to an arbitrary core-
property JSON blob. There is no substitute for `docProps/custom.xml` for this feature, so the
"corruption risk" tradeoff is worth taking (and mitigated the same way D11 already mitigated it: a
dedicated test asserting both registrations happen correctly, not just assumed).

**The `_OpcCoreProps` OPC-part-registration technique is reimplemented for `docProps/custom.xml`, not
imported from `roundtrip/provenance.py`.** `docstyle/custom_properties.py`'s `_register_custom_part`
follows the exact same two-registration pattern (`[Content_Types].xml` Override +
`_rels/.rels` Relationship) `_OpcCoreProps._register_core_part` already proved out for
`docProps/core.xml` on `.vsdx`. It is copied as a PATTERN, not shared as a library call: `roundtrip/`
(round-trip provenance, D11/D14, a different lifecycle -- runs on already-rendered artifacts, possibly
long after the render) and `docstyle/` (render-time post-processing, runs once per render immediately
after pandoc) are architecturally separate subsystems in this repo with no existing cross-imports
between them, and this repo's own precedent (`docstyle/marking_lint.py` and `gates/content_scan.py`
independently implement their own small raw-zip header/footer readers rather than sharing one) already
favours a small local helper over a premature shared abstraction for a ~20-line registration routine.
Revisit if a THIRD OPC-part writer ever needs the same pattern -- three independent copies is the
usual threshold where extracting a shared helper stops being premature.

**Declaration (template-profile-level) and display (per-span) are kept as two separate mechanisms, not
one.** A property's name/type/value lives centrally in `--template-profile`'s `custom_properties:` key
(read once, by `docstyle/custom_properties.py`, a post-pandoc step); WHERE it is shown, if anywhere, is
a `[ ]{.docproperty name="..."}` markdown span anywhere in the source, converted by
`docstyle/filters/doc-properties.lua` during the pandoc run itself into a real `w:fldSimple`
`DOCPROPERTY` field. This means a template can move or add a display location without touching the
declared value, and change the value without hunting down every place it is referenced -- and it means
the Lua filter itself stays simple and stateless (no YAML parsing inside Lua, no cross-file
coordination at pandoc-run time): it emits a well-formed field with a guillemet placeholder
(`«name»`) as the cached result, and `docstyle/custom_properties.py` fills in the real value
afterward, by matching the field's own `DOCPROPERTY <name>` instruction text -- a `.docproperty` span
whose name is never declared is left as its placeholder with a printed NOTE, not a hard failure (unlike
the malformed-input cases in #105's dropdown/checkbox filter): a template author plausibly stages a
field ahead of declaring its value, and that is a legitimate, non-error state this feature should not
punish.

**Discovered empirically while building this: pandoc's own DOCX writer already writes
`docProps/custom.xml` with exactly one property, `version`, sourced from the YAML frontmatter's
`version:` key** (verified: a plain `pandoc source.md -o out.docx` with `version: v1` in frontmatter
produces a `docProps/custom.xml` containing that property, with no `docstyle/` code involved at all;
arbitrary OTHER frontmatter keys are not carried through the same way). This is a narrow, pandoc-
internal special case, not a general mechanism -- it does not extend to arbitrary named/typed
properties -- but it is real, and confirms the "merge into whatever is already there, never overwrite
wholesale" design in `_merge_custom_xml` was necessary, not defensive-for-its-own-sake: a real render
already has a foreign-to-this-feature property present by the time `docstyle/custom_properties.py`
runs, on every single render, verified directly (`tests/test_custom_properties.py::
test_process_merges_with_existing_foreign_property`), not assumed from reading pandoc's source.
