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

The repository ships a fictional railway-infrastructure operator ("Meridian Rail Infrastructure")
under `demo/`: a full-candor procurement dossier with three audience profiles, a governance/financial
document, and a demo brand skin. Run the whole thing:

```bash
bash demo/render-demo.sh
```

That projects one source into three governed renders, generates the Meridian brand tokens, renders the
public-tender projection to DOCX (if pandoc is present), and renders the branded PDF (if typst + pandoc
are present). Or run the steps by hand -- project one profile:

```bash
render project demo/source/signalling-it-refresh.md \
  --profiles demo/profiles.yaml --profile public-tender
```

Try the other profiles (`internal-full`, `bidder-pack`) to see the same source projected differently:
the internal render keeps full candor; the public tender keeps only what may travel and carries the
abstract baseline.

## Render a branded governance/financial PDF

The second demo source, `demo/source/agm-minutes.md`, is Meridian's Annual General Meeting minutes. It
exercises the layout-native PDF backend and its semantic blocks -- an attendance callout, a **data-bound
statement** whose totals are computed and reconciled from `demo/source/afrekening.yaml`, and a signature
grid -- rendered with the Meridian skin, the `financial` theme variant, and a locale:

```bash
render pdf demo/source/agm-minutes.md \
  --brand demo/skin/brand.yaml --variant financial --locale en \
  --org "Meridian Rail Infrastructure" --title "AGM Minutes 2026" --date 2026-03-18
```

Change `--locale en` to `nl-BE` to reformat the amounts, date, and block labels in Belgian Dutch;
add `--project public-tender --profiles demo/profiles.yaml` to render an audience-projected branded PDF
(or `--project all` for one PDF per profile). Needs `typst` and `pandoc` (`render doctor` tells you).

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
