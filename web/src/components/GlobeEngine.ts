// GlobeEngine.ts
import * as THREE from "three";

export type LatLon = { lat: number; lon: number };

export type GlobeTimings = {
  globeFadeMs: number;
  cloudsDelayAfterGlobeMs: number;
  cloudsFadeMs: number;
  dataDelayAfterGlobeMs: number;
};

export type GlobeAssets = {
  // these are *paths*, e.g. "/textures"
  basePath: string;

  // naming conventions (default matches your main.js)
  landPrefix?: string;    // "land_"
  cloudsPrefix?: string;  // "clouds_"
  bordersPrefix?: string; // "borders_"
  dataPrefix?: string;    // "data_"

  // marker filename
  markerFile?: string;    // "marker.png"

  // optional fallback
  emptyFile?: string;     // "empty.png"
};

export type GlobeOptions = {
  canvas: HTMLCanvasElement;

  // behavior toggles like your flags
  enableBorders?: boolean;
  enableData?: boolean;
  enableClouds?: boolean;

  timings?: Partial<GlobeTimings>;
  assets: GlobeAssets;

  // visuals
  startRotY?: number; // e.g. Math.PI
  shadeStrength?: number;
  brightness?: number;

  // colors
  ocean?: number;
  land?: number;
  grid?: number;
  border?: number;
  marker?: number;

  // texture mask invert
  maskInvert?: number; // 1.0 or 0.0
  lonShiftDeg?: number; // e.g. 90

  // camera
  fov?: number;
  cameraZ?: number;

  // sizes
  desktopSize?: 2048 | 4096;
  mobileSize?: 1024 | 2048;
  desktopSmallSize?: 1024 | 2048;
  mobileSmallSize?: 512 | 1024;

  // callbacks
  onArrive?: () => void;
  onError?: (e: unknown) => void;
};

const DEFAULT_TIMING: GlobeTimings = {
  globeFadeMs: 2000,
  cloudsDelayAfterGlobeMs: 1000,
  cloudsFadeMs: 1000,
  dataDelayAfterGlobeMs: 2000,
};

function easeOutCubic(t: number) {
  return 1 - Math.pow(1 - t, 3);
}
function easeInOutCubic(t: number) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}
function delay(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}
function fadeMaterialOpacity(mat: THREE.Material & { opacity: number }, to: number, ms = 700) {
  const from = mat.opacity;
  const t0 = performance.now();
  const step = (now: number) => {
    const t = Math.min(1, (now - t0) / ms);
    const k = easeOutCubic(t);
    mat.opacity = from + (to - from) * k;
    mat.needsUpdate = true;
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

export class GlobeEngine {
  private renderer: THREE.WebGLRenderer;
  private scene: THREE.Scene;
  private camera: THREE.PerspectiveCamera;

  private introStarted = false;

  private readyResolve!: () => void;
  public ready: Promise<void> = new Promise((r) => (this.readyResolve = r));

  private sun: THREE.DirectionalLight;

  private earth!: THREE.Mesh;
  private earthMat!: THREE.ShaderMaterial;

  private marker!: THREE.Sprite;

  private cloudsTex: THREE.Mesh | null = null;
  private cloudsRequestedReveal = false;

  private uniforms: Record<string, THREE.IUniform> = {};

  private t0 = performance.now();

  private alive = true;
  private flyRaf = 0;
  private raf = 0;
  private running = false;

  private autorotate = true;
  private dataCycleT0: number | null = null;

  private timings: GlobeTimings;

  private enableBorders: boolean;
  private enableData: boolean;
  private enableClouds: boolean;

  private startRotY: number;
  private cloudDriftSpeed = 0.01; // radians/sec, same as your current

  private lonShiftDeg: number;

  constructor(private opts: GlobeOptions) {
    this.enableBorders = opts.enableBorders ?? true;
    this.enableData = opts.enableData ?? true;
    this.enableClouds = opts.enableClouds ?? true;

    this.timings = { ...DEFAULT_TIMING, ...(opts.timings ?? {}) };

    this.startRotY = opts.startRotY ?? Math.PI;

    // renderer/camera/scene
    this.renderer = new THREE.WebGLRenderer({ canvas: opts.canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.setSize(window.innerWidth, window.innerHeight, false);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.scene = new THREE.Scene();

    const fov = opts.fov ?? 35;
    this.camera = new THREE.PerspectiveCamera(fov, window.innerWidth / window.innerHeight, 0.1, 100);
    this.camera.position.set(0, 0, opts.cameraZ ?? 4.0);

    this.sun = new THREE.DirectionalLight(0xffffff, 0.9);
    this.sun.position.set(3, 1.5, 2.5);
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.85));
    this.scene.add(this.sun);

    this.lonShiftDeg = opts.lonShiftDeg ?? 90;

    // keep CSS and JS fade duration in sync (same as your main.js)
    document.documentElement.style.setProperty("--globe-fade-ms", `${this.timings.globeFadeMs}ms`);
  }

  destroy() {
    this.alive = false;
    this.running = false;
    cancelAnimationFrame(this.raf);
    cancelAnimationFrame(this.flyRaf);
    this.renderer.dispose();
    // (Optionally traverse + dispose textures/materials/geometries)
  }

  resize() {
    const rect = this.opts.canvas.getBoundingClientRect();
    const w = Math.max(1, rect.width);
    const h = Math.max(1, rect.height);

    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  setAutorotate(on: boolean) {
    this.autorotate = on;
  }

  setZoom(z: number) {
    this.camera.position.z = z;
  }

  setPalette(p: { ocean?: string; land?: string; grid?: string; border?: string }) {
    if (p.ocean) this.uniforms.oceanColor.value.set(p.ocean);
    if (p.land) this.uniforms.landColor.value.set(p.land);
    if (p.grid) this.uniforms.gridColor.value.set(p.grid);
    if (p.border) this.uniforms.borderColor.value.set(p.border);
  }

  private ll(lat: number, lon: number, r = 1) {
    // IMPORTANT: include your lon shift here if you have one
    return GlobeEngine.latLonToVec3(lat, lon + this.lonShiftDeg, r);
  }

  // Tangent direction that points to geographic north (in local earth coords)
  private northTangentLocal(lat: number, lon: number) {
    const latR = THREE.MathUtils.degToRad(lat);
    const lonR = THREE.MathUtils.degToRad(lon + this.lonShiftDeg);

    // derivative wrt lat of your latLonToVec3 formula
    const x = -Math.sin(latR) * Math.sin(lonR);
    const y =  Math.cos(latR);
    const z = -Math.sin(latR) * Math.cos(lonR);

    return new THREE.Vector3(x, y, z).normalize();
  }

  /**
   * Returns a new quaternion that:
   * - puts (lat,lon) at the front (+Z)
   * - keeps north pointing up (+Y)
   * starting from baseQuat.
   */
  private quatToFrontNorthUp(lat: number, lon: number, baseQuat: THREE.Quaternion) {
    // location & north direction in *local* (unrotated) space
    const L_local = this.ll(lat, lon, 1.0).normalize();
    const N_local = this.northTangentLocal(lat, lon);

    // convert those directions into *world* space under the current orientation
    const Lw = L_local.clone().applyQuaternion(baseQuat).normalize();
    const Nw0 = N_local.clone().applyQuaternion(baseQuat).normalize();

    // orthonormalize: make north tangent perpendicular to Lw
    const Nw = Nw0.sub(Lw.clone().multiplyScalar(Nw0.dot(Lw))).normalize();

    // right-handed basis at target: X = N × L, Y = N, Z = L
    const Xw = new THREE.Vector3().crossVectors(Nw, Lw).normalize();

    // B maps canonical axes -> (Xw,Yw,Lw). We want inverse to map (Xw,Yw,Lw) -> canonical.
    const B = new THREE.Matrix4().makeBasis(Xw, Nw, Lw);
    const R = B.clone().transpose(); // inverse for orthonormal basis

    const qRot = new THREE.Quaternion().setFromRotationMatrix(R);
    return qRot.multiply(baseQuat.clone());
  }

  warmup() {
    // compile shaders + upload textures once before we fade in
    this.renderer.compile(this.scene, this.camera);
    this.renderer.render(this.scene, this.camera);
  }

  /** Mini-globe use: lock earth to location instantly + marker on */
  setFixedLocation(lat: number, lon: number) {
    this.autorotate = false;
    this.setMarker(lat, lon);

    const zAxis = new THREE.Vector3(0, 0, 1);

    // “home” orientation matches hero’s startRotY
    const qHome = new THREE.Quaternion().setFromEuler(new THREE.Euler(0, this.startRotY, 0));
    const qTo = this.quatToFrontNorthUp(lat, lon, qHome);

    this.earth.quaternion.copy(qTo);
  }

  async setMarker(lat: number, lon: number) {
    await this.ready;
    this.marker.position.copy(this.ll(lat, lon, 1.05));
    this.marker.visible = true;
  }

  async flyTo(lat: number, lon: number, durationMs = 2200) {
    await this.ready;
    // stop earth spin; clouds drift continues
    this.autorotate = false;
    await this.setMarker(lat, lon);

    const target = this.ll(lat, lon, 1.0).normalize();
    const zAxis = new THREE.Vector3(0, 0, 1);

    const qFrom = this.earth.quaternion.clone();

    const targetLocal = this.ll(lat, lon, 1.0).normalize();
    const targetWorld = targetLocal.clone().applyQuaternion(qFrom);

    const qTo = this.quatToFrontNorthUp(lat, lon, qFrom);

    const camFrom = this.camera.position.clone();
    const camTo = new THREE.Vector3(0, 0, 3.4);

    await new Promise<void>((resolve) => {
      const tStart = performance.now();
      const step = (now: number) => {
        if (!this.alive) return resolve(); // ✅ abort cleanly on unmount
        const u = Math.min(1, (now - tStart) / durationMs);
        const k = easeInOutCubic(u);

        this.earth.quaternion.copy(qFrom).slerp(qTo, k);
        this.camera.position.lerpVectors(camFrom, camTo, k);
        this.camera.lookAt(0, 0, 0);

        if (u < 1) this.flyRaf = requestAnimationFrame(step);
        else resolve();
      };
      this.flyRaf = requestAnimationFrame(step);
    });

    this.opts.onArrive?.();
  }

  /** Start the “data reveal cycle” so it begins at 0 when called */
  startDataRevealCycle() {
    this.dataCycleT0 = this.getT();
  }

  stopDataRevealCycle() {
   this.dataCycleT0 = null;
  }

  runWarmingSequence(opts: {
    lat: number;
    lon: number;
    revealDelayMs?: number;   // wait before blending to data
    revealFadeMs?: number;    // blend duration
    spinDelayMs?: number;     // wait after blend before spin
    spinSpeed?: number;       // if you support this; otherwise ignore
  }) {
    const {
      lat,
      lon,
      revealDelayMs = 500,
      revealFadeMs = 1800,
      spinDelayMs = 300,
    } = opts;

    // No clouds for this mode (caller should also set enableClouds:false)
    this.setAutorotate(false);

    // Fix view on location
    this.setFixedLocation(lat, lon);

    // Ensure no cycle overrides
    this.stopDataRevealCycle();

    // Start from “no data overlay”
    this.setDataOpacity(0, 0);

    // Blend to warming overlay
    window.setTimeout(() => {
      this.setDataOpacity(1, revealFadeMs);

      // Start slow spin after blend
      window.setTimeout(() => {
        this.setAutorotate(true);
      }, revealFadeMs + spinDelayMs);
    }, revealDelayMs);
  }

  /** Clouds are pre-warmed at opacity 0; reveal just fades opacity up */
  requestCloudsReveal() {
    if (!this.enableClouds) return;
    this.cloudsRequestedReveal = true;
    if (this.cloudsTex) {
      fadeMaterialOpacity(this.cloudsTex.material as any, 0.85, this.timings.cloudsFadeMs);
    }
  }

  /** For mini-globe “turn data on once” */
  setDataOpacity(to: number, fadeMs = 700) {
    const u = this.uniforms.dataOpacity;
    if (!u) return;
    const from = u.value as number;
    const t0 = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - t0) / fadeMs);
      const k = easeOutCubic(t);
      u.value = from + (to - from) * k;
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /** Equivalent of your revealClouds()+revealData() sequencing */
  async runIntroSequence() {
    if (this.introStarted) return;
    this.introStarted = true;
    // clouds after globe fade
    void (async () => {
      await delay(this.timings.globeFadeMs + this.timings.cloudsDelayAfterGlobeMs);
      this.requestCloudsReveal();
    })();

    // data cycle starts after delay
    void (async () => {
      await delay(this.timings.globeFadeMs + this.timings.dataDelayAfterGlobeMs);
      this.startDataRevealCycle();
    })();
  }

  /** Call once after init to start rendering */
  start() {
    if (this.running) return; // ✅ prevents double start
    this.running = true;
    this.t0 = performance.now();
    this.animate();
  }

  // -------------------- init --------------------
  async init() {
    try {
      const ext = (await GlobeEngine.supportsAvif()) ? "avif" : "webp";

      const isMobile = Math.min(window.innerWidth, window.innerHeight) < 700;

      const desktopSize = this.opts.desktopSize ?? 4096;
      const mobileSize = this.opts.mobileSize ?? 2048;
      const size = isMobile ? mobileSize : desktopSize;

      const desktopSmall = this.opts.desktopSmallSize ?? 2048;
      const mobileSmall = this.opts.mobileSmallSize ?? 1024;
      const smallSize = isMobile ? mobileSmall : desktopSmall;

      const a = this.opts.assets;
      const base = a.basePath.replace(/\/$/, "");

      const landPrefix = a.landPrefix ?? "land_";
      const cloudsPrefix = a.cloudsPrefix ?? "clouds_";
      const bordersPrefix = a.bordersPrefix ?? "borders_";
      const dataPrefix = a.dataPrefix ?? "data_";
      const markerFile = a.markerFile ?? "marker.png";
      const emptyFile = a.emptyFile ?? "empty.png";

      const LAND_MASK_URL = `${base}/${landPrefix}${size}.${ext}`;
      const CLOUD_TEX_URL = `${base}/${cloudsPrefix}${size}.${ext}`;
      // you intentionally use webp for borders for sharpness (same as your file)
      const BORDERS_TEX_URL = `${base}/${bordersPrefix}${size}.webp`;
      const DATA_TEX_URL = `${base}/${dataPrefix}${smallSize}.${ext}`;

      await this.buildEarth({
        LAND_MASK_URL,
        BORDERS_TEX_URL,
        DATA_TEX_URL,
        emptyUrl: `${base}/${emptyFile}`,
        enableBorders: this.enableBorders,
        enableData: this.enableData,
      });

      await this.buildMarker(`${base}/${markerFile}`);
      this.readyResolve(); // ✅ marker is now created

      // clouds load async; doesn’t block main draw
      if (this.enableClouds) {
        this.loadClouds(CLOUD_TEX_URL).catch((e) => console.warn("Clouds failed:", e));
      }

    } catch (e) {
      this.opts.onError?.(e);
      throw e;
    }
  }

  getSnapshot() {
    const q = this.earth.quaternion;
    return {
        earthQuat: [q.x, q.y, q.z, q.w] as [number, number, number, number],
        cloudsRotY: this.cloudsTex ? this.cloudsTex.rotation.y : 0,
        cameraZ: this.camera.position.z,
    };
  }

    applySnapshot(s: { earthQuat: [number, number, number, number]; cloudsRotY: number; cameraZ: number }) {
    this.earth.quaternion.set(s.earthQuat[0], s.earthQuat[1], s.earthQuat[2], s.earthQuat[3]);
    if (this.cloudsTex) this.cloudsTex.rotation.y = s.cloudsRotY;
    this.camera.position.z = s.cameraZ;
  }

  // -------------------- internals --------------------
  private getT() {
    return (performance.now() - this.t0) / 1000;
  }

  private makeLoader() {
    const loader = new THREE.TextureLoader();
    const loadTex = (url: string, colorSpace: THREE.ColorSpace) =>
      new Promise<THREE.Texture>((resolve, reject) => {
        loader.load(
          url,
          (t) => {
            t.colorSpace = colorSpace;
            t.anisotropy = 8;
            //t.flipY = false;
            t.premultiplyAlpha = false as any; // (some builds expose it; harmless if ignored)
            resolve(t);
          },
          undefined,
          reject
        );
      });

    return { loadTex };
  }

  private async buildEarth(params: {
    LAND_MASK_URL: string;
    BORDERS_TEX_URL: string;
    DATA_TEX_URL: string;
    emptyUrl: string;
    enableBorders: boolean;
    enableData: boolean;
  }) {
    const { loadTex } = this.makeLoader();

    const landMask = await loadTex(params.LAND_MASK_URL, THREE.SRGBColorSpace);

    const loadTexSafe = async (enable: boolean, url: string) => {
      const fallback = await loadTex(params.emptyUrl, THREE.SRGBColorSpace);
      if (!enable) return fallback;
      try {
        return await loadTex(url, THREE.SRGBColorSpace);
      } catch (e) {
        console.warn("Texture failed:", url, e);
        return fallback;
      }
    };

    const bordersTex = await loadTexSafe(params.enableBorders, params.BORDERS_TEX_URL);
    const dataTex = await loadTexSafe(params.enableData, params.DATA_TEX_URL);

    const COLORS = {
      ocean: this.opts.ocean ?? 0xe0e0e0,
      land: this.opts.land ?? 0x5c85c6,
      grid: this.opts.grid ?? 0x49494b,
      border: this.opts.border ?? 0xffffff,
      marker: this.opts.marker ?? 0xdb4848,
    };

    const MASK_INVERT = this.opts.maskInvert ?? 1.0;

    this.uniforms = {
      landMask: { value: landMask },
      bordersTex: { value: bordersTex },
      dataTex: { value: dataTex },

      oceanColor: { value: new THREE.Color(COLORS.ocean) },
      landColor: { value: new THREE.Color(COLORS.land) },
      gridColor: { value: new THREE.Color(COLORS.grid) },
      borderColor: { value: new THREE.Color(COLORS.border) },
      lightDir: { value: new THREE.Vector3().copy(this.sun.position).normalize() },

      maskInvert: { value: MASK_INVERT },

      shadeStrength: { value: this.opts.shadeStrength ?? 0.2 },
      brightness: { value: this.opts.brightness ?? 1.05 },

      gridEveryDeg: { value: 10.0 },
      gridWidth: { value: 0.010 },
      gridOpacity: { value: 0.20 },

      bordersOpacity: { value: 0.22 },
      dataStrength: { value: 1.0 },
      dataOpacity: { value: 0.0 },
    };

    this.earthMat = new THREE.ShaderMaterial({
      uniforms: this.uniforms,
      toneMapped: false,
      vertexShader: `
        varying vec2 vUv;
        varying vec3 vNormalW;
        void main(){
          vUv = uv;
          vNormalW = normalize(mat3(modelMatrix) * normal);
          vec4 wp = modelMatrix * vec4(position, 1.0);
          gl_Position = projectionMatrix * viewMatrix * wp;
        }
      `,
      fragmentShader: `
        #include <common>
        varying vec2 vUv;
        varying vec3 vNormalW;

        uniform sampler2D landMask;
        uniform sampler2D bordersTex;
        uniform sampler2D dataTex;

        uniform vec3 oceanColor;
        uniform vec3 landColor;
        uniform vec3 gridColor;
        uniform vec3 borderColor;
        uniform vec3 lightDir;

        uniform float maskInvert;
        uniform float shadeStrength;
        uniform float brightness;

        uniform float gridEveryDeg;
        uniform float gridWidth;
        uniform float gridOpacity;
        uniform float bordersOpacity;

        uniform float dataStrength;
        uniform float dataOpacity;

        float saturatef(float x){ return clamp(x, 0.0, 1.0); }

        float gridLine(float coord, float linesPerUnit, float width){
          float x = fract(coord * linesPerUnit);
          float d = min(x, 1.0 - x);
          return 1.0 - smoothstep(0.0, width, d);
        }

        void main(){
          float m = texture2D(landMask, vUv).r;
          float land = step(0.5, mix(m, 1.0 - m, maskInvert));
          vec3 base = mix(oceanColor, landColor, land);

          vec3 N = normalize(vNormalW);
          float ndl = dot(N, normalize(lightDir));
          float day = saturatef(ndl * 0.8 + 0.25);
          float sphereShade = mix(0.85, 1.15, day);
          base *= mix(1.0, sphereShade, shadeStrength);

          base *= brightness;

          float linesLon = 360.0 / gridEveryDeg;
          float linesLat = 180.0 / gridEveryDeg;

          float poleFade = smoothstep(1.0, 0.72, abs(vUv.y * 2.0 - 1.0));
          float glon = gridLine(vUv.x, linesLon, gridWidth);
          float glat = gridLine(vUv.y, linesLat, gridWidth);
          float g = max(glon, glat) * gridOpacity * poleFade;

          float ba = texture2D(bordersTex, vUv).a * bordersOpacity * poleFade;

          vec4 d = texture2D(dataTex, vUv);
          vec3 dataColor = d.rgb;
          float da = d.a * dataStrength * dataOpacity;
          vec3 withData = mix(base, dataColor, da);

          vec3 withBorders = mix(withData, borderColor, ba);
          vec3 withGrid = mix(withBorders, gridColor, g);

          gl_FragColor = vec4(withGrid, 1.0);
          #include <colorspace_fragment>
        }
      `,
    });

    this.earth = new THREE.Mesh(new THREE.SphereGeometry(1.0, 256, 256), this.earthMat);
    this.earth.rotation.y = this.startRotY; // ensure same base orientation for hero+mini
    this.scene.add(this.earth);
  }

  private async buildMarker(markerUrl: string) {
    const { loadTex } = this.makeLoader();
    const markerTex = await loadTex(markerUrl, THREE.SRGBColorSpace);

    const mat = new THREE.SpriteMaterial({ map: markerTex, transparent: true, depthWrite: false });
    this.marker = new THREE.Sprite(mat);
    this.marker.scale.set(0.18, 0.18, 0.18);
    this.marker.visible = false;
    this.earth.add(this.marker);
  }

  private async loadClouds(url: string) {
    const loader = new THREE.TextureLoader();

    const cloudTex = await new Promise<THREE.Texture>((resolve, reject) => {
      loader.load(
        url,
        (t) => {
          t.colorSpace = THREE.NoColorSpace;
          t.wrapS = THREE.RepeatWrapping;
          t.wrapT = THREE.ClampToEdgeWrapping;
          t.anisotropy = 8;
          // t.flipY = false;
          t.premultiplyAlpha = false as any; // (some builds expose it; harmless if ignored)
          resolve(t);
        },
        undefined,
        reject
      );
    });

    const mat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.0, // prewarm invisible
      alphaMap: cloudTex,
      depthWrite: false,
    });
    mat.alphaTest = 0.02;

    this.cloudsTex = new THREE.Mesh(new THREE.SphereGeometry(1.018, 256, 256), mat);
    this.earth.add(this.cloudsTex);

    // prewarm: visible at opacity 0 so first GPU upload happens immediately
    this.cloudsTex.visible = true;

    // if reveal was already requested before clouds finished loading, start fade now
    if (this.cloudsRequestedReveal) {
      fadeMaterialOpacity(mat as any, 0.85, this.timings.cloudsFadeMs);
    }
  }

  private animate = () => {
    if (!this.running || !this.alive) return;
    this.raf = requestAnimationFrame(this.animate);

    const t = this.getT();

    if (this.autorotate) {
      this.earth.rotation.y = this.startRotY + t * 0.08;
    }

    // marker pulse
    if (this.marker.visible) {
      const s = 0.18 * (1.0 + 0.10 * Math.sin(t * 2.2));
      this.marker.scale.set(s, s, s);
    }

    // clouds drift (local)
    if (this.cloudsTex) {
      this.cloudsTex.rotation.y = t * this.cloudDriftSpeed;
    }

    if (this.dataCycleT0 != null) {
      // data reveal cycle (starts at 0 when dataCycleT0 is set)
      const dt = this.dataCycleT0 == null ? 0 : Math.max(0, t - this.dataCycleT0);
      const raw = 0.5 + 0.5 * Math.sin(dt * 0.12 - Math.PI / 2); // starts at 0
      const bloom = raw * raw; // your current eased curve
      this.uniforms.dataOpacity.value = bloom;
    }

    this.uniforms.lightDir.value.copy(this.sun.position).normalize();

    this.renderer.render(this.scene, this.camera);
  };

  static latLonToVec3(latDeg: number, lonDeg: number, r = 1.0) {
    const lat = THREE.MathUtils.degToRad(latDeg);
    const lon = THREE.MathUtils.degToRad(lonDeg);
    const x = r * Math.cos(lat) * Math.sin(lon);
    const y = r * Math.sin(lat);
    const z = r * Math.cos(lat) * Math.cos(lon);
    return new THREE.Vector3(x, y, z);
  }

  static supportsAvif() {
    return new Promise<boolean>((resolve) => {
      const img = new Image();
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src =
        "data:image/avif;base64," +
        "AAAAIGZ0eXBhdmlmAAAAAGF2aWZtaWYxbWlhZk1BMUIAAADybWV0YQAAAAAAAAAoaGRscgAAAAAAAAAAcGljdAAAAAAAAAAAAAAAAGxpYmF2aWYAAAAADnBpdG0AAAAAAAEAAAAeaWxvYwAAAABEAAABAAEAAAABAAABGgAAAB0AAAAoaWluZgAAAAAAAQAAABppbmZlAgAAAAABAABhdjAxQ29sb3IAAAAAamlwcnAAAABLaXBjbwAAABRpc3BlAAAAAAAAAAIAAAACAAAAEHBpeGkAAAAAAwgICAAAAAxhdjFDgQ0MAAAAABNjb2xybmNseAACAAIAAYAAAAAXaXBtYQAAAAAAAAABAAEEAQKDBAAAACVtZGF0EgAKCBgANogQEAwgMg8f8D///8WfhwB8+ErK42A=";
    });
  }
}
