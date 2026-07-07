# AiTells (vendored from tbhb/vale-ai-tells)

These rules detect linguistic patterns commonly associated with AI-generated
prose: overused vocabulary (`delve`, `tapestry`, `leverage`, `seamless`),
em-dash punctuation, contrastive-negation cadence ("it's not just X, it's Y"),
opening cliches ("In today's fast-paced world"), sycophantic openers
("Great question!"), and defensive hedging ("It's important to note").

## Source and license

Vendored, unmodified, from the `ai-tells` style of:

- Upstream: https://github.com/tbhb/vale-ai-tells
- Version: v1.21.0
- Author: Tony Burns
- License: MIT (see `LICENSE` in this folder)

Only the prose style (`styles/ai-tells/`) is vendored. The upstream
`ai-tells-commits` and `ai-tells-experimental` styles, and the upstream
`Packages =` / `vale sync` installation path, are deliberately not used: this
skin vendors raw `.yml` style files (the same pattern as `GoldenRules` and
`BeNl`) so the config stays self-contained and offline-buildable.

The folder is named `AiTells` (PascalCase) to match this skin's style-folder
convention; the rule filenames are unchanged from upstream, so a rule referenced
upstream as `ai-tells.OverusedVocabulary` is `AiTells.OverusedVocabulary` here.

## Updating

Re-copy `styles/ai-tells/*.yml` from a newer upstream tag and bump the version
above. Do not hand-edit the rule files; local tuning (rule level, disable)
belongs in the consuming `vale.ini`, not in the vendored rules.
