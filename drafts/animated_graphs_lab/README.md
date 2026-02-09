# Animated Climate Graph Lab

This mini-project prototypes the two chart types in your references:

- Mixed **bar + smooth line + area fill** chart for hot days
- Multi-line **anomaly + 5-year mean + trend** chart

## Library choice

This uses **Apache ECharts** because it gives you:

- Built-in animation and animated updates (`setOption`)
- Easy mixing of bars, smooth lines, filled areas, and trend overlays
- Solid tooltip/legend/axis defaults for data storytelling charts
- Responsive behavior without extra plugins

Docs:
- https://echarts.apache.org/
- https://echarts.apache.org/examples/en/

## Run

Open `animated_graphs_lab/index.html` in a browser.

If you prefer a local dev server:

```bash
cd animated_graphs_lab
python3 -m http.server 8080
```

Then visit `http://localhost:8080`.

## Tune quickly

In `animated_graphs_lab/main.js`:

- Replace `hotDays` and `anomaly` arrays with your real data
- Change playback speed in `startPlayback()` (interval currently `320` ms)
- Change smoothing via `smooth` on line series
- Adjust colors/styles in `lineStyle`, `areaStyle`, and `itemStyle`
