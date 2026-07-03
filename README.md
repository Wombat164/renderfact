<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/renderfact-lockup-dark.svg">
    <img src="assets/brand/renderfact-lockup.svg" alt="renderfact" width="480">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/Wombat164/renderfact/actions/workflows/ci.yml"><img src="https://github.com/Wombat164/renderfact/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/renderfact/"><img src="https://img.shields.io/pypi/v/renderfact" alt="PyPI"></a>
  <a href="https://pypi.org/project/renderfact/"><img src="https://img.shields.io/pypi/pyversions/renderfact" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Wombat164/renderfact" alt="License: MIT"></a>
</p>

# renderfact

A lightweight, governed **docs-as-code render framework**: take one full-candor source and
produce **governed projections** (per audience / clearance / disclosure) rendered to styled DOCX
and diagrams today (slide decks, A2 posters, and archival PDF/UA are roadmap: see the capability
matrix below), with provenance and QA gates, from one container-or-native toolchain. The name is
a double meaning: render + artefact (what it produces), and render *factory* (what it is).

| Capability | Status |
|---|---|
| Projection (audience/clearance/disclosure gating) | shipped (`render project`) |
| Styled DOCX pipeline + generic house style + field numbering | shipped (`render docx`) |
| Diagrams (mermaid, d2) + pre-render lint + visual-QA metrics | shipped (`render diagram`) |
| Brand tokens -> per-engine themes | shipped (`render tokens`) |
| Dual-mode LLM steps (harness / copy-paste) | shipped (`render init-ai` / `copy-paste`) |
| Hidden provenance across DOCX/XLSX/PPTX | shipped (`render provenance`) |
| Template import (derive a skin from a branded DOCX) | shipped (`render import-template`) |
| Mechanical DOCX re-ingestion (provenance verdict, reviewer-edit report, fast-forward apply) | shipped (`render reingest`) |
| Editable-diagram round-trip, drawio adapter (stable IDs, semantic/style/layout routing) | shipped (`render drawio`) |
| Post-render QA gates | shipped (`render qa`) |
| Pre-publish gate chain, fail-closed (Vale text hygiene + lychee offline link integrity + veraPDF PDF/A + PDF/UA conformance + duplicate-uid detection) | shipped (`render gate`) |
| Localhost HTTP API + thin reference UI | shipped (`render serve`) |
| Slide decks, A2 posters, archival PDF (PDF/UA + PDF/A) | roadmap (v0.2.x) |
| Structured source editor (browser, direct human edit) | designed, not built |

> Status: early (v0.1.0). Consolidating a set of real render pipelines into one OSS
> toolchain. Licence: MIT.

## Why this exists (the gap)

Plenty of strong prior art covers *parts* of this pattern, but none covers the whole:

| System | Licence | Does well | Doesn't |
|---|---|---|---|
| **S1000D** + `s1kd-tools` | GPL-3.0 | defence/aero technical pubs, data-module single source (CSDB) | heavyweight; no clearance/disclosure projection; no decks/posters |
| **DITA-OT** | Apache-2.0 | one source -> many formats via transformation types | no audience/clearance gating; no PDF/UA+PDF/A guarantee; no decks/posters |
| **NIST OSCAL** + compliance-trestle | Apache-2.0 | compliance-docs-as-code; profile-as-projection | data interchange, not human-facing styled render |
| **GOV.UK** tech-docs / govspeak | OSS | gov docs-as-code, live HTML | HTML-centric; no projection gating; no archival PDF |

**The gap none of them fills:** source-vs-render **disclosure/clearance gating** + **accessible +
archival PDF (PDF/UA + PDF/A)** + **decks / posters / diagrams from ONE source** + **provenance**,
as a lightweight framework. That intersection is what this toolchain is for.

(What we borrow: DITA-OT's transformation-type abstraction, OSCAL's profile-as-projection,
S1000D's data-module discipline.)

## Architecture: generic core, private skin

The toolchain is **domain-neutral**. Any organisation supplies its own private *skin* (brand
token values, reference templates, audience personas, classification markings) and its content;
the public core never contains domain content.

```
your private config (skin)            render-toolchain (this repo, generic)
  brand.yaml values  ----------------> tokens/  (mechanism + neutral defaults)
  reference.docx     ----------------> container/ (engines, pinned)
  audience personas  ----------------> render <mode> (one entry point)
  source corpus      ----------------> lint/ + QA gates -> governed artifacts
```

Two delivery modes, kept separate but sharing one spine (tokens / source / diagrams):
**artifacts** (this toolchain: DOCX / PDF / posters / decks) vs **live HTML wiki** (a separate
gitops consumer). They do not merge.

## Engines (pinned -- see `tools.lock`)

pandoc 3.10 (md->DOCX) · typst 0.15.0 (tagged PDF/UA + PDF/A, posters, decks via touying) ·
mermaid-cli 11.15.0 + d2 0.7.1 + graphviz (diagrams) · cairosvg (SVG->PDF) · marp 4.4.0 +
chromium 149 (decks) · LibreOffice (DOCX->PDF fallback) · python-docx + docxcompose + pypdf
(Word-COM-free DOCX/PDF assembly). All in one OCI image; `verify-pins.sh` asserts the build
matches the lock.

## Layout

```
render.py    the single entry point -- render <mode> [args...] (execution-plan chunk 0.1+0.2)
projection/  the F1 projection engine (chunk P1.1) -- profiled fenced-div blocks -> one governed
             render per audience/clearance/disclosure profile; consumer-defined ladders
             (profiles-example.yaml), preprocessor-level exclusion, fail-closed on unknown labels
docstyle/    generic DOCX house-style post-processor + field-based heading numbering (chunk F2b):
             palette/markings/cover behaviour from an optional template-profile yaml (neutral defaults)
api/         stdlib HTTP API (chunk 5.1, D9): D8 step contracts + projection over localhost, opt-in
             thin reference UI at /ui, openapi.json + /docs; loopback-Host/origin/path-jail guards (D15)
container/   OCI image (Containerfile) + render wrapper + render-doc.sh + bundle-annex-linux.py + verify-pins.sh
lint/        diagram render harness (render.py) + pre-render linters + visual-QA metrics + the first
             D8 step-contract (vision_review_contract.py, chunk 3.1)
tokens/      brand.yaml token mechanism + per-engine generators (tokens/gen/, chunk 0.4)
contracts/   generic D8 I/O-contract mechanism (schema_utils.py) -- harness/copy-paste/HTTP-API-
             agnostic validation, shared by every LLM-touching step (chunk 3.1+) -- plus init_ai.py,
             the harness-mode installer (chunk 3.2), and copy_paste.py, the no-harness/no-API-key
             fallback (chunk 3.4) -- both generate their prompts/instructions FROM the same schema
roundtrip/   D11 Track D DOCX/XLSX/PPTX round-trip (chunk 4.1+) -- source_uid.py (stable per-source
             identity via frontmatter + content hashing) and provenance.py (hidden embed/extract/
             adopt/retarget via the shared OOXML dc:identifier property). Named to avoid shadowing
             python-docx's own `docx` import name.
docs/        DECISIONS + ROADMAP + EXECUTION-PLAN + architecture
tests/       fixture-based tests (dispatcher, tokens, D8 contract, init-ai, copy-paste, provenance
             covered; per-engine render tests todo)
tools.lock   pinned engine versions (single source of truth)
```

## Usage (the unified entry point)

```sh
python render.py docx <source.md> [--pdf] [--qc] [--lint] ...   # dispatches to container/render-doc.sh
python render.py diagram <files...> [--formats svg,pdf]         # dispatches to lint/render.py
python render.py tokens [--brand path/to/brand.yaml]             # brand.yaml -> per-engine themes (A1)
python render.py init-ai [--assistant claude|copilot|all]        # install D8 harness-mode instructions (chunk 3.2)
python render.py copy-paste <step> [--tier T] [--image P] ...    # D8 copy-paste mode -- no harness, no API key (chunk 3.4)
python render.py provenance embed <docx|xlsx|pptx> --source <md> # D11 hidden provenance, existing source (chunk 4.1)
python render.py provenance adopt <docx|xlsx|pptx> --source <md> # D11 provenance, no source/history yet (chunk 4.1)
python render.py provenance retarget <old> <new>                 # D11 carry provenance across a format change (chunk 4.1)
python render.py provenance extract <docx|xlsx|pptx>             # D11 read back embedded provenance (chunk 4.1)
python render.py provenance strip <docx|xlsx|pptx>               # D14 scrub renderfact provenance (foreign ids untouched)
python render.py reingest <edited.docx> --source <md> [--apply]  # D11 mechanical re-ingestion: report-only by default (chunk 4.4)
python render.py drawio generate <graph.yaml> [--layout l.yaml]   # C8: concept graph -> editable .drawio (stable IDs)
python render.py drawio reingest <edited.drawio|.png> --source <g> # C8: classify hand-edits: semantic/style/layout routing
python render.py import-template <corp.docx> [--check probe.md]  # C7a: derive a template profile
                                                                 # from a branded DOCX + idempotency gate
python render.py project <src.md> --profiles <cfg.yaml> --all    # F1 projection: one source ->
                                                                 # one governed render per profile
python render.py qa leaks <full.txt> [--probes p.yaml] [--fail-on-hits]  # deterministic post-render
python render.py qa tables|paras|figs|all ...                    # QA gate (report-only by default)
python render.py gate <files...> [--stages vale,lychee,verapdf,uids] # fail-closed gate chain: findings or a missing tool FAIL (B3)
python render.py serve [--port N] [--enable-ui] [--root DIR]     # localhost HTTP API + thin reference
                                                                 # UI at /ui, docs at /docs (chunk 5.1)
python render.py container <podman-args...>                     # raw passthrough to container/render
python render.py doctor [--json]                                # host tools vs tools.lock: warn on drift, never fail (D10)
```

This is a thin dispatcher, not a rewrite -- each mode calls the existing, unmodified pipeline
underneath. See `docs/EXECUTION-PLAN.md` chunk 0.1/0.2 for what's still fragmented (per-mode
pipelines still each do their own arg parsing / path resolution; a real shared library is future
work, not yet done) and `tests/test_render_entrypoint.py` for dispatcher coverage.

## Build + run (container mode)

```sh
cd container && ./build.sh                 # sudo podman build -t localhost/renderfact:latest .
sudo podman run --rm localhost/renderfact:latest bash verify-pins.sh
```

See `docs/ROADMAP.md` for the canonical forward-looking plan (what to build, in what order, what to
adopt/imitate/build from prior art) and `docs/DECISIONS.md` for the historical record of why each
architecture decision was made.
