import * as maptilersdk from '@maptiler/sdk';
import '@maptiler/sdk/dist/maptiler-sdk.css';
import './style.css';

const apiKey = import.meta.env.VITE_MAPTILER_API_KEY;

if (!apiKey) {
  throw new Error('Missing VITE_MAPTILER_API_KEY. Add it in a .env file.');
}

maptilersdk.config.apiKey = apiKey;

const locationPanel = document.getElementById('location-panel');
const coordinatesLabel = document.getElementById('panel-coordinates');
const closePanelButton = document.getElementById('close-panel');
const zeroPadding = { top: 0, right: 0, bottom: 0, left: 0 };
let selectedLocationMarker;

const initialView = {
  center: [0, 0],
  zoom: 2.5,
  pitch: 0,
  bearing: 0
};

// Show geographic location labels only within this zoom range.
const LOCATION_LABELS_MIN_ZOOM = 3.8;
const LOCATION_LABELS_MAX_ZOOM = 10;
const LOCATION_LABEL_KEYWORDS = [
  'place',
  'settlement',
  'city',
  'town',
  'village',
  'country',
  'state',
  'province',
  'continent'
];

const map = new maptilersdk.Map({
  container: 'map',
  style: maptilersdk.MapStyle.BACKDROP_V4,
  navigationControl: false,
  projection: 'globe',
  zoom: initialView.zoom,
  minZoom: initialView.zoom,
  maxZoom: 10,
  center: initialView.center,
  pitch: initialView.pitch,
  bearing: initialView.bearing,
  space: {
    color: '#0000ff'
  }
});

function isEarthLocationLabelLayer(layer) {
  if (!layer || layer.type !== 'symbol') {
    return false;
  }

  const textField = layer.layout?.['text-field'];
  if (!textField) {
    return false;
  }

  const id = (layer.id || '').toLowerCase();
  return LOCATION_LABEL_KEYWORDS.some((keyword) => id.includes(keyword));
}

function updateEarthLocationLabelVisibility() {
  const zoom = map.getZoom();
  const visible =
    zoom >= LOCATION_LABELS_MIN_ZOOM && zoom <= LOCATION_LABELS_MAX_ZOOM;
  const visibility = visible ? 'visible' : 'none';
  const layers = map.getStyle()?.layers || [];

  for (const layer of layers) {
    if (!isEarthLocationLabelLayer(layer)) {
      continue;
    }

    map.setLayoutProperty(layer.id, 'visibility', visibility);
  }
}

class HomeControl {
  onAdd(mapInstance) {
    this.map = mapInstance;
    this.container = document.createElement('div');
    this.container.className = 'maplibregl-ctrl maplibregl-ctrl-group';

    this.button = document.createElement('button');
    this.button.type = 'button';
    this.button.className = 'maplibregl-ctrl-icon home-control-button';
    this.button.ariaLabel = 'Return to initial globe position';
    this.button.title = 'Home';
    this.button.textContent = '⌂';
    this.button.addEventListener('click', this.onClick);

    this.container.appendChild(this.button);
    return this.container;
  }

  onRemove() {
    this.button?.removeEventListener('click', this.onClick);
    this.container?.remove();
    this.map = undefined;
  }

  onClick = () => {
    locationPanel?.classList.remove('is-open');
    this.map.flyTo({
      center: initialView.center,
      zoom: initialView.zoom,
      pitch: initialView.pitch,
      bearing: initialView.bearing,
      padding: zeroPadding,
      duration: 1200,
      essential: true
    });
  };
}

map.addControl(new HomeControl(), 'top-left');
map.addControl(new maptilersdk.NavigationControl(), 'top-left');

map.on('load', updateEarthLocationLabelVisibility);
map.on('zoom', updateEarthLocationLabelVisibility);

function getPanelPadding() {
  if (!locationPanel) {
    return zeroPadding;
  }

  if (window.matchMedia('(max-width: 900px)').matches) {
    return zeroPadding;
  }

  // Use computed open dimensions so first click is correct even during panel transition.
  const mapRect = map.getContainer().getBoundingClientRect();
  const panelStyle = window.getComputedStyle(locationPanel);
  const panelWidth = parseFloat(panelStyle.width) || 0;
  const rightInset = parseFloat(panelStyle.right) || 0;
  const rightPadding = Math.min(mapRect.width, Math.max(0, panelWidth + rightInset));

  return { top: 0, right: rightPadding, bottom: 0, left: 0 };
}

map.on('click', (event) => {
  const { lng, lat } = event.lngLat;

  coordinatesLabel.textContent = `Longitude: ${lng.toFixed(4)} | Latitude: ${lat.toFixed(4)}`;
  locationPanel?.classList.add('is-open');

  if (!selectedLocationMarker) {
    selectedLocationMarker = new maptilersdk.Marker({ color: '#ff0000' })
      .setLngLat([lng, lat])
      .addTo(map);
  } else {
    selectedLocationMarker.setLngLat([lng, lat]);
  }

  map.flyTo({
    center: [lng, lat],
    zoom: 5.5,
    pitch: 0,
    bearing: 0,
    padding: getPanelPadding(),
    duration: 1500,
    essential: true
  });
});

closePanelButton?.addEventListener('click', () => {
  locationPanel?.classList.remove('is-open');
  map.easeTo({
    padding: zeroPadding,
    duration: 300,
    essential: true
  });
});
