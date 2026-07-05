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
  doc,
) = {
  set document(title: if title != none { title } else { "" })

  let accent = _role("accent")
  let ink = brand.ink

  set page(
    paper: paper,
    margin: (x: 2.2cm, top: 2.0cm, bottom: 2.0cm),
    footer: context {
      set text(size: 8pt, fill: ink)
      line(length: 100%, stroke: 0.4pt + accent.lighten(40%))
      v(0.15em)
      grid(
        columns: (1fr, auto),
        align(left, if date != none { date } else { [] }),
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
    size: 9.4pt, fill: ink, lang: lang,
  )
  set par(justify: false, leading: 0.58em, spacing: 0.68em)

  // Section labels (h2): tracked-out small-caps in the accent colour, one
  // hairline rule beneath -- the "regulatory, not Canva" cue from the research.
  // No h1 show rule: h1 is reserved for a genre's own raw identity block, not
  // pandoc heading flow (a consumer who does use markdown h1 gets sane bold
  // text, just without a special treatment layered on top).
  show heading.where(level: 2): it => block(above: 0.55em, below: 0.25em, breakable: false, {
    set text(size: 9.5pt, fill: accent, weight: "bold", tracking: 0.4pt)
    upper(it.body)
    v(0.25em)
    line(length: 100%, stroke: 0.6pt + accent)
  })

  show heading.where(level: 1): it => block(above: 0.6em, below: 0.4em, {
    set text(size: 15pt, fill: _role("primary"), weight: "bold")
    it.body
  })

  set list(marker: text(fill: accent)[•], spacing: 0.4em, indent: 0.2em)

  doc
}
