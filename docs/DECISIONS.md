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
