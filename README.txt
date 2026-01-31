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
$ cd web; npm run dev 

# Streamlit - http://localhost:8501/
$ streamlit run app/story_demo.py

# Warming Globe - http://localhost:8000/drafts/warming_globe_demo/
# python -m http.server 8000 

# Hero Wire Globe - http://localhost:8000/
# cd drafts/three_wire_globe_clouds; python -m http.server 8000 

---

6. Run v2 server  
# Install & Run Redis

# Run FastAPI thin client:
$ export REDIS_URL='redis://localhost:6379/0'
$ uvicorn apps.api.climate_api.main:app --reload --port 8001

# Inspect Redis
$ redis-cli DBSIZE
$ redis-cli keys 'climate_api:*'

# Query server
(London)
$ curl 'http://localhost:8001/api/v/dev/panel?lat=51.101&lon=-0.136&panel_id=overview&unit=C'
(Tamarin)
$ curl 'http://localhost:8001/api/v/dev/panel?lat=-20.32556&lon=57.37056&panel_id=ocean&unit=C'
$ curl 'http://localhost:8001/api/v/dev/panel?lat=-20.32556&lon=57.37056&panel_id=overview&unit=C'

---

Guardian articles:
URL: https://www.theguardian.com/environment/ng-interactive/2025/dec/18/how-climate-breakdown-is-putting-the-worlds-food-in-peril-in-maps-and-charts
URL: Wildfires mapped January 2026