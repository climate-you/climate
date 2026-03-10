# Climate Project Pipeline Diagrams

These diagrams use Mermaid and render natively on GitHub.

## Graph 1: Registry Relationships

```mermaid
flowchart LR
  D["<b>Dataset</b><br/><sub>registry/datasets.json</sub>"]
  M["<b>Metric</b><br/><sub>registry/metrics.json</sub>"]
  DM["<b>Derived metric</b><br/><sub>metric derives_from / transform</sub>"]
  MP["<b>Map</b><br/><sub>registry/maps.json</sub>"]
  L["<b>Layer</b><br/><sub>registry/layers.json</sub>"]
  P["<b>Panel</b><br/><sub>registry/panels.json</sub>"]
  G["<b>Panel graph reference</b><br/><sub>graphs[*].series[*].metric</sub>"]
  SM["<b>Score map reference</b><br/><sub>maps.type = score</sub>"]

  D --> M
  M --> G
  G --> P

  M --> DM
  DM --> G
  DM --> MP

  M --> MP
  MP --> L

  MP --> SM
  SM --> P

  classDef registry fill:#E8F1FF,stroke:#2F5EA8,color:#10233F,stroke-width:1.5px;
  classDef ref fill:#FFF3E8,stroke:#C46A1A,color:#4C2506,stroke-width:1.5px;
  classDef derived fill:#EAF9EE,stroke:#2D8A45,color:#12361C,stroke-width:1.5px;

  class D,M,MP,L,P registry;
  class G,SM ref;
  class DM derived;

  linkStyle default stroke:#9FB3C8,stroke-width:2px;
```

## Graph 2: Data Artifacts Flow (Build to Runtime)

```mermaid
flowchart LR
  C["<b>data/cache/*</b><br/>(ERDDAP/CDS downloads, intermediates)"]
  PKGS["<b>Packager script</b><br/>scripts/build/packager.py"]
  T["<b>Series tiles</b><br/>data/releases/<release>/series/*"]
  MAPS["<b>Map assets</b><br/>data/releases/<release>/maps/*"]
  REG["<b>Release registry snapshots</b><br/>data/releases/<release>/registry/*.json"]
  PKG["<b>Packaged release</b><br/>data/releases/<release>/"]
  API["<b>FastAPI backend</b><br/>(uvicorn)"]
  WEB["<b>Next.js web app</b>"]

  C --> PKGS
  PKGS --> T
  PKGS --> MAPS
  PKGS --> REG

  T --> PKG
  MAPS --> PKG
  REG --> PKG

  PKG --> API
  API -->|"/api/v/{release}/*"| WEB
  API -->|"/assets/v/{release}/{asset_path}"| WEB

  classDef data fill:#EAF5FF,stroke:#2E6DA4,color:#0E2C47,stroke-width:1.5px;
  classDef app fill:#FFF1E6,stroke:#C7702B,color:#4A2308,stroke-width:1.5px;

  class C,T,MAPS,REG,PKG data;
  class PKGS,API,WEB app;

  linkStyle default stroke:#9FB3C8,stroke-width:2px;
```

## Graph 3: API Endpoints and Data Sources (Simplified)

```mermaid
%%{init: {'theme':'base','themeCSS': '.cluster-label text {font-size: 30px !important; font-weight: 800 !important; fill: #E5EDF7 !important;}'} }%%
flowchart TB
  subgraph E["<b>Endpoints</b>"]
    E1["GET /api/v/{release}/release"]
    E2["GET /api/v/{release}/panel"]
    E3["GET /api/v/{release}/location/graphs"]
    E4["GET /api/v/{release}/locations/autocomplete"]
    E5["GET /api/v/{release}/locations/resolve"]
    E6["GET /api/v/{release}/locations/nearest"]
    E7["GET /assets/v/{release}/{asset_path}"]
  end

  subgraph A["<b>Application Services</b>"]
    R["<b>ReleaseResolver</b>"]
    PG["<b>Panel/Graph service</b>"]
    LS["<b>Location service</b>"]
    AS["<b>Asset service</b>"]
  end

  subgraph D["<b>Data + Cache</b>"]
    direction LR
    TS["<b>TileDataStore</b><br/>(series tiles + time axes)"]
    LI["<b>LocationIndex</b><br/>(locations.index.csv: city + marine names)"]
    PR["<b>PlaceResolver</b><br/>(locations.csv + locations.kdtree.pkl: city-only nearest)"]
    OC["<b>OceanClassifier</b><br/>(ocean_mask.npz + ocean_names.json)"]
    MAP["<b>Map assets</b><br/>data/releases/<release>/maps/*"]
    CA["<b>Cache</b><br/>(Redis or in-process TTL)"]
    TS ~~~ LI ~~~ PR ~~~ OC ~~~ MAP ~~~ CA
  end

  E1 --> R

  E2 --> PG
  E3 --> PG

  E4 --> LS
  E5 --> LS
  E6 --> LS

  E7 --> AS

  PG --> R
  LS --> R
  AS --> R

  A --> D

  classDef endpoint fill:#EAF2FF,stroke:#2C62B0,color:#102748,stroke-width:1.5px;
  classDef service fill:#FFF0E6,stroke:#C46F2B,color:#4A2308,stroke-width:1.5px;
  classDef data fill:#EAF8EE,stroke:#2F8B4A,color:#12351D,stroke-width:1.5px;

  class E1,E2,E3,E4,E5,E6,E7 endpoint;
  class R,PG,LS,AS service;
  class TS,LI,PR,OC,MAP,CA data;

  style E fill:#F3F8FF,stroke:#6D9EEB,stroke-width:1.5px;
  style A fill:#FFF7EF,stroke:#E3A36E,stroke-width:1.5px;
  style D fill:#F1FBF4,stroke:#83C596,stroke-width:1.5px;

  linkStyle default stroke:#9FB3C8,stroke-width:2px;
```

## Graph 4: Runtime Topology (Offline vs Online)

```mermaid
%%{init: {'theme':'base','themeCSS': '.cluster-label text {font-size: 30px !important; font-weight: 800 !important; fill: #E5EDF7 !important;}'} }%%
flowchart LR
  subgraph OFF["<b>Offline (build/precompute)</b>"]
    B1["scripts/build/build_locations.py"]
    B2["scripts/build/build_ocean_mask.py"]
    B3["scripts/build/build_reef_mask.py / build_dataset_mask.py / combine_masks.py"]
    B4["scripts/build/packager.py"]
    STORE["data/releases/* + data/locations/* + data/cache/*"]
  end

  subgraph ON["<b>Online (serving)</b>"]
    U["uvicorn climate_api.main:app"]
    RC["Redis (optional)"]
    N["Next.js web server<br/>(dev or prod)"]
    C["Browser client"]
  end

  B1 --> STORE
  B2 --> STORE
  B3 --> STORE
  B4 --> STORE

  STORE --> U
  RC <--> U
  U -->|"JSON APIs + map assets"| N
  N --> C

  classDef data fill:#EAF8EE,stroke:#2F8B4A,color:#12351D,stroke-width:1.5px;
  classDef app fill:#FFF0E6,stroke:#C46F2B,color:#4A2308,stroke-width:1.5px;

  class STORE,RC data;
  class B1,B2,B3,B4,U,N,C app;

  style OFF fill:#F3F8FF,stroke:#6D9EEB,stroke-width:1.5px;
  style ON fill:#FFF7EF,stroke:#E3A36E,stroke-width:1.5px;

  linkStyle default stroke:#9FB3C8,stroke-width:2px;
```
