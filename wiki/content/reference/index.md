---
title: Reference
---

# Reference

## The `render` command surface

| Command | What it does |
|---|---|
| `render docx <src> --profile <p>` | Project one source to a governed DOCX for one audience profile. |
| `render pdf <src> [--engine typst]` | Render a source to a layout-native branded A4 PDF via typst (a peer of the DOCX path, no LibreOffice). |
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

## `render pdf` -- layout-native PDF backend (typst)

A first-class PDF backend, a **peer of the DOCX path** rather than a LibreOffice
afterthought. Markdown is translated to typst by pandoc's typst writer, wrapped in a
brand-token-driven theme, and compiled to PDF by typst -- so page chrome, callout boxes,
tables and rules are laid out by typst, deterministically, where the DOCX->LibreOffice
conversion drifts.

```bash
render pdf minutes.md --org "VME Voorbeeld" --title "Algemene Vergadering 2025" --date "15 februari 2025"
# -> renders/minutes.pdf
```

| Flag | Meaning |
|---|---|
| `--engine typst` | Layout engine (only `typst` today; the flag reserves the peer slot). |
| `-o, --output <path>` | Output PDF path (default: `renders/<stem>.pdf`; `OUTPUT_DIR` overrides the dir). |
| `--theme <file.typ>` | A typst layout file (default: the built-in `pdf/theme/default.typ`). |
| `--brand <brand.yaml>` | A consumer palette/fonts/theme file, consumed through the token generators. |
| `--variant <name>` | A theme variant from `brand.yaml [theme.variants]` (default: `base`). |
| `--locale <code>` | Project locale (`nl-BE` / `fr-BE` / `en` / ...): number separators, hyphenation, and long-date formatting. |
| `--project <profile>` `--profiles <config>` | Project the source through an audience/clearance profile (Track F) before rendering, so one governed source yields one branded PDF per profile. `--project all` renders every profile in the config at once (`<stem>-<profile>.pdf`). |
| `--font-path <dir>` | A directory of brand fonts for typst to use (repeatable); env `RENDERFACT_FONT_PATH` (os-pathsep-separated) is a default. Lets a brand ship its font instead of relying on host install. |
| `--title` / `--subtitle` / `--org` / `--date` | Document metadata for the title block, header, and footer. A `--date` given as ISO `YYYY-MM-DD` is rendered as a localized long date under `--locale`. |
| `--paper <a4\|...>` | Paper size (default `a4`). |

**Toolchain:** pandoc (>=3, has a typst writer) and typst -- both reported by `render doctor`.
Missing either fails with an actionable message, never a traceback. Overridable via `PANDOC` /
`TYPST` env vars. **Generic core (D3):** the default theme needs no configuration; a consumer
overrides the whole layout via `--theme` and its palette + house-style via `--brand`.

**Images:** relative image paths (`![logo](logo.png)`, subfolders included) are resolved against the
source's directory and staged into the build so typst renders them; remote URLs are left as-is. Over
the API, an image resolving outside the server root is not staged, so an untrusted document cannot pull
a server file into the PDF.

### Theme descriptor (engine-agnostic house-style)

The chrome + component layer -- page margins, header/footer slots, heading/title/rule colour **roles**,
and the semantic-block styling (`callout` fill/border roles, `statement` rule/heading roles) -- is
declared in `brand.yaml`'s `theme` section, not hard-coded in the layout. The typst backend generates a
`chrome.typ` from it (the same generated-values / static-logic split as `tokens.typ`), so the
house-style is declarative and role-based (fields name a role in `colour.brand`, resolved to RGB by the
engine -- never a raw hex). **Variants** inherit `theme.base` (deep-merged, so nested `callout` /
`statement` overrides work) and override only the keys they name; e.g. the built-in `financial` variant
restyles headings and the ledger section headings to the primary role. Role-based and engine-neutral by
design so an OOXML consumer can read the same descriptor (Golden Rule -- one source -- extended from
palette to house-style).

### Semantic blocks (governance + financial documents)

Three first-class blocks (fenced divs), rendered by the active theme, cover components that recur
across meeting minutes and financial statements. Each reads a plain bullet list of pipe-delimited
fields, so the source stays markdown; a pandoc Lua filter maps them to typst functions.

```markdown
::: attendance
- present | A. Janssens (voorzitter)
- proxy   | C. De Wit, via A. Janssens
- quorum  | 3 van de 5 leden aanwezig: quorum bereikt
:::

::: statement
- heading  | Ontvangsten
- item     | Bijdragen leden | EUR 8.045,77
- subtotal | Totaal ontvangsten | EUR 8.045,77
- rule
- total    | Saldo boekjaar | EUR 1.510,53
:::

::: signatures
- A. Janssens | Voorzitter
- B. Peeters  | Secretaris
:::
```

| Block | Fields per item | Renders |
|---|---|---|
| `signatures` | `Name \| Role` | A card grid: bold name, muted role, reserved signature whitespace, a `Handtekening / Datum` rule. Hyphenation-safe (a long role never breaks the name). |
| `attendance` | `kind \| text` (kind = `present` / `proxy` / `quorum`) | A callout box (accent left border): present-in-person and represented-by-proxy sections, plus an emphasized quorum line. |
| `statement` | `kind \| label \| amount` (kind = `heading` / `item` / `subtotal` / `total` / `balance` / `rule`) | A ledger: section headings, right-aligned amounts, bold totals, `rule` hairlines. Amounts may be hand-typed, or **computed from data** (below). |

#### Data-bound statements (compute + reconcile)

Instead of hand-typing amounts, a statement can source its rows from a data file and **compute** its
subtotals / totals / balances -- and if the data also *states* a total, the computed and stated values
must **reconcile** or the render fails. This removes the silent-transcription error class from
financial documents.

```markdown
::: {.statement data="finance.yaml"}
:::
```

```yaml
# finance.yaml
format: { currency: EUR, thousands: ".", decimal: "," }   # #35 will make this a project locale
rows:
  - { kind: heading,  label: Ontvangsten }
  - { kind: item,     label: Bijdragen leden, amount: 8000.00 }
  - { kind: item,     label: Interesten,      amount: 45.77 }
  - { kind: subtotal, id: ontvangsten, label: Totaal ontvangsten, amount: 8045.77 }  # amount = optional check
  - { kind: heading,  label: Uitgaven }
  - { kind: item,     label: Onderhoud, amount: 6535.24 }
  - { kind: subtotal, id: uitgaven, label: Totaal uitgaven }
  - { kind: rule }
  - { kind: total,    label: Saldo boekjaar, formula: "ontvangsten - uitgaven" }
```

- A `subtotal` computes the sum of its section's `item` rows; a `heading` starts a new section.
- A `total` / `balance` evaluates a `formula` over subtotal `id`s (`+ - * /`, safe -- never `eval`), or,
  with no formula, sums every item so far.
- Any computed row may also carry a stated `amount`; if it does not match the computed value to the
  cent, the render **fails** with a clear reconciliation error.
- Data is YAML (structured, with `format` + `formula`) or CSV (flat `kind,label,amount,id,formula`).
- With `--locale`, the separators + currency placement come from the locale, so the data file need only
  state the `currency` (or nothing) -- amounts and dates are supplied as raw values and formatted per
  locale. An explicit `format` key in the data still overrides the locale.

## Environment variables

| Variable | Used by | Meaning |
|---|---|---|
| `RENDERFACT_VISION_THRESHOLD` | vision-review | D16 gate confidence threshold (default 0.6). |
| `RENDERFACT_DECISION_THRESHOLD` | decision-capture | D16 gate confidence threshold (default 0.6). |
| `RENDERFACT_CONTEXTUALIZE_THRESHOLD` | contextualize | D16 gate confidence threshold (default 0.6). |
| `RENDERFACT_GATE_LOG` | all gated steps | Path to the append-only gate decision log (opt-in). |
| `RENDERFACT_MODELS_CONFIG` | direct-API channel | Path to the `[models]` TOML (default `./renderfact-models.toml`). |
| `RENDERFACT_FONT_PATH` | render pdf | Default brand-font directories (os-pathsep-separated) passed to typst as `--font-path`. |
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

## HTTP API (`render serve`)

The localhost API (D9: "same contract, HTTP instead of copy-paste") exposes the D8 step
contracts, the projection engine, and -- since #42 -- **rendering**. Loopback-bound, no auth,
with a Host/Origin guard, a filesystem path jail, and a rate limit. Machine-readable at
`/openapi.json`; human table at `/docs`.

| Route | Purpose |
|---|---|
| `GET /` | Service info + advertised endpoints. |
| `GET /steps`, `GET /steps/{name}` | List / introspect D8 step contracts. |
| `POST /steps/{name}/validate-output` | Validate a candidate step output against its contract. |
| `POST /project` | Project a source through one audience profile. |
| `POST /render/pdf` | Render markdown to a PDF (or a paged PNG preview) via the typst backend. |
| `POST /statement/check` | Compute + reconcile a statement spec (YAML string / object / jailed path) without rendering. |
| `GET /doctor` | Tool availability + whether the PDF backend (typst + pandoc) is ready. |
| `GET /locales` | Supported locales, each with a sample formatted number + date. |
| `GET /theme/variants` | Theme variants from `brand.yaml [theme.variants]` (+ base). |
| `GET /ui` | The reference studio (only with `--enable-ui`). |

`POST /render/pdf` takes exactly one of `markdown` (inline, <=512 KB) or `source` (a path under the
server root), plus `format` (`pdf` | `png`), and the same options as `render pdf` (`title` / `subtitle`
/ `org` / `date` / `variant` / `locale` / `paper` / `brand` / `project` + `profiles`). It returns
`application/pdf` or `image/png` bytes; a bad input, a failed render, or a statement reconciliation
failure returns a `4xx` with a JSON `error`. For `png`, a 1-indexed `page` (clamped) selects the page
and the response carries an `X-Total-Pages` header. Statement `data=` and image paths are jailed under
the server root (source mode) or the render temp dir (inline mode), so an untrusted document cannot
read outside the sandbox.

The **studio** (`/ui`, `--enable-ui`) is a thin client of this endpoint: edit markdown, get a live PNG
preview (debounced), tweak variant/locale, download the PDF -- exercising the whole Track H pipeline.
