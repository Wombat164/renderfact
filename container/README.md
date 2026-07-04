# renderfact render toolchain (container image)

Self-contained OCI image that runs the docs-as-code render pipelines on Linux (no
Windows / PowerShell needed).

**Generic core / private skin.** The image and every script in this directory are
domain-neutral: any consumer supplies its own skin (reference template, filters,
house-style overrides) through the environment contract documented at the top of
`render-doc.sh`, and its own content. Nothing here assumes a particular source
tree layout.

## What's inside (pinned to ../tools.lock where applicable)

| Tool | Version | Pipeline |
|------|---------|----------|
| pandoc | 3.10 | structured document -> DOCX (+ optional Lua filters) |
| typst | 0.15.0 | A2 posters, PDF/UA + PDF/A archival (roadmap modes) |
| mmdc (mermaid-cli) | 11.15.0 | diagrams -> SVG (lint/ harness) |
| d2 | 0.7.1 | iconographic diagrams |
| marp-cli | 4.4.x | decks -> PDF/PPTX (roadmap mode) |
| cairosvg | 2.9.0 | SVG -> PDF in the harness |
| graphviz (dot) | 2.43 | dense graph layout |
| chromium | 149 | marp / mmdc headless engine |
| libreoffice (soffice) | 7.4 | DOCX -> PDF for `render-doc.sh --pdf` |
| python-docx, openpyxl, python-pptx, pyyaml | - | DOCX/XLSX/PPTX post-processing, configs |
| likec4 | 1.58.0 | architecture diagrams |
| fonts | Inter, Palanquin, Roboto | deterministic render |

(drawio-desktop is currently a broken, non-fatal layer; its resolve-or-drop
question is owned by the editable-diagram round-trip roadmap item.)

Chromium runs as root inside the container, so a `chromium-nosandbox` wrapper is
baked in and wired via `PUPPETEER_EXECUTABLE_PATH` / `CHROME_PATH`; mmdc, marp
and puppeteer all pick it up with no per-call flags.

## Build

    ./build.sh        # sudo podman build -t localhost/renderfact:latest .

## Run

The `render` wrapper always mounts `$PWD` at `/work`; set `SOURCE_ROOT` to also
mount a source tree at its real path:

    ./render pandoc --version

    SOURCE_ROOT=/path/to/your-source-tree \
      ./render bash render-doc.sh "$SOURCE_ROOT/your-doc.md" --number-headings FINAL

    ./render python3 lint/render.py diagram.mmd --formats svg,pdf

`render-doc.sh` is the portable annotated-markdown -> styled DOCX pipeline: one
script, auto-detects Windows (git-bash) vs Linux/macOS, resolves pandoc/python
from PATH, ships generic house-style + field-numbering defaults (docstyle/),
and takes every consumer-specific piece via environment variables (SKIN_DIR,
TEMPLATE_DOCX, STYLE_POSTPROCESS, ...) documented in its header. `--pdf` uses
LibreOffice, or a consumer-supplied Word-COM converter on Windows.
