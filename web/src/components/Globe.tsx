"use client";

import { Canvas, useFrame, useLoader } from "@react-three/fiber";
import * as THREE from "three";
import { Suspense, useEffect, useMemo, useRef } from "react";
import { motion as M } from "@/config/motion";

/**
 * Textures (served from web/public)
 *
 * Realistic Earth (landing):
 *  - BASE: equirectangular Earth (no clouds)
 *  - CLOUDS: equirectangular clouds-only with alpha
 *
 * Warming Earth (later / optional):
 *  - WARMING: your warming texture
 *  - BORDERS: your borders overlay
 */
const REAL_BASE_URL = "/data/earth/earth_base.webp";
const REAL_CLOUDS_URL = "/data/earth/earth_clouds.png";

const WARMING_TEX_URL =
  "/data/world/warming_texture_1979-1988_to_2016-2025_grid0p25_4096x2048.webp";
const BORDERS_TEX_URL = "/data/world/borders_8192x4096.png";

/**
 * Texture alignment knob.
 * You previously needed a ~90° shift for your globe demo; keep that here.
 */
const TEXTURE_LON_SHIFT_DEG = 90;

export type GlobeMode = "real" | "warming";

export default function Globe({
  targetLatLon,
  phase,
  onArrive,
  mode = "real",
  showClouds = true,
}: {
  targetLatLon: { lat: number; lon: number } | null;
  phase: "landing" | "flying" | "arrived";
  onArrive: () => void;
  mode?: GlobeMode;
  showClouds?: boolean;
}) {
  return (
    <div className="h-full w-full">
      <Canvas
        camera={{ position: [0, 0, 2.6], fov: 45 }}
        gl={{ antialias: true, alpha: true }}
        onCreated={({ gl }) => {
          gl.setClearColor(0x000000, 0);
        }}
      >
        <Suspense fallback={null}>
          <GlobeMesh
            targetLatLon={targetLatLon}
            phase={phase}
            onArrive={onArrive}
            mode={mode}
            showClouds={showClouds}
          />
        </Suspense>
      </Canvas>
    </div>
  );
}

function GlobeMesh({
  targetLatLon,
  phase,
  onArrive,
  mode,
  showClouds,
}: {
  targetLatLon: { lat: number; lon: number } | null;
  phase: "landing" | "flying" | "arrived";
  onArrive: () => void;
  mode: GlobeMode;
  showClouds: boolean;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const cloudsRef = useRef<THREE.Mesh>(null);

  // Deterministic start for fly-to (so delaying fly doesn't change the flight)
  const homeQuat = useMemo(() => new THREE.Quaternion(), []);
  const startedFlyRef = useRef(false);
  const arrivedRef = useRef(false);

  // Load all textures (hooks must not be conditional)
  const realBaseTex = useLoader(THREE.TextureLoader, REAL_BASE_URL);
  const realCloudsTex = useLoader(THREE.TextureLoader, REAL_CLOUDS_URL);

  const warmingTex = useLoader(THREE.TextureLoader, WARMING_TEX_URL);
  const bordersTex = useLoader(THREE.TextureLoader, BORDERS_TEX_URL);

  useEffect(() => {
    // Real base
    realBaseTex.colorSpace = THREE.SRGBColorSpace;
    realBaseTex.wrapS = THREE.ClampToEdgeWrapping;
    realBaseTex.wrapT = THREE.ClampToEdgeWrapping;
    realBaseTex.anisotropy = 8;
    realBaseTex.needsUpdate = true;

    // Real clouds (alpha)
    realCloudsTex.colorSpace = THREE.SRGBColorSpace;
    realCloudsTex.wrapS = THREE.ClampToEdgeWrapping;
    realCloudsTex.wrapT = THREE.ClampToEdgeWrapping;
    realCloudsTex.anisotropy = 8;
    realCloudsTex.needsUpdate = true;

    // Warming
    warmingTex.colorSpace = THREE.SRGBColorSpace;
    warmingTex.wrapS = THREE.ClampToEdgeWrapping;
    warmingTex.wrapT = THREE.ClampToEdgeWrapping;
    warmingTex.anisotropy = 8;
    warmingTex.needsUpdate = true;

    // Borders
    bordersTex.colorSpace = THREE.SRGBColorSpace;
    bordersTex.wrapS = THREE.ClampToEdgeWrapping;
    bordersTex.wrapT = THREE.ClampToEdgeWrapping;
    bordersTex.anisotropy = 8;
    bordersTex.needsUpdate = true;
  }, [realBaseTex, realCloudsTex, warmingTex, bordersTex]);

  /**
   * Target quaternion:
   * 1) bring target point to camera (+Z)
   * 2) remove roll so north is screen-up
   */
  const targetQuat = useMemo(() => {
    if (!targetLatLon) return null;

    const latRad = THREE.MathUtils.degToRad(targetLatLon.lat);
    const lonRad = THREE.MathUtils.degToRad(targetLatLon.lon + TEXTURE_LON_SHIFT_DEG);

    // (lat,lon) -> unit vector. Convention: Y up, Z toward camera, X right.
    const v = new THREE.Vector3(
      Math.cos(latRad) * Math.sin(lonRad),
      Math.sin(latRad),
      Math.cos(latRad) * Math.cos(lonRad)
    ).normalize();

    // Primary: point -> front (+Z)
    const front = new THREE.Vector3(0, 0, 1);
    const q = new THREE.Quaternion().setFromUnitVectors(v, front);

    // Roll fix: rotate around Z so that "north" points up on screen.
    const northLocal = new THREE.Vector3(0, 1, 0);
    const northCam = northLocal.clone().applyQuaternion(q);
    const north2 = new THREE.Vector3(northCam.x, northCam.y, 0);

    if (north2.lengthSq() < 1e-10) return q; // near poles
    north2.normalize();

    const up = new THREE.Vector3(0, 1, 0);
    const angle = Math.atan2(
      north2.x * up.y - north2.y * up.x,
      north2.x * up.x + north2.y * up.y
    );
    const rollFix = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), angle);

    return rollFix.multiply(q);
  }, [targetLatLon]);

  useFrame((_, dt) => {
    const g = groupRef.current;
    if (!g) return;

    // Clouds motion (slightly faster than Earth for life)
    if (cloudsRef.current && mode === "real" && showClouds) {
      cloudsRef.current.rotation.y += dt * M.globe.idleSpinCloudFactor; // tweakable
    }

    // Landing: idle spin
    if (!targetQuat || phase === "landing") {
      g.rotation.y += dt * M.globe.idleSpinRadPerSec;
      startedFlyRef.current = false;
      arrivedRef.current = false;
      return;
    }

    // Reset to home when starting fly to make it deterministic
    if (phase === "flying" && !startedFlyRef.current) {
      startedFlyRef.current = true;
      g.quaternion.copy(homeQuat);
    }

    const speed = phase === "flying" ? M.globe.flySlerp : 1.0;
    g.quaternion.slerp(targetQuat, 1 - Math.exp(-speed * dt));

    const angle = g.quaternion.angleTo(targetQuat);
    if (angle < 0.02 && !arrivedRef.current) {
      arrivedRef.current = true;
      onArrive();
    }
  });

  const baseMap = mode === "real" ? realBaseTex : warmingTex;

  return (
    <group ref={groupRef}>
      {/* Base globe */}
      <mesh>
        <sphereGeometry args={[1, 96, 96]} />
        <meshBasicMaterial map={baseMap} />
      </mesh>

      {/* Real clouds overlay */}
      {mode === "real" && showClouds && (
        <mesh ref={cloudsRef}>
          <sphereGeometry args={[1.01, 96, 96]} />
          <meshBasicMaterial
            map={realCloudsTex}
            transparent
            opacity={0.55}
            depthWrite={false}
          />
        </mesh>
      )}

      {/* Warming borders overlay */}
      {mode === "warming" && (
        <mesh>
          <sphereGeometry args={[1.002, 96, 96]} />
          <meshBasicMaterial
            map={bordersTex}
            transparent
            opacity={0.95}
            depthWrite={false}
          />
        </mesh>
      )}
    </group>
  );
}
