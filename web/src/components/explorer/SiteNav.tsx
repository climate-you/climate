"use client";

import {
  type MouseEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import styles from "@/app/page.module.css";

export type SiteNavStory = { title: string; href: string };
export type SiteNavLink = { label: string; href: string; onSelect: () => void };

type Props = {
  stories: SiteNavStory[];
  links: SiteNavLink[];
  onOpenCaseStudies: () => void;
  /** Hidden and inert while the cold open plays; still in the markup. */
  concealed?: boolean;
};

/** A plain click opens the overlay in place; anything else (a new tab, a
 *  middle click) follows the link to the page that opens it. */
function openInPlace(event: MouseEvent<HTMLAnchorElement>): boolean {
  if (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return false;
  }
  event.preventDefault();
  return true;
}

/**
 * Site navigation dock.
 *
 * Wide screens show the entries inline, where "Case studies" opens the browsing
 * overlay. Narrow screens collapse everything behind a hamburger sized to match
 * the map controls, listing the stories directly so a reader reaches one in a
 * single tap rather than through an overlay.
 *
 * Every entry is a real link to its own page, and the dock is rendered even
 * while the cold open hides it, so crawlers that never dismiss the intro still
 * find the rest of the site from the home page.
 */
export default function SiteNav({
  stories,
  links,
  onOpenCaseStudies,
  concealed = false,
}: Props) {
  const [open, setOpen] = useState(false);
  const dockRef = useRef<HTMLDivElement | null>(null);
  const menuId = useId();

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!dockRef.current?.contains(event.target as Node)) close();
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open, close]);

  return (
    <nav
      aria-label="Site"
      className={`${styles.sourcesLinkDock} ${concealed ? styles.navConcealed : ""}`}
      ref={dockRef}
      inert={concealed}
    >
      <button
        type="button"
        className={styles.navToggle}
        aria-expanded={open}
        aria-controls={menuId}
        aria-label={open ? "Close menu" : "Open menu"}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={styles.navToggleBars} aria-hidden="true" />
      </button>
      <div
        id={menuId}
        className={`${styles.navItems} ${open ? styles.navItemsOpen : ""}`}
      >
        <a
          className={`${styles.searchMetaLink} ${styles.navCaseStudies}`}
          href="/case-studies"
          onClick={(event) => {
            if (openInPlace(event)) onOpenCaseStudies();
          }}
        >
          Case studies
        </a>

        <span className={styles.navSectionLabel}>Case studies</span>
        {stories.map((story) => (
          // A full document load rather than a client-side transition: it
          // registers an analytics pageview for the story.
          <a
            key={story.href}
            className={`${styles.searchMetaLink} ${styles.navStoryLink}`}
            href={story.href}
            onClick={close}
          >
            {story.title}
          </a>
        ))}
        <span className={styles.navDivider} />

        {links.map((link) => (
          <a
            key={link.label}
            className={styles.searchMetaLink}
            href={link.href}
            onClick={(event) => {
              if (!openInPlace(event)) return;
              close();
              link.onSelect();
            }}
          >
            {link.label}
          </a>
        ))}
      </div>
    </nav>
  );
}
