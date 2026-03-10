export const DEMO_VIDEO_STEP_ORDER = [
  "cold-open",
  "fly-to-london",
  "pick-london",
  "close-panel",
  "home",
  "switch-layer",
  "outro",
  "done",
] as const;

export type DemoVideoStepId = (typeof DEMO_VIDEO_STEP_ORDER)[number];

export function isValidDemoVideoStepSequence(ids: string[]): boolean {
  if (ids.length !== DEMO_VIDEO_STEP_ORDER.length) return false;
  return ids.every((id, index) => id === DEMO_VIDEO_STEP_ORDER[index]);
}

