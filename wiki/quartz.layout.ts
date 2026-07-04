// quartz.layout.ts -- Quartz v4 layout for the renderfact documentation site.
//
// Verified against the official Quartz v4 docs + the canonical v4 branch (June 2026):
//   - Layout reference:        https://quartz.jzhao.xyz/layout
//   - Canonical v4 layout.ts:  https://github.com/jackyzha0/quartz/blob/v4/quartz.layout.ts
//
// v4 REQUIRES this file: the framework imports `sharedPageComponents`, `defaultContentPageLayout`,
// and `defaultListPageLayout` from it. This is where the Obsidian-style features are wired in:
// the Graph view (right), Backlinks (right), the Explorer file tree (left), the TableOfContents
// (right), Search, Darkmode, and ReaderMode. It mirrors the v4 default layout, changing only the
// Footer links to point at this project.

import { PageLayout, SharedLayout } from "./quartz/cfg"
import * as Component from "./quartz/components"

// components shared across all pages
export const sharedPageComponents: SharedLayout = {
  head: Component.Head(),
  header: [],
  afterBody: [],
  footer: Component.Footer({
    links: {
      // PLACEHOLDER -- replace with the public renderfact repo URL once published.
      GitHub: "https://github.com/Wombat164/renderfact",
      "Built with Quartz": "https://quartz.jzhao.xyz/",
    },
  }),
}

// components for pages that display a single page (e.g. a single note)
export const defaultContentPageLayout: PageLayout = {
  beforeBody: [
    Component.ConditionalRender({
      component: Component.Breadcrumbs(),
      condition: (page) => page.fileData.slug !== "index",
    }),
    Component.ArticleTitle(),
    Component.ContentMeta(),
    Component.TagList(),
  ],
  left: [
    Component.PageTitle(),
    Component.MobileOnly(Component.Spacer()),
    Component.Flex({
      components: [
        {
          Component: Component.Search(),
          grow: true,
        },
        { Component: Component.Darkmode() },
        { Component: Component.ReaderMode() },
      ],
    }),
    Component.Explorer(),
  ],
  right: [
    Component.Graph(),
    Component.DesktopOnly(Component.TableOfContents()),
    Component.Backlinks(),
  ],
}

// components for pages that display lists of pages (e.g. tags or folders)
export const defaultListPageLayout: PageLayout = {
  beforeBody: [Component.Breadcrumbs(), Component.ArticleTitle(), Component.ContentMeta()],
  left: [
    Component.PageTitle(),
    Component.MobileOnly(Component.Spacer()),
    Component.Flex({
      components: [
        {
          Component: Component.Search(),
          grow: true,
        },
        { Component: Component.Darkmode() },
      ],
    }),
    Component.Explorer(),
  ],
  right: [],
}
