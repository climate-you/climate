export EARTHKIT_CACHE_HOME=/Users/benoit.leveau/Documents/Programming/Climate/ek-cache

conda activate climate
streamlit run app.py

Ok, I now want to explore another web page, that will illustrate the change of temperature in a location over the past 50 years. The idea is to "zoom out" on the graphs as we scroll down the page. 

The experience for the user will look like:
1. Upon loading the page, the user location is read (from their IP or from the browser, I'm not sure how it's usually done).
The location is shown, eg. "London, UK", and a map is shown with a pin at the location.

2. Below the map, after scrolling down, we show a graph of the hourly average temperature over the past 7 days (is that data in the CDS datasets?)

3. Below, after scrolling down again, we show a graph of the daily average temperature of the last 5 months.

4. Below, we show a graph of the average monthly temperature of the past few years (let's say 5 years).

5. Below that, we show the same graph but we overlay the average monthly temperature 50 years in the past.

6. Below, I'd like to show 2 graphs:
- the daily average temperature over a typical year in the 2020-2025 range
- the daily average temperature over a typical year 50 years in the past

Challenges:
- it seems like it might be a lot of data to load. I think it's best to send the requests as soon as the location is known.
- ideally i'd like to extract insights from the data to highlight things on the graph (like a record high temperature, etc.)
- I'm not sure whether the average monthly or even daily temperatures will clearly show the effect of global warming, maybe it's only visible in daily highs and lows rather than average? in this case it might make sense to show not only the average but also the min/max.

---

Step 1 - Detect location
- I wasn't prompted to allow browser location, so not sure if this happens at all?
- There are two maps shown on the page (CARTO and Leaflet), not sure why.
- Clicking on any map doesn't set the location or change the latitude/longitude.
I'd like a better UX:
- location is detected from IP or browser API
- location is displayed with a dot/pin on a single map
- no latitude/longitude inputs
- clicking somewhere else on the map updates the location

Step 2:
- once the chunks have been downloaded, I'm getting this error (same as the one we got on the other page I believe, so we need to account for a different 'time' field)
```
KeyError: "No variable named 'time'. Variables on the dataset include ['2t', 'forecast_reference_time', 'latitude', 'longitude']"
```