# Prior art: PaperBanana prompt-scaffolding patterns

Reusable prompting patterns extracted 2026-07-02 from `llmsresearch/paperbanana` (MIT, unofficial
reimplementation of arXiv:2601.23265, audited via a forked clone -- see the security-audit findings
in that session's transcript for the parts NOT reused here, notably an unsandboxed LLM-code-exec
path in its plot pipeline that this toolchain should NOT replicate). Feeds C6 (sovereign LLM
design-assist) on the roadmap -- these are prompt-architecture ideas, not code to import verbatim.

## Pipeline shape worth copying
Retriever -> Planner -> Stylist -> (Visualizer <-> Critic loop) -> optional vector-exporter.
Each stage is a separate LLM call with ONE narrow role and a strict, parseable output contract --
not one mega-prompt doing everything.

## The rules worth stealing

**Natural-language color names, never hex/pixel/CSS values, enforced at every stage.**
Repeated identically in Planner, Stylist, and Critic prompts (Critic explicitly flags leaked
hex-codes as a defect). Reason: raster image-gen models render literal hex/pixel values as garbled
text on the image if the prompt contains them -- describing "muted teal" works, "#184652" doesn't.
Directly applicable to any of our own concept-to-visual generation prompts (D2/Mermaid/Typst-cetz
generation from natural-language descriptions): keep the token *values* in code (tokens.yaml/brand
config), but if an LLM is describing the desired look in a planning step, make it describe colors
in words, not hand it hex codes to reproduce.

**Stylist = refinement pass, hard content/style separation, stated three times.**
Six numbered rules gate it: preserve/enhance aesthetics only, intervene only where genuinely weak
(explicit anti-over-editing instruction), respect per-domain visual conventions instead of forcing
one template, enrich vague visual language into concrete detail, NEVER touch
content/structure/labels (byte-identical requirement), and treat domain-semantic icons as protected
unless verified against source context. Reusable pattern for any "style pass that must not silently
mutate content" step in a pipeline -- state the content/style boundary more than once, in different
words, at the start AND end of the prompt.

## Retriever: structural match beats topical match
Given a target diagram brief + a candidate reference-example pool, it reranks (not embeds) on TWO
axes -- Domain (closed taxonomy) and Visual Intent (Framework/Pipeline/Detailed-Module/
Performance-Chart-type structural similarity) -- with an explicit priority rule: "a Framework
diagram example is useless for drawing a Bar Chart, even in the same domain." Output is a strict
`{"selected_ids": [...]}`, no free text. Applicable to our own reference-set selection (e.g. if we
ever build a "pick the closest existing template" step ahead of D2/Typst generation): rank
candidates on what SHAPE of diagram they are, not just topic-keyword overlap.

## Planner: one dense paragraph + one structured trailer line
Converts (brief + N retrieved examples) into a single natural-language visual spec covering 7 fixed
dimensions every time (layout/flow direction, components with exact labels, connections/arrows,
groupings, labels/annotations, input/output boundary, styling-in-words) -- then appends ONE
machine-parseable trailer line (`RECOMMENDED_RATIO: <ratio>`) with concrete heuristics attached
(sequential pipelines -> wide 16:9/21:9, deep hierarchies -> tall 2:3/9:16, balanced -> square-ish).
Pattern: rich free-text body for a human/LLM-visualizer to read, ONE structured trailer field for
code to parse -- avoids forcing the whole spec into brittle JSON while still giving downstream code
something reliable to grab.

## Critic: strict JSON output with a null-sentinel stop condition
Two axes -- Content (fidelity, no hallucinated content, text-QA for garbled/misspelled labels and
leaked hex/CSS values, caption-must-not-be-baked-into-the-image) and Presentation (clarity,
redundant in-image legend removal -- color-coding should be self-evident or explained in the
caption, not duplicated inside the figure). Output: `{"critic_suggestions": [...],
"revised_description": "..."}`, where `revised_description: null` IS the stop signal for an
auto-refine loop. Told explicitly to modify the prior description incrementally, not rewrite from
scratch -- keeps refinement convergent across iterations instead of resetting each round.

## The vision-to-vector-code trick (closest analog to an image-to-editable-source step)
Single-shot, not iterative. Given the RENDERED RASTER IMAGE plus the ORIGINAL semantic spec
(planner's description) and source text as disambiguation context, it asks for a self-contained
TikZ fragment (no `\documentclass`/`\begin{document}`/`\input`, inline `\usetikzlibrary{}`,
`at (x,y)` cm-grid node placement, `% --- Section ---` comments separating logical groups for
human-editability afterward). **The key idea, generalizable beyond TikZ**: don't ask the model to
trace pixels blind -- give it BOTH the pixels AND the known-correct semantic spec that generated
them, so structure/labels come from the spec (ground truth) and only visual-fidelity details
(positions-as-rendered, colors-as-seen) come from the image. Directly applicable to any
raster/sketch -> D2/Mermaid/Typst-cetz reverse-pipeline step: if a spec already exists (even a
rough one), feed both, don't rely on vision alone.

## Venue style-guide plug-in architecture
Base guide + per-venue override files share an IDENTICAL 5-axis schema (Color Palettes / Shapes &
Containers / Lines & Arrows / Typography & Icons / Layout & Composition) plus a "Venue Format Facts
(grounded)" header citing hard sourced constraints (column width, fonts, resolution, dated source
URLs) and a "Common Pitfalls" section. Only the CONTENT under each heading changes per venue
(NeurIPS: pastel/rounded/illustrative-icons-ok; IEEE: white-grey/sharp-corners/grayscale-safe/
control-systems conventions, explicit warning that ML-pastel aesthetics read as informal to IEEE
reviewers). Adding a new venue/audience/classification-tier profile = write one markdown file
matching the schema, not a code change. Directly reusable for our own audience-persona /
classification-tier render profiles (RA1-RA10 personas, clearance-tier renders) -- same idea, keep
the schema stable, vary the content file per profile.

## What NOT to replicate
PaperBanana's `_execute_plot_code()` runs LLM-generated Python via bare `subprocess.run` with only
a 60s timeout, no sandbox, no import allowlist -- reachable via its MCP tools, CLI, and web UI. Its
own SECURITY.md claims this is "sandboxed to plotting functions"; it is not, per source review.
If C6 (sovereign LLM design-assist) ever needs a code-execution step (e.g. an LLM writing D2/cetz
source that then gets rendered), the render step must go through the render-toolchain's OWN pinned,
isolated engines (d2/typst/mmdc binaries invoked on TEXT the LLM produced) -- never `exec()`/
`subprocess`-run raw LLM-generated Python or JS with OS-level privileges. Text-DSL-in, deterministic
renderer-out is the safe shape; LLM-writes-and-we-execute-arbitrary-code is not.

## Source
`llmsresearch/paperbanana` (MIT); audited from a working fork.
Prompts read in full: `prompts/diagram/{retriever,planner,stylist,critic,tikz_exporter}.txt`.
Guidelines read in full: `data/guidelines/methodology_style_guide.md` (NeurIPS base),
`data/guidelines/ieee/methodology_style_guide.md` (venue override).
