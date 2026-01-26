ERDDAP_DATASETS = {
    "oisst_sst_v21_daily": {
        "dataset_id": "ncdcOisst21Agg_LonPM180",
        "var": "sst",
        "dataset_start": "1981-09-01",
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
    },
    "crw_dhw_daily": {
        "dataset_id": "noaacrwdhwDaily",
        "var": "degree_heating_week",
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
    },
}
