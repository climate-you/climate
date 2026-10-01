import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/siteConfig";
import { STORIES, storyPath } from "@/content/stories";

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
    // Dated to the story's last real change: the pages are finished, so a fresh
    // lastModified on every build would only teach crawlers to distrust it.
    ...STORIES.map((story) => ({
      url: `${SITE_URL}${storyPath(story.slug)}`,
      lastModified: new Date(story.updated ?? story.published),
      changeFrequency: "yearly" as const,
      priority: 0.8,
    })),
  ];
}
