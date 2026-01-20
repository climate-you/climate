export const motion = {
  layout: {
    globeMoveMs: 2500,
    textFadeMs: 2000,
    landingHoldMs: 4800,
  },
  globe: {
    idleSpinRadPerSec: 0.08,
    idleSpinCloudFactor: 0.004,
    flySlerp: 2.2,
    zoomLanding: 0.8,
    zoomFlying: 1.25,
    zoomArrived: 2.0,
  },
} as const;
