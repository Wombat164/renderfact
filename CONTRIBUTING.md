# Contributing to renderfact

Thanks for your interest. renderfact is a governed docs-as-code render framework; contributions that
keep the core domain-neutral and honest about what is built are very welcome.

## Development setup

```sh
git clone <repo-url> renderfact
cd renderfact
pip install -e .[dev]     # editable install + pytest
pytest -q                 # the full suite
```

`pip install -e .` is the supported install mode: the entry point dispatches to sibling directories
via repo-relative paths, so an editable install is what wires `render <mode>` correctly. The render
ENGINES (pandoc, typst, mermaid-cli, d2, marp, and so on) are pinned separately in `tools.lock` and
shipped in the container image; the container path is verified by `verify-pins.sh` inside the image.

## Test discipline

- **Every change lands with tests.** A new mode, gate, or contract change is not done until it has
  coverage; tests shadow the code as it lands, not at the end.
- **Fixtures are built programmatically, never committed as binaries.** DOCX/XLSX/PPTX fixtures are
  constructed in-test with python-docx / openpyxl / python-pptx; source and config fixtures are
  written to a temp dir. There are no binary fixtures in the repo. This keeps the tree reviewable and
  the fixtures self-documenting.
- Prefer real end-to-end exercise over mock-only tests where a pipeline can actually be driven (for
  example, run the projection engine over a real source and assert the gate held).

## Prose and file conventions

- **ASCII only** in source, docs, and generated text (plus the diacritics a target language needs).
  No smart quotes, em dashes, or other decorative Unicode.
- **Do not use the spaced double-hyphen token** as a separator anywhere (prose, headings, filenames).
  Use a colon, a comma, parentheses, or a single hyphen instead.
- Keep the public core domain-neutral: no organisation-specific content, paths, or branding in the
  repo. Domain specifics belong in a private skin (see `ARCHITECTURE.md`).
- Files are UTF-8 without BOM.

## Pull requests

- Keep each PR to a single reviewable unit of work (one mode, one gate, one fix), with its tests.
- State honestly what is DONE versus specified: a claim in the docs must match the code. If a mode is
  a stub or a format is roadmap-only, say so rather than implying it works.
- Update the relevant doc (`ARCHITECTURE.md` for current-state behaviour, `ROADMAP.md` for what is
  next, `DECISIONS.md` for a genuinely new architectural choice) in the same PR.
- Add a CHANGELOG entry for user-visible changes.

## CI must be green

Every PR runs the test suite (across the container-pinned and dev-host interpreters, on Linux and
Windows) plus the repo's hygiene gates. A PR does not merge with a red CI. If a hygiene gate fails,
fix the underlying issue rather than bypassing the gate.
