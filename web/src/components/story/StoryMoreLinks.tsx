import { STORIES, storyPath } from "@/content/stories";
import { SITE_NAME } from "@/lib/siteIdentity";
import styles from "./story.module.css";

/**
 * Closing links from a story to the rest of the site: the other case studies,
 * then the globe and the site's own pages. Plain links, so a crawler landing
 * on a story reaches everything else from it.
 */
export default function StoryMoreLinks({ slug }: { slug: string }) {
  const others = STORIES.filter((story) => story.slug !== slug);
  return (
    <nav className={styles.moreLinks} aria-label={`More from ${SITE_NAME}`}>
      {others.length > 0 ? (
        <>
          <p className={styles.moreLinksHeading}>More case studies</p>
          <ul className={styles.moreLinksStories}>
            {others.map((story) => (
              <li key={story.slug}>
                <a href={storyPath(story.slug)}>{story.title}</a>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {/* Full document loads, like the story's back link: the globe starts
          cleanly instead of resuming a torn-down WebGL context. */}
      <p className={styles.moreLinksSite}>
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
        <a href="/">Explore the globe</a>
        <span aria-hidden="true"> · </span>
        <a href="/case-studies">All case studies</a>
        <span aria-hidden="true"> · </span>
        <a href="/about">About {SITE_NAME}</a>
        <span aria-hidden="true"> · </span>
        <a href="/sources">Sources</a>
      </p>
    </nav>
  );
}
