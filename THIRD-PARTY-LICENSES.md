# Third-party licences (P2.5)

renderfact itself is MIT (see LICENSE). The container image REDISTRIBUTES the
engines below; native mode merely invokes what the host has installed. Every
identifier below was verified against its upstream primary source on
2026-07-04 (LICENSE/COPYING files, official licence pages, or PyPI metadata).

Where the full verbatim licence texts live: pip-installed libraries carry
their licence files inside their own wheel metadata (site-packages
`*.dist-info`); Debian-packaged components keep their copyright files at
`/usr/share/doc/<package>/copyright` inside the image; the two directly
downloaded fonts bundle their upstream OFL texts.

## Engines redistributed in the container image

| Component | Licence (SPDX, verified 2026-07-04) | Role |
|---|---|---|
| Debian bookworm-slim base | various (per-package; see /usr/share/doc) | base image |
| Python 3.11 | PSF-2.0 | runtime |
| pandoc | GPL-2.0-or-later (bundles sub-components under BSD-3-Clause, MIT, and dual-licensed templates; see its COPYRIGHT file) | md to DOCX conversion |
| typst | Apache-2.0 | tagged PDF, posters |
| mermaid-cli (mmdc) | MIT (drives headless Chromium at runtime) | diagrams |
| d2 | MPL-2.0 | diagrams |
| graphviz | EPL-2.0 (lineage: AT&T SCA, then CPL-1.0, then EPL-2.0 current) | diagrams |
| marp-cli | MIT (drives headless Chromium at runtime) | decks |
| chromium | BSD-3-Clause core; third_party/ components under many licences (see chrome://credits or the source tree's README.chromium files) | headless engine for marp/mmdc |
| LibreOffice | MPL-2.0 primary; contributions dual MPL-2.0/LGPL-3.0-or-later plus Apache-2.0 heritage code | DOCX to PDF fallback |
| cairosvg | LGPL-3.0-or-later (the "or later" per its packaging metadata; the LICENSE file text is LGPL-3.0) | SVG to PDF |
| likec4 | MIT | architecture diagrams |
| Inter font | OFL-1.1 | fonts |
| Palanquin font | OFL-1.1 | fonts |
| Roboto font | Apache-2.0 AS BAKED (installed from Debian's fonts-roboto package, the classic build; note the CURRENT Google-Fonts Roboto distribution is OFL-1.1 after the ~2021 relicensing, so this identifier is pinned to the package the image actually installs) | fonts |

OFL note: the Reserved Font Name clause only bites on MODIFIED fonts promoted
under the original name; all bundled fonts are unmodified upstream files.

## Python libraries (dependencies, not vendored)

All verified 2026-07-04: PyYAML MIT, python-docx MIT, openpyxl MIT (Heptapod
upstream; corroborated via PyPI metadata), python-pptx MIT, docxcompose MIT,
pypdf BSD-3-Clause, pytest MIT (dev only).

## Recorded licence elections (decisions, not yet integrations)

- **veraPDF** (INTEGRATED 2026-07-04, B3c; redistributed in the container image, greenfield 1.30.2 + openjdk-17-jre-headless): dual GPL-3.0 / MPL-2.0. Election recorded 2026-07-03: invoke as a
  CLI SUBPROCESS, never embed as a library, so no copyleft obligation attaches to renderfact's
  MIT code. Revisit only if performance ever demands embedding, and then under the MPL-2.0 arm.
- **PlantUML** (planned, A6/B1): GPL-3.0. Same treatment as pandoc: a GPL engine invoked as a
  subprocess and redistributed in the image with this NOTICE; renderfact code stays MIT.

## Pattern imitations (no code taken, no licence obligation)

calm-ai (init-ai pattern), aider (copy-paste mechanism), PaperBanana (doctor/run_id/prompt
scaffolding patterns), docling-serve (route + /ui mount shape), Style Dictionary (transform
pipeline shape), DTCG (token syntax conventions), Asciidoctor conditionals + Quarto profiles
(projection gate models), BrandDocs (theme sysClr/lastClr resolution logic, MIT, credited in
docstyle/ooxml_theme.py), EMF Compare + Structurizr (diagram round-trip matching and layout
separation doctrines), mammoth (style-map DSL shape), markdownlint MD043 (structure-gate
semantics). Patterns were studied and reimplemented; no source was copied.
