# wiki/ -- renderfact documentation site (Quartz v4)

This directory holds the **source of the public documentation site**: the Quartz v4 config and the
Markdown content, organised by the [Diataxis](https://diataxis.fr/) framework. The site is built with
[Quartz v4](https://quartz.jzhao.xyz/) and published to GitHub Pages.

```
wiki/
  quartz.config.ts     # Quartz v4 site config (title, baseUrl, theme, plugins)
  quartz.layout.ts     # Quartz v4 layout (graph, backlinks, explorer, TOC, search)
  content/             # the docs, by Diataxis quadrant
    index.md           #   landing page
    tutorials/         #   learning-oriented  (getting started)
    how-to/            #   task-oriented      (recipes)
    reference/         #   information-oriented (engine catalog, header spec, env config)
    explanation/       #   understanding-oriented (the portable-core model + doctrine)
```

The deploy workflow lives at the repo root (`.github/workflows/deploy-wiki.yml`) because GitHub Actions
only reads workflows from there.

## The framework is fetched, not vendored

The Quartz framework itself (the `quartz/` engine, `package.json`, build tooling) is **not** committed to
this repo. We keep only **our config + content** here. The framework is fetched at build time and our
files are overlaid into it. This keeps the repo small and the upstream framework upgradable.

Quartz is fetched via the official scaffolder, `npx quartz create`, or by cloning the `v4` branch
directly. Our `quartz.config.ts`, `quartz.layout.ts`, and `content/` then slot into the Quartz project
root (the deploy workflow does this copy automatically; see below).

## Build & preview locally

You need Node.js (the deploy CI uses Node 22). From a scratch directory:

```bash
# 1. fetch the Quartz v4 framework
git clone --depth 1 --branch v4 https://github.com/jackyzha0/quartz.git quartz-site
cd quartz-site
npm i

# 2. overlay this repo's config + content (adjust the path to your checkout)
cp /path/to/renderfact/wiki/quartz.config.ts ./quartz.config.ts
cp /path/to/renderfact/wiki/quartz.layout.ts ./quartz.layout.ts
rm -rf ./content && cp -r /path/to/renderfact/wiki/content ./content

# 3. build + serve with live reload at http://localhost:8080
npx quartz build --serve
```

Alternatively, `npx quartz create` will scaffold a fresh Quartz project interactively; choose to start
with an empty/links source, then copy the three items above in.

> The repository's own CI does **not** run `npx`/`npm` for these files -- this scaffold is authored as
> plain source and is only built at publish time by the deploy workflow.

## How deploy works

`.github/workflows/deploy-wiki.yml` (verified against the official Quartz v4 GitHub Pages recipe):

1. **Triggers** on push to the default branch (`main`, scoped to `wiki/**` changes) and on manual
   `workflow_dispatch`.
2. **Checks out** this repo with full history (so `CreatedModifiedDate` can use git dates).
3. **Fetches** Quartz v4 and **overlays** `quartz.config.ts`, `quartz.layout.ts`, and `content/`.
4. **Builds** with `npx quartz build` (Node 22) and uploads `public/` as the Pages artifact.
5. **Deploys** to GitHub Pages via `actions/deploy-pages`.

**Before the first deploy:** set repo **Settings > Pages > Source = "GitHub Actions"**, and replace the
placeholder `baseUrl` in `quartz.config.ts` (and the footer URL in `quartz.layout.ts`) with your real
GitHub Pages URL. Pages must be enabled for the deploy job to succeed -- a one-time setup step.

## Editing the content

- Write standard Markdown. Obsidian-flavored features are preserved: `[[wikilinks]]`, `![[embeds]]`,
  `> [!callout]` blocks, tags, and LaTeX. Backlinks, the graph view, and the file explorer are wired up
  in `quartz.layout.ts`.
- Keep each page in its correct Diataxis quadrant (see the folder roles above). Mixing tutorial and
  reference material in one page is the most common docs anti-pattern.
- Front-matter `title:` sets the page title; `tags:` feed the tag pages and graph.

## Versioning note

This scaffold targets **Quartz v4** (TypeScript config: `quartz.config.ts` / `quartz.layout.ts`). The
live docs site (quartz.jzhao.xyz) now documents Quartz **v5**, whose config is YAML
(`quartz.config.yaml`). If you upgrade to v5, the config format changes -- consult the current docs and
migrate the config accordingly; the `content/` Markdown carries over.
