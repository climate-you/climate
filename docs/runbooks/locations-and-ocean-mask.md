# Runbook: Locations and Ocean Mask

This runbook builds the location lookup artifacts consumed by API location services.

What you are building:

- a canonical location table for search and selection
- a fast text index and nearest-neighbor structure for resolver endpoints
- an ocean mask + ocean-name mapping so sea coordinates can still resolve to readable place labels
- a country raster mask so nearest-location lookups are constrained to the clicked country before falling back to unconstrained search
- a country name map so coordinates in countries with no populated places (e.g. Antarctica) still resolve to a readable country label

Where it is used:

- `GET /locations/autocomplete`
- `GET /locations/resolve`
- `GET /locations/nearest`
- panel/location enrichment in backend services (including sea/ocean naming)

## Input Data Sources

- GeoNames city dumps (for place names, coordinates, population metadata): <https://download.geonames.org/export/dump/>
- GeoNames schema/readme: <https://download.geonames.org/export/dump/readme.txt>
- Natural Earth marine polygons (for ocean-name rasterization): <https://www.naturalearthdata.com/>
- Natural Earth download mirror commonly used by the script: <https://naciscdn.org/naturalearth/10m/physical/ne_10m_geography_marine_polys.zip>
- Natural Earth 50m country polygons (for country-mask rasterization): <https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip>

## Environment Setup (Recommended)

Conda (Anaconda or Miniconda) is recommended for reproducible local runs.

```bash
conda create -n <your-env-name> python=3.11
conda activate <your-env-name>
export PYTHONPATH="$(pwd)"
```

You can install Python dependencies manually outside Conda, but this is not recommended.

## Build locations index and KD-tree

```bash
python scripts/build/build_locations.py --source cities500 --write-index --write-kdtree --write-country-mask --write-country-names
```

`build_locations.py` builds four different location artifacts from different inputs:

- `locations.csv` + `locations.kdtree.pkl`: city-only (GeoNames populated places), used by nearest-location logic.
- `locations.index.csv`: city + marine names (Natural Earth marine polygons by default), used by autocomplete/resolve.
- `country_mask.npz` + `country_codes.json`: country raster mask (Natural Earth 50m country polygons), used by country-constrained nearest-location lookup.
- `country_names.json`: country code → name map (from GeoNames `countryInfo.txt`), used by nearest-location lookup as a label fallback for countries with no populated places.

By default, when `--write-index` is enabled, marine polygons are read from Natural Earth and merged into the index with synthetic stable IDs. You can override the marine source with:

- `--marine-input` (local GeoJSON/Shapefile/zip)
- `--marine-source`
- `--marine-cache-dir`
- `--marine-name-field`

By default, when `--write-country-mask` is enabled, country polygons are downloaded from Natural Earth (50m). You can override with:

- `--country-input` (local GeoJSON/Shapefile/zip)
- `--country-mask-deg` (grid resolution in degrees, default `0.1`)
- `--country-cache-dir`
- `--country-code-field`

Primary outputs:

- `data/locations/locations.csv` (canonical city dataset consumed by nearest-location backend services)
- `data/locations/locations.index.csv` (normalized search index used for autocomplete/resolve; includes city + marine names)
- `data/locations/locations.kdtree.pkl` (spatial nearest-neighbor index used by nearest-location lookups)
- `data/locations/country_mask.npz` (raster mask mapping grid cells to country ids, used by country-constrained nearest-location lookup)
- `data/locations/country_codes.json` (mapping of country ids to ISO 3166-1 alpha-2 codes)
- `data/locations/country_names.json` (mapping of ISO 3166-1 alpha-2 codes to country names, used as a label fallback for countries with no populated places)

## Build ocean mask assets

```bash
python scripts/build/build_ocean_mask.py
```

Primary outputs:

- `data/locations/ocean_mask.npz` (grid mask used to identify oceanic coordinates)
- `data/locations/ocean_names.json` (mapping used by `PlaceResolver` to return readable sea/ocean names)

## Notes

- Re-run this runbook when location source data is updated.
- Backend location endpoints rely on these files at runtime.
