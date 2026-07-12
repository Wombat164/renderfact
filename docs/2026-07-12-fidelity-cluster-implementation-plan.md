# DOCX fidelity cluster: low-level implementation plan

> **What this is.** The concrete, function-level breakdown of ROADMAP.md's Track B5 (items B5.1-B5.3a)
> and B6 -- the four highest-priority items from the 2026-07-12 issue-triage pass (#122, #123, #87,
> #120), scoped down to what's actually being implemented in this pass. B5.3b (#87's non-trivial
> append-if-absent half), B5.4 (#121 heading-size derivation), and Track L (image assets) are deferred
> to a later pass per the roadmap's own priority ordering -- not attempted here. A real consumer's
> procurement-justification document (the one that surfaced all four of these bugs during a real
> institutional-template onboarding session) is the validation testbed: every fix below gets
> re-verified by re-rendering that actual document, not synthetic fixtures alone.

## 1. #122 -- `build_reference_cover()` title-match, not positional deletion

**File:** `docstyle/style_postprocess.py`, function `build_reference_cover()` (currently ~line 311-337).

**Current (buggy) logic:**
```python
# 1. Remove the duplicate title H1 (first Heading 1 that is not a part divider).
for p in list(doc.paragraphs):
    nm = p.style.name if p.style and p.style.name else ''
    if nm == 'Heading 1' and not p.text.strip().startswith(part_prefix):
        p._element.getparent().remove(p._element)
        break
```

**Fix:**
```python
# 1. Remove the duplicate title H1 (first Heading 1 whose TEXT matches the real
#    Title paragraph, not just the first Heading 1 that isn't Part-prefixed --
#    positional-only deletion silently destroyed a genuine section heading on
#    any flat, non-multi-part document; see #122).
title_text = _find_title_text(doc)  # None if no [Title]-styled paragraph exists
if title_text:
    for p in list(doc.paragraphs):
        nm = p.style.name if p.style and p.style.name else ''
        if (nm == 'Heading 1' and not p.text.strip().startswith(part_prefix)
                and _normalize(p.text) == _normalize(title_text)):
            p._element.getparent().remove(p._element)
            break
    else:
        print(f"NOTE: build_reference_cover found no Heading 1 matching the "
              f"Title paragraph ('{title_text}') to remove as a duplicate; "
              f"the source may not have a duplicate H1 at all (fine), or the "
              f"two texts differ (check for a typo/edit-drift between them).")
```

Add two small helpers near the top of the cover-cleanup section:
```python
def _find_title_text(doc):
    for p in doc.paragraphs:
        if p.style and p.style.name == 'Title':
            return p.text.strip()
    return None

def _normalize(s):
    return ' '.join(s.split()).strip().lower()
```

**New `cover.no_parts` opt-out** (for documents with genuinely no Part structure, where nothing
should be treated as "the duplicate" and TOC-repositioning step 3 should also no-op cleanly, which it
already does when no Part heading is found -- verify this stays true after the fix, add a regression
test for it specifically):
```python
# in the COVER dict / apply_template_profile()'s cover: block parsing:
COVER = {
    'part_heading_prefix': 'Part',
    'version_label': 'Version {version} - {date}',
    'no_parts': False,   # NEW: skip duplicate-H1 removal entirely (no Part
                          # structure exists in this document at all)
}
```
```python
def build_reference_cover(doc, version=None, date_str=None):
    ...
    if not COVER.get('no_parts', False):
        # existing (now title-matched) step 1 logic
        ...
    # step 2 (version/date line) and step 3 (TOC repositioning) unchanged;
    # step 3 already no-ops correctly when no Part heading is found
```

**Tests to add** (`tests/test_docstyle.py`):
1. Flat document (no Part heading, body H1s = real section headings, one matches a `[Title]`
   paragraph's text exactly) -> the matching H1 is removed, ALL OTHER H1s survive.
2. Flat document with NO H1 duplicating the title at all (the real-consumer shape: title comes
   purely from YAML frontmatter via `--keep-frontmatter`, no body H1 repeats it) -> nothing is
   removed, a NOTE prints, all section H1s survive untouched. This is the exact regression this fix
   targets.
3. `cover.no_parts: true` -> step 1 skipped entirely regardless of what's in the document.
4. Existing book-shaped document (title H1 + `# Part 1: ...` real chapters) -> unchanged behavior,
   confirms no regression on the case the function was originally designed for.

**Real-document validation:** re-render the consumer's actual full-candor source with `--profile
reference` (previously avoided specifically because of this bug -- the render used `--profile
compact` as a workaround) and confirm all real section headings survive with a correct, unnumbered
Title.

## 2. #123 (core) -- default check for an unconfigured template-inherited marking

Two independent deliverables per the roadmap item; both are additive, neither touches existing
render-path behavior.

**2a. `render doctor`-style lint** (new, since `POSTRENDER_GATE_SCRIPT` is opt-in and per-consumer --
this ships a usable default rather than requiring every consumer to write their own from scratch).

New file `docstyle/marking_lint.py`:
```python
"""Default POSTRENDER_GATE_SCRIPT-shaped check: flag header/footer text that looks like a
classification/marking placeholder with no corresponding classification.* replacement rule
configured. A consumer wires this in via POSTRENDER_GATE_SCRIPT (or copies/extends it); it is
NOT auto-run by render-doc.sh (matches the existing opt-in gate-hook posture, D18)."""
MARKING_PATTERNS = [
    r'\bUNCLASS(IFIED)?\b', r'\bCONFIDENTIAL\b', r'\bSECRET\b', r'\bRESTRICTED\b',
    r'\bINTERNAL\b', r'\bPROPRIETARY\b', r'\bFOR OFFICIAL USE ONLY\b', r'\bFOUO\b',
]
# CLI: python marking_lint.py <rendered.docx> [--template-profile <yaml>]
# Exit 1 (finding) if header/footer text matches a pattern AND no classification.*
# rule (either key) has that exact matched substring as one of its `find` entries.
# Exit 0 otherwise. Advisory by default (matches POSTRENDER_GATE_ADVISORY posture);
# consumer sets POSTRENDER_GATE_ADVISORY=0 to make it blocking.
```

**2b. `render import-template` flags detected marking-like text.** In `template_import.py`, after the
existing header/footer text extraction (reuse whatever the importer already walks for the header/
footer, don't add a second XML walk), run the same `MARKING_PATTERNS` list against it and emit into
the generated `template-profile.yaml`:
```yaml
# classification: NOT derived -- this template's header/footer contains text that looks like a
# marking ("UNCLASS", detected 2026-07-12): review whether it needs a header_footer_replacements
# and/or brief_replacements rule before shipping any render under this skin.
# classification:
#   header_footer_replacements: []
#   brief_replacements: []
```
Same honesty-comment pattern the importer already uses for `body_muted`/`table_body`/`zebra`
(`template-profile.yaml` header: "Only keys this importer could genuinely derive... every other key
stays commented, at the built-in default, with the reason it could not be derived").

**Tests to add:** `tests/test_marking_lint.py` (new) -- matches/no-matches for each pattern, a
configured-rule case that correctly suppresses the finding, an advisory-vs-blocking exit-code case.
`tests/test_template_import.py` -- a synthetic source `.docx` with "CONFIDENTIAL" in its header
produces the flagged comment block in the generated profile; one with no marking-like text produces
neither the comment nor an empty stub (don't add noise when there's nothing to flag).

**Real-document validation:** run `marking_lint.py` against the real consumer skin's `reference.docx`
BEFORE this session's earlier fix (the one that added a `brief_replacements` rule for the template's
own leftover marking text) is applied, confirm it flags the finding; run it again after, confirm
clean.

## 3. #87 (cheap half only) -- run-boundary fix for `apply_brief_classification_marking`

**File:** `docstyle/style_postprocess.py`, function `apply_brief_classification_marking()`
(~line 697-750), specifically the `fixpart()` inner function's per-run matching loop (~line 719-728).

Port the pattern `fix_header_footer_text` already proves works (paragraph-level concatenation, then
write the result back into the run structure), adapted to preserve this function's own PAGE-field
constraint (already handled by the existing code AFTER the match-and-replace step -- only the
matching itself needs to change from per-run to paragraph-concatenated):

```python
def fixpart(part):
    for para in part.paragraphs:
        full_text = ''.join(r.text for r in para.runs)
        matched_rule = None
        for rule in rules:
            for find in (rule.get('find') or []):
                if find and find in full_text:
                    matched_rule = (rule, find)
                    break
            if matched_rule:
                break
        if matched_rule is None:
            continue
        rule, find = matched_rule
        new_text = full_text.replace(find, rule['replace'])
        if matched is not None:
            matched.add(find)
        # write the full replacement into the first run, blank the rest --
        # matches the existing pattern fix_header_footer_text already uses
        if para.runs:
            para.runs[0].text = new_text
            for r in para.runs[1:]:
                r.text = ''
        # existing between-run whitespace/fragment cleanup (PAGE field
        # preservation) runs unchanged after this point
        ...
```

**Explicitly NOT attempted in this pass** (B5.3b, deferred): the "bare marking, no suffix" case
(nothing to replace INTO when the marking string has no trailing parenthetical to swap) needs run
synthesis, a materially different change; do not conflate with the run-boundary fix above.

**Tests to add:** a marking string deliberately split across 2+ runs (mirrors how python-docx /
real Word documents commonly fragment a paragraph after an edit) under `--profile reference`,
confirm the replacement now succeeds where it previously silently failed. Regression: confirm the
existing PAGE-field-preservation test (`test_header_footer_replacements_from_profile`-adjacent
brief-path test, if one exists -- check `tests/test_docstyle.py` for the current brief coverage)
still passes unchanged.

**Real-document validation:** deliberately construct a probe where the real consumer skin's marking
text in `reference.docx`'s header is split across two runs (simulate a real Word hand-edit), confirm
the fixed code now replaces it correctly under `--profile reference`; confirm the ALREADY-passing
single-run case (that skin's actual current header) is unaffected.

## 4. #120 -- `--pdf` help text + optional bundled Word-COM converter

**Minimum (do first, in this pass):** `container/render-doc.sh` line ~109, correct:
```
--pdf                  also convert to PDF (Word-COM on Windows via PDF_CONVERTER_PS1,
                        else soffice; see PDF_CONVERTER_PS1 in the env-var header above)
```

**Better (attempt in this pass if time allows, else split to a follow-up):** ship
`container/word-to-pdf.ps1` (the script this session already wrote and validated against real
renders) as a repo-bundled default, and change the `DO_PDF` block (~line 388) to fall back to it when
`PDF_CONVERTER_PS1` is unset AND running on Windows AND Word is detected on PATH/registry, keeping
`PDF_CONVERTER_PS1` as the override:
```bash
if [ "$OS" = windows ] && [ -z "$PDF_CONVERTER_PS1" ]; then
  DEFAULT_PS1="$REPO_ROOT/container/word-to-pdf.ps1"
  [ -f "$DEFAULT_PS1" ] && PDF_CONVERTER_PS1="$DEFAULT_PS1"
fi
if [ "$OS" = windows ] && [ -n "$PDF_CONVERTER_PS1" ] && [ -f "$PDF_CONVERTER_PS1" ]; then
  ... # existing invocation, unchanged
```
Word-detection itself should NOT be a hard requirement gate (COM instantiation failing is a fine,
already-handled runtime error path) -- just prefer the bundled script over silently falling through
to the WARN when nothing else is configured.

**Tests to add:** `tests/test_render_doc_toc_opt_out.py`-style real-pipeline integration test (same
subprocess pattern) asserting the corrected help text; a Windows-only test (skip on other platforms,
matching the existing `pytest.skip` pattern for missing engines) that the bundled script is picked up
when `PDF_CONVERTER_PS1` is unset and produces a real PDF.

**Real-document validation:** re-run the exact `render docx --pdf` invocation from earlier this
session WITHOUT manually setting `PDF_CONVERTER_PS1` (this session's original failure mode) and
confirm a PDF is now produced automatically.

## Sequencing

1. #122 first (P0, data loss, the most isolated change -- touches only `build_reference_cover`).
2. #120 minimum (help text) is a one-line change, do it alongside #122 for a cheap early win.
3. #123 core (marking_lint.py + import-template flag) -- new files, additive, no risk to existing
   render paths, can proceed independently of 1/2.
4. #87 cheap half -- touches the same file/function-cluster as #122 (`style_postprocess.py`), do
   after #122 lands and its tests pass, to avoid conflicting mid-flight edits to the same file.
5. #120 better (bundled script) -- only if 1-4 land with time remaining; otherwise a clean follow-up.

Full test suite run once at the end (targeted files during each step's own iteration, not after
every edit -- the exact tokenomics mistake PR #124's own review caught: five full-suite runs at
~160s each for one three-file change, when the relevant test files alone run in under 15s).
