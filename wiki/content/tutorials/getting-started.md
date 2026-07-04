---
title: Getting started
---

# Getting started

This walks you from a clean checkout to a rendered document, using the bundled fictional demo so
nothing depends on your own content.

## Install

renderfact runs on Python 3.11+ (dev-tested on 3.14 too). Editable install from a checkout:

```bash
git clone https://github.com/Wombat164/renderfact
cd renderfact
pip install -e .
```

That installs the `render` console entry point. Some steps use external engines (pandoc, typst,
mermaid-cli, d2) or optional Python libraries (svgpathtools for diagram metrics, vsdx for the Visio
adapter, markitdown for embedded-object previews); each degrades gracefully or tells you exactly what
to install when you reach a step that needs it. Check your host against the pinned tool versions:

```bash
render doctor
```

`render doctor` reports OK / OK-unpinned / DRIFT / MISSING / SKIP per tool and always exits 0 -- it is a
report, not a gate.

## Render the demo

The repository ships a fictional railway-infrastructure operator's procurement dossier under `demo/`:
one full-candor source, three audience profiles, a demo brand skin. Render it:

```bash
render docx demo/source/meridian-rail-signalling.md --profile public-tender
```

You get a styled, numbered DOCX with the public-tender profile's disclosure rules applied. Try the
other profiles (`bidder-confidential`, `internal-evaluation`) to see the same source projected
differently.

## Gate a document

Run the fail-closed QA chain over any rendered artifact:

```bash
render gate demo/renders/*.docx --stages vale,lychee,verapdf
```

Findings fail; a requested stage whose tool is missing fails loudly. This is what CI would run.

## Next

- Recipes for each capability: **[How-to](../how-to/index.md)**.
- The full command surface and environment variables: **[Reference](../reference/index.md)**.
- Why the pipeline is shaped this way: **[Explanation](../explanation/index.md)**.
