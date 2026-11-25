import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/siteConfig";
import { STORIES, storyPath } from "@/content/stories";

// lastModified only where it is a real date. The globe, About and Sources have
// no edit date worth reporting, and a build timestamp would change on every
// deploy and teach crawlers to ignore the field everywhere.
export default function sitemap(): MetadataRoute.Sitemap {
  const storyDates = STORIES.map(
    (story) => new Date(story.updated ?? story.published),
  );
  const latestStory = new Date(
    Math.max(...storyDates.map((date) => date.getTime())),
  );
  return [
    {
      url: `${SITE_URL}/`,
      changeFrequency: "weekly",
      priority: 1,
    },
    {
      url: `${SITE_URL}/case-studies`,
      // The list changes when a story is added or updated.
      lastModified: latestStory,
      changeFrequency: "monthly",
      priority: 0.7,
    },
    {
      url: `${SITE_URL}/about`,
      changeFrequency: "monthly",
      priority: 0.6,
    },
    {
      url: `${SITE_URL}/sources`,
      changeFrequency: "monthly",
      priority: 0.6,
    },
    // Dated to the story's last real change: the pages are finished, so a fresh
    // lastModified on every build would only teach crawlers to distrust it.
    ...STORIES.map((story, index) => ({
      url: `${SITE_URL}${storyPath(story.slug)}`,
      lastModified: storyDates[index],
      changeFrequency: "yearly" as const,
      priority: 0.8,
    })),
  ];
}
