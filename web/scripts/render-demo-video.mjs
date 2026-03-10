#!/usr/bin/env node

import { mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const ARTIFACT_DIR = resolve("artifacts/demo-video");
const RAW_INPUT = resolve(ARTIFACT_DIR, "raw/demo-square-1080.webm");
const MP4_OUTPUT = resolve(ARTIFACT_DIR, "demo-square-1080.mp4");

function run(command, args) {
  const result = spawnSync(command, args, { stdio: "inherit" });
  if (result.status !== 0) {
    throw new Error(`${command} failed with exit code ${result.status ?? 1}`);
  }
}

function ensureFfmpeg() {
  const probe = spawnSync("ffmpeg", ["-version"], { stdio: "ignore" });
  if (probe.status !== 0) {
    throw new Error("ffmpeg is required and was not found in PATH.");
  }
}

function main() {
  ensureFfmpeg();
  mkdirSync(ARTIFACT_DIR, { recursive: true });
  run("ffmpeg", [
    "-y",
    "-i",
    RAW_INPUT,
    "-vf",
    "fps=60,scale=1080:1080:flags=lanczos,format=yuv420p",
    "-r",
    "60",
    "-c:v",
    "libx264",
    "-profile:v",
    "high",
    "-level:v",
    "4.2",
    "-tune",
    "animation",
    "-preset",
    "veryslow",
    "-crf",
    "14",
    "-x264-params",
    "aq-mode=3:aq-strength=0.9:deblock=-1,-1",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    "-an",
    MP4_OUTPUT,
  ]);
  console.log(`Rendered MP4 demo video: ${MP4_OUTPUT}`);
}

try {
  main();
} catch (error) {
  console.error(
    `Failed to render demo video: ${error instanceof Error ? error.message : String(error)}`,
  );
  process.exit(1);
}
