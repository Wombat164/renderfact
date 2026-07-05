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
