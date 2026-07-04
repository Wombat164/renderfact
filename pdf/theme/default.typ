// renderfact default PDF theme (generic core, D3).
//
// The LAYOUT LOGIC. All *values* (margins, colour roles, header/footer slots)
// come from the generated chrome.typ descriptor (tokens/brand.yaml [theme] -> #32),
// so the house-style is declarative and engine-neutral; this file only turns those
// values into a typst page. Consumers override the whole layout via --theme, their
// palette via --brand, and the chrome/component values + variants in brand.yaml.

#import "tokens.typ": *
#import "chrome.typ": chrome

// Resolve a colour ROLE (a key in `brand`) to its rgb; fall back to ink.
#let _role(name) = brand.at(name, default: brand.ink)

// Resolve a header/footer slot key to its content, from the document metadata.
#let _slot(key, meta) = if key == none { [] } else { meta.at(key, default: []) }

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

  let meta = (
    org: if org != none { org } else { [] },
    title: if title != none { title } else { [] },
    date: if date != none { date } else { [] },
    pagenumber: context {
      let here-page = counter(page).at(here()).first()
      let total = counter(page).final().first()
      [#here-page / #total]
    },
  )
  let rule-colour = _role(chrome.rule-role)

  set page(
    paper: paper,
    margin: chrome.margin,
    header: {
      set text(size: 8pt, fill: brand.ink)
      grid(
        columns: (1fr, auto),
        align(left, _slot(chrome.header.left, meta)),
        align(right, _slot(chrome.header.right, meta)),
      )
      v(-0.55em)
      line(length: 100%, stroke: 0.5pt + rule-colour)
    },
    footer: {
      line(length: 100%, stroke: 0.5pt + rule-colour)
      v(0.2em)
      set text(size: 8pt, fill: brand.ink)
      grid(
        columns: (1fr, auto),
        align(left, _slot(chrome.footer.left, meta)),
        align(right, _slot(chrome.footer.right, meta)),
      )
    },
  )

  // brand-font first, then broadly-available sans fallbacks so a host without
  // the brand font still renders predictably (a brand ships its own font).
  set text(
    font: (brand-font, "Liberation Sans", "Arial", "DejaVu Sans"),
    size: chrome.body-pt * 1pt, fill: brand.ink, lang: lang,
  )
  set par(justify: chrome.justify, leading: 0.65em)

  // Headings in the theme's heading role.
  show heading: it => block(above: 1.1em, below: 0.55em, {
    set text(fill: _role(chrome.heading-role), weight: "bold")
    it
  })

  // Title block, only when a title is supplied.
  if title != none {
    text(size: 20pt, weight: "bold", fill: _role(chrome.title-role), title)
    if subtitle != none {
      linebreak()
      text(size: 12pt, fill: brand.ink, subtitle)
    }
    v(0.5em)
    line(length: 100%, stroke: 1pt + rule-colour)
    v(1.0em)
  }

  doc
}
