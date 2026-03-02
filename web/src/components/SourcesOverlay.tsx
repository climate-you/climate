"use client";

import { useState } from "react";
import styles from "./SourcesOverlay.module.css";

type SourcesOverlayProps = {
  onClose: () => void;
};

export default function SourcesOverlay({ onClose }: SourcesOverlayProps) {
  const [activeTab, setActiveTab] = useState<"sources" | "licenses">("sources");

  return (
    <section
      className={styles.sourcesOverlay}
      role="dialog"
      aria-modal="true"
      aria-label="Sources and licenses"
    >
      <div className={styles.sourcesCard}>
        <div className={styles.sourcesHeader}>
          <div
            className={styles.sourcesTabs}
            role="tablist"
            aria-label="Sources tabs"
          >
            <button
              type="button"
              role="tab"
              id="sources-tab"
              aria-selected={activeTab === "sources"}
              aria-controls="sources-panel"
              className={`${styles.sourcesTab} ${
                activeTab === "sources" ? styles.sourcesTabActive : ""
              }`}
              onClick={() => setActiveTab("sources")}
            >
              Sources
            </button>
            <button
              type="button"
              role="tab"
              id="licenses-tab"
              aria-selected={activeTab === "licenses"}
              aria-controls="licenses-panel"
              className={`${styles.sourcesTab} ${
                activeTab === "licenses" ? styles.sourcesTabActive : ""
              }`}
              onClick={() => setActiveTab("licenses")}
            >
              Licenses/Copyrights
            </button>
          </div>
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

        {activeTab === "sources" ? (
          <div role="tabpanel" id="sources-panel" aria-labelledby="sources-tab">
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
              <h3 className={styles.sourcesSectionTitle}>
                Official References
              </h3>
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
                    The Guardian: How climate breakdown is putting the
                    world&apos;s food in peril
                  </a>
                </li>
                <li>
                  <a
                    href="https://www.theguardian.com/world/ng-interactive/2026/jan/13/mapped-how-the-world-is-losing-its-forests-to-wildfires"
                    target="_blank"
                    rel="noreferrer"
                  >
                    The Guardian: Mapped - how the world is losing its forests
                    to wildfires
                  </a>
                </li>
              </ul>
            </section>
          </div>
        ) : (
          <div
            role="tabpanel"
            id="licenses-panel"
            aria-labelledby="licenses-tab"
          >
            <section className={styles.sourcesSection}>
              <p className={styles.sourcesNotice}>
                Some published layers and metrics are derived products built
                from multiple upstream datasets. Original data providers and
                map/tile services used by this project are credited below.
              </p>
              <ul className={styles.sourcesList}>
                <li>
                  Basemap and labels: OpenFreeMap, based on OpenMapTiles data
                  and OpenStreetMap contributors (
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
                  Terrain hillshade source in the web map: Amazon Terrain Tiles
                  (Terrarium format) (
                  <a
                    href="https://registry.opendata.aws/terrain-tiles/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    elevation-tiles-prod
                  </a>
                  ).
                </li>
                <li>
                  ERA5 daily statistics, accessed via the Copernicus Climate
                  Data Store (C3S), implemented by ECMWF (
                  <a
                    href="https://cds.climate.copernicus.eu/datasets/derived-era5-single-levels-daily-statistics"
                    target="_blank"
                    rel="noreferrer"
                  >
                    ERA5 daily statistics
                  </a>
                  ).
                </li>
                <li>
                  CMIP6 historical projections, accessed via CDS projections
                  dataset (
                  <a
                    href="https://cds.climate.copernicus.eu/datasets/projections-cmip6"
                    target="_blank"
                    rel="noreferrer"
                  >
                    projections-cmip6
                  </a>
                  ), with usage subject to CMIP6 terms (
                  <a
                    href="https://cds.climate.copernicus.eu/licences/cmip6-wps"
                    target="_blank"
                    rel="noreferrer"
                  >
                    CMIP6 terms of use
                  </a>
                  ).
                </li>
                <li>
                  NOAA ERDDAP datasets: OISST v2.1 sea-surface temperature and
                  NOAA Coral Reef Watch Degree Heating Week (DHW) (
                  <a
                    href="https://coastwatch.pfeg.noaa.gov/erddap/info/ncdcOisst21Agg_LonPM180/index.html"
                    target="_blank"
                    rel="noreferrer"
                  >
                    OISST v2.1
                  </a>{" "}
                  |{" "}
                  <a
                    href="https://coastwatch.noaa.gov/erddap/info/noaacrwdhwDaily/index.html"
                    target="_blank"
                    rel="noreferrer"
                  >
                    CRW DHW
                  </a>
                  ).
                </li>
                <li>
                  Reef-domain preprocessing uses reef polygon sources from UNEP
                  World Conservation Monitoring Centre (WCMC) and Natural Earth
                  (
                  <a
                    href="https://wcmc.io/WCMC_008"
                    target="_blank"
                    rel="noreferrer"
                  >
                    UNEP-WCMC coral reefs
                  </a>{" "}
                  |{" "}
                  <a
                    href="https://www.naturalearthdata.com/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Natural Earth
                  </a>
                  ).
                </li>
                <li>
                  Ocean/land mask preprocessing also uses Natural Earth
                  geography datasets (
                  <a
                    href="https://www.naturalearthdata.com/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Natural Earth marine and land layers
                  </a>
                  ).
                </li>
                <li>
                  Location search preprocessing uses GeoNames (
                  <a
                    href="https://www.geonames.org/"
                    target="_blank"
                    rel="noreferrer"
                  >
                    GeoNames
                  </a>
                  ).
                </li>
              </ul>
              <p className={styles.sourcesNotice}>
                <a href="/THIRD_PARTY_NOTICES.md" target="_blank" rel="noreferrer">
                  Open-source notices
                </a>
              </p>
            </section>
          </div>
        )}

        <br />
      </div>
    </section>
  );
}
