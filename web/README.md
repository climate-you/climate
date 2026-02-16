# Web app

This is the Next.js front-end for the climate API demo.

## Run locally

```bash
npm install
npm run dev
```

Open `http://localhost:3000/`.

## API target

By default the app calls the backend on port `8001` of the current host.
Override with:

```bash
export NEXT_PUBLIC_CLIMATE_API_BASE="http://localhost:8001"
```

Optional map layer root override:

```bash
export NEXT_PUBLIC_MAP_LAYER_ROOT="/data/maps"
```
