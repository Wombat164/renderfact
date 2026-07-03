# renderfact documentation

The reading order depends on what you came for:

| You want to... | Read |
|---|---|
| Understand the system's shape (modules, data flow, trust boundaries) | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Know why things are the way they are (numbered decision record, with rationale) | [DECISIONS.md](DECISIONS.md) |
| See what is planned, in what order, and what gets adopted vs imitated vs built | [ROADMAP.md](ROADMAP.md) |
| Try the framework in five minutes | [../demo/](../demo/) (start with its README) |
| Contribute (test discipline, generic-core rule) | [../CONTRIBUTING.md](../CONTRIBUTING.md) |

## Design records

Deeper design work behind specific features, kept because the reasoning is reusable:

| Document | What it settles |
|---|---|
| [2026-07-03-d8-copy-paste-design-spike.md](2026-07-03-d8-copy-paste-design-spike.md) | The dual-mode LLM step design: one schema whether a harness runs the step or a human copy-pastes it |
| [2026-07-03-editor-design-spike.md](2026-07-03-editor-design-spike.md) | The structured source editor (three-pane markdown, two-pane spreadsheet): designed, not yet built |

## Prior-art research passes

Verification-disciplined research (claims checked against primary sources; refuted claims kept
on record) that feeds the roadmap's adopt/imitate/build tags:

| Document | Topic |
|---|---|
| [prior-art-diagram-roundtrip.md](prior-art-diagram-roundtrip.md) | Editable-diagram round-trip (drawio/vsdx): the loop is open ground; format and library verdicts |
| [prior-art-template-analysis.md](prior-art-template-analysis.md) | Deriving a house-style profile from an existing branded DOCX |
| [prior-art-paperbanana-prompt-patterns.md](prior-art-paperbanana-prompt-patterns.md) | Prompt-scaffolding patterns for vision-review and future generative steps |

## Conventions

- Docs state what is BUILT vs designed vs roadmap explicitly; a claim without a shipped mode
  behind it belongs in ROADMAP.md, not here.
- Decision entries are append-only history: they get corrected by dated addenda, never rewritten.
