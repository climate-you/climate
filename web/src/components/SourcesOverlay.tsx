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
              Copernicus Climate Data Store (CDS):{" "}
              <a
                href="https://cds.climate.copernicus.eu/"
                target="_blank"
                rel="noreferrer"
              >
                CDS portal
              </a>{" "}
              |{" "}
              <a
                href="https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels"
                target="_blank"
                rel="noreferrer"
              >
                ERA5 on CDS
              </a>
            </li>
            <li>
              ERA5 documentation:{" "}
              <a
                href="https://www.ecmwf.int/en/forecasts/dataset/ecmwf-reanalysis-v5"
                target="_blank"
                rel="noreferrer"
              >
                ECMWF overview
              </a>
            </li>
            <li>
              Earth System Grid Federation (ESGF):{" "}
              <a
                href="https://esgf.llnl.gov/"
                target="_blank"
                rel="noreferrer"
              >
                ESGF portal
              </a>{" "}
              |{" "}
              <a
                href="https://esgf-node.llnl.gov/projects/cmip6/"
                target="_blank"
                rel="noreferrer"
              >
                CMIP6 archive
              </a>
            </li>
            <li>
              NOAA ERDDAP:{" "}
              <a
                href="https://coastwatch.pfeg.noaa.gov/erddap/index.html"
                target="_blank"
                rel="noreferrer"
              >
                ERDDAP project
              </a>{" "}
              |{" "}
              <a
                href="https://coastwatch.pfeg.noaa.gov/erddap/info/ncdcOisst21Agg_LonPM180/index.html"
                target="_blank"
                rel="noreferrer"
              >
                OISST v2.1 daily SST dataset
              </a>
            </li>
          </ul>
        </section>

        <section className={styles.sourcesSection}>
          <h3 className={styles.sourcesSectionTitle}>Official References</h3>
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
          </ul>
        </section>

        <section className={styles.sourcesSection}>
          <h3 className={styles.sourcesSectionTitle}>Further Reading</h3>
          <ul className={styles.sourcesList}>
            <li>
              <a
                href="https://www.theguardian.com/environment/ng-interactive/2026/feb/19/extreme-heat-lab-enduring-the-climate-of-the-future"
                target="_blank"
                rel="noreferrer"
              >
                The Guardian: Extreme Heat Lab
              </a>
            </li>
            <li>
              <a
                href="https://www.theguardian.com/environment/ng-interactive/2025/dec/18/how-climate-breakdown-is-putting-the-worlds-food-in-peril-in-maps-and-charts"
                target="_blank"
                rel="noreferrer"
              >
                The Guardian: How climate breakdown is putting the world&apos;s food in peril
              </a>
            </li>
            <li>
              <a
                href="https://www.theguardian.com/world/ng-interactive/2026/jan/13/mapped-how-the-world-is-losing-its-forests-to-wildfires"
                target="_blank"
                rel="noreferrer"
              >
                The Guardian: Mapped - how the world is losing its forests to wildfires
              </a>
            </li>
          </ul>
        </section>

        <section className={styles.sourcesSection}>
          <h3 className={styles.sourcesSectionTitle}>Licenses/Copyrights</h3>
          <ul className={styles.sourcesList}>
            <li>
              Data and visual references remain the property of their respective
              providers and publishers.
            </li>
            <li>
              Reuse is subject to each source&apos;s own license, terms of use,
              and attribution requirements.
            </li>
            <li>
              Please refer to the original source pages linked above for current
              licensing and copyright details.
            </li>
          </ul>
        </section>

        <br />
      </div>
    </section>
  );
}
