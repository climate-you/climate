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
- `locations.index.csv`: cities plus area entries — seas, lakes and countries — used by autocomplete/resolve.
- `country_mask.npz` + `country_codes.json`: country raster mask (Natural Earth 50m country polygons), used by country-constrained nearest-location lookup.
- `country_names.json`: country code → name map (from GeoNames `countryInfo.txt`), used by nearest-location lookup as a label fallback for countries with no populated places.

### Area entries in the index

When `--write-index` is enabled, three polygon sources are merged into the index alongside the cities, each with synthetic stable IDs drawn from its own id block:

| Kind | Source | Pseudo country code |
| --- | --- | --- |
| `marine` | Natural Earth 10m marine polygons | `OC` |
| `lake` | Natural Earth 50m lakes | `LK` |
| `country` | Natural Earth 50m admin_0 polygons, named from GeoNames `countryInfo.txt` | the real ISO code |

Every area entry carries a `bbox` column (`west,south,east,north`) that the map fits when the entry is selected; `east` runs past 180 for a box straddling the antimeridian. Cities have an empty `bbox` and `kind=city`.

A country's point is Natural Earth's hand-placed `LABEL_X`/`LABEL_Y`, and its box covers only its largest landmass, so France frames the mainland rather than stretching to French Guiana.

You can override the polygon sources with:

- `--marine-input` (local GeoJSON/Shapefile/zip), `--marine-source`, `--marine-cache-dir`, `--marine-name-field`
- `--lake-input` (local GeoJSON/Shapefile/zip), `--lake-source`, `--lake-cache-dir`, `--lake-name-field`
- `--country-input` (local GeoJSON/Shapefile/zip), `--country-cache-dir`, `--country-code-field`

By default, when `--write-country-mask` is enabled, country polygons are downloaded from Natural Earth (50m) — the same file the country index entries use. You can override with:

- `--country-input` (local GeoJSON/Shapefile/zip)
- `--country-mask-deg` (grid resolution in degrees, default `0.05`)
- `--country-cache-dir`
- `--country-code-field`

Primary outputs:

- `data/locations/locations.csv` (canonical city dataset consumed by nearest-location backend services)
- `data/locations/locations.index.csv` (normalized search index used for autocomplete/resolve; includes cities plus sea, lake and country entries)
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
- `data/locations/ocean_overlay_mask.npz` (seas lying *inside* another sea, same ids as the ocean mask; build-time only)

The ocean mask is a partition: each cell belongs to exactly one sea, the last one burned, so a sea wholly inside another is erased by it. The only real case is the Great Barrier Reef, which the Coral Sea covers entirely. Features whose Natural Earth `featurecla` is `reef` are therefore also burned into the overlay mask, where they keep their full extent. The partition itself is unchanged, so point lookups inside the reef still say "Coral Sea"; the overlay is read only by the regional aggregates and the region outlines below, which count a reef cell towards both seas.

The existing mask was built at 0.05°; pass `--deg 0.05` to reproduce it (the script's default is 0.25°).

## Build region outlines

```bash
python scripts/build/build_region_shapes.py
```

Polygonises the masks above (country, ocean and ocean overlay) into one outline per country and sea, which the explorer draws over a region selected from search. It reads the masks, so run it **after** `build_locations.py --write-country-mask` and `build_ocean_mask.py` whenever either mask is rebuilt. `scripts/precompute_regional_aggregates.py` reads the same masks, so rerun it too (see `dataset-cache-and-packaging.md`) and publish a release: a region only gets a panel when the release has its aggregate.

The outline is the mask itself, cell edge for cell edge, not the Natural Earth polygon it was rasterised from, so it shows exactly the area the region's average is computed over. A region with no mask cells (the Drake Passage, which Natural Earth carries as a label with no extent) gets no outline, just as it gets no average.

Primary output:

- `data/locations/region_shapes.json` (region id → GeoJSON `MultiPolygon`; ~3.7 MB, ~540 KB gzipped, served one region at a time by `GET /api/v/{release}/regions/shape`)

The file is optional at runtime: without it the API logs a warning and region panels still work, with no outline drawn. Override its location with `REGION_SHAPES_JSON`.

## Deploying

The deploy script does not ship `data/locations/`. After rebuilding any of these artifacts, copy the changed files to the server's `data/locations/` by hand and restart the API — in particular `locations.index.csv` (it carries the `region_id` column) and `region_shapes.json`. The overlay mask is only read at build time and need not be copied.

## Notes

- Re-run this runbook when location source data is updated.
- Backend location endpoints rely on these files at runtime.
