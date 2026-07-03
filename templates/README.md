# Template pack

Five genre skeletons for the projection engine's usual outputs: a decision brief, an
external briefing, two pitch lengths, and a purchase request. Each carries real guidance
prose per section, bracketed placeholders, and worked fenced-div blocks so the profile
vocabulary (clearance, releasable, and disclosure posture) is visible in place, not just
described.

## Instantiation workflow

1. Copy a template out of `templates/` to where your working source lives; do not edit
   the template in place.
2. Replace every `[bracketed placeholder]` with real content, and delete any guidance
   sentence once you no longer need the reminder.
3. Render the copy. The first render engages provenance automatically: a stable identity
   is generated once and written back into your copy's frontmatter, then reused on every
   render after that.
4. Never add a `renderfact_uid` to a template file itself. A uid on a template is an
   identity-copy hazard: every file instantiated from it would inherit the same lineage,
   and the `uids` gate stage exists to catch exactly that mistake.

## Render commands

Plain governed DOCX, full-candor:

```sh
python render.py docx templates/<name>.md
```

One governed projection per audience profile, using the ladders and profiles this pack's
blocks were written against:

```sh
python render.py project templates/<name>.md --profiles projection/profiles-example.yaml --profile partner-brief
```

Add `--all` in place of `--profile <name>` to produce every configured profile in one
pass.

## Templates in this pack

| Template                       | Genre                                                              |
|-------------------------------------|-------------------------------------------------------------------------|
| `executive-summary.md`              | One-page decision brief: ask, situation, options, recommendation, risks |
| `external-party-brief.md`           | Briefing an external organisation: context, shareable scope, ask, offer |
| `pitch-1pager.md`                   | Single-page pitch: problem, answer, value, cost and effort, one ask     |
| `pitch-5pager.md`                   | Long-form pitch memo: situation, complication, options, recommendation  |
| `purchase-request.md`               | Purchase request dossier: need, requirements, cost estimate, approvals  |
