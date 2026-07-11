# Standalone-CLI capabilities index

`render --help` only lists the commands wired into `render.py`'s top-level dispatcher (`MODES`).
Several other modules in this repo also have their own argv-parsing `main()` (argparse or manual) and
run directly as `python <path> ...`, but are one abstraction level down: internal stages of a wired
pipeline, or dev/CI tooling. Because `--help`-driven discovery only sees the wired set, a real,
standalone-useful capability can sit undiscovered until someone reads the module source end to end --
exactly what happened with `docstyle/style_postprocess.py`'s `--table-widths` before issue #74. This
index exists so that does not have to happen again: every module with its own CLI surface is listed
here, wired or not.

## Wired into `render` (top-level, `render <mode> ...`)

See `wiki/content/reference/index.md` for the full flag reference of each. Source module per mode:

| Mode | Module |
|---|---|
| `docx` | `container/render-doc.sh` (+ `docstyle/style_postprocess.py`, `docstyle/heading_numbering.py` internally) |
| `docstyle` | `docstyle/style_postprocess.py` |
| `pdf` | `pdf/typst_backend.py` |
| `diagram` | `lint/render.py` |
| `tokens` | `tokens/gen/generate_all.py` |
| `init-ai` | `contracts/init_ai.py` |
| `copy-paste` | `contracts/copy_paste.py` |
| `provenance` | `roundtrip/provenance.py` |
| `reingest` | `roundtrip/reingest.py` |
| `drawio` | `roundtrip/drawio.py` |
| `vsdx` | `roundtrip/visio.py` |
| `decision-capture` | `roundtrip/decision_capture.py` |
| `contextualize` | `roundtrip/contextualize.py` |
| `gate-stats` | `contracts/gate_telemetry.py` |
| `import-template` | `docstyle/template_import.py` |
| `project` | `projection/projector.py` |
| `qa` | `lint/render_qa.py` |
| `serve` | `api/app.py` |
| `gate` | `gates/run_gates.py` |
| `doctor` | `doctor.py` |
| `container` | `container/render` (raw podman passthrough) |

## Standalone-CLI, not wired into `render`

Real, independently runnable command surfaces that are internal stages of a wired pipeline (the wired
mode's own orchestrator calls them), or dev/CI/build tooling outside the render pipeline entirely.
Each is runnable directly for debugging a single stage without the full pipeline.

| Module | CLI surface | Normally invoked by | Notes |
|---|---|---|---|
| `docstyle/heading_numbering.py` | `python heading_numbering.py <docx...> [--check] [--scheme modern\|trailing-dot] [--profile <yaml>] [--levels N]` (argparse) | `render docx` via `--number-headings` (render-doc.sh) | Field-based heading-numbering injector, idempotent. Same shape as the #74 gap: a real standalone tool only reachable by direct script invocation. Candidate for a future `render heading-numbering` subcommand if a caller needs it outside the docx pipeline. |
| `lint/element_budget.py` | `python element_budget.py <svg...> [--tier <name>]` | `render diagram` (`lint/render.py` orchestrates the diagram lint stages) | GR-4 view-tier element-budget check. |
| `lint/mermaid_source.py` | `python mermaid_source.py <mmd...>` | `render diagram` | Pre-render `.mmd` source lint (GR-MM-* rules), runs before `mmdc`. |
| `lint/patch_svg_a11y.py` | `python patch_svg_a11y.py <svg...>` | `render diagram` | Post-render SVG accessibility patch (`role="img"` + `aria-labelledby`), idempotent. |
| `lint/svg_metrics.py` | `python svg_metrics.py <svg...>` | `render diagram` | Deterministic visual-QA metrics for rendered Mermaid SVG. |
| `lint/visual_quality.py` | `python visual_quality.py <svg...>` | `render diagram` | Graphical golden-rule linter (palette, contrast, a11y attributes). |
| `tokens/gen/marp_theme.py` | `python marp_theme.py <brand.yaml>` | `render tokens` (`generate_all.py` orchestrates all engine generators) | Marp CSS theme generator. |
| `tokens/gen/mermaid_theme.py` | `python mermaid_theme.py <brand.yaml>` | `render tokens` | Mermaid JSON theme generator. |
| `tokens/gen/pandoc_template_profile.py` | `python pandoc_template_profile.py <brand.yaml>` | `render tokens` | Emits the flat `template-profile.yaml` `docstyle/style_postprocess.py` consumes. |
| `tokens/gen/theme_tokens.py` | `python theme_tokens.py <brand.yaml>` | `render tokens` | Base token-set resolution shared by the other generators. |
| `tokens/gen/typst_tokens.py` | `python typst_tokens.py <brand.yaml>` | `render tokens` | Typst theme-token generator (`render pdf`'s theme source). |
| `container/bundle-annex-linux.py` | `python bundle-annex-linux.py <cover> <body> [annex...] -o <out.docx>` | container release/bundling step | Cross-platform (Linux, `docxcompose`-based) analog of a Word-COM cover+body+annex bundler. Build/release tooling, not a content-pipeline mode. |
| `scripts/generic_gate.py` | `python scripts/generic_gate.py` | CI, pre-publish | Public repo-hygiene gate (personal paths, non-allowlisted committer emails, generic secrets). Repo hygiene, not a render capability. |
| `scripts/check_wiki_sync.py` | `python scripts/check_wiki_sync.py` | CI | Enforces that this very index's sibling, the wiki reference table, stays in sync with `render.py`'s `MODES`. Repo hygiene, not a render capability. |

Repo hygiene / build tooling (the last three rows) are listed for completeness but are intentionally
out of scope for `render` top-level wiring: they operate on the repo itself, not on a document being
rendered.
