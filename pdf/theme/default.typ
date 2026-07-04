// renderfact default PDF theme (generic core, D3).
//
// A clean, brand-token-driven A4 layout so `render pdf` works with ZERO skin
// configuration. Consumers override this whole file via --theme <file.typ> /
// THEME_TYP and their palette via --brand (through the tokens.typ generator).
// Everything visual here is derived from tokens.typ -- no hard-coded colours.

#import "tokens.typ": *

// conf() is applied as a show rule over the whole document; the pandoc-produced
// body flows through `doc`. Metadata (title/org/date) is passed by the backend.
#let conf(
  title: none,
  subtitle: none,
  org: none,
  date: none,
  paper: "a4",
  doc,
) = {
  set document(title: if title != none { title } else { "" })

  set page(
    paper: paper,
    margin: (x: 2.2cm, top: 2.6cm, bottom: 2.4cm),
    header: {
      set text(size: 8pt, fill: brand.ink)
      grid(
        columns: (1fr, auto),
        align(left, if org != none { org } else { [] }),
        align(right, if title != none { title } else { [] }),
      )
      v(-0.55em)
      line(length: 100%, stroke: 0.5pt + brand.primary)
    },
    footer: {
      line(length: 100%, stroke: 0.5pt + brand.primary)
      v(0.2em)
      set text(size: 8pt, fill: brand.ink)
      grid(
        columns: (1fr, auto),
        align(left, if date != none { date } else { [] }),
        align(right, context {
          let here-page = counter(page).at(here()).first()
          let total = counter(page).final().first()
          [#here-page / #total]
        }),
      )
    },
  )

  // brand-font first, then broadly-available sans fallbacks so a host without
  // the brand font still renders predictably (a brand ships its own font).
  set text(
    font: (brand-font, "Liberation Sans", "Arial", "DejaVu Sans"),
    size: 10.5pt, fill: brand.ink, lang: "en",
  )
  set par(justify: true, leading: 0.65em)

  // Headings in the brand accent; a numbered feel without full chips (#33 later).
  show heading: it => block(above: 1.1em, below: 0.55em, {
    set text(fill: brand.accent, weight: "bold")
    it
  })

  // Title block, only when a title is supplied.
  if title != none {
    text(size: 20pt, weight: "bold", fill: brand.primary, title)
    if subtitle != none {
      linebreak()
      text(size: 12pt, fill: brand.ink, subtitle)
    }
    v(0.5em)
    line(length: 100%, stroke: 1pt + brand.primary)
    v(1.0em)
  }

  doc
}
