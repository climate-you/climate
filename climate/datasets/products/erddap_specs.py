ERDDAP_DATASETS = {
    "oisst_sst_v21_daily": {
        "dataset_id": "ncdcOisst21Agg_LonPM180",
        "var": "sst",
        "dataset_start": "1981-09-01",
        "recommended_block_years": 5,
        "bases": [
            "https://upwell.pfeg.noaa.gov/erddap",
            "https://coastwatch.pfeg.noaa.gov/erddap",
        ],
        # IMPORTANT: OISST sst uses a zlev axis; constrain it explicitly
        "dims": ["time", "zlev", "latitude", "longitude"],
        "fixed": {"zlev": 0.0},
        # OISST time stamps are at 12:00Z
        "time_hms": "12:00:00Z",
        # Longitude convention for this dataset id is [-180, 180]
        "lon_mode": "pm180",
        # Common coord column names returned by ERDDAP CSV
        "lat_col_candidates": ["latitude", "lat"],
        "lon_col_candidates": ["longitude", "lon"],
        # Keep SST cache footprint lower on disk (same strategy as DHW cache).
        "compress_cache": True,
        "compress_cache_level": 4,
    },
    "crw_dhw_daily": {
        "dataset_id": "noaacrwdhwDaily",
        "var": "degree_heating_week",
        "bases": [
            # CRW DHW is currently published on this host.
            "https://coastwatch.noaa.gov/erddap",
        ],
        # CRW DHW uses daily time at 12:00Z (as observed from curl)
        "dims": ["time", "latitude", "longitude"],
        "time_hms": "12:00:00Z",
        "dataset_start": "1985-03-25",
        # Longitude convention: degrees_east (your curl shows 57.375 etc.); keep as-is
        "lon_mode": "east",
        "lat_col_candidates": ["latitude", "lat"],
        "lon_col_candidates": ["longitude", "lon"],
        # Operational note: large multi-year requests often yield 500/502; use yearly chunks
        "recommended_block_years": 1,
        # Store cache files compressed to keep long DHW runs manageable on disk.
        "compress_cache": True,
        "compress_cache_level": 4,
    },
}
