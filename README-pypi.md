# renderfact

A lightweight, governed docs-as-code render framework: one full-candor source, projected per
audience/clearance/disclosure profile, rendered to styled DOCX and diagrams, with hidden
provenance, deterministic QA gates, dual-mode LLM steps (harness or copy-paste), a template
importer that derives a house-style profile from a branded DOCX, and a localhost HTTP API with a
thin reference UI.

The wheel installs the pure-Python layers (projection engine, style post-processor, provenance round-trip,
step contracts, API), but the full toolchain (the DOCX pipeline scripts and pinned render
engines) is currently supported from a source checkout only:

    git clone https://github.com/Wombat164/renderfact
    cd renderfact
    pip install -e .[dev]

Documentation, roadmap, and the decision record live in the repository.

Licence: MIT.
