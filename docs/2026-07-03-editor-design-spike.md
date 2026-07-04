# Design spike: the structured source editor (chunk 5.7, resolving OQ5)

> **What this is.** The design pass D13 requires before any editor implementation chunk
> (5.8/5.9/5.10) is scopeable, mirroring chunk 3.3's spike discipline: decisions with rationale,
> a worked example per format, and an honest list of what stays open. Inputs: D12/D12b/D12c
> (DECISIONS.md), OQ5 (ROADMAP.md), the shipped 5.1 API (api/app.py), and the F3 demo as the
> worked-example corpus. Already resolved upstream and NOT relitigated here: UI stack (stdlib
> backend, vanilla JS + vendored mermaid.js/KaTeX only), XLSX canonical format family (YAML/JSON,
> not CSV), PPTX `[imitate]` marp-cli.

## 1. E7 (markdown): the three-pane editor

### 1.1 Section granularity: leaf sections on fence-aware ATX headings

**Decision.** The edit unit is the LEAF SECTION: an ATX heading (`#`..`######`) plus everything
up to the next heading of ANY level. The nav tree still shows the full hierarchy (an H3 nests
under its H2), but selecting any node edits exactly that node's own leaf content, never its
children. YAML frontmatter is section 0, editable like any other section. Text before the first
heading (after frontmatter) is section 1, labeled "(preamble)".

**Why leaf, not subtree.** Subtree editing (H1 plus all nested content) makes the middle pane
arbitrarily large, reintroduces the scroll-one-long-document problem D12 exists to solve, and
makes save conflicts coarser. A user who wants subtree scope can still get it: the nav tree
offers the parent node, and a parent's leaf content is simply what sits between the parent
heading and its first child heading.

**Fence-awareness is a correctness requirement, not a nicety.** A `#` line inside a ``` code
fence or a `:::` projection block is content, not a boundary. The section splitter must track
both fence kinds (same discipline as projection/projector.py's parser) and treat them as opaque.
Setext headings (underlined style) are NOT boundaries; the parser recognizes ATX only, and the
docs say so (pandoc accepts both, but this repo's own corpus and the demo use ATX exclusively).

**Section identity.** Sections are addressed by index in document order, with a per-section
content hash (sha256 of the section's raw text) returned alongside. The hash, not the index, is
the concurrency token (section 1.4). Indexes are ephemeral by design; heading renames are just
edits. No stable-ID scheme is needed for a single-operator local editor.

### 1.2 Right-pane rendering: live-approximate client-side, exact server-side on demand

**Decision (the OQ5 "hybrid" resolved into a concrete rule).** Two preview qualities, one rule:

- **Live preview (as you type, client-side, vendored libs only):** markdown structure via a
  single vendored md renderer, formulas via vendored KaTeX, `mermaid` fences via vendored
  mermaid.js. Approximate is acceptable here because its job is orientation, not sign-off.
- **Exact preview (on demand, server-side, real engines):** a "render this section" action calls
  the API, which runs the real chain (pandoc fragment render; d2/typst/likec4 for their fence
  kinds) and returns HTML/SVG. Engines with no practical client-side equivalent (d2, typst,
  likec4) are ONLY available this way; their fences show a placeholder card in live preview with
  a render button.

**Why not exact-always:** a keystroke-debounced pandoc/d2 round-trip per edit is the heavyweight
coupling D12's minimal-dependency resolution rejected; and why not client-always: no faithful
client d2/typst exists, and pretending otherwise produces sign-off on previews that lie.

**Vendored-lib list (the complete set, per D12's "kept to the genuinely irreplaceable"):**
one md renderer, KaTeX, mermaid.js. Nothing else. Vendoring happens in 5.8, pinned versions
recorded in tools.lock's js section (new).

### 1.3 Save, mandatory commit message, git wiring

- Explicit Save button + implicit save-on-navigate-away when dirty (D12 verbatim).
- Save with a detected diff REQUIRES a non-empty commit message; enforced server-side (400 on
  empty), not just by UI validation. No-diff save is a no-op (200, "nothing to commit").
- Every save-with-diff is one git commit whose message is exactly the operator's text (D11 part
  4). The server refuses to operate on a source outside a git work tree (clear error naming the
  D11 rationale) rather than silently skipping the commit.
- **Provenance refresh on save: NO (resolves D12 open question 4).** Embedded provenance in
  DOCX/XLSX/PPTX artifacts describes a RENDER event (source version AT RENDER TIME). Editing the
  source does not change what an existing artifact was rendered from; the next `render` or
  `retarget` stamps fresh provenance. The editor never touches artifacts.
  **The out-for-review scenario this rule protects (operator challenge, 2026-07-03):** source V1
  is rendered and sent for comments; the operator edits the source to V2 through this editor; the
  commented DOCX returns. Its provenance still records hash(V1), the CURRENT source hashes to V2,
  and that MISMATCH is exactly what routes re-ingestion into D11 part 3's three-way conflict
  merge (V1 = common ancestor, V2 = local branch, the commented DOCX = remote branch). Refreshing
  provenance on save would FORGE the render record: the returning DOCX would claim V2 ancestry,
  re-ingestion would fast-forward cleanly, and the V1-to-V2 edits would be silently stomped.
  The editor's commit-per-save rule is also what keeps V1 recoverable (as a real git commit) for
  that merge. Hardening requirement passed to chunk 4.4: recover the ancestor by hash-walking the
  source's git history, and extend `Provenance` with an optional `source_commit` field stamped at
  render time ONLY when the source sits in a clean git work tree (omitted or flagged dirty
  otherwise, since HEAD would not match the content), making ancestor lookup direct.

### 1.4 The API contract (extends api/app.py; the first genuinely MUTATING routes)

```
GET  /editor/doc?path=<src.md>           -> outline: [{index, level, title, hash}], frontmatter
                                            flag, doc-level hash
GET  /editor/section?path=&index=        -> {raw, hash, preview_blocks: [{kind, language}]}
POST /editor/render-fragment             -> {content, kind} -> exact server-side preview HTML/SVG
PUT  /editor/section                     -> {path, index, base_hash, content, commit_message}
                                            -> 409 if base_hash no longer matches (file changed
                                            on disk or in another tab); 400 on empty message
                                            when a diff exists; else commits and returns the new
                                            outline + hashes
```

Guards: everything rides the existing D15 set (loopback Host, Origin allowlist, path jail under
--root), and `PUT /editor/section` additionally REQUIRES the `X-Renderfact-CSRF` header carrying
a `/session` token: this is the mutating surface the token mechanism was built waiting for.
`POST /editor/render-fragment` is compute-only and follows the /project posture.

### 1.5 Worked example (against the F3 demo source)

`GET /editor/doc?path=demo/source/signalling-it-refresh.md` yields section 0 (frontmatter),
section 1 "(preamble)" (the demo's callout paragraph), then one node per ATX heading ("1.
Overview", "2. Scope", ... "Annex B: glossary"), each a leaf. The projection fenced-divs inside
"3. Requirements" do not split it: the fence-aware splitter keeps the whole requirements section
(prose + table + `:::` blocks) as one editable leaf. Editing the requirements table and saving
with message "tighten R-04 latency wording" produces exactly one commit with that message; a
second tab holding the stale hash gets 409 on its own save attempt.

## 2. E7b (XLSX): the two-pane editor and the canonical schema

### 2.1 Schema shape: dense row-major, one row per line (resolves the OQ5 sub-question)

**Decision.** Per workbook, one YAML document:

```yaml
renderfact_xlsx: 1            # schema version
sheets:
  - sheet: Budget
    merges: [A1:C1]           # sorted, only when present
    rows:
      - ["Item", "Qty", "Unit cost", "Total"]
      - ["Cab radio units", 120, 1850, {f: "=B2*C2", v: 222000}]
      - ["Trackside gateways", 46, 3200, {f: "=B3*C3", v: 147200}]
```

- A cell is a bare YAML scalar (string/int/float/bool/null) when it is a plain value; it becomes
  a small mapping `{f: <formula>, v: <last computed value>}` ONLY when a formula exists (formula
  and value as distinct fields, per D12b). Dates serialize as `{t: date, v: "2026-07-03"}` so
  type survives the round trip.
- **Diff stability comes from the one-row-per-line rule:** rows serialize as YAML flow sequences,
  exactly one line each. A row insert/delete is then a one-line git diff; a cell edit is a
  one-line change. This is why cell-address-keyed maps (`A1:`, `B2:`) were REJECTED: inserting
  one row renumbers every address below it and the diff becomes the whole sheet. The accepted
  cost: a COLUMN insert rewrites every row line; column operations are rarer than row operations
  in the tabular sources this targets, and the diff is at least honest about touching every row.
- Deterministic ordering rules (the "canonical" in canonical source): sheets in workbook order;
  rows ascending; trailing empty cells trimmed per row; trailing empty rows trimmed; merges
  sorted lexicographically. The exporter (xlsx to yaml) is deterministic by construction; two
  exports of the same workbook are byte-identical.
- Formatting (fonts, fills, widths) is EXPLICITLY out of scope for the canonical source v1: the
  source mirrors CONTENT (values, formulas, types, merges). Presentation belongs to the render
  side (a template profile), same separation the DOCX path already lives by.

### 2.2 Editor mechanics

Two panes (D12b): left = sheet list, right = an HTML table that IS the edit surface. A cell
displays its value; entering a cell that has a formula shows the formula for editing (standard
spreadsheet convention). **No recompute engine in v1:** editing a formula marks its `v:` as
stale (visible badge; stored as `v: null` plus `stale: true`) until a real export from a
recalculating tool, or a hand-entered value, refreshes it. Building a formula evaluator is a
rabbit hole explicitly declined; the metasource (WHY the formula changed, via the mandatory
commit message) outweighs a stale cached value (D12b's metasource-primacy, applied).

Save/diff/commit-message mechanics are IDENTICAL to 1.3/1.4: same PUT semantics against a sheet
(base_hash per sheet), same CSRF requirement, same git wiring. The editor edits the YAML
canonical source; `render` produces the XLSX artifact from it (the exporter/importer pair is
part of chunk 5.9's scope).

## 3. E7c (PPTX): as-text depth and the deck-engine coupling

### 3.1 Depth decision: slide-level as-text now, shape-level declined for the canonical source

**Decision.** The canonical deck source is Marp-flavored markdown (already-pinned engine, D12c's
`[imitate]`): slide separators, per-slide directives (`<!-- _class: ... -->`, background, layout
class), frontmatter theme reference fed by the A1 token generator's marp theme. That covers
slide-level structure and styling fully as reviewable, diffable text.

**Shape-level pixel positioning (text boxes at x,y; free-form art slides) is DECLINED as a
canonical-source feature.** Rationale: a coordinate soup in YAML is technically "as text" but
fails D12c's actual bar, human-readable and changeable; nobody reviews `x: 2.31in` deltas
meaningfully. Decks needing hand-placed pixel art are out of this tool's governed-projection
lane; the honest boundary is: if it cannot be said in slide-level directives plus content, it is
presentation-side work in the rendered artifact, and the provenance `adopt` path already covers
governing such externally-authored files.

### 3.2 The deck-engine question: resolution path, not unilateral resolution

tools.lock's deferred question (Marp vs Slidev vs Typst-touying) stays open, and 5.10 inherits
it. What this spike fixes is HOW and WHEN it resolves: a small bench INSIDE chunk 5.10's first
step, before any editor UI work: render one 6-slide deck (the demo's tender briefing) through
marp-cli (pinned) and typst-touying (typst already pinned for posters/PDF), compare: chromium
dependency (marp needs it, touying drops it, a real D10/native-mode win), A1 token-theme fit
(generators already emit BOTH a marp CSS theme and typst tokens), PDF quality, and source-syntax
migration cost. Slidev is EXCLUDED from the bench: it drags a Vue/Node app dependency, exactly
the weight class D12's stack decision rejected. Whichever wins, the canonical source stays
markdown-shaped; a touying win adds a thin md-to-touying transform rather than changing the
authoring format.

### 3.3 Editor shape for decks

Three panes like E7, not two like E7b: left = slide list (nav), middle = the slide's markdown
source, right = preview. Live preview is the vendored md renderer (approximate; no chromium in
the browser); exact preview renders the single slide server-side through the real deck engine
(debounced, on demand), same live/exact rule as 1.2. Save/commit mechanics identical to 1.3.

## 4. What 5.7 unblocks and in what order

- **5.8 (markdown editor): fully scopeable now.** Backend routes (1.4) + fence-aware splitter +
  the three-pane page. First mutating route lands with the CSRF requirement.
- **5.9 (XLSX): scopeable now**, including the exporter/importer pair for the 2.1 schema.
- **5.10 (PPTX): scopeable EXCEPT its first step is the 3.2 engine bench**; UI work follows the
  bench outcome.
- Build order recommendation: 5.8 first (proves the shared save/diff/commit/CSRF mechanics),
  5.9 second (reuses them against the sheet shape), 5.10 last (bench, then UI).
- D13's freeze note: these remain BEHIND the F-track publish items whenever those have open work;
  the spike itself was fill-in work, as D13 allows.

## 5. Still open after this spike (honest list)

1. Which md renderer to vendor for live preview (bench marked-class candidates for size and
   CommonMark fidelity during 5.8; a one-afternoon choice, not a design question).
2. Whether `POST /editor/render-fragment` should cache by content hash (decide in 5.8 when real
   latency numbers exist).
3. XLSX `stale: true` UX detail: whether saving a stale value warns or blocks (default: warn).
4. The deck-engine bench outcome itself (3.2, inside 5.10).
