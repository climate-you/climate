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
              NOAA ERDDAP (project):{" "}
              <a
                href="https://coastwatch.noaa.gov/erddap/index.html"
                target="_blank"
                rel="noreferrer"
              >
                CoastWatch ERDDAP index
              </a>
            </li>
            <li>
              NOAA ERDDAP (SST):{" "}
              <a
                href="https://coastwatch.pfeg.noaa.gov/erddap/info/ncdcOisst21Agg_LonPM180/index.html"
                target="_blank"
                rel="noreferrer"
              >
                OISST v2.1 daily SST dataset
              </a>
            </li>
            <li>
              NOAA ERDDAP (DHW):{" "}
              <a
                href="https://coastwatch.noaa.gov/erddap/info/noaacrwdhwDaily/index.html"
                target="_blank"
                rel="noreferrer"
              >
                Coral Reef Watch DHW daily dataset
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
              OpenFreeMap © OpenMapTiles Data from OpenStreetMap (
              <a
                href="https://openfreemap.org/"
                target="_blank"
                rel="noreferrer"
              >
                OpenFreeMap
              </a>{" "}
              |{" "}
              <a
                href="https://openmaptiles.org/"
                target="_blank"
                rel="noreferrer"
              >
                OpenMapTiles
              </a>{" "}
              |{" "}
              <a
                href="https://www.openstreetmap.org/copyright"
                target="_blank"
                rel="noreferrer"
              >
                OpenStreetMap
              </a>
              ).
            </li>
            <li>
              ERA5 data are provided via the Copernicus Climate Data Store
              (C3S), operated by ECMWF on behalf of the European Union, and are
              distributed under the Creative Commons Attribution 4.0
              International license (CC BY 4.0). Attribution to Copernicus
              Climate Change Service (C3S) and ECMWF is required, together with
              the relevant dataset citation.
            </li>
            <li>
              ECMWF website materials are subject to ECMWF terms of use; unless
              otherwise stated on specific pages or assets, ECMWF web content is
              generally available under CC BY 4.0 with appropriate attribution.
            </li>
            <li>
              CMIP6 data accessed through ESGF are governed by the CMIP6 Terms
              of Use and associated data licenses. CMIP6 model output is
              generally distributed under CC BY 4.0, with model-specific
              licensing details defined in the CMIP6 controlled vocabularies,
              and users should include the required CMIP6/ESGF acknowledgements
              and citations.
            </li>
            <li>
              NOAA OISST (via NOAA ERDDAP) is publicly available for use and
              redistribution at no cost. NOAA data are provided without
              warranty and are not intended for legal use; users should include
              NOAA attribution and follow dataset-specific notices.
            </li>
          </ul>
        </section>

        <br />
      </div>
    </section>
  );
}
