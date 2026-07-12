#!/usr/bin/env python3
"""marking_lint.py: default POSTRENDER_GATE_SCRIPT-shaped check for a template-
inherited classification/marking string that shipped in a rendered DOCX with no
corresponding classification.* replacement rule configured (#123).

A DOCX template's header/footer text passes into every future render of a skin
built from it verbatim (pandoc's --reference-doc mechanism reuses the reference
document's own header/footer parts structurally); `render import-template`
flags marking-like text it finds AT IMPORT TIME (see template_import.py's
`_detect_header_footer_markings`), but nothing previously checked AT RENDER TIME
whether that flag was ever actually acted on. This is that check.

NOT auto-run by render-doc.sh (matches the existing opt-in gate-hook posture,
D18): a consumer wires this in via `POSTRENDER_GATE_SCRIPT=docstyle/marking_lint.py`
(or copies/extends it for a real marking vocabulary beyond the generic English
defaults in marking_patterns.py). Exit 1 (finding) if the rendered document's
header/footer text matches a marking pattern with no classification.* rule (on
EITHER key: header_footer_replacements or brief_replacements, since this script
does not know which --profile produced the file) covering that exact matched
text. Exit 0 otherwise, including when TEMPLATE_PROFILE is unset (nothing to
check the finding against; note this is different from "TEMPLATE_PROFILE is set
but has no classification: block at all", which DOES count as unconfigured).

Usage: python marking_lint.py <rendered.docx>
Reads the template-profile.yaml path from the TEMPLATE_PROFILE env var
(render-doc.sh exports it before invoking POSTRENDER_GATE_SCRIPT) or the
optional --template-profile flag for standalone/manual invocation.
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

import yaml

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
from marking_patterns import find_marking_matches  # noqa: E402


def _extract_header_footer_text(docx_path: Path) -> str:
    """Plain-text concatenation of every header*.xml/footer*.xml part's <w:t>
    runs. Deliberately simple (no python-docx dependency, no run/paragraph
    structure needed -- this is a text-content check, not a formatting one)."""
    import re
    texts = []
    with zipfile.ZipFile(docx_path) as z:
        for name in z.namelist():
            base = name.rsplit("/", 1)[-1]
            if not (base.startswith("header") or base.startswith("footer")):
                continue
            if not base.endswith(".xml"):
                continue
            xml = z.read(name).decode("utf-8", errors="ignore")
            texts.extend(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
    return "\n".join(texts)


def _configured_finds(template_profile_path: str | None) -> set[str]:
    """Every literal `find` string configured under EITHER classification key,
    across the whole template-profile.yaml. Union, not per-key, since this
    script does not know which --profile rendered the file being checked."""
    if not template_profile_path:
        return set()
    p = Path(template_profile_path)
    if not p.exists():
        return set()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cls = data.get("classification") or {}
    finds: set[str] = set()
    for key in ("header_footer_replacements", "brief_replacements"):
        for rule in (cls.get(key) or []):
            for f in ((rule or {}).get("find") or []):
                if f:
                    finds.add(f)
    return finds


def check(docx_path: Path, template_profile_path: str | None) -> list[str]:
    """Return the list of marking matches found in the document with NO
    covering classification.* find-string (a covering find-string is one that
    is a substring of, or identical to, the match -- e.g. a configured
    find: ["UNCLASS"] covers a matched "UNCLASSIFIED" or vice versa)."""
    text = _extract_header_footer_text(docx_path)
    matches = find_marking_matches(text)
    if not matches:
        return []
    configured = _configured_finds(template_profile_path)
    uncovered = []
    for m in matches:
        covered = any(f in m or m in f for f in configured)
        if not covered:
            uncovered.append(m)
    return uncovered


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("docx", help="rendered .docx to check")
    ap.add_argument("--template-profile", default=None,
                     help="path to template-profile.yaml (default: $TEMPLATE_PROFILE env var)")
    args = ap.parse_args(argv)

    docx_path = Path(args.docx)
    if not docx_path.exists():
        print(f"ERROR: {docx_path} does not exist", file=sys.stderr)
        return 2

    template_profile = args.template_profile or os.environ.get("TEMPLATE_PROFILE")
    uncovered = check(docx_path, template_profile)

    if uncovered:
        print(f"FINDING: {docx_path.name}'s header/footer contains marking-like "
              f"text with no covering classification.* rule: {sorted(uncovered)}")
        if not template_profile:
            print("  (no template-profile.yaml was checked against -- set "
                  "TEMPLATE_PROFILE or pass --template-profile to rule out a "
                  "false positive from an unconfigured but intentional marking)")
        return 1

    print(f"OK: {docx_path.name}'s header/footer has no unconfigured marking-like text.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
