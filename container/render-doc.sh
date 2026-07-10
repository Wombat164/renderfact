#!/usr/bin/env bash
# render-doc.sh: PORTABLE annotated-markdown -> styled DOCX (+ optional PDF) pipeline.
#
# One script, runs on Windows (git-bash/MSYS) AND Linux/macOS. OS is auto-detected.
# GENERIC CORE (D3): this script assumes no consumer directory layout. Every
# consumer-supplied piece (reference template, lua filters, house-style
# post-processor, QC/lint/numbering helpers) is plugged in via environment
# variables and each step is SKIPPED with an honest message when its piece is
# not configured. The pipeline itself (projection, pandoc conversion, optional
# PDF) runs with zero consumer configuration.
#
# Consumer skin configuration (all optional, all env):
#   SKIN_DIR            convenience root: unset vars below default into it
#   TEMPLATE_DOCX       pandoc --reference-doc (unset: pandoc built-in default)
#                         SKIN_DIR default: $SKIN_DIR/reference.docx
#   FILTERS_DIR         directory of pandoc lua filters, applied in name order
#                         SKIN_DIR default: $SKIN_DIR/filters
#   TEMPLATE_PROFILE    yaml consumed by the style post-processor
#                         SKIN_DIR default: $SKIN_DIR/template-profile.yaml
#   STYLE_POSTPROCESS   house-style DOCX post-processor script (cover page,
#                       styles); called as: <script> <docx> --profile <p>
#                       [--template-profile <yaml>] --cover-version --cover-date
#                       default: <repo>/docstyle/style_postprocess.py (generic
#                       in-repo implementation); consumers override with their own
#   QC_SCRIPT           pre-render QC script, called with <source.md> (--qc);
#                       ADVISORY by default (findings print, render continues);
#                       set QC_BLOCKING=1 (or pass --qc-blocking) so a non-zero
#                       exit stops the render instead
#   QC_BLOCKING         1 = QC_SCRIPT findings stop the render; default 0
#                       (advisory-only stays the default: the more common case)
#   NLQA_DIR            consumer lint bundle (vale config + generator) (--lint)
#   HEADING_NUMBERING   field-numbering script, called with <docx> (--number-headings)
#                       default: <repo>/docstyle/heading_numbering.py (generic
#                       in-repo implementation); consumers override with their own
#   PAGECHECK_SCRIPT    page-economy analyzer, called with <docx|pdf> (--page-check)
#   POSTRENDER_GATE_SCRIPT   post-render content-safety gate, called with the
#                       finished <docx> (--postrender-gate), after render and
#                       before the completion summary. BLOCKING by default (a
#                       non-zero exit stops the run): its purpose is "does the
#                       artifact contain content it must never contain", so
#                       silent-advisory is the wrong default here even though it
#                       is right for QC_SCRIPT above (see docs/DECISIONS.md D18
#                       for the reasoning). Set POSTRENDER_GATE_ADVISORY=1 to opt
#                       back into advisory-only. gates/content_scan.py is the
#                       generic (pattern-as-parameter) reference implementation.
#   POSTRENDER_GATE_ADVISORY  1 = POSTRENDER_GATE_SCRIPT findings are advisory
#                       only (print, do not stop the render); default 0 (blocking)
#   PDF_CONVERTER_PS1   Windows Word-COM converter script (--pdf); without it,
#                       LibreOffice (soffice) is used on any OS when present
#   PROJECTION_CONFIG   ladders+profiles yaml for --project
#                         default: <repo>/projection/profiles-example.yaml
#   RESOURCE_PATH       pandoc --resource-path root for relative images
#                         default: the source file's own directory
#   OUTPUT_DIR          default: ./renders
#   PROVENANCE          auto (default) embeds D11 provenance from the canonical
#                       source into every rendered artifact, EXCEPT under a
#                       projection profile with strip_provenance: true, where the
#                       artifact is scrubbed instead (D14 full/none rule). Set
#                       PROVENANCE=off to skip both. NB the first embed persists a
#                       renderfact_uid line into the source's frontmatter.
#   PANDOC / PYTHON     tool overrides, else resolved from PATH
#
# Note (2026-07-03 generalization): the VAULT_ROOT-era interface (self-location
# inside a specific tree layout) is REMOVED from this generic script. A consumer
# keeps a thin wrapper that exports the variables above; see docs/DECISIONS.md
# (D3, D4) and docs/2026-07-03-forward-plan.md (P1.2).
#
# Usage: render-doc.sh <source.md> [--name <p>] [--profile reference|compact]
#          [--project <profile>] [--template-profile <yaml>] [DRAFT|REVIEW|FINAL]
#          [--pdf] [--qc] [--qc-blocking] [--lint] [--number-headings]
#          [--scheme <scheme>] [--page-check] [--postrender-gate]
# Output: <OUTPUT_DIR>/<prefix>_<VERSION>_<DATE>_<SUFFIX>.docx (+ .pdf with --pdf)
set -euo pipefail

# ---- help (before any tool resolution, so it works without pandoc/python) ----
usage() {
  cat <<'EOF'
render-doc.sh: annotated-markdown -> styled DOCX (+ optional PDF).

Usage: render-doc.sh <source.md> [--name <p>] [--profile reference|compact]
         [--project <profile>] [--template-profile <yaml>] [DRAFT|REVIEW|FINAL]
         [--pdf] [--qc] [--qc-blocking] [--lint] [--number-headings]
         [--scheme <scheme>] [--page-check] [--postrender-gate]

Output: <OUTPUT_DIR>/<prefix>_<VERSION>_<DATE>_<SUFFIX>.docx (+ .pdf with --pdf)

Options:
  --name <p>            output basename prefix (default: source stem)
  --profile <p>         style profile: reference (default) | compact
  --project <profile>   apply a projection profile before rendering
  --template-profile    yaml consumed by the house-style post-processor
  --scheme <scheme>     numbering/style scheme (default: modern)
  DRAFT|REVIEW|FINAL    document lifecycle suffix (default: DRAFT)
  --pdf                 also convert to PDF (Word-COM on Windows, else soffice)
  --qc                  run the pre-render QC script (needs QC_SCRIPT); advisory
                         unless --qc-blocking or QC_BLOCKING=1
  --qc-blocking          same as --qc, but a QC_SCRIPT finding stops the render
  --lint                run the consumer lint bundle (needs NLQA_DIR)
  --number-headings     apply field-based heading numbering
  --page-check          run the page-economy analyzer
  --postrender-gate     run the post-render content-safety gate on the finished
                         docx (needs POSTRENDER_GATE_SCRIPT); blocking unless
                         POSTRENDER_GATE_ADVISORY=1
  -h, --help            show this help and exit

Consumer skin + tool configuration is via environment variables; see the
header of this script (SKIN_DIR, TEMPLATE_DOCX, FILTERS_DIR, PANDOC, ...).
EOF
}
for _arg in "$@"; do
  case "$_arg" in -h|--help) usage; exit 0 ;; esac
done

# ---- OS detection -----------------------------------------------------------
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
  Darwin)               OS=mac ;;
  Linux)                OS=linux ;;
  *)                    OS=linux ;;
esac

# ---- repo root (this script lives at <repo>/container/) ----------------------
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"

# ---- pandoc ----
PANDOC="${PANDOC:-}"
[ -z "$PANDOC" ] && PANDOC="$(command -v pandoc 2>/dev/null || true)"
if [ -z "$PANDOC" ] && [ "$OS" = windows ]; then
  for c in "${LOCALAPPDATA:-}/Pandoc/pandoc.exe" \
           "/c/Users/${USER:-${USERNAME:-}}/AppData/Local/Pandoc/pandoc.exe" \
           "/c/Program Files/Pandoc/pandoc.exe"; do
    [ -f "$c" ] && { PANDOC="$c"; break; }
  done
fi
[ -z "$PANDOC" ] && { echo "ERROR: pandoc not found (PATH or known install dirs)" >&2; exit 3; }

# ---- python ----
PYTHON="${PYTHON:-}"
[ -z "$PYTHON" ] && PYTHON="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
[ -z "$PYTHON" ] && { echo "ERROR: python not found" >&2; exit 3; }

# ---- consumer skin resolution (each var: explicit env, else SKIN_DIR, else off) ----
SKIN_DIR="${SKIN_DIR:-}"
skin_default() {  # $1 = relative path under SKIN_DIR; echoes it when it exists
  [ -n "$SKIN_DIR" ] && [ -e "$SKIN_DIR/$1" ] && echo "$SKIN_DIR/$1" || true
}
TEMPLATE_DOCX="${TEMPLATE_DOCX:-$(skin_default reference.docx)}"
FILTERS_DIR="${FILTERS_DIR:-$(skin_default filters)}"
TEMPLATE_PROFILE="${TEMPLATE_PROFILE:-$(skin_default template-profile.yaml)}"
STYLE_POSTPROCESS="${STYLE_POSTPROCESS:-$REPO_ROOT/docstyle/style_postprocess.py}"
QC_SCRIPT="${QC_SCRIPT:-}"
QC_BLOCKING="${QC_BLOCKING:-0}"
NLQA_DIR="${NLQA_DIR:-}"
HEADING_NUMBERING="${HEADING_NUMBERING:-$REPO_ROOT/docstyle/heading_numbering.py}"
PAGECHECK_SCRIPT="${PAGECHECK_SCRIPT:-}"
POSTRENDER_GATE_SCRIPT="${POSTRENDER_GATE_SCRIPT:-}"
POSTRENDER_GATE_ADVISORY="${POSTRENDER_GATE_ADVISORY:-0}"
PDF_CONVERTER_PS1="${PDF_CONVERTER_PS1:-}"
PROJECTION_CONFIG="${PROJECTION_CONFIG:-$REPO_ROOT/projection/profiles-example.yaml}"
PROJECTOR="$REPO_ROOT/projection/projector.py"
OUTPUT_DIR="${OUTPUT_DIR:-./renders}"

SOURCE=""; NAME=""; PROFILE="reference"; SUFFIX="DRAFT"
DO_PDF=0; DO_QC=0; DO_LINT=0; DO_NUMBER=0; DO_PAGECHECK=0; DO_POSTRENDER_GATE=0
SCHEME="modern"; PROJECT_PROFILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --name)             NAME="$2"; shift 2 ;;
    --profile)          PROFILE="$2"; shift 2 ;;
    --project)          PROJECT_PROFILE="$2"; shift 2 ;;
    --template-profile) TEMPLATE_PROFILE="$2"; shift 2 ;;
    --scheme)           SCHEME="$2"; shift 2 ;;
    --pdf)              DO_PDF=1; shift ;;
    --qc)               DO_QC=1; shift ;;
    --qc-blocking)      DO_QC=1; QC_BLOCKING=1; shift ;;
    --lint)             DO_LINT=1; shift ;;
    --number-headings)  DO_NUMBER=1; shift ;;
    --page-check)       DO_PAGECHECK=1; shift ;;
    --postrender-gate)  DO_POSTRENDER_GATE=1; shift ;;
    DRAFT|REVIEW|FINAL) SUFFIX="$1"; shift ;;
    *) if [ -z "$SOURCE" ]; then SOURCE="$1"; else SUFFIX="$1"; fi; shift ;;
  esac
done
[ -z "$SOURCE" ] && { echo "ERROR: <source.md> is required" >&2; exit 2; }
[ -f "$SOURCE" ] || { echo "ERROR: source not found: $SOURCE" >&2; exit 2; }
[ -z "$NAME" ] && NAME="$(basename "${SOURCE%.md}")"
RESOURCE_PATH="${RESOURCE_PATH:-$(cd "$(dirname "$SOURCE")" && pwd)}"
mkdir -p "$OUTPUT_DIR"

ORIG_SOURCE="$SOURCE"
PROJECTED=""
if [ -n "$PROJECT_PROFILE" ]; then
  echo "Projecting source via profile '$PROJECT_PROFILE' (projection engine, $PROJECTION_CONFIG)..."
  PROJECTED="${TMPDIR:-/tmp}/render-doc-projected-$$.md"
  "$PYTHON" "$PROJECTOR" "$SOURCE" --profiles "$PROJECTION_CONFIG" \
    --profile "$PROJECT_PROFILE" --stdout --keep-frontmatter > "$PROJECTED"
  SOURCE="$PROJECTED"
fi

DATE=$(date +%Y%m%d)
TMP_INPUT="${TMPDIR:-/tmp}/render-doc-$$.md"
VERSION=$(awk '/^version:/ {print $2; exit}' "$SOURCE" 2>/dev/null || true)
[ -z "$VERSION" ] && VERSION="v1"
OUTPUT_FILE="$OUTPUT_DIR/${NAME}_${VERSION}_${DATE}_${SUFFIX}.docx"

echo "=== render-doc ($OS): annotated markdown -> DOCX ==="
echo "Source:  $SOURCE"
echo "Output:  $OUTPUT_FILE"
echo "Version: $VERSION   Profile: $PROFILE"
[ -n "$SKIN_DIR" ] && echo "Skin:    $SKIN_DIR"
echo ""

if [ "$DO_QC" = "1" ]; then
  if [ -n "$QC_SCRIPT" ] && [ -f "$QC_SCRIPT" ]; then
    echo "Pre-render QC ($(basename "$QC_SCRIPT")) on source..."
    if [ "$QC_BLOCKING" = "1" ]; then
      "$PYTHON" "$QC_SCRIPT" "$SOURCE"
    else
      "$PYTHON" "$QC_SCRIPT" "$SOURCE" || echo "  (findings above are advisory, not blocking; set QC_BLOCKING=1 or --qc-blocking to fail the render on findings)"
    fi
  else
    echo "Skipping --qc: no QC_SCRIPT configured (consumer skin supplies one)."
  fi
  echo ""
fi

if [ "$DO_LINT" = "1" ]; then
  if [ -n "$NLQA_DIR" ] && [ -d "$NLQA_DIR" ]; then
    "$PYTHON" "$NLQA_DIR/nlqa.py" gen-vale >/dev/null 2>&1 || true
    DOC_LANG="$(awk -F'[: ]+' '/^lang:/ {print $2; exit}' "$SOURCE" 2>/dev/null | tr -d '\r' | tr '[:upper:]' '[:lower:]')"
    if [ "$DOC_LANG" = "nl" ]; then VALE_CFG=".vale.ini"; else VALE_CFG=".vale-common.ini"; fi
    echo "Consistency lint (Vale; lang=${DOC_LANG:-unknown} -> $VALE_CFG)..."
    VALE_BIN="$(command -v vale 2>/dev/null || true)"
    if [ -z "$VALE_BIN" ] && [ "$OS" = windows ]; then
      for c in "$HOME/AppData/Local/Microsoft/WinGet/Links/vale.exe" \
               "$HOME/AppData/Local/Microsoft/WinGet/Links/vale"; do
        [ -x "$c" ] && { VALE_BIN="$c"; break; }
      done
    fi
    if [ -n "$VALE_BIN" ]; then
      "$VALE_BIN" --config "$NLQA_DIR/vale/$VALE_CFG" "$SOURCE" || echo "  (Vale findings above are advisory, not blocking)"
    else
      echo "  Vale not installed (rules refreshed under $NLQA_DIR/vale/, advisory)."
      [ "$OS" = windows ] && echo "    install: winget install errata-ai.Vale"
    fi
  else
    echo "Skipping --lint: no NLQA_DIR configured (consumer skin supplies one)."
  fi
  echo ""
fi

# Audience-vs-SoT projection: drop render:skip blocks; light heading cleanup; pass FM.
awk '
  BEGIN { in_fm=0; fm_done=0; skip=0 }
  /<!-- render:skip -->/   { skip=1; next }
  /<!-- \/render:skip -->/ { skip=0; next }
  skip { next }
  /^#/ {
    gsub(/ \((NEW in [^)]*|normative, V[0-9.]*|AUTHORITATIVE, V[0-9.]*|authoritative tuples, V[0-9.]*|RT-[0-9]* RESOLVED[^)]*)\)/, "")
  }
  /^---$/ {
    print
    if (in_fm) { in_fm=0; fm_done=1 }
    else if (!fm_done) { in_fm=1 }
    next
  }
  { print }
' "$SOURCE" > "$TMP_INPUT"

PANDOC_ARGS=(
  --from=markdown+wikilinks_title_after_pipe+pipe_tables+yaml_metadata_block
  --resource-path="$RESOURCE_PATH"
  --toc --toc-depth=2
)
if [ -n "$TEMPLATE_DOCX" ] && [ -f "$TEMPLATE_DOCX" ]; then
  PANDOC_ARGS+=(--reference-doc="$TEMPLATE_DOCX")
  echo "Running pandoc (reference-doc: $(basename "$TEMPLATE_DOCX"))..."
else
  echo "Running pandoc (no TEMPLATE_DOCX configured: pandoc built-in reference style)..."
fi
if [ -n "$FILTERS_DIR" ] && [ -d "$FILTERS_DIR" ]; then
  for lf in "$FILTERS_DIR"/*.lua; do
    [ -f "$lf" ] || continue
    PANDOC_ARGS+=(--lua-filter="$lf")
    echo "  lua-filter: $(basename "$lf")"
  done
fi
"$PANDOC" "${PANDOC_ARGS[@]}" -o "$OUTPUT_FILE" "$TMP_INPUT"

echo ""
if [ -n "$STYLE_POSTPROCESS" ] && [ -f "$STYLE_POSTPROCESS" ]; then
  echo "Applying configured house style (profile: $PROFILE)..."
  COVER_DATE=$(date +"%d %B %Y")
  TP_ARG=()
  if [ -n "$TEMPLATE_PROFILE" ] && [ -f "$TEMPLATE_PROFILE" ]; then
    TP_ARG=(--template-profile "$TEMPLATE_PROFILE")
    echo "  template-profile: $(basename "$TEMPLATE_PROFILE")"
  fi
  "$PYTHON" "$STYLE_POSTPROCESS" "$OUTPUT_FILE" \
    --profile "$PROFILE" "${TP_ARG[@]}" --cover-version "$VERSION" --cover-date "$COVER_DATE"
else
  echo "Skipping house-style pass: no STYLE_POSTPROCESS configured (consumer skin supplies one)."
fi

rm -f "$TMP_INPUT"
[ -n "$PROJECTED" ] && rm -f "$PROJECTED"

if [ "$DO_NUMBER" = "1" ]; then
  echo ""
  if [ -n "$HEADING_NUMBERING" ] && [ -f "$HEADING_NUMBERING" ]; then
    echo "Injecting field-based heading numbering (scheme: $SCHEME)..."
    NUM_ARGS=(--scheme "$SCHEME")
    if [ -n "$TEMPLATE_PROFILE" ] && [ -f "$TEMPLATE_PROFILE" ]; then
      NUM_ARGS+=(--profile "$TEMPLATE_PROFILE")
    fi
    "$PYTHON" "$HEADING_NUMBERING" "$OUTPUT_FILE" "${NUM_ARGS[@]}"
  else
    echo "Skipping --number-headings: no HEADING_NUMBERING configured (consumer skin supplies one)."
  fi
fi

# ---- D11/D14 provenance: full by default, stripped for flagged projection profiles ----
if [ "${PROVENANCE:-auto}" != "off" ]; then
  echo ""
  PROV_TOOL="$REPO_ROOT/roundtrip/provenance.py"
  PROV_STRIP=0
  if [ -n "$PROJECT_PROFILE" ]; then
    PROV_STRIP=$("$PYTHON" -c "import sys,yaml; prof = yaml.safe_load(open(sys.argv[1], encoding='utf-8'))['profiles'][sys.argv[2]]; print(int(bool(prof.get('strip_provenance', False))))" "$PROJECTION_CONFIG" "$PROJECT_PROFILE")
  fi
  if [ "$PROV_STRIP" = "1" ]; then
    echo "Provenance (D14): profile '$PROJECT_PROFILE' is externally bound: stripping, not embedding..."
    "$PYTHON" "$PROV_TOOL" strip "$OUTPUT_FILE"
  else
    echo "Provenance (D11/D14): embedding source identity (from the canonical source, not the projection)..."
    "$PYTHON" "$PROV_TOOL" embed "$OUTPUT_FILE" --source "$ORIG_SOURCE"
  fi
fi

# ---- optional PDF: Word COM (when a converter is configured) or LibreOffice ----
PDF_MADE=0
if [ "$DO_PDF" = "1" ]; then
  PDF_FILE="${OUTPUT_FILE%.docx}.pdf"
  echo ""
  if [ "$OS" = windows ] && [ -n "$PDF_CONVERTER_PS1" ] && [ -f "$PDF_CONVERTER_PS1" ]; then
    echo "Converting to PDF via Word (TOC + fields refreshed)..."
    MSYS2_ARG_CONV_EXCL='*' MSYS_NO_PATHCONV=1 powershell.exe -NoProfile -ExecutionPolicy Bypass \
      -File "$PDF_CONVERTER_PS1" "$OUTPUT_FILE"
    PDF_MADE=1
  elif command -v soffice >/dev/null 2>&1; then
    echo "Converting to PDF via LibreOffice headless..."
    soffice --headless --convert-to pdf --outdir "$OUTPUT_DIR" "$OUTPUT_FILE" >/dev/null && PDF_MADE=1
  else
    echo "WARN: --pdf needs LibreOffice (soffice) on PATH, or PDF_CONVERTER_PS1 on Windows."
    echo "      For archival PDF use the typst path (render-pdf.py). Skipping PDF + prune."
  fi
  # prune prior-dated same-name+suffix artefacts (only when a PDF was actually made)
  if [ "$PDF_MADE" = "1" ]; then
    echo "Pruning prior-dated ${NAME}_${VERSION}_*_${SUFFIX} artefacts..."
    keep_docx="$(basename "$OUTPUT_FILE")"; keep_pdf="$(basename "$PDF_FILE")"
    shopt -s nullglob
    for f in "$OUTPUT_DIR/${NAME}_${VERSION}_"*"_${SUFFIX}".docx \
             "$OUTPUT_DIR/${NAME}_${VERSION}_"*"_${SUFFIX}".pdf; do
      b="$(basename "$f")"
      if [ "$b" != "$keep_docx" ] && [ "$b" != "$keep_pdf" ]; then echo "  removed $b"; rm -f "$f"; fi
    done
    shopt -u nullglob
  fi
fi

if [ "$DO_PAGECHECK" = "1" ]; then
  echo ""
  if [ -n "$PAGECHECK_SCRIPT" ] && [ -f "$PAGECHECK_SCRIPT" ]; then
    PAGECHK_TARGET="$OUTPUT_FILE"
    if [ "$PDF_MADE" = "1" ] && [ -f "${OUTPUT_FILE%.docx}.pdf" ]; then
      PAGECHK_TARGET="${OUTPUT_FILE%.docx}.pdf"
    fi
    echo "Page-economy check ($(basename "$PAGECHECK_SCRIPT"))..."
    "$PYTHON" "$PAGECHECK_SCRIPT" "$PAGECHK_TARGET" || true
  else
    echo "Skipping --page-check: no PAGECHECK_SCRIPT configured (consumer skin supplies one)."
  fi
fi

# ---- post-render content-safety gate: runs on the FINISHED docx, after every
# step that can still touch it (style, numbering, provenance), before the
# completion summary. Blocking by default (D18): see the POSTRENDER_GATE_SCRIPT
# header comment for why this hook's default differs from QC_SCRIPT's.
if [ "$DO_POSTRENDER_GATE" = "1" ]; then
  echo ""
  if [ -n "$POSTRENDER_GATE_SCRIPT" ] && [ -f "$POSTRENDER_GATE_SCRIPT" ]; then
    echo "Post-render content-safety gate ($(basename "$POSTRENDER_GATE_SCRIPT")) on $(basename "$OUTPUT_FILE")..."
    if [ "$POSTRENDER_GATE_ADVISORY" = "1" ]; then
      "$PYTHON" "$POSTRENDER_GATE_SCRIPT" "$OUTPUT_FILE" || echo "  (findings above are advisory, not blocking; POSTRENDER_GATE_ADVISORY=1 is set)"
    else
      "$PYTHON" "$POSTRENDER_GATE_SCRIPT" "$OUTPUT_FILE"
    fi
  else
    echo "Skipping --postrender-gate: no POSTRENDER_GATE_SCRIPT configured (consumer skin supplies one)."
  fi
fi

echo ""
echo "=== render-doc complete ==="
echo "Output: $OUTPUT_FILE"
[ "$PDF_MADE" = "1" ] && echo "PDF:    ${OUTPUT_FILE%.docx}.pdf"
exit 0
