// GENERATED from tokens/brand.yaml -- do not edit by hand.
// Regenerate: python tokens/gen/typst_tokens.py

#let brand = (
  primary: rgb("#1F4A38"),
  accent: rgb("#E8A33D"),
  background: rgb("#F7F6F1"),
  ink: rgb("#20241F"),
  fill: rgb("#E2EBE3"),
  white: rgb("#FFFFFF"),
)
#let status = (
  ok: rgb("#2E7D32"),
  warn: rgb("#C97F1A"),
  risk: rgb("#C62828"),
  info: rgb("#3E7CB1"),
)
#let data = (
  rgb("#000000"), rgb("#E69F00"), rgb("#56B4E9"), rgb("#009E73"), rgb("#F0E442"), rgb("#0072B2"), rgb("#D55E00"), rgb("#CC79A7"),
)
#let brand-font = "Public Sans"
#let print-font = "Public Sans"
#let mono-font = "Roboto Mono"
#let body-min-pt = 14

// peace-of-posters theme, derived from the tokens (brand identity,
// scientific layout stays separate -- import peace-of-posters yourself)
#let brand-theme = (
  "body-box-args": (inset: 0.8em, width: 100%, fill: brand.background, stroke: none),
  "body-text-args": (fill: brand.ink),
  "heading-box-args": (inset: 0.7em, width: 100%, fill: brand.primary, stroke: brand.primary),
  "heading-text-args": (fill: white, weight: "bold"),
  "title-text-args": (fill: white),
)
