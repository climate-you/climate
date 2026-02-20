"use client";

import styles from "./SourcesOverlay.module.css";

type SourcesOverlayProps = {
  onClose: () => void;
};

export default function SourcesOverlay({ onClose }: SourcesOverlayProps) {
  return (
    <section className={styles.sourcesOverlay} role="dialog" aria-modal="true">
      <div className={styles.sourcesCard}>
        <div className={styles.sourcesHeader}>
          <h2 className={styles.sourcesTitle}>Sources</h2>
          <button
            type="button"
            className={styles.sourcesClose}
            aria-label="Close sources"
            onClick={onClose}
          >
            <svg
              className={styles.sourcesCloseIcon}
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path d="M6 6L18 18" />
              <path d="M18 6L6 18" />
            </svg>
          </button>
        </div>

        <section className={styles.sourcesSection}>
          <h3 className={styles.sourcesSectionTitle}>Data Sources</h3>
          <ul className={styles.sourcesList}>
            <li>
              <a
                href="https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels"
                target="_blank"
                rel="noreferrer"
              >
                Copernicus Climate Data Store: ERA5 reanalysis
              </a>
            </li>
            <li>
              <a
                href="https://www.ecmwf.int/en/forecasts/dataset/ecmwf-reanalysis-v5"
                target="_blank"
                rel="noreferrer"
              >
                ECMWF: ERA5 overview and documentation
              </a>
            </li>
            <li>
              <a
                href="https://esgf-node.llnl.gov/projects/cmip6/"
                target="_blank"
                rel="noreferrer"
              >
                ESGF: CMIP6 climate model archive
              </a>
            </li>
          </ul>
        </section>

        <section className={styles.sourcesSection}>
          <h3 className={styles.sourcesSectionTitle}>More Information</h3>
          <ul className={styles.sourcesList}>
            <li>
              <a
                href="https://www.ipcc.ch/report/ar6/syr/"
                target="_blank"
                rel="noreferrer"
              >
                IPCC AR6 Synthesis Report
              </a>
            </li>
            <li>
              <a
                href="https://climate.nasa.gov/"
                target="_blank"
                rel="noreferrer"
              >
                NASA Climate: evidence and indicators
              </a>
            </li>
            <li>
              <a
                href="https://ourworldindata.org/climate-change"
                target="_blank"
                rel="noreferrer"
              >
                Our World in Data: climate change
              </a>
            </li>
            <li>
              <a
                href="https://www.theguardian.com/environment/ng-interactive/2026/feb/19/extreme-heat-lab-enduring-the-climate-of-the-future"
                target="_blank"
                rel="noreferrer"
              >
                The Guardian: Extreme Heat Lab
              </a>
            </li>
          </ul>
        </section>
      </div>
    </section>
  );
}
