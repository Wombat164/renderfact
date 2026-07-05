// cv-personal.typ -- a CV / cover-letter theme (D3-consistent: reads the same
// generated tokens.typ every theme reads, defines richer layout logic than
// default.typ's role-based chrome supports).
//
// Design intent (2026-07-05 Typst CV prior-art research: brilliant-CV, chicv,
// grotesk-cv, typst-neat-cv): single-column, no sidebar, no skill-bar widgets.
// One restrained accent colour used ONLY for the name, section labels, and
// hairline rules -- never as a fill. Section breaks are tracked-out small-caps
// with a single hairline rule beneath, not a thick coloured bar. Generous
// whitespace does the separating work a horizontal rule usually does. This is
// the deliberate opposite of the generic "Canva template" register: no icon
// rows, no gradient header, no progress-bar skill meters.
//
// A CV/cover-letter genre has an identity block (name, title, contact, an
// optional photo) that default.typ's simple org/title header has no slot for.
// Consumers place that block themselves as a raw typst passthrough at the top
// of the markdown body (see templates/cv.md / templates/cover-letter.md) --
// this theme supplies the section/heading/spacing register around it.
//
// Two spacing profiles, selected by --mode (passed through into conf() by
// typst_backend.py; deliberately a separate knob from --variant, which is
// validated against brand.yaml's declared theme.variants -- --mode has no
// such registry). "base" is the CV's profile, tuned tight for one-page fit
// under real content load. "letter" is the cover letter's profile: a letter
// runs to well under a page even with generous spacing, so it should not
// inherit the CV's page-fit compression -- cramped paragraphs on a
// three-quarters-empty page read as a mistake, not restraint.

#import "tokens.typ": *
#import "chrome.typ": chrome

#let _role(name) = brand.at(name, default: brand.ink)

#let conf(
  title: none,
  subtitle: none,
  org: none,
  date: none,
  paper: "a4",
  lang: "en",
  mode: "base",
  doc,
) = {
  set document(title: if title != none { title } else { "" })

  let accent = _role("accent")
  let ink = brand.ink
  let letter = mode == "letter"

  set page(
    paper: paper,
    // Margins are a spacing knob too. "base" (CV) runs tight so a content-dense
    // CV holds one page. "letter" runs generous on all four sides: a short cover
    // letter should sit in a comfortable, well-inset text column on a mostly-full
    // page, not span edge-to-edge like a data-dense CV.
    margin: (if letter {
      (x: 2.7cm, top: 2.0cm, bottom: 1.8cm)
    } else {
      (x: 2.0cm, top: 1.5cm, bottom: 1.5cm)
    }),
    // Subtle VDHome letterhead background (the DOC/light register). Two layers:
    //   1. a soft violet-50 -> white wash across the top ~8.5cm, so the identity
    //      block sits on a faint branded field while the body stays on pure white
    //      (near-black ink on white below the wash = full print legibility; no
    //      light-text-on-tint failure mode). Uses the `fill` token, never `accent`
    //      -- the "accent is stroke/label only" restraint holds for the wash.
    //   2. ONE full-saturation touch: a 2pt top-edge rule in the vivid web-brand
    //      violet (#7C3AED, violet-600). This is the single deliberate link to the
    //      energetic web register; everywhere else the print palette stays deepened
    //      and muted. Full-bleed at the very top edge, above the text block.
    background: {
      place(top, rect(width: 100%, height: 8.5cm,
        fill: gradient.linear(brand.fill, brand.background, angle: 90deg)))
      place(top, rect(width: 100%, height: 2pt, fill: rgb("#7C3AED")))
    },
    footer: context {
      set text(size: 8pt, fill: ink)
      line(length: 100%, stroke: 0.4pt + accent.lighten(40%))
      v(0.15em)
      // Three slots: date (left), an optional document-handling / distribution
      // marking (centre, fed from the generic `org` param so the theme stays
      // application-neutral -- any consumer can pass a handling caveat via --org),
      // page x/y (right). The marking is set smaller + muted: an info-classification
      // convention, present but never shouting.
      grid(
        columns: (1fr, auto, 1fr),
        align(left, if date != none { date } else { [] }),
        align(center, if org != none {
          text(size: 7pt, fill: ink.lighten(30%), org)
        } else { [] }),
        align(right, {
          let here-page = counter(page).at(here()).first()
          let total = counter(page).final().first()
          [#here-page / #total]
        }),
      )
    },
  )

  // No org/title auto-title-block: the identity header is genre content the
  // consumer places at the top of the markdown body (name/photo/contact carry
  // more structure than a single title+subtitle line can express). This
  // avoids double identity blocks stacking on top of each other.

  set text(
    font: (brand-font, "Liberation Sans", "Arial", "DejaVu Sans"),
    size: (if letter { 10.2pt } else { 9.0pt }), fill: ink, lang: lang,
  )
  // "letter" gets deliberately open vertical rhythm: comfortable line leading and
  // generous paragraph spacing so a short letter fills its page as a composed,
  // breathing document rather than a compressed CV. "base" stays tight for fit.
  set par(
    justify: false,
    leading: (if letter { 0.78em } else { 0.56em }),
    spacing: (if letter { 1.32em } else { 0.62em }),
  )

  // Clickable links (contact line email/LinkedIn, in-text URLs) carry the accent
  // colour so they read as intentional links without a dated underline.
  show link: set text(fill: accent)

  // Section labels (h2): tracked-out small-caps in the accent colour, one
  // hairline rule beneath -- the "regulatory, not Canva" cue from the research.
  // Whitespace goes ABOVE the label (separating it from the section it closes
  // out), not below (the label should sit close to ITS OWN content, the same
  // pattern default.typ's own heading rule already uses: above > below).
  // No h1 show rule: h1 is reserved for a genre's own raw identity block, not
  // pandoc heading flow (a consumer who does use markdown h1 gets sane bold
  // text, just without a special treatment layered on top).
  // The "gap ABOVE the section header" deliberately does NOT use block(above:):
  // Typst collapses adjacent block spacing to the MAX of the two values, and the
  // preceding paragraph already emits its own trailing spacing via set par(...)
  // (0.68em base / 0.9em letter), so any `above:` at or near that size collapses
  // away to almost nothing. Instead we emit an explicit NON-weak v() before the
  // block: non-weak spacing is not subject to weak-spacing collapse, so it adds
  // in full on top of whatever the previous paragraph contributed, producing a
  // clearly visible separator between the previous section and the new header.
  // Inside the block, a tight local par spacing keeps the header text flush to
  // its own underline rule (no gap between the label and its hairline).
  show heading.where(level: 2): it => {
    v(if letter { 1.3em } else { 1.0em }, weak: false)
    block(above: 0em, below: 0.2em, breakable: false, {
      set text(size: 9.5pt, fill: accent, weight: "semibold", tracking: 0.4pt)
      set par(spacing: 0.16em, leading: 0.4em)
      upper(it.body)
      line(length: 100%, stroke: 0.6pt + accent)
    })
  }

  show heading.where(level: 1): it => block(above: 0.6em, below: 0.4em, {
    set text(size: 15pt, fill: _role("primary"), weight: "bold")
    it.body
  })

  set list(marker: text(fill: accent)[•], spacing: 0.4em, indent: 0.2em)

  doc
}

// A small accent-stroked initials badge, no fill (rule 1: accent never fills).
// For a cover letter's lighter identity block (rule 7: no photo) this is the
// same circular-badge motif the CV uses for its photo, so the pair reads as
// one visual identity across both documents without repeating the photo.
#let initials-badge(initials, size: 2.0cm) = {
  let accent = _role("accent")
  box(clip: true, radius: 50%, width: size, height: size, stroke: 0.6pt + accent,
    align(center + horizon, text(size: size * 0.34, fill: accent, weight: "medium", initials)))
}

// A small drawn LinkedIn mark (brand blue, white "in"), no external SVG/icon
// font bundled -- keeps the licensing surface as simple as the OFL-bundled
// Geist fonts already are. Meant to sit inline just before a linked name, so
// a contact line reads as an icon + human name rather than a bare printed
// URL (the URL still lives in the surrounding #link(...) as the real href).
#let linkedin-mark(size: 0.85em) = box(
  width: size, height: size, radius: 15%, fill: rgb("#0A66C2"), baseline: 15%,
  align(center + horizon, text(size: size * 0.62, fill: white, weight: "bold")[in]),
)
