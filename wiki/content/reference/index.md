---
title: Reference
---

# Reference

## The `render` command surface

| Command | What it does |
|---|---|
| `render docx <src> --profile <p>` | Project one source to a governed DOCX for one audience profile. |
| `render diagram ...` | Render a diagram from its source. |
| `render project ...` | Audience/clearance/disclosure projection of a source (the preprocessor). |
| `render tokens ...` | Compile brand tokens to per-engine themes. |
| `render import-template <docx>` | Derive a brand skin from any branded DOCX. |
| `render qa <files> ...` | Post-render QA probes (leaks, table geometry, paragraph weight). |
| `render serve [--enable-ui]` | Localhost HTTP API + thin reference UI. |
| `render gate <files> --stages ...` | Fail-closed QA gate chain (vale, lychee, verapdf, uids). |
| `render doctor [--json]` | Host tools vs `tools.lock`: report OK/DRIFT/MISSING; always exit 0. |
| `render provenance embed\|extract\|strip\|adopt\|retarget` | D11 provenance operations on DOCX/XLSX/PPTX/VSDX. |
| `render reingest <edited.docx> --source <md>` | Mechanical re-ingestion of an edited document. |
| `render drawio generate\|reingest` | Editable-diagram round-trip, draw.io adapter (C8.1). |
| `render vsdx generate\|reingest` | Editable-diagram round-trip, Visio adapter (C8.2; needs `vsdx`). |
| `render decision-capture --source <g> --reingest <j>` | Capture diagram-edit intent; deterministic first, LLM past the gate (C8.3). |
| `render contextualize --source <md> --reingest <j>` | Capture document-edit intent from a reingest diff; deterministic first, LLM past the gate (Track D 4.5). |
| `render copy-paste vision-review --image <svg>` | Gated visual-quality review of a diagram. |
| `render gate-stats` | D16 gate escalation-rate stats + storm detection. |
| `render init-ai [--assistant ...]` | Install renderfact-aware instruction files into your assistant. |
| `render copy-paste <step>` | Run one D8 step in copy-paste mode. |
| `render container <podman-args>` | Passthrough to the container render entry. |

Run any subcommand with `--help` for its flags.

## Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `RENDERFACT_VISION_THRESHOLD` | vision-review | D16 gate confidence threshold (default 0.6). |
| `RENDERFACT_DECISION_THRESHOLD` | decision-capture | D16 gate confidence threshold (default 0.6). |
| `RENDERFACT_CONTEXTUALIZE_THRESHOLD` | contextualize | D16 gate confidence threshold (default 0.6). |
| `RENDERFACT_GATE_LOG` | all gated steps | Path to the append-only gate decision log (opt-in). |
| `RENDERFACT_MODELS_CONFIG` | direct-API channel | Path to the `[models]` TOML (default `./renderfact-models.toml`). |
| `RENDERFACT_LLM_API_KEY` / `RENDERFACT_VLM_API_KEY` | direct-API channel | Bearer token for the text / vision endpoint. **Env-only, never read from the TOML.** |
| `RENDERFACT_LLM_BASE_URL` / `_MODEL` / `_VISION` | direct-API channel | Env overrides for the `[llm]` endpoint. |
| `RENDERFACT_VLM_BASE_URL` / `_MODEL` / `_VISION` | direct-API channel | Env overrides for the `[vlm]` endpoint. |
| `RENDERFACT_VALE_CONFIG` | gate (vale) | Override the built-in Vale config. |
| `RENDERFACT_LYCHEE_BIN` / `_VERAPDF_BIN` | gate | Native binary overrides. |
| `PROVENANCE=off` | render pipeline | Skip provenance embedding for a render. |

## D17 direct-API escalation channel (optional, off by default)

When the D16 gate escalates, the default channels are the assistant harness and human copy-paste (D8).
D17 adds an **optional third channel**: a directly-called OpenAI-compatible model. It is off unless a
`[models]` config is present, and it never fails a render -- an unreachable endpoint falls back to
copy-paste.

Declare endpoints in `renderfact-models.toml` (base URL + model only -- the api_key is **env-only**):

```toml
[llm]
base_url = "http://localhost:11434/v1"   # any OpenAI-compatible server (ollama, vLLM, ...)
model = "qwen2.5:14b"

[vlm]                                     # optional; falls back to [llm] when unset/unreachable
base_url = "http://localhost:11434/v1"
model = "qwen2.5vl:7b"
vision = true                             # required for a vision step (else it degrades to copy-paste)
```

Then set the key(s) in the environment and opt in per command:

```bash
export RENDERFACT_LLM_API_KEY=...         # omit for a keyless local endpoint
render copy-paste vision-review --image d.svg --tier tier-3   # uses the API when configured
render copy-paste vision-review --image d.svg --tier tier-3 --no-api   # force copy-paste
render contextualize --source doc.md --reingest r.json --escalate api  # try API, fall back to copy-paste
```

Routing: a step whose input carries a `rendered_image_path` (vision-review) routes to the `[vlm]`
(with the rendered image attached as a base64 data URL); every other step routes to the `[llm]`. The
result's mode field records `api`, alongside `harness` / `copy-paste` / `deterministic`.

## Provenance schema (D11)

Embedded in the OOXML `dc:identifier` core property (and, for VSDX, `docProps/core.xml`) as
`renderfact:v1:<json>`:

| Field | Meaning |
|---|---|
| `source_uid` | Stable identity of the canonical source. |
| `source_version` | Content hash of the source at render time. |
| `rendered_at` | UTC render timestamp. |
| `tool_version` | renderfact's own git describe. |
| `source_commit` | The source repo's commit at render (`<sha>` or `<sha>-dirty`). |

## D16 gate contract (per step)

Every gated step exposes: `confidence(input) -> Confidence` (a score plus named sub-signals),
`gate(input, threshold) -> (accept|escalate, Confidence)`, `deterministic_entry(input)` (the
accept-path result), plus `MODE_FIELD` (the provenance field naming which mode produced the output).
The shared `contracts/confidence_gate.py` provides `decide(score, threshold)` and `resolve(...)` (the
gate -> telemetry -> accept/escalate/needs-review orchestration); the per-step `confidence()` heuristic
stays local. Sub-signals are logged to the gate telemetry (`render gate-stats`) for per-signal
calibration. See [Explanation](../explanation/index.md#the-d16-fuzzy-gate).
