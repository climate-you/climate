# Runbook: Reef-Domain Mask (DHW)

Use this runbook to rebuild the Coral Reef DHW domain mask (`global_0p05`).

What you are building:

- a reef-aware analysis domain mask for DHW workflows
- source reef masks (UNEP + Natural Earth), constrained to ocean and data-available cells

Where it is used:

- during DHW metric computation, to filter grid cells to reef-relevant regions
- as a publishable layer that can be visualized directly in the web application
- as an explicit domain boundary for downstream packaging/validation work
- as the source for a coarse `0.25°` sparse-risk mask used by API panel bbox optimization in mixed-grid click handling

## Input Data Sources

- UNEP-WCMC coral reef polygons (script source option `unep_wcmc`): <https://wcmc.io/WCMC_008>
- Natural Earth reef polygons (script source option `natural_earth`): <https://www.naturalearthdata.com/>
- Natural Earth reefs download mirror: <https://naciscdn.org/naturalearth/10m/physical/ne_10m_reefs.zip>
- NOAA Coral Reef Watch context (DHW product family): <https://coralreefwatch.noaa.gov/>
- ERDDAP source used for DHW availability mask sampling: <https://coastwatch.pfeg.noaa.gov/erddap/index.html>

## Environment Setup (Recommended)

Conda (Anaconda or Miniconda) is recommended for reproducible local runs.

```bash
conda create -n <your-env-name> python=3.11
conda activate <your-env-name>
export PYTHONPATH="$(pwd)"
```

You can install Python dependencies manually outside Conda, but this is not recommended.

## 1) Build source reef masks (UNEP + Natural Earth)

```bash
python scripts/build/build_reef_mask.py \
  --source unep_wcmc \
  --grid-id global_0p05 \
  --all-touched \
  --output-npz data/masks/reef_unep_all_touched_global_0p05_mask.npz

python scripts/build/build_reef_mask.py \
  --source natural_earth \
  --grid-id global_0p05 \
  --all-touched \
  --output-npz data/masks/reef_ne_all_touched_global_0p05_mask.npz
```

Notes:

- Sources are cached under `data/cache/geojson/` with source-specific filenames:
  - `reef_polygons_unep_wcmc_source.zip`
  - `reef_polygons_natural_earth_source.zip`
- UNEP source ZIP contains multiple layers; script auto-selects the polygon layer.

Primary outputs:

- `data/masks/reef_unep_all_touched_global_0p05_mask.npz` (UNEP reef footprint rasterized on target grid)
- `data/masks/reef_ne_all_touched_global_0p05_mask.npz` (Natural Earth reef footprint rasterized on target grid)

## 2) Build DHW availability masks and union

Example sampled dates:

```bash
python scripts/build/build_dataset_mask.py --dataset-id crw_dhw_daily --start-date 1985-06-15 --end-date 1985-06-15 --output data/masks/dhw_available_1985_06_15_global_0p05_mask.npz
python scripts/build/build_dataset_mask.py --dataset-id crw_dhw_daily --start-date 2000-06-15 --end-date 2000-06-15 --output data/masks/dhw_available_2000_06_15_global_0p05_mask.npz
python scripts/build/build_dataset_mask.py --dataset-id crw_dhw_daily --start-date 2010-06-15 --end-date 2010-06-15 --output data/masks/dhw_available_2010_06_15_global_0p05_mask.npz
python scripts/build/build_dataset_mask.py --dataset-id crw_dhw_daily --start-date 2020-06-15 --end-date 2020-06-15 --output data/masks/dhw_available_2020_06_15_global_0p05_mask.npz
python scripts/build/build_dataset_mask.py --dataset-id crw_dhw_daily --start-date 2025-06-15 --end-date 2025-06-15 --output data/masks/dhw_available_2025_06_15_global_0p05_mask.npz
```

Combine with OR:

```bash
python scripts/build/combine_masks.py \
  --mode or \
  --input data/masks/dhw_available_1985_06_15_global_0p05_mask.npz \
  --input data/masks/dhw_available_2000_06_15_global_0p05_mask.npz \
  --input data/masks/dhw_available_2010_06_15_global_0p05_mask.npz \
  --input data/masks/dhw_available_2020_06_15_global_0p05_mask.npz \
  --input data/masks/dhw_available_2025_06_15_global_0p05_mask.npz \
  --output data/masks/dhw_available_global_0p05_mask.npz
```

Primary outputs:

- `data/masks/dhw_available_YYYY_MM_DD_global_0p05_mask.npz` (per-date DHW availability masks sampled from source dataset coverage)
- `data/masks/dhw_available_global_0p05_mask.npz` (union availability mask used to keep only cells with DHW data support)

## 3) Build water mask and final reef-domain mask

```bash
python scripts/build/build_water_mask.py \
  --grid-id global_0p05 \
  --output-npz data/masks/water_global_0p05_mask.npz

python scripts/build/build_reef_domain_mask.py \
  --reef-mask data/masks/reef_unep_all_touched_global_0p05_mask.npz \
  --reef-mask data/masks/reef_ne_all_touched_global_0p05_mask.npz \
  --water-mask data/masks/water_global_0p05_mask.npz \
  --dhw-mask data/masks/dhw_available_global_0p05_mask.npz \
  --dilate-iterations 1 \
  --output data/masks/crw_dhw_daily_global_0p05_mask.npz
```

Primary outputs:

- `data/masks/water_global_0p05_mask.npz` (water/sea mask used to constrain dilation to ocean cells)
- `data/masks/crw_dhw_daily_global_0p05_mask.npz` (final reef-domain mask used by DHW computation and visualization layers)

Final formula:

```text
reef_seed = UNEP_all_touched OR NE_all_touched
dil = reef_seed OR (dilate(reef_seed) AND water_mask)
mask = dil AND dhw_available_union
```

## 4) Build sparse-risk mask for mixed-grid panel click optimization

Build a coarse (`0.25°`) binary sparse-risk mask from the final DHW domain mask:

```bash
python scripts/build/build_sparse_risk_mask.py \
  --source-mask data/masks/crw_dhw_daily_global_0p05_mask.npz \
  --target-deg 0.25 \
  --output data/masks/sparse_risk_global_0p25_mask.npz
```

To make it available to a specific release at runtime:

```bash
mkdir -p data/releases/<release>/aux
cp data/masks/sparse_risk_global_0p25_mask.npz data/releases/<release>/aux/sparse_risk_global_0p25_mask.npz
```

Runtime note:

- API panel responses use this mask to choose `panel_valid_bbox` resolution (`global_0p25` vs `global_0p05`).
