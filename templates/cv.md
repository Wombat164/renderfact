---
title: "CV Template"
version: v0.1
lang: en
summary: "A consultant capability-statement CV: lead with delivered work, not a chronological job-title timeline. Pairs with cover-letter.md and pdf/theme/cv-personal.typ."
---

<!--
Genre: a freelance/consulting CV for a screening application, not a corporate HR CV.
Render with the CV/cover-letter theme, not the default governance theme:
  python render.py pdf your-copy.md --theme pdf/theme/cv-personal.typ --brand your-brand.yaml
Instantiate: copy this file, replace every [bracketed placeholder], delete guidance
sentences you no longer need, then render. See docs/2026-07-05-cv-cover-letter-design-spec.md
for the rationale behind the identity-block-as-raw-typst pattern below and the
section-styling this pairs with.
-->

```{=typst}
#grid(
  columns: (1fr, auto),
  align: (left + horizon, right + horizon),
  column-gutter: 1.2em,
  [
    #text(size: 22pt, weight: "black", fill: brand.primary)[[Full name]]
    #v(0.12em)
    #text(size: 11.5pt, fill: brand.accent, weight: "medium")[[One-line positioning: role + practice, e.g. "Freelance X Consultant --- Y"]]
    #v(0.55em)
    #text(size: 8.8pt, fill: brand.ink)[
      [phone] #sym.dot.c [email] #sym.dot.c [city, country] \
      [LinkedIn or portfolio URL] #sym.dot.c [second URL, if any]
    ]
  ],
  // Delete the box()/image() block entirely if no photo is wanted -- the grid
  // still works with a single [1fr] column.
  box(clip: true, radius: 50%, width: 2.6cm, height: 2.6cm, stroke: 0.6pt + brand.accent)[
    #image("[photo filename, same folder as this source]", width: 2.6cm, height: 2.6cm, fit: "cover")
  ],
)
#v(0.5em)
#line(length: 100%, stroke: 0.7pt + brand.accent)
#v(0.7em)
```

## Profile

Three to five sentences. Lead with what you actually deliver (the assessment, the
report, the recommendation), not a list of adjectives. Name the one or two things that
differentiate you from someone else with the same job title -- a specific technical
background, a specific methodology, a genuinely current niche few competitors are
equipped for. Close with languages and availability model (freelance/remote/hours-
capacity) in one sentence -- a screening reader should not have to hunt for this.

[Profile paragraph.]

## Core Capabilities

A bullet per capability, each earning its place with a concrete qualifier (a named
methodology, a named framework, a named regulation) rather than a generic noun phrase.
Order by what the target engagement actually needs first, not by how impressive each
one sounds in isolation.

- **[Capability one]** -- [what it concretely means, named frameworks/standards].
- **[Capability two]** -- [concrete qualifier].
- **[Capability three]** -- [the differentiator -- the thing that isn't generic].
- **Multilingual delivery** -- [language (level), language (level), ...].

## Selected Experience

Prefer this "capability statement" shape over a full chronological job history,
especially where naming a specific employer isn't possible or desirable (institutional
confidentiality, ongoing employment, genericization requirements). State scope and
duration without naming the employer if that constraint applies; lead every bullet with
a verb and a concrete, quantifiable outcome, not "responsible for" phrasing.

**[Role/employer phrasing -- generic if needed, e.g. "Senior [Function] Officer, [sector] organization"]** ([duration])
[One-line scope description.]

- [Concrete deliverable/outcome, with a number or named methodology where honest.]
- [Concrete deliverable/outcome.]

## Certifications & Training

List only what's real. An in-progress credential belongs here too (labelled
"in progress"), reinforcing the experience above -- it should never be the document's
main credibility claim by itself.

- **[Certification/training name]** -- [status: held / in progress].

## Technical / Open-Source Credibility

Optional section -- include only if there's real, checkable public work (a published
repo, a shipped tool). A private/internal project can be described without a link;
don't imply public availability of something that isn't public.

- **[Project name]** -- [one line: what it is, why it's relevant here]. [URL, if public.]

## Availability

State the actual constraint explicitly (hours/month, schedule flexibility, remote vs.
on-site radius) -- vague availability language reads as evasive to a screening reader
who needs to plan around it.

[Concrete availability statement.]

## References

[Available upon request / list names.]
