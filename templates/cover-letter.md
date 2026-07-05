---
title: "Cover Letter Template"
version: v0.1
lang: en
summary: "A direct capability pitch for a freelance/consulting screening application -- not a narrative why-I-want-this-job letter. Pairs with cv.md and pdf/theme/cv-personal.typ."
---

<!--
Genre: a cover letter for a freelance-network or consulting-firm screening
application (a broker matching you to client mandates), not a single-employer
corporate job application -- the tone and structure differ from both.
Render with the CV/cover-letter theme, not the default governance theme:
  python render.py pdf your-copy.md --theme pdf/theme/cv-personal.typ --brand your-brand.yaml
Instantiate: copy this file, replace every [bracketed placeholder], delete guidance
sentences you no longer need, then render. See docs/2026-07-05-cv-cover-letter-design-spec.md
for why this genre's identity block is deliberately lighter than the CV's (no photo,
smaller type -- the letter's job is the argument, not re-establishing identity).
-->

```{=typst}
#text(size: 15pt, weight: "black", fill: brand.primary)[[Full name]]
#v(0.08em)
#text(size: 10pt, fill: brand.accent, weight: "medium")[[Practice/title, e.g. "Company --- Role"]]
#v(0.4em)
#text(size: 8.8pt, fill: brand.ink)[
  [phone] #sym.dot.c [email] #sym.dot.c [LinkedIn or portfolio URL]
]
#v(0.4em)
#line(length: 100%, stroke: 0.7pt + brand.accent)
#v(0.9em)
```

[Date]

[Recipient organization]
[Recipient role/team, if known]

**Re: Application -- [role/network name]**

To [whom it may concern / named contact],

One page, three to five short paragraphs (3-4 sentences each), varied in shape and
length so the letter doesn't read as templated. A screening reader skims this in
under 30 seconds -- lead every paragraph with the point, not a warm-up sentence.

Paragraph one: who you are and why this specific shift/application, in one or two
sentences -- not "I am writing to apply for..." Name the practice/consultancy you
operate through if relevant, and state directly what you're extending it into.

[Opening paragraph.]

Paragraph two: the single strongest, most concrete piece of evidence for why you're
credible here -- one real deliverable, with real numbers or named specifics
(a methodology, a scale, a corrected error, a resolved volume of feedback). This
paragraph is the one that has to survive on its own if the reader only reads one.

[Evidence paragraph -- one concrete deliverable, quantified where honest.]

Paragraph three (optional): the differentiator -- what points toward where this is
heading, not just where it's been. A genuinely current niche, an adjacent capability,
an in-progress credential framed as continued formalization, not the credibility
source itself.

[Differentiator paragraph.]

Paragraph four: availability stated as explicitly as on the CV (hours/month,
schedule flexibility, remote/on-site radius) -- and frame the constraint as
deliberate (depth over spread), not apologetic.

[Availability paragraph.]

Close with a direct, single-sentence invitation to the next step -- not a restated
summary of the letter.

[Closing line.]

Kind regards,

[Full name]
