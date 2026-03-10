#!/usr/bin/env node

import { spawnSync } from "node:child_process";

function runNodeScript(scriptPath) {
  const result = spawnSync("node", [scriptPath], { stdio: "inherit" });
  if (result.status !== 0) {
    throw new Error(`Script failed: ${scriptPath}`);
  }
}

try {
  runNodeScript("scripts/record-demo-video.mjs");
  runNodeScript("scripts/render-demo-video.mjs");
} catch (error) {
  console.error(
    `Failed to build demo video: ${error instanceof Error ? error.message : String(error)}`,
  );
  process.exit(1);
}

