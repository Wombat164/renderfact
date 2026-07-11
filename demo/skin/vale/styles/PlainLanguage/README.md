# PlainLanguage (issue #76)

Reader-facing plain-language/KISS quality is a distinct concern from AiTells:
AiTells flags *authorial tells* (does this read like an AI wrote it), this
style flags *comprehension load* (will a plain reader follow it), whatever
wrote the prose. Both are deterministic, no-LLM checks; both sit underneath
an LLM tone/register review rather than replacing one.

## Rules

- **SentenceLength** (`existence`, `scope: sentence`, warning): flags a
  sentence over a word-count threshold (English default: 30+ words) and
  suggests a split at a coordinating conjunction or a semicolon. The
  threshold is language-tunable: edit the repeat count in the rule's regex
  token to retune for a house style or another language's natural sentence
  length.
- **NominalisationDensity** (`occurrence`, `scope: paragraph`, warning):
  flags a paragraph carrying more than a threshold count (default: 4) of
  English noun-suffix words (`-tion`, `-ance`, `-ment`), suggesting a
  verb-first rewrite. Suffix-only matching cannot distinguish a true
  nominalisation ("reach a decision") from an ordinary noun sharing the
  ending ("moment"); that judgment call is left to the human or LLM pass
  this check sits underneath, deliberately (issue #76 asks for a simple
  suffix heuristic, not a lexical model).

Both rules are `level: warning`: informational and non-blocking (they never
fail `render gate --stages vale` on their own), matching `GoldenRules.Hedges`
rather than `GoldenRules.ThroatClearing`: these are heuristic and
tunable, not a clear-cut defect.

## What is not here: repeated-phrase-across-sections

Issue #76's third check (the same multi-word comparator/transition phrase
appearing near-verbatim 3+ times across a document) is **not** implemented as
a Vale rule. Vale's rule types (`existence`, `substitution`, `occurrence`,
`repetition`, `consistency`, `conditional`, `spelling`, `capitalization`,
`sequence`) all match against a pattern or token list fixed at authoring
time; `occurrence` can count how often a *known* pattern recurs within a
scope (which is what NominalisationDensity uses), but nothing in the DSL
can discover an *a priori unknown* phrase and then count its recurrence
across the whole document. That is a real DSL limitation, not a modeling
choice: this check needs the document text itself as the source of the
patterns to look for, which Vale rules cannot express. It ships instead as
a small deterministic Python check, `docstyle.plain_language`, wired into
`render gate` as the `plainlang` stage. See that module's docstring and
`gates/run_gates.py` for the implementation.

## Suffix-set extension (Dutch, future)

The nominalisation suffix set lives on a single `token:` line in
`NominalisationDensity.yml` precisely so a Dutch sibling
(`NominalisationDensityNl.yml`, suffixes `-atie`, `-heid`, `-ing`-as-noun)
can be added later without touching the English rule, following the same
opt-in pattern `BeNl` already uses for BE-NL lexical checks (wired only into
`vale.be-nl.ini`, not the base `vale.ini`). Not built in this pass: issue
#76 explicitly treats the Dutch suffix set as a stretch goal and English-first
as sufficient for v1.
