Data attribution: “Data: ERA5 climate reanalysis via Open-Meteo archive API”

Usage:

1. Contents of ~/.cdsapirc:
url: https://cds.climate.copernicus.eu/api
key: XXXXXX

2. Environment:
$ export EARTHKIT_CACHE_HOME=/Users/benoit.leveau/Documents/Programming/Climate/ek-cache
$ conda activate climate

3. Precompute:
$ python source/precompute.py  --area "-18 55 -22 59" --year-start 1975 --year-end 2024 --out data/era5_t2m_monthly_1975_2024_mauritius.nc
$ python source/precompute.py --area "53 -2.5 50 1.5" --year-start 1975 --year-end 2024 --out data/era5_t2m_monthly_1975_2024_london.nc

4. Run web page:
$ streamlit run source/zoom_temp.py
