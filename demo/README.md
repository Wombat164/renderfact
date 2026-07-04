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

## Adapt it into your own skin

Copy the pattern, not the fiction: write your own ladders + profiles (start from
`projection/profiles-example.yaml`), mark up your source with the same fenced-div blocks,
and supply your own brand override of `tokens/brand.yaml` (see `demo/skin/brand.yaml`).
The engine has no built-in vocabulary: ladders, audiences, and brand are all yours.
