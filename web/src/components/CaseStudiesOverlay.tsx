"use client";

import { useEffect } from "react";
import styles from "./CaseStudiesOverlay.module.css";

export type CaseStudy = {
  title: string;
  href: string;
  thumbnail: string;
  meta?: string;
};

type Props = {
  studies: CaseStudy[];
  onClose: () => void;
};

export default function CaseStudiesOverlay({ studies, onClose }: Props) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <section
      className={styles.overlay}
      role="dialog"
      aria-modal="true"
      aria-label="Case studies"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={styles.card}>
        <div className={styles.header}>
          <h2 className={styles.title}>Case Studies</h2>
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="Close case studies"
          >
            ×
          </button>
        </div>

        <p className={styles.intro}>
          Deep dives into individual climate events, built from the same data
          that powers the interactive globe. Each one maps where an event sat,
          how it moved, and how far it ran from the seasonal norm.
        </p>

        <div className={styles.grid}>
          {studies.map((study) => (
            // A full document load rather than a client-side transition, so the
            // visit registers an analytics pageview.
            <a key={study.href} className={styles.story} href={study.href}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                className={styles.thumb}
                src={study.thumbnail}
                alt=""
                loading="lazy"
              />
              <span className={styles.storyTitle}>{study.title}</span>
              {study.meta ? (
                <span className={styles.storyMeta}>{study.meta}</span>
              ) : null}
            </a>
          ))}

          <div className={styles.soon} aria-hidden="true">
            <div className={styles.soonThumb}>More to come</div>
            <span className={styles.storyTitle}>&nbsp;</span>
          </div>
        </div>
      </div>
    </section>
  );
}
