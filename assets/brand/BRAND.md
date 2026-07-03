# renderfact brand

## The mark: the gated document

A rounded document tile carrying three text lines. The middle line is the brand story: its first
half is disclosed (a true knockout hole), the remainder is veiled (a ghost pill at 42% white over
the tile). One source, governed disclosure: the mark encodes what the tool does.

- `renderfact-mark.svg` is the MASTER. Every other asset embeds its geometry as a transformed
  copy; if the mark changes, regenerate the lockups and the social card from it (they do not sync
  themselves).
- The line knockouts are TRUE holes (`fill-rule="evenodd"`), so the disclosed lines adopt the
  surface behind the mark: white on light pages, dark on dark pages. That adaptivity is intended.
  The ghost pill is the one element that never changes.
- Always embed these files as `<img>` references, never inline raw SVG markup (sanitizers strip
  accessibility attributes from inline SVG; as an image reference the file stays intact).

## Palette

| Token | Value | Use |
|---|---|---|
| accent | `#4F46E5` | tile, "fact" wordmark (light) |
| ink | `#334155` | "render" wordmark (light) |
| ghost | `#FFFFFF` at 0.42 | the veiled line fragment |
| ink-dark | `#E2E8F0` | "render" wordmark (dark variant) |
| accent-dark | `#818CF8` | "fact" wordmark (dark variant) |

## Wordmark

Inter SemiBold (600), lowercase, two-tone split at "render|fact" (the double meaning: render +
artefact, render factory). Shipped lockups have the text OUTLINED to paths so they render
identically everywhere; the live-text master for re-typesetting is `src/lockup-src.svg` (outline
with the brand-cycle tooling and Inter 600 static TTF after any text change; paths do not reflow).

## Files

- `renderfact-mark.svg`: master mark, favicon-safe (verified legible at 24px)
- `renderfact-lockup.svg`: mark + wordmark, light surfaces
- `renderfact-lockup-dark.svg`: dark-surface variant (wordmark colors swapped, tile unchanged)
- `renderfact-social.png`: 1280x640 GitHub social preview (dark lockup on an indigo radial)
- `src/lockup-src.svg`: live-text lockup master (not for direct embedding)

## History

2026-07-04: initial system. Two candidates were reviewed (design + technical panels); the
projection-cascade variant (echo tiles behind the document) was rejected: its alpha-stroke echoes
smear at favicon size, and it crowded the gated line. The cascade idea remains available for
large-format hero art if ever needed, rebuilt with flat solid-tint fills.
