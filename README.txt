Data attribution: “Data: ERA5 climate reanalysis via Open-Meteo archive API”

Usage:

1. Contents of ~/.cdsapirc:
url: https://cds.climate.copernicus.eu/api
key: XXXXXX

2. Environment:
$ export EARTHKIT_CACHE_HOME=/Users/benoit.leveau/Documents/Programming/Climate/ek-cache
# export PYTHONPATH=`pwd`
$ conda activate climate

3. Generate city list:
# Fill extra_locations.txt to include additional cities (tweak source if needed)
$ python scripts/make_city_list.py --source cities500 --extra-file locations/extra_locations.txt --top-per-country=3

4. Precompute cities climatology:
# Tweak favorites.txt
$ python scripts/precompute_story_cities.py --only-favorites --limit 10 [--dry-run]

5. Precompute global series and maps:
# For anomaly/world graphs:
$ python scripts/make_global_series.py
$ python scripts/make_latest_anomaly_map_assets.py
# For 2d map:
$ python scripts/make_warming_map_cds.py --grid-deg 0.5
# For 3d maps:
$ python scripts/make_warming_texture.py \
  --nc data/world/warming_map_1979-1988_to_2016-2025_grid0p25.nc \
  --out data/world/warming_texture_1979-1988_to_2016-2025_grid0p25_4096x2048 \
  --size 4096x2048
$ python scripts/make_borders_overlay.py \ 
  --out data/world/borders_8192x4096.png \
  --size 8192x4096 \
  --scale 10m \
  --coast-lw 2.2 --borders-lw 1.4
# For MonteCarlo:
$ python scripts/download_era5_daily_t2m_cds.py --grid-deg 1.0 --timeout 300
$ python scripts/make_montecarlo_experiment.py --grid-deg 1.0 --experiment-id 1 --seed 12345 --n-samples 50000


5. Run web page:

# Next web - http://localhost:3000/
$ cd web; npm run dev:fast
# Next web (LAN / phone testing):
$ cd web; npm run dev:fast:lan

# Streamlit - http://localhost:8501/
$ streamlit run app/story_demo.py

# Warming Globe - http://localhost:8000/drafts/warming_globe_demo/
# python -m http.server 8000 

# Hero Wire Globe - http://localhost:8000/
# cd drafts/three_wire_globe_clouds; python -m http.server 8000 

---

6. Run v2 server  
# Install & Run Redis

# API data prep (locations + ocean labels):
$ python scripts/make_locations.py --source cities500 --write-index --write-kdtree
$ python scripts/build_ocean_mask.py
# Optional tuning:
# Keep city labels when click is very close to a city, even if ocean mask says water:
# $ export OCEAN_CITY_OVERRIDE_MAX_KM=2
# $ export OCEAN_OFF_CITY_MAX_KM=80

# Run FastAPI thin client:
$ export REDIS_URL='redis://localhost:6379/0'
# Optional: preload all non-constant score maps into RAM at startup
# (avoids first-request disk I/O for score maps):
$ export SCORE_MAP_PRELOAD=1
# Optional: enable backend timing headers for /api/v/{release}/panel?profile=true
# Safe gate:
# - default is disabled
# - only local requests are allowed
# - disabled => HTTP 400, non-local => HTTP 403
$ export ENABLE_PROFILE_HEADERS=true
# FastAPI (LAN / phone testing):
$ ./scripts/dev_api_lan.sh
# Works without watchfiles installed:
$ uvicorn apps.api.climate_api.main:app --reload --reload-dir apps/api --port 8001
# Optional (after `pip install watchfiles`) to reduce reload scanning further:
# $ uvicorn apps.api.climate_api.main:app --reload --reload-dir apps/api --reload-exclude 'data/*' --reload-exclude 'web/*' --port 8001

# Example local profile request (returns X-Profile-Breakdown-ms + Server-Timing):
$ curl -i "http://127.0.0.1:8001/api/v/dev/panel?lat=48.8566&lon=2.3522&profile=true"

# Benchmark with profiling breakdown aggregation:
$ python scripts/bench_api_endpoints.py --base-url http://127.0.0.1:8001 --release dev --n 200 --profile-panel --profile-samples 40

# Inspect Redis
$ redis-cli DBSIZE
$ redis-cli keys 'climate_api:*'

---

Tests

# Unit tests + Registry validation + Coverage check
PYTHONPATH=. pytest -q

---

Script dependencies (non-stdlib)

- scripts/make_locations.py: requests, scipy (only if --write-kdtree)
- scripts/build_ocean_mask.py: numpy, fiona, rasterio
- scripts/packager.py: cdsapi, jsonschema, pillow, xarray, zstandard (dask only if --dask)
- scripts/redis_monitor.py: redis
- scripts/tile_coverage.py: numpy, jsonschema, zstandard
- scripts/validate_all.py: jsonschema

---

Guardian articles:
URL: https://www.theguardian.com/environment/ng-interactive/2025/dec/18/how-climate-breakdown-is-putting-the-worlds-food-in-peril-in-maps-and-charts
URL: Wildfires mapped January 2026
