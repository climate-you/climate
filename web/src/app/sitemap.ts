import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/siteConfig";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    {
      url: `${SITE_URL}/`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 1,
    },
    {
      url: `${SITE_URL}/about`,
      lastModified: now,
      changeFrequency: "monthly",
      priority: 0.6,
    },
    {
      url: `${SITE_URL}/sources`,
      lastModified: now,
      changeFrequency: "monthly",
      priority: 0.6,
    },
    {
      url: `${SITE_URL}/stories/june-2026-heatwave`,
      // Dated to the story's data cutoff: the page is finished, so a fresh
      // lastModified on every build would only teach crawlers to distrust it.
      lastModified: new Date("2026-07-19"),
      changeFrequency: "yearly",
      priority: 0.8,
    },
  ];
}
