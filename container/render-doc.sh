#!/usr/bin/env bash
# render-doc.sh: annotated-markdown -> styled DOCX (+ optional PDF).
#
# THIN CALLER. The implementation lives in container/render_doc.py; this script only finds a
# python and hands it the arguments unchanged. It is kept so that existing shell consumers,
# container entry points and documentation that invoke `render-doc.sh` keep working exactly as
# before.
#
# Why the implementation moved (issue #157): `render docx` used to locate a bash to run this
# script with. On a managed Windows machine that allows software by Authenticode signature rather
# than by path, there is no bash to find, so the entire DOCX half of the tool was unreachable on a
# platform this project supports and runs CI against. The pipeline was never really shell work:
# every functional step was already `python <script>` or `pandoc`.
#
# There is deliberately ONE implementation with two entry points, rather than a shell version and
# a Python version kept in step by hand. Two copies of a 433-line pipeline is how a consumer ends
# up with two answers to the same question.
#
# The full env-var contract (SKIN_DIR, TEMPLATE_DOCX, FILTERS_DIR, TEMPLATE_PROFILE,
# STYLE_POSTPROCESS, QC_SCRIPT, QC_BLOCKING, NLQA_DIR, HEADING_NUMBERING, PAGECHECK_SCRIPT,
# POSTRENDER_GATE_SCRIPT, POSTRENDER_GATE_ADVISORY, PDF_CONVERTER_PS1, PROJECTION_CONFIG,
# RESOURCE_PATH, OUTPUT_DIR, PANDOC_EXTRA_EXTENSIONS, PROVENANCE, PANDOC, PYTHON) is documented in
# container/render_doc.py's module docstring and is unchanged.
#
# Usage: render-doc.sh <source.md> [--name <p>] [--profile reference|compact]
#          [--project <profile>] [--template-profile <yaml>] [DRAFT|REVIEW|FINAL]
#          [--pdf] [--qc] [--qc-blocking] [--lint] [--number-headings] [--no-toc]
#          [--scheme <scheme>] [--page-check] [--postrender-gate]
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-}"
[ -z "$PYTHON" ] && PYTHON="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
[ -z "$PYTHON" ] && { echo "ERROR: python not found" >&2; exit 3; }

exec "$PYTHON" "$SELF_DIR/render_doc.py" "$@"
