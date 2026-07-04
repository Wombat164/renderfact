# Prior art: OOXML template import / template-analysis (C7)

> Verification-disciplined research pass, 2026-07-03 (9 parallel sub-searches; every claim traced
> to a primary source fetched in-session; refuted claims listed, not dropped). Feeds C7's
> adopt/imitate/build tags in `ROADMAP.md`. Condensed; assertions carry their source.

## 1. Native capability baseline (the three libraries we already depend on)

- **Theme part (DrawingML colors/fonts): NO library exposes it.** python-docx stores only which
  theme ROLE a color uses, never resolves RGB (docs: `ColorFormat.theme_color`; maintainer:
  "have a look directly at the XML", python-docx issue 1267). openpyxl: zero theme hits in its
  doc genindex, and no documented lxml fallback either. python-pptx: maintainer-confirmed,
  "you'd be starting pretty much from scratch" (issue 308, open). **[build]** a shared raw-lxml
  theme parser; the gap is maintainer-confirmed in two of the three libraries, so this is
  genuinely novel glue, not an oversight workaround.
- **Styles / geometry / placeholders: [adopt] the existing deps.** python-docx Styles +
  ParagraphStyle + Font and Section (sectPr geometry) are documented APIs; python-pptx
  slide_masters/slide_layouts + placeholders (layout-level vs slide-level distinct); openpyxl
  NamedStyle + defined_names. All three MIT, actively maintained (verified via PyPI/repos).
  Caveats found: python-pptx documents solid/gradient/pattern background fills, NOT picture
  fills; openpyxl has no workbook-theme API at all.

## 2. Existing extractors

- **BrandDocs (github.com/ferdinandobons/brand-docs, MIT, verified): the biggest finding.**
  Roughly four weeks old (v0.10.0), 206 stars: extracts full clrScheme INCLUDING sysClr/lastClr
  resolution (verified by reading its color.py), named styles, page geometry, headers/footers,
  PPTX placeholders/layouts, XLSX named ranges/styles, into a versioned JSON "Brand Profile".
  Independent validation that C7's concept has traction. Too immature and differently packaged
  (AI-agent-skill bundle, JSON not YAML) to depend on: **[imitate]**, especially its
  sysClr/lastClr resolution logic, with attribution.
- **docx4j** (Apache-2.0, active): Java ThemePart + StyleTree + PropertyResolver, real
  effective-style CASCADE resolution. **[imitate]** the PropertyResolver pattern (basedOn-chain
  resolution) for whatever cascade depth we implement.
- **officer (R): REFUTED** as an extractor; it is write/generate-oriented. Skip.
- **LibreOffice headless to Flat ODF**: real but lossy (OOXML-to-ODF transform). Fallback idea
  only.

## 3. Pandoc reference-doc mechanics (what the derived profile must cover)

From the pandoc MANUAL: the DOCX writer consumes a CANONICAL style list from reference.docx
(Normal, Body Text, First Paragraph, Compact, Title, Subtitle, Author, Date, Abstract,
Bibliography, Heading 1-9, Block/Footnote/Source Code/Definition/Caption family, TOC Heading;
character styles incl. Hyperlink, Verbatim Char; the Table table style) AND carries "document
properties (including margins, page size, header, and footer)". **DrawingML theme colors/fonts
are not addressed by the mechanism at all**: exactly the hole the derived profile + the [build]
theme parser fill. PPTX also has --reference-doc (since pandoc 2.0.5), matching layouts BY NAME
(Title Slide, Title and Content, ...). **[adopt]** reference-doc as the primary styling carrier
for both formats; the profile covers what it cannot.

## 4. Theme spec identity

Confirmed via Microsoft Learn OOXML docs (ISO/IEC 29500): one DrawingML theme structure
(themeElements > clrScheme dk1/lt1/dk2/lt2/accent1-6/hlink/folHlink + fontScheme major/minor)
shared by all three application formats. Paths: word/theme/theme1.xml primary-verified;
xl/ and ppt/ equivalents secondary-verified only (flagged; trivially checkable by unzipping);
addressing is relationship-based, filename is convention. **[adopt-spec]**: one shared parser
module is justified.

## 5. Style-diff / idempotency gate

**No adoptable prior art exists** (searched: docx-compare variants, xmldiff, pptx-diff,
render-to-image diffing; Word/LibreOffice compare are GUI/tracked-changes tools). xmldiff (MIT)
is a generic building block with zero OOXML knowledge. **[build]**, scoped: compare the DERIVED
properties (heading/body font, color, size, page geometry) between template and probe render,
not a general effective-style differ.

## 6. Content-skeleton axis

- **[adopt] pandoc's docx READER with `-f docx+styles`** as the skeleton extractor: Heading N
  maps to #xN (verified at source level), custom paragraph/character/table styles arrive as
  Divs/Spans (manual, custom-styles section), and SDT/content-control BODIES are unwrapped and
  included since pandoc 2.0.6 (changelog), so controls are not invisible; only their metadata
  (tag/alias/placeholder flag) is lost. Known wart: horizontally merged table cells are dropped
  (issue 2783, open).
- **[imitate] mammoth's style-map DSL** (BSD-2-Clause, active) as the CONFIG SYNTAX for mapping
  instruction styles to author-only blocks: `p[style-name='X'] => ...`, including the `=> !`
  ignore form. Mammoth itself is not the engine (its markdown output is deprecated by its own
  docs).
- **[build] SDT/content-control metadata reading** via lxml: python-docx has no API (issues 155,
  965: even XPath-edited SDTs are fragile in Word); the only found reader (docx-form, MIT) is
  archived/dead: study its subtype-tag targeting, do not depend on it. PPTX placeholders and
  XLSX defined_names use the native **[adopt]** APIs; "fill-in anchor" is OUR convention over
  those APIs, not an existing one.
- **Structure-conformance gate: [build]**, modeled on markdownlint's MD043 semantics (required
  headings, order, wildcards; verified in its md043 doc) combined with an external YAML manifest.
  **okflint REFUTED**: its own RULES.md shows a frontmatter/metadata linter, zero heading-order
  rules; the earlier gap-analysis description of it was wrong.
- **Instruction/example classification: [build]**, no OSS prior art found. Deterministic
  pre-signals first, all OOXML-detectable: content-control placeholder flags, `w:vanish` hidden
  text, style-name regex (the Readability/boilerpipe class-name heuristic transplanted to Word
  style names); the D8 dual-mode LLM step runs only on what the pre-signals leave ambiguous.
  Boilerpipe-style text-density scoring transfers POORLY (headings score as boilerplate): noted
  and avoided.

## Refuted claims (kept per verification discipline)

1. okflint as a section-order manifest checker: refuted (frontmatter linter only).
2. docxtpl's run-splitting workaround being "an MS Word add-in": refuted (manual run-merge
   markers).
3. python-pptx documenting picture background fills: refuted (solid/gradient/pattern only).
4. officer (R) exposing style/theme introspection: refuted (write-oriented).

## Flagged as not primary-verified (re-verify before public ADR citation)

xl/ and ppt/ theme paths (secondary sources only); several Microsoft Learn pages that blocked
direct fetch (SdtBlock, content-control PlaceholderText, w:vanish usage); exact ECMA-376
5th-edition section numbers (ISO 29500 numbering confirmed only); OpenXmlDiff/DIFFOPC (host
unreachable).
