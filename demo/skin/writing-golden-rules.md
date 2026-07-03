# Writing golden rules (demo skin)

This file is part of the DEMO SKIN, deliberately: writing doctrine is consumer configuration,
not renderfact core. The core gives you mechanisms (projection, gates, styles); what good prose
means for YOUR organisation lives in files like this one, next to your brand tokens and profiles.
Adapt or replace it wholesale. The rules below are distilled from public, citable traditions
(structure doctrine, cognitive science, documentation engineering); sources at the end.

## The one rule

Every unit of text (document, section, subsection, paragraph) has exactly ONE job, states that
job in its first line, and contains nothing that does not serve it.

## Condensation, per level

| Level | The one job | First-line rule | Fluff test |
|---|---|---|---|
| Document | One governing thought | Answer first (BLUF); brief context opening only if needed | Does every part answer a question the governing thought raises? |
| Section | One message (a claim, not a topic) | Heading states the claim ("One substrate, many tenants", not "Tenancy") | No overlap with sibling sections; overlap means one of them loses the content |
| Subsection | Answer exactly one why or how the section raised | Label in 3 to 5 words; point first | If it answers no question the parent raised, it is misplaced or dead |
| Paragraph | One point | Point sentence first; about 7 sentences maximum | Delete it: can the reader still act correctly? Then it was a seductive detail |
| Sentence | One assertion | Front-load the information-carrying words | Characters as subjects, actions as verbs; omit needless words |
| Visual | One relationship | Caption states what to SEE, not what it is | Erase non-data ink and redundant ink |

## The fluff taxonomy (what to cut, with its detector)

1. Seductive details: interesting, true, off-objective. Detector: the deletion test.
2. Throat-clearing meta-text: "In this section we will discuss...". The heading plus a point
   sentence already do this job. (The demo Vale style blocks the common patterns.)
3. Same-channel redundancy: prose restating an adjacent table or figure hurts more than either
   alone.
4. Mode-mixing: explanation bleeding into reference, background inside procedure. Relocate, do
   not delete.
5. Hedges and intensifiers: "quite", "rather", "very", "it should be noted that". (The demo Vale
   style warns on these.)
6. Orphaned context: background no downstream claim ever uses.

Sanctioned repetition is the exception: structural reinforcement at DIFFERENT altitudes
(preview, in-place marker, closing recap) helps; repetition within one channel is deletion fuel.

## Engagement, before condensing

Condensation decides what survives onto the page; engagement decides what the reader must
experience. The four highest-yield moves, in order: (1) lead with something concrete (a diagram
or plain-language map), never meta-theory; (2) pull a worked example forward; (3) even out the
pacing so no section is a wall; (4) gloss jargon on first use.

## Mechanical enforcement (this skin's Vale style)

`vale/` in this skin encodes the deterministic slice as a consumer Vale config:
throat-clearing patterns BLOCK, hedges and intensifiers WARN. Run it through the gate chain:

```sh
RENDERFACT_VALE_CONFIG=demo/skin/vale/vale.ini python render.py gate demo/source --stages vale
```

Everything else in the taxonomy above needs human judgment (or a reviewing pass); the gate only
automates what is genuinely deterministic.

## Sources (public traditions this distils)

Minto, The Pyramid Principle (governing thought, answer-first, MECE) - BLUF per US Army AR 25-50 -
Nielsen Norman Group F-pattern eyetracking - GOV.UK content design principles - Mayer, multimedia
learning (coherence, seductive details, signaling, redundancy) - Horn, Information Mapping -
Diataxis (diataxis.fr) - Carroll and van der Meij, minimalism - ISO 24495-1:2023 Plain language -
Tufte (data-ink ratio) - Williams, Style: Lessons in Clarity and Grace - Knowles (andragogy) -
Sweller (cognitive load).
