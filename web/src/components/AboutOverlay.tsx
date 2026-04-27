"use client";

import { useEffect } from "react";
import {
  defaultTemperatureUnitForLocale,
  observedWarmingString,
} from "@/lib/temperatureUnit";
import styles from "./AboutOverlay.module.css";

type AboutOverlayProps = {
  onClose: () => void;
  appVersion?: string | null;
  assetsRelease?: string | null;
};

export default function AboutOverlay({
  onClose,
  appVersion = null,
  assetsRelease = null,
}: AboutOverlayProps) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const defaultUnit = defaultTemperatureUnitForLocale();
  const observedWarmingText = `${observedWarmingString(defaultUnit)}`;
  const parisTargetText = defaultUnit === "F" ? "3.6°F" : "2°C";
  const appVersionText = appVersion ?? "unknown";
  const assetsReleaseText = assetsRelease ?? "latest";
  const issueBody = `\n\n---\nApp version: ${appVersionText}\nAssets release: ${assetsReleaseText}`;
  const issueUrl = `https://github.com/climate-you/climate/issues/new?${new URLSearchParams(
    {
      body: issueBody,
    },
  ).toString()}`;

  return (
    <section
      className={styles.aboutOverlay}
      role="dialog"
      aria-modal="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={styles.aboutCard}>
        <div className={styles.aboutHeader}>
          <h2 className={styles.aboutTitle}>About</h2>
          <button
            type="button"
            className={styles.aboutClose}
            aria-label="Close about"
            onClick={onClose}
          >
            <svg
              className={styles.aboutCloseIcon}
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path d="M6 6L18 18" />
              <path d="M18 6L6 18" />
            </svg>
          </button>
        </div>

        <section className={styles.aboutSection}>
          <p className={`${styles.aboutText} ${styles.aboutParagraph}`}>
            The IPCC&apos;s 2023 Synthesis Report indicates that global mean
            temperature has already increased by approximately{" "}
            <b>{observedWarmingText}</b>, while the Paris Agreement sets the
            objective of limiting warming to well below <b>{parisTargetText}</b>
            . For us, these global numbers felt abstract, so this project asks a
            simple question: how do these changes translate at the local level?
          </p>
          <p className={`${styles.aboutText} ${styles.aboutParagraph}`}>
            We focus only on temperature change, over land and sea, to show how
            warming is already affecting people everywhere. It is now
            unequivocally established that this warming is caused by{" "}
            <b>human activities</b>. The numbers we have seen while working on
            this project are alarming and underscore the urgency for governments
            to take decisive action. This project does not cover the full range
            of downstream impacts such as wildfires, sea-level rise and coastal
            flooding, droughts and water stress, crop losses and food
            insecurity, biodiversity loss, health impacts, displacement and
            migration, and conflict risks.
          </p>
          <p className={styles.aboutText}>
            The code for this website is available on{" "}
            <a
              href="https://github.com/climate-you/climate"
              target="_blank"
              rel="noreferrer"
            >
              github.com/climate-you/climate
            </a>{" "}
            under the{" "}
            <a
              href="https://github.com/climate-you/climate/blob/main/LICENSE"
              target="_blank"
              rel="noreferrer"
            >
              AGPL 3.0 license
            </a>
            .
          </p>
          <p className={styles.aboutText}>
            Background art by{" "}
            <a
              href="https://www.instagram.com/about_dunja_jankovic/"
              target="_blank"
              rel="noreferrer"
            >
              Dunja Janković
            </a>
            .
          </p>
          <h3 className={styles.aboutSectionTitle}>Authors</h3>
          <p className={`${styles.aboutText} ${styles.aboutParagraph}`}>
            <b>Benoit Leveau</b> and <b>Fanny Chaleon</b>, two software
            engineers concerned about global warming and committed to making
            climate information more accessible.
          </p>
          <p className={styles.aboutText}>
            <a
              href="https://www.linkedin.com/in/benoitleveau/"
              target="_blank"
              rel="noreferrer"
            >
              linkedin.com/in/benoitleveau
            </a>
            <br />
            <a
              href="https://www.linkedin.com/in/fannychaleon/"
              target="_blank"
              rel="noreferrer"
            >
              linkedin.com/in/fannychaleon
            </a>
          </p>
          <div className={styles.aboutFooter}>
            <div className={styles.aboutActions}>
              <a
                className={styles.aboutActionButton}
                href="mailto:info@climate.you"
              >
                <span
                  className={`${styles.aboutActionPngIcon} ${styles.aboutMailIcon}`}
                  aria-hidden="true"
                />
                Contact us
              </a>
              <a
                className={`${styles.aboutActionButton} ${styles.aboutKofiButton}`}
                href="https://ko-fi.com/G2G31UWBDU"
                target="_blank"
                rel="noreferrer"
              >
                <span className={styles.aboutKofiIcon} aria-hidden="true" />
                Buy us a coffee
              </a>
              <a
                className={styles.aboutActionButton}
                href={issueUrl}
                target="_blank"
                rel="noreferrer"
              >
                <span
                  className={`${styles.aboutActionPngIcon} ${styles.aboutGithubIcon}`}
                  aria-hidden="true"
                />
                Report a bug
              </a>
            </div>
            <p className={`${styles.aboutText} ${styles.aboutVersion}`}>
              <span>App version: {appVersionText}</span>
              <span>Assets release: {assetsReleaseText}</span>
            </p>
          </div>
        </section>
      </div>
    </section>
  );
}
