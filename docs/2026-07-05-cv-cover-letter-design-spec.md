# CV / cover-letter genre: design spec

Written after building `pdf/theme/cv-personal.typ` for a real freelance-application
use case. Captures what "good" looks like for this genre specifically, so the theme
and the two templates it pairs with (`templates/cv.md`, `templates/cover-letter.md`)
stay anchored to a rationale instead of drifting on taste alone.

## The failure mode this is reacting to

The default theme (`pdf/theme/default.typ`) is built for governed internal documents
(decision briefs, external-party briefs, purchase requests) -- a single org/title
header, bold-role headings, a thick rule under the title block. Applied unchanged to
a CV/cover-letter, the result reads as "generic AI-drafted resume": no identity block
worth the name (a photo, name, and contact line have more structure than one
title+subtitle line expresses), heading treatment identical to a governance memo, and
none of the whitespace-as-hierarchy a personal/professional document needs.

## Prior art (Typst CV packages, surveyed 2026-07-05)

- **brilliant-CV** (github.com/yunanwg/brilliant-CV, 800+ stars) -- modular,
  multilingual, single accent colour used only for name/rules/links, grid-based
  role/date alignment instead of tables.
- **chicv** (github.com/skyzh/chicv, 700+ stars) -- deliberately minimal,
  single-column, no photo -- the "engineer-clean" reference point for restraint.
- **grotesk-cv** (github.com/AsiSkarp/grotesk-cv) and **typst-neat-cv**
  (github.com/UntimelyCreation/typst-neat-cv) -- both explicitly ship a CV *and* a
  matching cover letter as a pair, which is this genre's actual shape (one identity,
  two documents), not two unrelated templates.
- **modern-cv**-style Typst ports (Awesome-CV look) -- the most-copied, most
  recognizable layout; useful as the thing to deliberately diverge from, not imitate.

## The design rules that came out of it

1. **Single accent colour, three uses only**: name, section labels, hairline rules
   (and links). Never a fill, never a second accent. This is the single biggest
   lever separating "GRC/compliance-consultant CV" from "Canva template."
2. **No thick coloured bars.** A section break is a tracked-out, small-caps label in
   the accent colour, with one hairline rule beneath it (`0.5-0.7pt`) -- not a solid
   block of colour. See `cv-personal.typ`'s `heading.where(level: 2)` show rule.
3. **The identity block is genre content, not theme chrome.** A CV/cover-letter
   needs a name, a one-line positioning statement, a contact line, and (CV only) a
   photo -- more structure than `default.typ`'s title/subtitle slot expresses, and it
   varies per person. The theme supplies the surrounding register (fonts, spacing,
   section styling); the *identity block itself* is a raw typst passthrough
   (` ```{=typst} ... ``` `) at the top of the markdown body. See both templates for
   the pattern -- a `grid(columns: (1fr, auto), ...)` with name/title/contact on the
   left and a circular-clipped photo on the right for the CV; a shorter no-photo
   version for the cover letter.
4. **Whitespace is the separator, not a rule.** `density: loose` in brand.yaml,
   generous `v()` gaps between sections, `par(leading: 0.72em)` -- resist compressing
   to fit more onto one page. A CV genre document earns its second page before it
   earns crowding.
5. **Restrained heading hierarchy.** h1 (if used at all, outside the identity block)
   stays modest -- 15pt bold, not the loud 20-22pt `default.typ` uses for a document
   title. The identity block already carries the "big text" role; a second loud
   heading competes with it.
6. **A circular photo, small, never dominant.** `box(clip: true, radius: 50%, width:
   2.6cm, height: 2.6cm)[#image(...)]`, placed top-right of the identity grid, with a
   thin accent-coloured stroke -- not centred, not badge-styled, not larger than the
   contact-info column it sits beside.
7. **Cover letter gets a lighter identity block than the CV.** No photo, smaller type
   -- the letter's job is the argument, not re-establishing identity a second time.
   Keep the business-letter shape (date, recipient, subject line, salutation) below
   the header rather than folding it into the header block itself.

## Lessons from the first real production use (same day, second pass)

Built for a real freelance application; both documents went through several rounds
of visual re-inspection (rendering to PDF and reading it back) before they were
right. Two lessons worth keeping:

- **`tracking:` in Typst `text()` is an ABSOLUTE point value per character, not a
  relative one.** `tracking: 1.6pt` on 9.5pt section-header text rendered as visibly
  broken, wildly-spaced letters ("P R O F I L E"), not a tasteful tracked small-caps
  look. `0.4pt` is the value that actually reads as intentional letter-spacing at
  this genre's font sizes. Sanity-check any tracking value against font size before
  trusting the description "tracked-out small-caps" to mean the same thing across
  themes.
- **Base font size is the highest-leverage lever for page-fit, ahead of margin or
  paragraph-spacing tweaks.** Chasing a one-page CV through margin (2.4 to 2.2cm),
  leading (0.72em to 0.62em), and heading-spacing reductions each bought a little
  room but left a stubborn half-page of spillover; dropping the base body size from
  10.3pt to 9.4pt closed most of the remaining gap in one move, with real content
  trims (merging near-duplicate closing sections) closing the rest. Reach for font
  size early in a page-fit pass, not as a last resort after several rounds of
  spacing surgery.
- **`--` as a prose separator renders as a real dash character through pandoc, and
  reads as an AI-writing tell.** Markdown source written with " -- " between clauses
  (this project's own vault house style, ironically) comes out the other side as an
  en-dash in the PDF; dash-heavy prose is one of the most recognisable LLM
  fingerprints to a human reader. For consumer-facing genres like CV/cover-letter,
  write with commas, colons, semicolons, and parentheses instead, reserve the
  hyphen for actual compound words.

## What's still open (candidates for a real `--genre cv` mode, #TODO)

- The identity-block-as-raw-typst pattern works but is copy-paste per document; a
  first-class `#let identity-block(name, title, contact, photo: none)` helper in the
  theme (or a new semantic-blocks fenced-div type, e.g. `:::identity`) would let a
  consumer write structured markdown instead of raw typst for this one part. Not
  built here -- flagged in the GitHub issue as a real follow-up, not attempted as a
  Lua-filter change in this pass given the scope already covered.
- `sym.dot.small` does not exist in Typst 0.15 (hit during this build, fixed by
  falling back to a literal `•` glyph) -- worth a `render doctor`-level symbol-name
  lint if theme authors keep tripping on this.

## 2026-07-05 (second pass): the real VDHome brand, two registers

The earlier passes styled these documents with a generic navy+teal palette and a
placeholder "Inter" font token (which, it turned out, was silently falling back to
Liberation Sans -- Inter is not installed on the build host). This pass replaces
that with the ACTUAL VDHome brand, derived from the live site (www.vdhome.be), and
formalises it as one brand in two deliberate registers. Full token definition lives
in the consumer brand file `vdhome-brand.yaml` (in the vault's `10 - Bijlagen/`);
this section records the rationale.

**One brand, two registers (stated so it reads as one brand later, not two palettes):**
Two deliberate expressions of a single violet-hue, single-font-family brand --
energetic/full-saturation for digital surfaces, restrained/deepened for formal print.

- **Web / dark** (digital surfaces, unchanged from the live site): near-black
  `#0A0A0A`, foreground `#EDEDED`, VIVID violet `#7C3AED` (Tailwind violet-600, the
  brand anchor), Geist / Geist Mono at full expression. Documented under
  `colour.web_dark` + declared as the `web-dark` theme variant. Not rendered to PDF
  (print is a light medium); it is a formal token set for the website/decks.
  Contrast: `#EDEDED` on `#0A0A0A` ~= 15:1 (AAA); `#7C3AED` on `#0A0A0A` ~= 3.7:1 --
  fine for large text / UI accents (WCAG AA large >= 3:1), step to violet-400
  `#A78BFA` for small accent-coloured body text on dark.
- **Doc / light** (this CV + cover letter + future formal VDHome docs): the ACTIVE
  `colour.brand` palette. Name/primary `#4C1D95` (violet-900), accent `#5B21B6`
  (violet-800) for section labels / hairlines / bullets / badge / links, ink
  `#171717` near-black, background `#FFFFFF`, fill `#F5F3FF` (violet-50) for the
  letterhead wash. The full-saturation `#7C3AED` is reserved for ONE tiny touch (the
  2pt top-edge rule) -- everywhere else the print register stays deepened and muted.
  Contrast on white: ink 16:1, `#4C1D95` ~9:1, `#5B21B6` ~7.6:1 (all >= AA).

**Font: Geist (+ Geist Mono).** Vercel's OSS grotesk (SIL OFL,
github.com/vercel/geist-font) -- the real typeface already in production on the live
site, so the choice is the brand's, not a designer's guess. Considered but rejected:
inventing a distinctive serif/sans pairing (e.g. Cambria + Gill Sans) from generic
CV prior art -- correct instinct for a one-off, wrong for a brand refresh where the
company already HAS a deliberate font. Geist's metrics (tall x-height, lining
figures) are close enough to Inter -- which the one-page layout was originally tuned
against -- that the CV holds one page after re-tuning the base size (see below).
Geist is NOT a Windows system font: it is bundled in `pdf/theme/fonts/` (static
TTFs from the v1.7.2 release) and supplied to typst via `--font-path pdf/theme/fonts`
(the project's existing brand-font mechanism -- `--font-path` / `RENDERFACT_FONT_PATH`,
see `typst_backend._compile_cmd`). Verified rendering (not falling back) by the
distinct single-story Geist letterforms in the output and by `typst fonts
--font-path pdf/theme/fonts` listing "Geist" / "Geist Mono".

**Print vs web is a difference of USE, not of font:** the web register uses Geist
Black and vivid violet at size; the print register uses Geist SemiBold for the name
(not Black), slight negative tracking (-0.2pt, echoing the logo's tight spacing),
deepened violet, and small tracked-out SemiBold section labels. Same family, quieter
voice -- the institutional/compliance register the role calls for.

**Subtle background.** `set page(background: ...)` draws two layers: (1) a soft
violet-50 -> white vertical gradient wash across the top ~8.5cm (a faint branded
field the identity block sits on; body text sits on pure white below it, so there is
NO light-text-on-tint legibility failure), and (2) the single vivid touch, a 2pt
full-bleed top-edge rule in `#7C3AED`. This is present on both documents.

**Deliberate deviation from design rule 1 ("accent never used as a fill").** The 2pt
top-edge rule IS a fill of the vivid brand violet. Kept intentionally: it is the one
sanctioned full-saturation touch that ties the restrained print register back to the
energetic web brand, it is 2pt at the extreme page edge (not a Canva colour-block
header), and the wash uses the separate `fill` token, never the `accent`. Rule 1
otherwise still holds everywhere in the body. Noted here per the "if you deviate,
update the rules section" instruction.

**Cover-letter spacing + signature space.** Paragraph spacing raised from the prior
1.2em toward more breathing room; it now sits at 1.32em (leading 0.78em) -- the
ceiling that still holds one page once the data-handling note (below) is added.
Between "Kind regards," and the printed name there is a `#v(1.0cm)` signature gap
(plus the natural line gap) for a pen/scanned or itsme signature. (`v(1fr)` was tried
to pin the closing note to the page bottom but it greedily consumes remaining space
and pushes following content to page 2 -- use a fixed `v()`, not `1fr`, before
trailing content on a one-page document.)

**Clickable links.** Contact-line email (`mailto:`) + LinkedIn URLs and the in-text
renderfact URL are real PDF link annotations (`#link(...)` in the raw-typst identity
block; markdown `[text](url)` in the body), coloured in the accent via
`show link: set text(fill: accent)` so they read as links without a dated underline.

**Canonical render command (updated -- now needs `--font-path` + clean `--title` + the
distribution `--org`):**

```
python render.py pdf "<cv-draft.md>" -o "<cv-final.pdf>" \
  --theme "pdf/theme/cv-personal.typ" --brand "<vdhome-brand.yaml>" \
  --date "2026-07-05" --font-path "pdf/theme/fonts" \
  --title "Mathias Vanderhoeven - Curriculum Vitae" \
  --org "Distribution: DPO Associates BV recruitment team only. Not for redistribution."
# cover letter: same, source/-o swapped, add --mode letter, --title "... - Cover Letter"
```

## 2026-07-05 (third pass): compliance craftsmanship baked into the artifact

For a DPO/privacy-consultant application, the document itself should DEMONSTRATE the
skill, not just claim it -- but a genuinely skilled DPO shows proportionality, so each
element below is small, quiet, and correct. Every legal claim was checked against a
real source before being written (sources listed per item); nothing is invented.

**On the CV (lighter-weight items, to protect the one-page constraint):**
- *Distribution / handling marking* in the footer centre: "Distribution: DPO
  Associates BV recruitment team only. Not for redistribution." A standard
  information-classification convention. Fed via the generic `--org` param (the
  theme stays application-neutral; any consumer can pass a handling caveat).
- *Photo non-use caption* (6pt, muted, under the header rule): the photo is included
  solely to identify the candidate in this process and is not licensed for other
  use/publication/redistribution. Legal basis cited briefly and accurately: Belgian
  portrait right ("recht op afbeelding") -- a personality right grounded in art. 22
  of the Belgian Constitution and art. XI.174 of the Code of Economic Law (WER, ex
  art. 10 Copyright Act) plus case law -- retained by the subject; and the GDPR
  processing basis for the photo, Art. 6(1)(f) legitimate interest in candidate
  identification (best practice separates the portrait-right consent from the GDPR
  basis, grounding processing on legitimate interest rather than revocable consent).
- *Real PDF alt text* on the photo (`image(alt: ...)`, Typst 0.15) -- verified present
  as an `/Alt` entry in the output PDF. Accessibility signal (WCAG / EU Accessibility
  Act). NOTE on "hover tooltip": a true on-hover tooltip in a PDF is NOT the same as
  alt text and is not portably rendered across viewers (it needs a `/TU` field or a
  link tooltip, honoured inconsistently). The honest, correct substitute is embedded
  alt text (for AT) + the visible caption -- so that is what was done; no unreliable
  "hover" feature is claimed.

**On the cover letter (the fuller piece, where there is room):**
- *Data-retention / erasure notice* (7.2pt, muted, footed under a short rule): a
  courteous, proactive request that the application be retained only for the duration
  of the recruitment process and then erased, or -- if kept for future openings -- for
  no longer than the two-year-after-last-contact period. Cited to the storage-
  limitation principle (GDPR Art. 5(1)(e)) and the right to erasure (Art. 17); the
  two-year figure is the CNIL recommendation (max 2 years after last contact for
  recruitment data), widely used as a proportionality reference in Belgium where no
  statutory recruitment-retention term exists. Phrased as a professional request,
  not a legal threat.
- The distribution/handling marking (footer) appears here too.

**Data hygiene ("protect our data in this document"):**
- The source photo `mathias-cv-photo.png` was checked for embedded metadata: it is a
  clean PNG (RGBA, ancillary chunks only srgb/gamma/dpi) -- NO EXIF, no GPS, no
  camera model, no timestamp, no text chunks. Nothing to strip; a GPS-tagged photo
  would have been a real personal-data leak surviving into the embedded image, so
  this was verified rather than assumed.
- The rendered PDFs' own metadata was checked: Creator = "Typst 0.15.0" only, no
  Author field, no local username / machine path / temp-dir leak. The Info `Title`
  was defaulting to the source stem ("...-draft"); now set explicitly via `--title`
  to a clean human title, so the draft filename does not travel in the PDF.

**itsme / QES readiness:** not applied here (no eID access from the build side). The
cover letter's ~1cm signature gap is sized for a manual signature, and both documents
are ready for an itsme-based Qualified Electronic Signature pass whenever the human
runs one.

**Sources consulted (verified before writing any legal claim):** Belgian DPA (GBA)
"Recht op afbeelding" guidance; FOD Economie on the recht op afbeelding (art. 22 Const
/ art. XI.174 WER); CNIL HR/recruitment retention guidance (2-year-after-last-contact
default) as summarised by Belgian employment-law firms (Claeys & Engels, Lexgo,
Sirius Legal) as the Belgian reference framework absent a statutory term; GDPR Arts.
5(1)(e), 6(1)(f), 17; Typst `image(alt:)` accessibility support.

## 2026-07-05: follow-up -- feed this back into renderfact as first-class features

These compliance elements were hand-built into two documents. They generalise into
real renderfact capabilities (a candidate `--genre cv`/`--genre letter` mode, plus a
compliance layer) -- captured as a proposal, NOT yet built:
- A `handling`/`distribution` marking as a first-class footer slot (not a repurposed
  `--org`), driven from a document-classification token.
- A `:::photo-notice` / `:::data-handling` semantic-block (fenced-div) type that
  emits the correctly-cited portrait-right + GDPR notice and retention/erasure notice
  from structured fields, instead of hand-written raw typst.
- A `render qa` gate extension: PDF/image EXIF-leak scan + PDF-metadata (Author /
  path / username) leak scan as a fail-closed hygiene check -- this is a genuine,
  deterministic, high-value gate.
- Enforced `image(alt: ...)` (missing-alt lint) toward tagged-PDF / EU Accessibility
  Act conformance.
- CAUTION on the "claim full GDPR/DPIA compliance" framing: renderfact can legitimately
  offer *compliance-craftsmanship building blocks* (handling marks, cited notices,
  metadata/EXIF hygiene gates, accessibility lint) and can help PRODUCE DPIA/ROPA
  documents, but "GDPR/DPIA compliant" is a property of an organisation's processing,
  not of a rendering tool -- the honest, defensible claim is "GDPR-aware document
  tooling: builds in data-handling markings, correctly-cited privacy notices, PII/
  metadata leak gates, and accessibility checks," which is itself a strong,
  demonstrable differentiator. Tracked as a renderfact follow-up (GitHub issue).
