"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import styles from "@/app/page.module.css";

export type SiteNavStory = { title: string; href: string };
export type SiteNavLink = { label: string; onSelect: () => void };

type Props = {
  stories: SiteNavStory[];
  links: SiteNavLink[];
  onOpenCaseStudies: () => void;
};

/**
 * Site navigation dock.
 *
 * Wide screens show the entries inline, where "Case studies" opens the browsing
 * overlay. Narrow screens collapse everything behind a hamburger sized to match
 * the map controls, listing the stories directly so a reader reaches one in a
 * single tap rather than through an overlay.
 */
export default function SiteNav({ stories, links, onOpenCaseStudies }: Props) {
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
    <div className={styles.sourcesLinkDock} ref={dockRef}>
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
        <button
          type="button"
          className={`${styles.searchMetaLink} ${styles.navCaseStudies}`}
          onClick={onOpenCaseStudies}
        >
          Case studies
        </button>

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
          <button
            key={link.label}
            type="button"
            className={styles.searchMetaLink}
            onClick={() => {
              close();
              link.onSelect();
            }}
          >
            {link.label}
          </button>
        ))}
      </div>
    </div>
  );
}
