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

4. Precompute:
# Tweak favorites.txt
$ python scripts/precompute_story_cities.py --only-favorites --limit 10 [--dry-run]

5. Run web page:
$ streamlit run app/story_demo.py
