# Writing golden rules: BE-NL (Flemish) formal register

Companion to `writing-golden-rules.md`, one layer down. That file governs STRUCTURE:
what survives onto the page, at every level from document to sentence, regardless of
language. This file governs REGISTER: what "formal" sounds like in Belgian Dutch
specifically, for renderfact output whose target language is BE-NL. Compose both: a
BE-NL formal letter should be plain-language and BLUF per the generic doc, dressed in
the address/salutation/grammar conventions below.

Distilled from public, citable Belgian-Dutch language-advisory sources (Team
Taaladvies, the Flemish government's own language service; Dutch-linguistics
comparative references); sources at the end. Like its companion, this is DEMO SKIN,
not renderfact core: a starting point for a BE-NL consumer skin, not a mandate.

## The core insight: formal address, plain construction

Flemish formal writing is formal in ADDRESS (the u-form, "Geachte", "Hoogachtend")
but is explicitly NOT meant to be formal in CONSTRUCTION. The Flemish government's own
language office promotes B1 "klare taal" (plain language) as the golden standard for
business and government communication -- short sentences, common words, one idea per
sentence. Do not read "formal register" as license for bureaucratic, Latinate, or
subordinate-clause-heavy prose: the two goals (formal address, plain construction)
are not in tension, they are the actual target.

## BE-NL vs NL-NL: real register differences, not errors

These are genuine national-variant differences. When the target is BE-NL, do not
"correct" them toward NL-NL forms -- that is the mistake, not the fix.

1. **Modal verbs in formal register**: NL-NL formal writing requires "u kunt / u zult
   / u wilt"; the short forms "kan / zal / wil" read as informal in the Netherlands.
   BE-NL uses "u kan / u zal / u wil" in formal contexts too -- the short forms are
   not a register downgrade in Belgium.
2. **Conditional/subjunctive opener**: BE-NL formal prose favours "Moest ik ziek
   worden, ..." (a "moest"-led subjunctive-style conditional). NL-NL favours "Mocht ik
   ziek worden, ..." or an "als"-construction. Keep whichever the source variant is;
   do not cross-correct.
3. **"te" vs "in" before place names**: BE-NL formal/official register prefers
   "te Leuven"; NL-NL almost always uses "in Leuven" and treats "te" as dated or
   overly formal. In BE-NL letterheads, datelines, and official prose, "te [plaats]"
   is the expected form, not an archaism to strip out.
4. **Surname capitalisation**: Belgian convention capitalises the first letter of a
   surname regardless of a leading initial or tussenvoegsel; Dutch (NL-NL) convention
   differs on tussenvoegsel lowercasing. Check this explicitly when a document
   crosses the border, it is a real typographic convention difference, not a typo.

## Business-letter layout markers (Belgium)

- Salutation/closing pairing is load-bearing, not decorative: the impersonal
  "Geachte heer/mevrouw," (always followed by a comma) pairs with the fully formal
  close "Hoogachtend,". A named recipient, "Geachte heer/mevrouw [Naam],", pairs with
  the more modern default close "Met vriendelijke groeten,". Do not mix an impersonal
  opener with the casual close or vice versa.
- Standard layout markers: "Betreft:" (subject line), "t.a.v." (attention of),
  "Bijlage(n):" (enclosures), dates written with lowercase month names.
- After the closing formula: a comma, a blank line for the signature, then the typed
  name (this document's own cover-letter template already follows this shape).

## Tone-register traps to catch in review

- Do not import Netherlands-Dutch informality markers ("je/jij" address, "Groetjes"
  sign-offs) into a BE-NL formal document.
- Do not import French formal-register constructions literally when translating
  BE-FR into BE-NL ("veuillez agréer" has no clean word-for-word BE-NL equivalent;
  reach for the actual BE-NL closing convention above instead of a calque).
- Watch for NL-NL forms creeping in from translation-memory or LLM training data bias
  (most Dutch-language training data skews NL-NL): "u kunt/zult", "mocht", "in
  [Belgian city]" are the highest-frequency tells.

## Tie-in: renderfact's translation pipeline

The vault-side trilingual pipeline (`.claude/trilingual/`) already encodes rule #1 as
"Belgian variants: BE-NL (not NL-NL), BE-FR (not FR-FR)" -- correct, but a single
blunt label with no register substance behind it. This file is the substance: point
the pipeline's Layer-4 LLM review step (`review_prompt.txt`) and any `terms.json`
BE-NL entries at the four register rules above, not just the two-word "use BE-NL"
instruction. A mechanical slice of rules 1-3 (modal-verb forms, "moest" vs "mocht",
"te" vs "in") is existence-checkable the same way `GoldenRules/Hedges.yml` catches
intensifiers; see `vale/styles/BeNl/NlNlForms.yml` and the opt-in
`vale/vale.be-nl.ini` config in this skin for a first cut. Layout markers and the
salutation/closing pairing need human review (or a structural Vale `existence` rule
per opener/closer, TODO if this proves worth mechanising further).

## What's still open

- The Vale `BeNl` style only catches lexical tells (rules 1-3); it cannot check that
  a salutation and its closing actually pair correctly, that needs a `sequence`-style
  check spanning the whole document, not shipped here.
- No FR-BE equivalent register doc exists yet in this skin; the vault pipeline treats
  "BE-FR (not FR-FR)" the same way it treated BE-NL before this file, as a label
  without substance. Same gap, not filled in this pass.

## Sources

Team Taaladvies (Vlaamse overheid, Departement Kanselarij en Buitenlandse Zaken),
taaladvies.net "Opmaak van een zakelijke brief in Belgie" -
[taaladvies.net](https://taaladvies.net/opmaak-van-een-zakelijke-brief-in-belgie-algemeen/)
- Dutch++ (FU Berlin), "Belgie en Nederland: grammaticale verschillen" -
[userblogs.fu-berlin.de](https://userblogs.fu-berlin.de/dutch/nederlands-taalgebied/belgie/taalvarieteit-belgie/belgie-en-nederland-grammaticale-verschillen/)
- Frankwatching, "Is Vlaamse verfijning in zakelijke e-mail nodig?" -
[frankwatching.com](https://www.frankwatching.com/archive/2023/09/28/vlaams-nederlands-zakelijke-e-mail-verschillen/)
- Onze Taal / Vlaamse overheid B1-niveau guidance (klare taal as the business-
communication standard) - [onzetaal.nl](https://onzetaal.nl/taalloket/b1-niveau)
- Beaks.nl / cvster.nl, Dutch-language salutation/closing convention references -
[beaks.nl](https://www.beaks.nl/geachte-heer-mevrouw/)
