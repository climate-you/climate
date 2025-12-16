import pandas as pd
import streamlit as st

st.set_page_config(page_title="Locations map", layout="wide")

st.title("locations.csv — city distribution")

# Adjust path if needed
CSV_PATH = "locations/locations.csv"

df = pd.read_csv(CSV_PATH)

# Expect columns like: lat, lon (or latitude, longitude). Adapt if yours differ.
if "lat" in df.columns and "lon" in df.columns:
    plot_df = df.rename(columns={"lat": "latitude", "lon": "longitude"})
elif "latitude" in df.columns and "longitude" in df.columns:
    plot_df = df.copy()
else:
    st.error(f"Couldn't find lat/lon columns in {CSV_PATH}. Found: {list(df.columns)}")
    st.stop()

st.caption(f"{len(plot_df):,} locations")

# Optional: quick filters
with st.sidebar:
    st.header("Filters (optional)")
    if "country_code" in df.columns:
        countries = ["(all)"] + sorted(df["country_code"].dropna().unique().tolist())
        cc = st.selectbox("Country code", countries, index=0)
        if cc != "(all)":
            plot_df = plot_df[df["country_code"] == cc].rename(columns={"lat": "latitude", "lon": "longitude"}) \
                if "lat" in df.columns else df[df["country_code"] == cc]
    st.write("")

# Streamlit's built-in map (fast + simple)
st.map(plot_df[["latitude", "longitude"]], zoom=1)
