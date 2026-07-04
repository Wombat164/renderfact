// blocks.typ -- renderfact's first-class semantic blocks (issue #33).
//
// The typst render of the fenced-div blocks that pdf/filters/semantic-blocks.lua
// emits: `#signatures(...)`, `#attendance(...)`, `#statement(...)`. Styling is
// derived from the palette (tokens.typ) and the theme roles (chrome.typ), so a
// consumer's brand + variant restyle the blocks with everything else. Domain-
// generic across meeting minutes and financial reports.

#import "tokens.typ": *
#import "chrome.typ": chrome

#let _role(name) = brand.at(name, default: brand.ink)
#let _muted = brand.ink.lighten(35%)

// ---- signatures: a card grid, reserved signature space, hyphenation-safe ----
// A long role label must never force the NAME to hyphenate mid-word (a real bug
// when this was hand-built): names disable hyphenation; the role wraps freely.
#let signatures(roster, columns: 2, sign-label: "Handtekening", date-label: "Datum") = {
  let card(entry) = {
    let (name, role) = entry
    block(
      width: 100%,
      inset: 9pt,
      radius: 2pt,
      stroke: 0.5pt + _role(chrome.rule-role),
      {
        set par(justify: false)
        {
          set text(weight: "bold", hyphenate: false)
          name
        }
        if role != "" {
          linebreak()
          text(size: 9pt, fill: _muted, role)
        }
        v(2.2cm)  // reserved whitespace for a scanned signature
        line(length: 100%, stroke: 0.4pt + brand.ink)
        v(2pt)
        set text(size: 8pt, fill: _muted)
        grid(
          columns: (auto, 1fr),
          column-gutter: 6pt,
          sign-label,
          align(right, [#date-label: #box(width: 3cm, baseline: 2pt,
            line(length: 100%, stroke: 0.4pt + _muted))]),
        )
      },
    )
  }
  grid(
    columns: columns,
    column-gutter: 10pt,
    row-gutter: 10pt,
    ..roster.map(card),
  )
}

// ---- attendance: present / represented-by-proxy / quorum callout ----
#let attendance(
  entries,
  present-label: "Present in person",
  proxy-label: "Represented by proxy",
) = {
  let of(kind) = entries.filter(e => e.kind == kind)
  block(
    width: 100%,
    inset: 10pt,
    fill: _role(chrome.callout.fill-role),
    stroke: (left: 2pt + _role(chrome.callout.border-role)),
    {
      let section(label, items) = if items.len() > 0 {
        text(weight: "bold", label)
        list(..items.map(e => e.text))
      }
      section(present-label, of("present"))
      section(proxy-label, of("proxy"))
      for q in of("quorum") {
        v(4pt)
        text(weight: "bold", fill: _role(chrome.callout.border-role), q.text)
      }
    },
  )
}

// ---- statement / ledger: typed rows, right-aligned amounts, rule lines ----
// Row kinds: heading (section label, spans), item (label + amount), subtotal /
// total / balance (bold), rule (a full-width hairline). #34 will let this SOURCE
// its rows from data and COMPUTE + reconcile the totals; here amounts are given.
#let statement(rows) = {
  let bold-kinds = ("subtotal", "total", "balance")
  let cells = ()
  for r in rows {
    let kind = r.at("kind", default: "item")
    if kind == "rule" {
      cells.push(table.hline(stroke: 0.6pt + _role(chrome.statement.rule-role)))
    } else if kind == "heading" {
      cells.push(table.cell(colspan: 2,
        text(weight: "bold", fill: _role(chrome.statement.heading-role), r.at("label", default: ""))))
    } else {
      let is-bold = bold-kinds.contains(kind)
      let label = r.at("label", default: "")
      let amount = r.at("amount", default: "")
      cells.push(if is-bold { text(weight: "bold", label) } else { label })
      cells.push(align(right, if is-bold { text(weight: "bold", amount) } else { amount }))
    }
  }
  table(
    columns: (1fr, auto),
    stroke: none,
    inset: (x: 4pt, y: 3pt),
    ..cells,
  )
}
