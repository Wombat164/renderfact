---
title: renderfact
---

# renderfact

A governed **docs-as-code render framework**: one full-candor markdown/YAML source becomes many
governed, audience-specific projections -- styled DOCX, accessible + archival PDF, diagrams, decks,
posters -- each carrying hidden provenance and passing deterministic QA gates.

**Generic core, private skin.** The engine is domain-agnostic and OSS; an organisation's house style,
terminology, and disclosure rules live in a private "skin" it consumes. The demo ships a fictional rail
operator's procurement dossier so you can taste the whole pipeline with zero real-world coupling.

## Start here

- **[Getting started](tutorials/getting-started.md)** -- install, then render the bundled demo.
- **[How-to recipes](how-to/index.md)** -- render a document, gate it, round-trip a diagram, capture a
  decision.
- **[Reference](reference/index.md)** -- the `render` command surface, environment variables, the
  provenance schema.
- **[Explanation](explanation/index.md)** -- the architecture doctrines: the D8 harness-optional
  contract, the D16 fuzzy-gate, projection-aware provenance, and the editable-diagram round-trip.

## What makes it different

- **Round-trip, not one-way.** A rendered DOCX or an editable diagram (draw.io / Visio) can be
  hand-edited and re-ingested: the mechanical diff flows back to the source, and the human intent flows
  to a decision log.
- **Harness-optional AI.** Every LLM-touching step degrades across three modes -- your own assistant
  (harness), a human pasting into any chat LLM (copy-paste), or, opt-in, a configured model -- behind
  one contract, so no step is locked to a vendor.
- **Deterministic first, LLM only past a gate.** Steps run a deterministic result first and escalate to
  a model only when a confidence gate is missed. Most invocations cost zero tokens.
- **Provenance + QA built in.** Hidden source identity in every editable artifact (stripped for
  external projections), and a fail-closed gate chain (style, links, PDF/A conformance).

> Repository: [github.com/Wombat164/renderfact](https://github.com/Wombat164/renderfact) (MIT).
