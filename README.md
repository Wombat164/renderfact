<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/renderfact-lockup-dark.svg">
    <img src="assets/brand/renderfact-lockup.svg" alt="renderfact" width="440">
  </picture>
</p>

<p align="center">
  <b>One full-candor source. Many governed renders.</b><br>
  Audience-gated projections, styled DOCX, diagrams, provenance, and fail-closed QA gates,<br>
  from one docs-as-code toolchain.
</p>

<p align="center">
  <a href="https://github.com/Wombat164/renderfact/actions/workflows/ci.yml"><img src="https://github.com/Wombat164/renderfact/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/renderfact/"><img src="https://img.shields.io/pypi/v/renderfact" alt="PyPI"></a>
  <a href="https://pypi.org/project/renderfact/"><img src="https://img.shields.io/pypi/pyversions/renderfact" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Wombat164/renderfact" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#whats-in-the-box">Capabilities</a> ·
  <a href="demo/">Demo</a> ·
  <a href="templates/">Templates</a> ·
  <a href="docs/">Docs</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

---

Write a document once, with everything in it. renderfact projects it per audience (clearance and
disclosure gating at the preprocessor level, so excluded content never reaches any output), renders
it through pinned engines (styled DOCX, mermaid/d2 diagrams, editable draw.io), stamps every
artifact with provenance, and round-trips reviewer edits back toward the source. The name is a
double meaning: render + artefact (what it produces), render factory (what it is).

> Status: early (v0.1.0), MIT. Real pipelines consolidated into one OSS toolchain; the
> capability matrix below says exactly what runs today vs. what is roadmap.

## Quickstart

```sh
git clone https://github.com/Wombat164/renderfact && cd renderfact
pip install -e ".[dev]"        # editable install is the supported mode; wires the render CLI
pytest -q                      # the full suite, green from a clean clone

# taste it on the bundled demo (a fictional rail operator's procurement dossier):
python render.py project demo/source/signalling-it-refresh.md \
    --profiles demo/profiles.yaml --all --output-dir demo/renders
python render.py gate demo/source --stages vale,uids   # fail-closed QA on the demo source
python render.py doctor                                 # what your host has vs. tools.lock
```

The three projected renders differ exactly as the profiles dictate: `internal-full` keeps
everything, `bidder-pack` keeps commercially shareable content, `public-tender` carries no
internal material, no provenance, and no projection stamp. `pip install renderfact` from PyPI
installs the library layer; the CLI's per-mode pipelines expect the repo checkout.

## How it works

Mark blocks in ordinary markdown with the audience they belong to:

```markdown
The programme starts in Q3.                       <- everyone sees this

::: {.block clearance="internal"}
Budget ceiling before negotiation: 4.2M.          <- internal renders only
:::

::: {.block releasable="bidders" detail="true"}
Interface spec, full protocol tables.             <- bidders, full-disclosure profiles only
:::
```

Profiles (your own YAML: ladders and audiences are consumer-defined, the engine ships no
vocabulary) decide what survives per render. The same source then feeds every output family, and
every artifact carries hidden provenance (source identity, content version, git commit) so edited
copies can be re-ingested, diffed, and routed back: unless the profile says it is externally
bound, in which case provenance is stripped.

## What's in the box

| | Capability | |
|---|---|---|
| **Author + project** | Audience/clearance/disclosure projection | `render project` |
| | Styled DOCX with generic house style + field numbering | `render docx` |
| | Diagrams (mermaid, d2) with pre-render lint + visual-QA metrics | `render diagram` |
| | Brand tokens to per-engine themes | `render tokens` |
| | Template import: derive a skin from any branded DOCX | `render import-template` |
| | Genre template pack (executive summary, briefs, pitches, purchase request) with rendered exemplars | [`templates/`](templates/) |
| **Round-trip** | Hidden provenance across DOCX/XLSX/PPTX | `render provenance` |
| | Mechanical DOCX re-ingestion: verdicts, reviewer-edit report, fast-forward apply, embedded-doc triage | `render reingest` |
| | Editable-diagram round-trip (draw.io lead adapter; stable IDs; semantic/style/layout routing) | `render drawio` |
| | Editable-diagram round-trip, Visio adapter (NameU anchors; OPC provenance; optional `vsdx` lib) | `render vsdx` |
| | Diagram-edit decision capture (deterministic first; LLM only past a confidence gate) | `render decision-capture` |
| | Vision-review with a D16 gate (deterministic svg-metrics verdict first; LLM only past a threshold) | `render copy-paste vision-review` |
| | D16 gate telemetry: escalation-rate stats + storm detection from an opt-in decision log | `render gate-stats` |
| **Gate + verify** | Fail-closed QA chain: Vale, lychee (offline), veraPDF (PDF/A + PDF/UA), duplicate-uid detection | `render gate` |
| | Post-render QA: leak probes, table geometry, paragraph weight | `render qa` |
| | Host-vs-lock drift report (never fails: that is the container's job) | `render doctor` |
| **Operate** | Dual-mode LLM steps: your harness or plain copy-paste, one schema | `render init-ai` / `copy-paste` |
| | Localhost HTTP API + thin reference UI | `render serve` |
| **Roadmap** | Slide decks, A2 posters, archival PDF output (v0.2.x); structured source editor (designed) | |

## Why this exists

Strong prior art covers parts of this pattern; none covers the whole. The gap: source-vs-render
**disclosure gating** + **archival, accessible PDF targets** + **many output families from one
source** + **provenance and round-trip**, as a lightweight framework.

<details>
<summary>Prior-art comparison (what we borrow, what was missing)</summary>

| System | Licence | Does well | Doesn't |
|---|---|---|---|
| **S1000D** + `s1kd-tools` | GPL-3.0 | defence/aero technical pubs, data-module single source (CSDB) | heavyweight; no clearance/disclosure projection; no decks/posters |
| **DITA-OT** | Apache-2.0 | one source to many formats via transformation types | no audience/clearance gating; no PDF/UA+PDF/A guarantee; no decks/posters |
| **NIST OSCAL** + compliance-trestle | Apache-2.0 | compliance-docs-as-code; profile-as-projection | data interchange, not human-facing styled render |
| **GOV.UK** tech-docs / govspeak | OSS | gov docs-as-code, live HTML | HTML-centric; no projection gating; no archival PDF |

We borrow DITA-OT's transformation-type abstraction, OSCAL's profile-as-projection, and S1000D's
data-module discipline.
</details>

## Architecture: generic core, private skin

The core is **domain-neutral**: any organisation supplies its own private *skin* (brand token
values, reference templates, audience profiles, markings) and its content. The public core never
contains domain content, and the bundled [demo](demo/) proves the split end to end.

```
your private config (skin)            renderfact (this repo, generic)
  brand.yaml values  ----------------> tokens/  (mechanism + neutral defaults)
  reference.docx     ----------------> container/ (engines, pinned)
  audience profiles  ----------------> render <mode> (one entry point)
  source corpus      ----------------> gates + QA -> governed artifacts
```

<details>
<summary>Repository layout</summary>

```
render.py    the single entry point: render <mode> [args...]
projection/  the projection engine: profiled fenced-div blocks -> one governed render per
             profile; consumer-defined ladders, preprocessor-level exclusion, fail-closed
docstyle/    generic DOCX house-style post-processor + field-based heading numbering
             (template-profile yaml, neutral defaults)
api/         stdlib HTTP API: step contracts + projection over localhost, opt-in /ui,
             openapi.json + /docs; loopback-Host/origin/path-jail guards
gates/       fail-closed QA chain (vale / lychee / verapdf / uids stages)
container/   OCI image + render wrapper + render-doc.sh + bundle-annex-linux.py + verify-pins.sh
lint/        diagram render harness + pre-render linters + visual-QA metrics + render_qa +
             the first LLM step contract (vision review)
tokens/      brand.yaml token mechanism + per-engine generators
contracts/   dual-mode LLM step mechanism: one schema for harness, copy-paste, and HTTP
roundtrip/   provenance (embed/extract/adopt/retarget/strip), source identity, DOCX
             re-ingestion, drawio round-trip
demo/        the fictional showcase: profiled source, profiles, skin, golden rules,
             committed rendered exemplars
docs/        architecture, decisions, roadmap, prior-art research (see docs/README.md)
tests/       fixture-based tests; fixtures built in-test, no committed binaries
tools.lock   pinned engine versions (the single source of truth the container asserts)
```
</details>

<details>
<summary>Full CLI reference</summary>

```sh
python render.py docx <source.md> [--pdf] [--qc] [--lint] ...    # markdown -> styled DOCX pipeline
python render.py project <src.md> --profiles <cfg.yaml> --all    # one source -> one render per profile
python render.py diagram <files...> [--formats svg,pdf]          # mermaid/d2 render harness
python render.py tokens [--brand path/to/brand.yaml]             # brand.yaml -> per-engine themes
python render.py import-template <corp.docx> [--check probe.md]  # derive a template profile from a DOCX
python render.py provenance embed|extract|adopt|retarget|strip . # hidden provenance operations
python render.py reingest <edited.docx> --source <md> [--apply]  # re-ingestion: report-only by default
python render.py drawio generate <graph.yaml> [--layout l.yaml]  # concept graph -> editable .drawio
python render.py drawio reingest <edited.drawio|.png> --source <g>  # classify + route hand-edits
python render.py vsdx generate <graph.yaml> [-o d.vsdx]          # concept graph -> editable Visio .vsdx
python render.py vsdx reingest <edited.vsdx> --source <g>        # classify + route Visio hand-edits
python render.py decision-capture --source <g> --reingest <j.json> # capture edit intent (deterministic+gate)
python render.py gate <files...> [--stages vale,lychee,verapdf,uids] # fail-closed QA chain
python render.py qa leaks|tables|paras|figs|all ...              # post-render QA (report-only default)
python render.py init-ai [--assistant claude|copilot|all]        # install harness-mode instructions
python render.py copy-paste <step> [--tier T] ...                # LLM step without harness or API key
python render.py serve [--port N] [--enable-ui] [--root DIR]     # localhost API + reference UI
python render.py doctor [--json]                                 # host tools vs tools.lock: warn only
python render.py container <podman-args...>                      # passthrough to the container wrapper
```

Each mode is a thin dispatcher to its own pipeline; `tests/test_render_entrypoint.py` covers the
dispatch layer.
</details>

## Container mode

Pinned engines (pandoc, typst, mermaid-cli, d2, marp, vale, lychee, veraPDF, LibreOffice) ship in
one OCI image; `verify-pins.sh` asserts the build matches `tools.lock`, fail-closed. Native mode
runs the same pipelines against host tools, with `render doctor` reporting drift instead.

```sh
cd container && ./build.sh
sudo podman run --rm localhost/renderfact:latest bash verify-pins.sh
```

## Documentation

Start at **[docs/README.md](docs/README.md)**: architecture, the decision record, the
forward-looking roadmap with adopt/imitate/build tags, and the prior-art research passes.

## Contributing

Contributions welcome: see [CONTRIBUTING.md](CONTRIBUTING.md) (test discipline, generic-core
rule), [SECURITY.md](SECURITY.md) for private vulnerability reporting, and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Licence: [MIT](LICENSE); bundled engine licences in
[THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).
