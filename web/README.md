# Web app

This is the Next.js front-end for the climate API.

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

Optional map asset base override:

```bash
export NEXT_PUBLIC_MAP_ASSET_BASE="http://localhost:8001"
```

Site canonical base URL (used for metadata/sitemap/robots):

```bash
export SITE_URL="https://example.com"
```

## Routes

- `/` map experience (cold-open enabled, once per browser session)
- `/about` map + About overlay opened
- `/sources` map + Sources overlay opened
- `/robots.txt` crawl rules
- `/sitemap.xml` sitemap

## Query options

Preview a specific release:

```text
http://localhost:3000/?release=2022-02-17
```

Force intro behavior:

- `?intro=1` force cold-open even if already seen in this session
- `?intro=0` skip cold-open
