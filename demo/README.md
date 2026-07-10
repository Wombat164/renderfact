# Demo: one source, three governed renders

A worked, fully fictional showcase of the projection engine (`projection/projector.py`).
**Meridian Rail Infrastructure**, an invented railway operator, runs a signalling-adjacent
IT procurement. One full-candor markdown dossier is the single source of truth; the engine
projects it into one governed render per audience profile:

| Profile         | Audience       | Ceiling                 | Travels to | Disclosure | Stamp |
|-----------------|----------------|-------------------------|------------|------------|-------|
| `internal-full` | programme-team | internal                | team       | full       | yes   |
| `bidder-pack`   | bidder         | commercial-confidential | bidders    | contextual | yes   |
| `public-tender` | general        | public                  | public     | minimal    | no    |

The source (`source/signalling-it-refresh.md`) exercises every gate the engine supports:
clearance (an internal-only note and a commercial-confidential budget envelope),
distribution (site-visit details releasable to bidders but not to the public), disclosure
postures (a `detail` baseline for the full posture, replaced by an `abstract` variant
elsewhere, plus a `softspot` schedule risk that minimal disclosure drops), an audience
allow-list (evaluation-panel note), an audience deny-list (`hide` from the general
public), and language select (one French block, dropped by all three English profiles).
The unmarked prose is written so each projection still reads as a coherent document.

## Run it

From the repo root (or from `demo/`; the script resolves its own location):

```sh
bash demo/render-demo.sh
```

Manual equivalents of the three steps:

```sh
# 1. project all three profiles into demo/renders/
python render.py project demo/source/signalling-it-refresh.md \
  --profiles demo/profiles.yaml --all --output-dir demo/renders

# 2. generate the Meridian demo brand tokens (per-engine themes)
python render.py tokens --brand demo/skin/brand.yaml --output-dir demo/renders/tokens

# 3. render the public-tender projection to DOCX (requires pandoc)
OUTPUT_DIR=demo/renders PROJECTION_CONFIG=demo/profiles.yaml \
  python render.py docx demo/source/signalling-it-refresh.md \
  --project public-tender --name signalling-it-refresh-public
```

Then diff the three files in `demo/renders/`: the internal render keeps the candid
context and the full technical baseline; the bidder pack keeps the budget envelope, the
site visits, and the honest schedule risk; the public tender keeps only what may travel,
carries the abstract baseline instead of the detailed one, and has no projection stamp.

## Branded PDF: a governance + financial deliverable

Step 4 renders a second showcase, `source/agm-minutes.md` - Meridian's Annual General
Meeting minutes - to a layout-native branded A4 PDF (`render pdf`, needs typst + pandoc).
One source exercises the full Track H feature set:

- the **`::: attendance`** callout (present / represented-by-proxy / quorum),
- a **data-bound `::: statement`** whose rows come from `source/afrekening.yaml` and whose
  subtotals + operating result are **computed and reconciled** (change a line item and a
  stated total that no longer matches fails the render),
- the **`::: signatures`** card grid (with locale-aware labels),
- rendered with the **Meridian skin** (`--brand`), the **`financial` theme variant**, and
  the **`en` locale** (number formatting + hyphenation + block labels).

```sh
python render.py pdf demo/source/agm-minutes.md \
  --brand demo/skin/brand.yaml --variant financial --locale en \
  --org "Meridian Rail Infrastructure" --title "AGM Minutes 2026" --date 2026-03-18 \
  -o demo/renders/agm-minutes.pdf
```

Swap `--locale en` for `nl-BE` to see the same document formatted in Belgian Dutch
(`EUR 1.234,56`, `18 maart 2026`, "Handtekening / Datum"); drop `--variant financial` for
the base theme. Add `--project <profile> --profiles demo/profiles.yaml` to render an
audience-projected branded PDF, or `--project all` for one per profile.

## Diagram archetype: a layered technology stack

`diagrams/layered-stack-example.yaml` is a separate, self-contained worked example - not part of
the Meridian Rail narrative - for the `layered-stack` diagram archetype (issue #68). Two
interchangeable, entirely fictional vendor platform stacks ("Vendor A" / "Vendor B") each realize
the SAME shared service interface, so client applications above and the shared transport network
below never need to know which vendor is plugged in underneath:

```sh
python render.py diagram demo/diagrams/layered-stack-example.yaml
```

Produces `layered-stack-example.svg` / `.pdf` plus the intermediate generated `.d2` source, all
under `renders/` (or `--output-dir`). Edit the YAML to see the layout, the interface-boundary
markers, and the brand-token-driven colours change; see `render diagram --help` and
`lint/layered_stack.py`'s module docstring for the full source shape.

## Adapt it into your own skin

Copy the pattern, not the fiction: write your own ladders + profiles (start from
`projection/profiles-example.yaml`), mark up your source with the same fenced-div blocks,
and supply your own brand override of `tokens/brand.yaml` (see `demo/skin/brand.yaml`).
The engine has no built-in vocabulary: ladders, audiences, and brand are all yours.

## Writing rules as skin config (golden rules)

`skin/writing-golden-rules.md` is the demo organisation's writing doctrine (core-message-first
condensation + a fluff taxonomy + four engagement moves), and `skin/vale/` encodes its
deterministic slice as a consumer Vale style: throat-clearing patterns BLOCK, hedges WARN.
Doctrine is skin, not core: the generic gate ships only built-in checks, and an organisation
plugs its own rules in exactly like this:

    RENDERFACT_VALE_CONFIG=demo/skin/vale/vale.ini python render.py gate demo/source --stages vale

The demo dossier passes its own rules (that is a test, so it stays true).
