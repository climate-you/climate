// Published case studies, newest first. The case-studies list and the sitemap
// are built from this, and each entry reads its title and dates from the
// story's own meta.ts. A new story adds its meta.ts and one entry here.
import * as june2026 from "./june-2026-heatwave/meta";
import * as summer2026 from "./summer-2026-heat-and-drought/meta";

export type StoryEntry = {
  /** Route segment under /stories, also the stem of its /story images. */
  slug: string;
  title: string;
  /** ISO date first published; the date the case-studies list shows. */
  published: string;
  /** ISO date of the last change to the story's figures, if any. */
  updated?: string;
};

export const STORIES: StoryEntry[] = [
  {
    slug: "summer-2026-heat-and-drought",
    title: summer2026.TITLE,
    published: summer2026.PUBLISHED,
    updated: summer2026.UPDATED,
  },
  {
    slug: "june-2026-heatwave",
    title: june2026.TITLE,
    published: june2026.PUBLISHED,
  },
];

export const storyPath = (slug: string) => `/stories/${slug}`;
export const storyThumbnail = (slug: string) => `/story/${slug}-thumb.png`;
