# Changelog

Format: Keep a Changelog. Versioning: semver; v0.1.0 is tagged on the fresh
public history at the flip (pre-publish commits live in the private archive;
their hashes do not survive the history rewrite, see the publish protocol).
`tool_version` in embedded provenance follows `git describe --tags` and picks
up real tags from v0.1.0 onward, with bare-commit fallback for dev builds.

## [0.1.0] - 2026-07-04

### Capability set

- **Projection engine** (`render project`): one full-candor markdown source with profiled
  fenced-div blocks projects into one governed render per audience/clearance/disclosure
  profile; consumer-defined ladders; preprocessor-level exclusion; fail-closed on unknown
  labels; per-profile header-stamp suppression.
- **DOCX pipeline** (`render docx`): annotated markdown to styled DOCX (+ optional PDF) with a
  consumer-free shell: every consumer piece is env-configured, optional steps skip honestly;
  generic house style + field-based heading numbering ship as defaults (docstyle/).
- **Diagram pipeline** (`render diagram`): mermaid/d2 rendering with pre-render linting and
  visual-QA metrics (lint/).
- **Brand tokens** (`render tokens`): brand.yaml to per-engine themes (mermaid JSON, marp CSS,
  pandoc template profile, typst tokens).
- **D8 dual-mode LLM steps**: `render init-ai` (installs step instructions into the user's own
  assistant) and `render copy-paste` (no-harness fallback), one identical schema per step.
- **Provenance** (`render provenance embed|extract|adopt|retarget`): hidden source
  identity/version stamping across DOCX/XLSX/PPTX. The projection-aware POLICY is decided (full
  internal, stripped external) but the strip mechanism is NOT implemented yet: treat every
  externally-bound artifact as manually-scrub-required until it ships (top of the v0.2 queue).
- **Template import** (`render import-template`): derive a template profile (theme colors, fonts,
  page geometry) from a branded corporate DOCX, with template provenance in the derived config
  and a `--check` idempotency gate that probe-renders and diffs the derived properties.
- **Post-render QA gate** (`render qa`): leak scan on rendered text, table geometry pressure,
  overweight paragraphs, figure contrast pre-filter; probes config-driven; CI-gateable.
- **HTTP API + thin reference UI** (`render serve`): stdlib server exposing the step contracts
  and projection; loopback-only posture with anti-rebinding, origin checks, path jail, rate
  limiting; opt-in /ui; /openapi.json + /docs.
- **Demo**: a fictional railway-operator tender dossier exercising every projection gate, with
  profiles, brand skin, and a runner.
- **Container + native modes**: pinned-engine OCI image (tools.lock + verify-pins) and
  native-host execution.

### Roadmap formats not yet wired (annotated, not claimed)

Poster mode, deck mode, and the PDF/UA typst path are advertised directions with working
consumer-side precedents, not shipped modes; they land in v0.2.x.
