# What this changes

<!-- One or two sentences: the problem and the shape of the fix. Link the issue if one exists. -->

## Checklist

- [ ] Tests land with the change (programmatic fixtures, no committed binaries; see CONTRIBUTING.md)
- [ ] `pytest -q` green locally
- [ ] The generic core stays domain-neutral: no organisation-, locale-, or consumer-specific
      content in code, comments, or example config (`scripts/generic_gate.py` passes)
- [ ] Docs updated where behaviour changed (README usage block, docs/ROADMAP.md status notes)
- [ ] Honest scoping: anything intentionally NOT done is stated in the PR description, not left
      to be discovered
