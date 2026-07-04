#!/usr/bin/env bash
# demo/render-demo.sh: run the full Meridian Rail Infrastructure demo.
#
# One fictional full-candor source (demo/source/signalling-it-refresh.md) is
# projected into three governed renders (internal-full, bidder-pack,
# public-tender), demo brand tokens are generated, and, when pandoc is
# available, the public-tender projection is rendered to DOCX through the
# document pipeline. Works from the repo root or from demo/ (paths resolve
# from this script's own location). Outputs land in demo/renders/ (gitignored).
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEMO_DIR/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="$(command -v python3 || command -v python || true)"
[ -z "$PYTHON" ] && { echo "ERROR: python not found on PATH" >&2; exit 3; }

echo "== 1/4 projection: one source -> three governed renders =="
"$PYTHON" render.py project demo/source/signalling-it-refresh.md \
  --profiles demo/profiles.yaml --all --output-dir demo/renders

echo ""
echo "== 2/4 brand tokens: Meridian demo skin -> per-engine themes =="
"$PYTHON" render.py tokens --brand demo/skin/brand.yaml \
  --output-dir demo/renders/tokens

echo ""
echo "== 3/4 DOCX render of the public-tender projection (needs pandoc) =="
if command -v pandoc >/dev/null 2>&1; then
  OUTPUT_DIR="demo/renders" PROJECTION_CONFIG="demo/profiles.yaml" \
    "$PYTHON" render.py docx demo/source/signalling-it-refresh.md \
    --project public-tender --name signalling-it-refresh-public
else
  echo "pandoc not found on PATH: skipping the DOCX step."
  echo "The projections and tokens above are complete; install pandoc to try the DOCX render."
fi

echo ""
echo "== 4/4 branded PDF: AGM minutes + financial statement (needs typst + pandoc) =="
if command -v typst >/dev/null 2>&1 && command -v pandoc >/dev/null 2>&1; then
  "$PYTHON" render.py pdf demo/source/agm-minutes.md \
    --brand demo/skin/brand.yaml --variant financial --locale en \
    --org "Meridian Rail Infrastructure" --title "AGM Minutes 2026" --date 2026-03-18 \
    -o demo/renders/agm-minutes.pdf
  echo "  -> demo/renders/agm-minutes.pdf (attendance callout, data-bound reconciled"
  echo "     ledger, signature block; Meridian skin, financial variant, en locale)"
else
  echo "typst and/or pandoc not found on PATH: skipping the PDF step."
  echo "Install both (https://github.com/typst/typst, pandoc >=3) to try the layout-native PDF."
fi

echo ""
echo "Done. Compare the three projections in demo/renders/:"
echo "  signalling-it-refresh--internal-full.md   (full candor, stamped)"
echo "  signalling-it-refresh--bidder-pack.md     (commercial-confidential ceiling, stamped)"
echo "  signalling-it-refresh--public-tender.md   (public, minimal, no stamp)"
echo "and the branded PDF: demo/renders/agm-minutes.pdf"
