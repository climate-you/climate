#!/usr/bin/env node

import { cpSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

const BASE_URL = process.env.DEMO_VIDEO_BASE_URL ?? "http://localhost:3000";
const ARTIFACT_DIR = resolve("artifacts/demo-video");
const RAW_DIR = resolve(ARTIFACT_DIR, "raw");
const RAW_OUTPUT = resolve(RAW_DIR, "demo-square-1080.webm");
const DEBUG_SCREENSHOT = resolve(ARTIFACT_DIR, "recording-failure.png");
const VIEWPORT = { width: 1080, height: 1080 };
const HEADLESS =
  String(process.env.DEMO_VIDEO_HEADLESS ?? "1").toLowerCase() !== "0";
function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
const STATUS_TIMEOUT_MS = parsePositiveInt(
  process.env.DEMO_VIDEO_STATUS_TIMEOUT_MS,
  600000,
);
const PREWARM_ENABLED =
  String(process.env.DEMO_VIDEO_PREWARM ?? "1").toLowerCase() !== "0";
const PREWARM_WAIT_MS = parsePositiveInt(
  process.env.DEMO_VIDEO_PREWARM_WAIT_MS,
  9000,
);

mkdirSync(RAW_DIR, { recursive: true });

async function loadPlaywright() {
  try {
    return await import("playwright");
  } catch {
    console.error(
      "Missing dependency 'playwright'. Install it with: npm install -D playwright",
    );
    process.exit(1);
  }
}

async function runPrewarmQueries(page, baseUrl) {
  await page.goto(`${baseUrl}/?intro=0`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  const report = await page.evaluate(async () => {
    const apiBase = `http://${window.location.hostname}:8001`;
    const panelTargets = [
      { lat: 51.5074, lon: -0.1278, unit: "C" }, // London
      { lat: -1.8, lon: 117.3, unit: "C" }, // Indonesia
      { lat: -20.32556, lon: 57.37056, unit: "C" }, // default app location
    ];
    const out = {
      apiBase,
      release: "latest",
      panelOk: 0,
      panelFail: 0,
      assetOk: 0,
      assetFail: 0,
    };
    try {
      const releaseResp = await fetch(`${apiBase}/api/v/latest/release`);
      if (releaseResp.ok) {
        const releaseJson = await releaseResp.json();
        const resolvedRelease =
          typeof releaseJson?.release === "string" && releaseJson.release
            ? releaseJson.release
            : "latest";
        out.release = resolvedRelease;
        for (const target of panelTargets) {
          const qs = new URLSearchParams({
            lat: String(target.lat),
            lon: String(target.lon),
            unit: target.unit,
          });
          const panelUrl = `${apiBase}/api/v/${encodeURIComponent(resolvedRelease)}/panel?${qs.toString()}`;
          try {
            const panelResp = await fetch(panelUrl);
            if (panelResp.ok) out.panelOk += 1;
            else out.panelFail += 1;
          } catch {
            out.panelFail += 1;
          }
        }
        const layers = Array.isArray(releaseJson?.layers)
          ? releaseJson.layers
          : [];
        for (const layer of layers.slice(0, 8)) {
          const assetPath =
            typeof layer?.asset_path === "string" ? layer.asset_path : null;
          if (!assetPath) continue;
          const assetUrl = `${apiBase}/assets/v/${encodeURIComponent(resolvedRelease)}/${assetPath}`;
          try {
            const assetResp = await fetch(assetUrl, { mode: "cors" });
            if (assetResp.ok) out.assetOk += 1;
            else out.assetFail += 1;
          } catch {
            out.assetFail += 1;
          }
        }
      }
    } catch {
      // Ignore prewarm fetch errors; recording can still continue.
    }
    return out;
  });
  return report;
}

async function main() {
  const { chromium } = await loadPlaywright();
  const browser = await chromium.launch({
    headless: HEADLESS,
    args: [
      "--enable-webgl",
      "--ignore-gpu-blocklist",
      "--enable-unsafe-swiftshader",
      "--disable-background-timer-throttling",
      "--disable-backgrounding-occluded-windows",
      "--disable-renderer-backgrounding",
      "--disable-frame-rate-limit",
      "--disable-features=UseEcoQoSForBackgroundProcess",
    ],
  });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: {
      dir: RAW_DIR,
      size: VIEWPORT,
    },
  });
  context.setDefaultTimeout(Math.max(STATUS_TIMEOUT_MS, 120000));
  console.log(
    `[recorder] base=${BASE_URL} headless=${HEADLESS} prewarm=${PREWARM_ENABLED} prewarm_wait_ms=${PREWARM_WAIT_MS} status_timeout_ms=${STATUS_TIMEOUT_MS}`,
  );

  if (PREWARM_ENABLED) {
    const warmupPage = await context.newPage();
    const warmupReport = await runPrewarmQueries(warmupPage, BASE_URL);
    console.log(
      `[recorder] prewarm release=${warmupReport.release} panel_ok=${warmupReport.panelOk} panel_fail=${warmupReport.panelFail} asset_ok=${warmupReport.assetOk} asset_fail=${warmupReport.assetFail}`,
    );
    await warmupPage.waitForTimeout(PREWARM_WAIT_MS);
    await warmupPage.close();
  }

  const page = await context.newPage();
  page.on("console", (msg) => {
    console.log(`[browser:${msg.type()}] ${msg.text()}`);
  });
  page.on("pageerror", (error) => {
    console.error(`[browser:pageerror] ${error.message}`);
  });
  page.on("requestfailed", (request) => {
    const errorText = request.failure()?.errorText ?? "unknown error";
    if (errorText === "net::ERR_ABORTED") return;
    console.error(
      `[browser:requestfailed] ${request.method()} ${request.url()} - ${errorText}`,
    );
  });
  const video = page.video();
  const url = `${BASE_URL}/demo-video?intro=1`;
  await page.goto(url, { waitUntil: "networkidle", timeout: 120000 });
  await page.waitForFunction(
    () => {
      const status = window.__CLIMATE_DEMO_VIDEO_STATUS__?.status;
      return status === "done" || status === "error";
    },
    { timeout: STATUS_TIMEOUT_MS },
  );
  const finalStatus = await page.evaluate(
    () => window.__CLIMATE_DEMO_VIDEO_STATUS__ ?? null,
  );
  if (finalStatus?.status === "error") {
    await page.screenshot({ path: DEBUG_SCREENSHOT, fullPage: true });
    throw new Error(finalStatus.error || "Demo timeline failed.");
  }
  await context.close();
  await browser.close();

  if (!video) {
    throw new Error("No recorded video handle from Playwright.");
  }

  const sourcePath = await video.path();
  mkdirSync(dirname(RAW_OUTPUT), { recursive: true });
  cpSync(sourcePath, RAW_OUTPUT);
  console.log(`Recorded raw demo video: ${RAW_OUTPUT}`);
}

main().catch((error) => {
  console.error(
    `Failed to record demo video: ${error instanceof Error ? error.message : String(error)}`,
  );
  console.error(`Debug screenshot path (if captured): ${DEBUG_SCREENSHOT}`);
  process.exit(1);
});
