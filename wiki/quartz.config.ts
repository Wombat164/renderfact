// quartz.config.ts -- Quartz v4 configuration for the renderfact documentation site.
//
// Verified against the official Quartz v4 docs + the canonical v4 branch (June 2026):
//   - Configuration reference:  https://quartz.jzhao.xyz/configuration
//   - Plugin catalog:           https://quartz.jzhao.xyz/plugins
//   - Canonical v4 config.ts:   https://github.com/jackyzha0/quartz/blob/v4/quartz.config.ts
//   - GitHub Pages hosting:     https://github.com/jackyzha0/quartz/blob/v4/docs/hosting.md
//
// NOTE (version): the live docs site (quartz.jzhao.xyz) has moved on to Quartz v5, whose config is
// YAML (quartz.config.yaml) with `source/enabled/order` plugin entries. This file targets v4, whose
// config is this TypeScript module (`Plugin.X()` from `./quartz/plugins`). The schema below mirrors
// the v4-branch default config verbatim, changing only pageTitle, baseUrl, analytics, and the footer.
//
// The Quartz framework itself is NOT vendored in this repo (see wiki/README.md). At build time the v4
// framework is fetched and this file + quartz.layout.ts + content/ are overlaid into it. The relative
// imports below ("./quartz/cfg", "./quartz/plugins") resolve once this file sits at the Quartz root.

import { QuartzConfig } from "./quartz/cfg"
import * as Plugin from "./quartz/plugins"

/**
 * Quartz 4 Configuration -- renderfact
 */
const config: QuartzConfig = {
  configuration: {
    pageTitle: "renderfact",
    enableSPA: true,
    enablePopovers: true,
    // No third-party analytics by default (privacy-friendly for an OSS docs site).
    // To enable: analytics: { provider: "plausible" } | { provider: "google", tagId: "..." } | etc.
    analytics: null,
    locale: "en-US",
    // PLACEHOLDER -- replace with your GitHub Pages URL (host/path, no protocol, no trailing slash).
    // Required for sitemap + RSS absolute URLs and for correct cross-page links once deployed.
    baseUrl: "wombat164.github.io/renderfact",
    ignorePatterns: ["private", "templates", ".obsidian"],
    defaultDateType: "modified",   // Quartz v4 requires this (created | modified | published)
    theme: {
      fontOrigin: "googleFonts",
      cdnCaching: true,
      typography: {
        header: "Schibsted Grotesk",
        body: "Source Sans Pro",
        code: "IBM Plex Mono",
      },
      colors: {
        lightMode: {
          light: "#faf8f8",
          lightgray: "#e5e5e5",
          gray: "#b8b8b8",
          darkgray: "#4e4e4e",
          dark: "#2b2b2b",
          secondary: "#284b63",
          tertiary: "#84a59d",
          highlight: "rgba(143, 159, 169, 0.15)",
          textHighlight: "#fff23688",
        },
        darkMode: {
          light: "#161618",
          lightgray: "#393639",
          gray: "#646464",
          darkgray: "#d4d4d4",
          dark: "#ebebec",
          secondary: "#7b97aa",
          tertiary: "#84a59d",
          highlight: "rgba(143, 159, 169, 0.15)",
          textHighlight: "#b3aa0288",
        },
      },
    },
  },
  plugins: {
    transformers: [
      Plugin.FrontMatter(),
      Plugin.CreatedModifiedDate({
        priority: ["frontmatter", "git", "filesystem"],
      }),
      // Syntax highlighting (build-time, via rehype/Shiki).
      Plugin.SyntaxHighlighting({
        theme: {
          light: "github-light",
          dark: "github-dark",
        },
        keepBackground: false,
      }),
      // Obsidian-flavored markdown: preserves [[wikilinks]], ![[embeds]], > [!callout]s, tags.
      Plugin.ObsidianFlavoredMarkdown({ enableInHtmlEmbed: false }),
      Plugin.GitHubFlavoredMarkdown(),
      Plugin.TableOfContents(),
      // Resolve [[wikilinks]] by shortest unique path (matches Obsidian default).
      Plugin.CrawlLinks({ markdownLinkResolution: "shortest" }),
      Plugin.Description(),
      Plugin.Latex({ renderEngine: "katex" }),
    ],
    filters: [Plugin.RemoveDrafts()],
    emitters: [
      Plugin.AliasRedirects(),
      Plugin.ComponentResources(),
      Plugin.ContentPage(),
      Plugin.FolderPage(),
      Plugin.TagPage(),
      Plugin.ContentIndex({
        enableSiteMap: true,
        enableRSS: true,
      }),
      Plugin.Assets(),
      Plugin.Static(),
      Plugin.Favicon(),
      Plugin.NotFoundPage(),
      Plugin.CustomOgImages(),
    ],
  },
}

export default config
