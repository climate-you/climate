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

Enable local demo-video route (disabled by default):

```bash
export NEXT_PUBLIC_ENABLE_DEMO_VIDEO=1
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
- `/demo-video` scripted local demo route (only when `NEXT_PUBLIC_ENABLE_DEMO_VIDEO=1`)

## Query options

Preview a specific release:

```text
http://localhost:3000/?release=2022-02-17
```

Force intro behavior:

- `?intro=1` force cold-open even if already seen in this session
- `?intro=0` skip cold-open

## Demo video workflow (square 1080x1080)

1. Run the app locally with demo route enabled:

```bash
export NEXT_PUBLIC_ENABLE_DEMO_VIDEO=1
npm run dev
```

2. In another shell, capture and render:

```bash
npm run demo:video
```

This writes:

- raw recording: `artifacts/demo-video/raw/demo-square-1080.webm`
- final export: `artifacts/demo-video/demo-square-1080.mp4`

You can also run steps independently:

```bash
npm run demo:video:record
npm run demo:video:render
```

Notes:

- `demo:video:record` requires Playwright (`npm install -D playwright`) and a running local dev server.
- Recorder target URL defaults to `http://localhost:3000`; override with `DEMO_VIDEO_BASE_URL`.
- Set `DEMO_VIDEO_HEADLESS=0` to run recorder in headed mode if headless WebGL is flaky on your machine.
- Set `DEMO_VIDEO_STATUS_TIMEOUT_MS` (default `600000`) to adjust max wait for full demo completion.
- Recorder prewarms cache by default before capture (`DEMO_VIDEO_PREWARM=1`).
- Tune warmup duration with `DEMO_VIDEO_PREWARM_WAIT_MS` (default `9000`), or disable via `DEMO_VIDEO_PREWARM=0`.
- `demo:video:render` requires `ffmpeg` available on `PATH`.

Prewarm behavior:

- Opens `/?intro=0` in the same browser context.
- Fetches release metadata + a few panel queries (including London/Indonesia).
- Prefetches several layer assets before recording begins.

### Smoother capture in production mode

For smoother animation than `next dev`, record against `next start`:

```bash
# shell 1
cd web
export NEXT_PUBLIC_ENABLE_DEMO_VIDEO=1
npm run build
npm run start
```

```bash
# shell 2
cd web
DEMO_VIDEO_BASE_URL=http://localhost:3000 npm run demo:video
```

Important: `NEXT_PUBLIC_ENABLE_DEMO_VIDEO` is a build-time env var, so it must
be set before `npm run build`.
