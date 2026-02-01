import * as THREE from "https://esm.sh/three@0.160.0";

// --- Assets (all 2:1 equirectangular) ---

// References for textures (check licenses)
// Clouds
// https://commons.wikimedia.org/wiki/File:Solarsystemscope_texture_8k_earth_clouds.jpg

// Land
// http://shadedrelief.com/natural3/ne3_data/8192/masks/water_8k.png

// Warming
// Self generated from CDS

// Borders?
// Matplotlib version3.10.7, https://matplotlib.org/ (TBC)

let dataCycleT0 = null; // seconds, set when data is revealed

const enableBorders = false;
const enableData = false;

const TIMING = {
  globeFadeMs: 4000,

  cloudsDelayAfterGlobeMs: 1000,
  cloudsFadeMs: 4000,

  dataDelayAfterGlobeMs: 2000,
};

// sync CSS and JS
document.documentElement.style.setProperty("--globe-fade-ms", `${TIMING.globeFadeMs}ms`);

const isSmall = Math.min(window.innerWidth, window.innerHeight) < 700;
const dpr = Math.min(window.devicePixelRatio || 1, 2);

function supportsAvif() {
  // quick AVIF decode test
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(true);
    img.onerror = () => resolve(false);
    img.src =
      "data:image/avif;base64," +
      "AAAAIGZ0eXBhdmlmAAAAAGF2aWZtaWYxbWlhZk1BMUIAAADybWV0YQAAAAAAAAAoaGRscgAAAAAAAAAAcGljdAAAAAAAAAAAAAAAAGxpYmF2aWYAAAAADnBpdG0AAAAAAAEAAAAeaWxvYwAAAABEAAABAAEAAAABAAABGgAAAB0AAAAoaWluZgAAAAAAAQAAABppbmZlAgAAAAABAABhdjAxQ29sb3IAAAAAamlwcnAAAABLaXBjbwAAABRpc3BlAAAAAAAAAAIAAAACAAAAEHBpeGkAAAAAAwgICAAAAAxhdjFDgQ0MAAAAABNjb2xybmNseAACAAIAAYAAAAAXaXBtYQAAAAAAAAABAAEEAQKDBAAAACVtZGF0EgAKCBgANogQEAwgMg8f8D///8WfhwB8+ErK42A=";
  });
}

// Choose size based on desktop size
const size = (Math.min(innerWidth, innerHeight) < 700) ? 2048 : 4096;

// Use smaller size for data texture
const smallSize = (Math.min(innerWidth, innerHeight) < 700) ? 1024 : 2048;

// Choose texture format based on compatibility (avif is smaller)
const ext = (await supportsAvif()) ? "avif" : "webp";

const LAND_MASK_URL = `./textures/land_${size}.${ext}`;
const STICKER_TEX_URL = `./textures/sphere.png`; // <-- put your transparent PNG here
const CLOUD_TEX_URL = `./textures/clouds_${size}.${ext}`;
const BORDERS_TEX_URL = `./textures/borders_${size}.webp`; // Use webp for borders for sharpness
const DATA_TEX_URL = `./textures/data_${smallSize}.${ext}`;

// Invert land/border mask (ocean=white, land=black)
const MASK_INVERT = 1.0;

const COLORS = {
  ocean: 0xF0F0F0,   // light grey
  land:  0xFFFFFF,   // same as ocean; land will be shown via coastline outline
  ink:   0x111111,   // dot “ink”
  coast: 0x1A1A1A,   // coastline stroke
  grid:  0x49494B,
  border: 0xFFFFFF,
  marker: 0xDB4848,
};

const START_ROT_Y = Math.PI; // 180° (other side)

const canvas = document.getElementById("c");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight, false);
// keep sRGB output (we ALSO do explicit shader output conversion)
renderer.outputColorSpace = THREE.SRGBColorSpace;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(0, 0, 4.0);

const sun = new THREE.DirectionalLight(0xffffff, 0.9);
sun.position.set(3, 1.5, 2.5);
scene.add(new THREE.AmbientLight(0xffffff, 0.85));
scene.add(sun);

const loader = new THREE.TextureLoader();
function loadTex(url){
  return new Promise((resolve, reject) => {
    loader.load(url, (t) => {
      t.colorSpace = THREE.SRGBColorSpace;
      t.anisotropy = 8;
      resolve(t);
    }, undefined, reject);
  });
}

// Map look controls
const uniforms = {
  landMask: { value: null },
  bordersTex: { value: null },
  dataTex: { value: null },

  // NEW: screen-space overlay (sampled in fragment shader)
  overlayTex: { value: null },
  overlayOpacity: { value: 1.0 }, // 0..1
  overlayScale:   { value: 0.825 },              // < 1 => smaller, > 1 => larger
  overlayOffset:  { value: new THREE.Vector2(0, 0) }, // in UV units

  oceanColor: { value: new THREE.Color(COLORS.ocean) },
  landColor:  { value: new THREE.Color(COLORS.land)  },

  // NEW: “ink” + coastline
  inkColor:   { value: new THREE.Color(COLORS.ink) },
  coastColor: { value: new THREE.Color(COLORS.coast) },

  // NEW: used to compute coastline thickness in UV space
  landTexel:  { value: new THREE.Vector2(1 / 2048, 1 / 1024) }, // overwritten after texture load

  gridColor:  { value: new THREE.Color(COLORS.grid)  },
  borderColor:{ value: new THREE.Color(COLORS.border) },
  // Make terminator visible: light comes from the side a bit
  lightDir: { value: new THREE.Vector3( -0.85, 0.55, 1.25 ).normalize() },

  maskInvert: { value: MASK_INVERT },

  // We'll rely on halftone for shading, so keep the smooth shading minimal.
  shadeStrength: { value: 0.0 },
  brightness:    { value: 1.0 },

  // Grid off for the newspaper look
  gridEveryDeg: { value: 10.0 },
  gridWidth:    { value: 0.010 },
  gridOpacity:  { value: 0.0 },

  bordersOpacity: { value: 0.0 },
  dataStrength:   { value: 1.0 },
  dataOpacity:    { value: 0.0 },

  // Stochastic stipple controls (single-layer)
  stippleScale:     { value: 0.0 },//500.0 }, // dot density grid; try 700..1400
  stippleStrength:  { value: 0.0 },//2.9 },  // overall ink amount
  stippleRadius:    { value: 0.0 },//0.26 },  // dot radius in cell-space; try 0.14..0.22
  stippleSoftness:  { value: 0.16 },  // fade width for in/out; try 0.03..0.10
  stippleGamma:     { value: 0.65 },  // shape shade→density; try 1.0..1.6

  rimFade:          { value: 0.62 },  // keep (reduces crunchy silhouette)

  shadeGain: { value: 2.9 },  // increase to get blacker shadows
  shadeBias: { value: -0.05 }, // slight bias to keep highlights cleaner
  shadow2Start: { value: 0.45 }, // when second dot candidate starts

  // NEW: coastline intensity/thickness tuning
  coastStrength: { value: 0.95 }, // 0..1
  coastSoftness: { value: 1.2 },  // >1 softer
};

const earthMat = new THREE.ShaderMaterial({
  uniforms,
  toneMapped: false,
  vertexShader: `
    varying vec2 vUv;
    varying vec3 vNormalW;
    varying vec3 vPosW;
    varying vec4 vClipPos;

    void main(){
      vUv = uv;
      vNormalW = normalize(mat3(modelMatrix) * normal);
      vec4 wp = modelMatrix * vec4(position, 1.0);
      vPosW = wp.xyz;

      vClipPos = projectionMatrix * viewMatrix * wp;
      gl_Position = vClipPos;
    }
  `,
  fragmentShader: `
  #include <common>
  varying vec2 vUv;
  varying vec3 vNormalW;
  varying vec3 vPosW;
  varying vec4 vClipPos;

  uniform sampler2D landMask;
  uniform sampler2D bordersTex;
  uniform sampler2D dataTex;

  // NEW: overlay sampled in screen space
  uniform sampler2D overlayTex;
  uniform float overlayOpacity;
  uniform float overlayScale;
  uniform vec2 overlayOffset;

  uniform vec3 oceanColor;
  uniform vec3 landColor;

  uniform vec3 inkColor;
  uniform vec3 coastColor;

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

  uniform vec2  landTexel;

  uniform float stippleScale;
  uniform float stippleStrength;
  uniform float stippleRadius;
  uniform float stippleSoftness;
  uniform float stippleGamma;

  uniform float rimFade;

  uniform float shadeGain;
  uniform float shadeBias;
  uniform float shadow2Start;

  uniform float coastStrength;
  uniform float coastSoftness;

  float saturatef(float x){ return clamp(x, 0.0, 1.0); }

  float gridLine(float coord, float linesPerUnit, float width){
    float x = fract(coord * linesPerUnit);
    float d = min(x, 1.0 - x);
    return 1.0 - smoothstep(0.0, width, d);
  }

  vec2 rot2(vec2 p, float a){
    float s = sin(a), c = cos(a);
    return mat2(c,-s,s,c) * p;
  }

  float hash12(vec2 p){
    // Stable hash in [0,1)
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }

  // Returns 0..1 ink coverage for ONE dot layer.
  // Dots are randomly placed (1 candidate per cell), density controlled by shade.
  float stippleInk(vec2 uv, float shade){
    // compensate for equirectangular stretch towards poles (helps uniform dot size)
    float lat = (uv.y - 0.5) * 3.14159265;
    float k = max(0.35, cos(lat));
    vec2 uvIso = vec2(uv.x * k, uv.y);

    // shade: 0 bright .. 1 dark, shaped by gamma
    float s0 = clamp(shade, 0.0, 1.0);
    float s  = pow(s0, stippleGamma);

    // add a little extra boost only in the dark end
    s = mix(s, 1.0, smoothstep(0.65, 1.0, s0) * 0.25);

    // one candidate dot per cell
    vec2 p = uvIso * stippleScale;
    vec2 cell = floor(p);

    // random point within the cell
    float rx = hash12(cell + 13.2);
    float ry = hash12(cell + 71.9);
    vec2  center = vec2(rx, ry);

    // distance to that random point (cell-space)
    vec2 f = fract(p);
    float d = length(f - center);

    // dot shape (constant radius)
    float r = clamp(stippleRadius, 0.02, 0.48);
    float aa = max(fwidth(d) * 1.35, 0.0025);
    float dotShape = 1.0 - smoothstep(r - aa, r + aa, d);

    // density gate: probability of dot being "on" grows with shade
    float t = max(stippleSoftness, 0.001);
    float gateRand = hash12(cell + 191.7);

    // smooth probabilistic gate (reduces popping as light moves)
    float gate = smoothstep(gateRand - t, gateRand + t, s);

    float ink = dotShape * gate;

    // In deep shadow, allow a second independent candidate.
    // Visually it still reads like one stipple layer, just denser.
    float shadow2 = smoothstep(shadow2Start, 1.0, s);
    if (shadow2 > 0.0) {
      float rx2 = hash12(cell + 201.3);
      float ry2 = hash12(cell + 419.6);
      vec2  center2 = vec2(rx2, ry2);

      float d2 = length(f - center2);
      float dot2 = 1.0 - smoothstep(r - aa, r + aa, d2);

      float gateRand2 = hash12(cell + 777.7);
      float gate2 = smoothstep(gateRand2 - t, gateRand2 + t, s);

      ink += dot2 * gate2 * shadow2;
    }

    return clamp(ink, 0.0, 1.0);
  }


  float coastline(vec2 uv){
    // Land mask edge detector (UV-space). landTexel is 1/textureSize.
    float m  = texture2D(landMask, uv).r;
    float mx = texture2D(landMask, uv + vec2( landTexel.x, 0.0)).r;
    float my = texture2D(landMask, uv + vec2(0.0,  landTexel.y)).r;
    float mx2= texture2D(landMask, uv + vec2(-landTexel.x, 0.0)).r;
    float my2= texture2D(landMask, uv + vec2(0.0, -landTexel.y)).r;

    float e = max(max(abs(m-mx), abs(m-my)), max(abs(m-mx2), abs(m-my2)));
    // Tune these two numbers if your land mask is “soft”
    float a = smoothstep(0.04, 0.22, e);
    return a;
  }

  void main(){
    float m = texture2D(landMask, vUv).r;
    float land = step(0.5, mix(m, 1.0 - m, maskInvert));

    // Monochrome base (land==ocean, but keep land var if you want later)
    vec3 base = mix(oceanColor, landColor, land);

    // Lighting drives dot density
    vec3 N = normalize(vNormalW);
    float ndl  = dot(N, normalize(lightDir));
    float day  = clamp(ndl * 0.5 + 0.5, 0.0, 1.0); // 0 night -> 1 day
    day        = smoothstep(0.08, 0.92, day);
    float shade = 1.0 - day; // 0 day -> 1 night

    // NEW: explicit remap to reach deep shadows
    shade = clamp(shade * shadeGain + shadeBias, 0.0, 1.0);

    // extra punch in deep shadow
    shade = pow(shade, 0.85);  // <1 => darker shadows

    // Optional smooth shading (kept mostly off by default)
    float sphereShade = mix(0.92, 1.08, day);
    base *= mix(1.0, sphereShade, shadeStrength);

    // Halftone “ink” dots
    float ink = stippleInk(vUv, shade);

    // rim fade (keep your existing code)
    vec3 V = normalize(cameraPosition - vPosW);
    float ndv = clamp(dot(normalize(vNormalW), V), 0.0, 1.0);
    float rim = smoothstep(0.08, 0.55, ndv);
    float dotFade = mix(1.0 - rimFade, 1.0, rim);

    base = mix(base, inkColor, ink * stippleStrength * dotFade);

    // Coastline outline on top
    float coast = coastline(vUv);
    // soften a touch near poles to avoid noisy sampling at extreme UV squeeze
    float poleFade = smoothstep(1.0, 0.68, abs(vUv.y * 2.0 - 1.0));
    float ca = pow(coast * poleFade, coastSoftness) * coastStrength;
    base = mix(base, coastColor, ca);

    // If you want to keep your existing grid/borders hooks:
    float linesLon = 360.0 / gridEveryDeg;
    float linesLat = 180.0 / gridEveryDeg;
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

    vec3 outRgb = withGrid * brightness;

    // Screen-space UV in [0,1]
    vec2 screenUV = (vClipPos.xy / vClipPos.w) * 0.5 + 0.5;
    // Most PNGs are authored top-left origin
    screenUV.y = 1.0 - screenUV.y;

    // Scale around center (0.5,0.5)
    // Aspect-correct scale around center so circles stay circles even if viewport isn't square.
    vec2 centered = screenUV - 0.5;

    // Apply scale
    centered.x /= overlayScale * 0.465;
    centered.y /= overlayScale;

    vec2 uv = centered + 0.5 + overlayOffset;

    // Sample overlay + alpha composite (over)
    if (overlayOpacity > 0.0) {

      // Hard mask outside [0,1] so we never smear edge pixels
      float inside =
          step(0.0, uv.x) * step(0.0, uv.y) *
          step(uv.x, 1.0) * step(uv.y, 1.0);

      vec2 uvClamped = clamp(uv, 0.0, 1.0);
      vec4 o = texture2D(overlayTex, uvClamped);

      vec3 oLin = o.rgb;
      float a = clamp(o.a * overlayOpacity * inside, 0.0, 1.0);
      outRgb = mix(outRgb, oLin, a);
    }

    gl_FragColor = vec4(outRgb, 1.0);
  }
`,
});

const earth = new THREE.Mesh(new THREE.SphereGeometry(1.0, 256, 256), earthMat);
scene.add(earth);

let cloudsTex = null;

function loadCloudTex(url){
  return new Promise((resolve, reject) => {
    loader.load(url, (t) => {
      // Cloud textures are usually “data-ish” (not color-corrected artwork)
      // so avoid sRGB conversion unless you specifically want it.
      t.colorSpace = THREE.NoColorSpace;
      t.wrapS = THREE.RepeatWrapping;
      t.wrapT = THREE.ClampToEdgeWrapping;
      t.anisotropy = 8;
      resolve(t);
    }, undefined, reject);
  });
}

loadCloudTex(CLOUD_TEX_URL).then((cloudTex) => {
  const mat = new THREE.MeshBasicMaterial({
    color: 0xffffff,
    transparent: true,
    opacity: 0.0,
    alphaMap: cloudTex,
    depthWrite: false,
  });
  mat.alphaTest = 0.02;

  cloudsTex = new THREE.Mesh(new THREE.SphereGeometry(1.018, 256, 256), mat);
  earth.add(cloudsTex);

  cloudsTex.visible = true;          // important: must be drawn to upload to GPU
});

function fadeMaterialOpacity(mat, to, ms = 700) {
  const from = mat.opacity;
  const t0 = performance.now();

  function step(now) {
    const t = Math.min(1, (now - t0) / ms);
    // ease out
    const k = 1 - Math.pow(1 - t, 3);
    mat.opacity = from + (to - from) * k;
    mat.needsUpdate = true;
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// Marker sprite
const marker = new THREE.Sprite(new THREE.SpriteMaterial({ map: null, transparent: true, depthWrite: false }));
marker.scale.set(0.18, 0.18, 0.18);
marker.visible = false;
earth.add(marker);          // <— attach to earth
marker.position.set(0,0,0); // local space now

function latLonToVec3(latDeg, lonDeg, r=1.01){
  const lat = THREE.MathUtils.degToRad(latDeg);
  const lon = THREE.MathUtils.degToRad(lonDeg);
  const x = r * Math.cos(lat) * Math.sin(lon);
  const y = r * Math.sin(lat);
  const z = r * Math.cos(lat) * Math.cos(lon);
  return new THREE.Vector3(x,y,z);
}

function setMarker(lat, lon){
  marker.position.copy(latLonToVec3(lat, lon, 1.05));
  marker.visible = true;
}

// Tween + flyTo
function easeInOutCubic(t){ return t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3)/2; }
function tween(durationMs, onUpdate){
  return new Promise(resolve => {
    const tStart = performance.now();
    function step(now){
      const t = Math.min(1, (now - tStart) / durationMs);
      onUpdate(easeInOutCubic(t), t);
      if(t < 1) requestAnimationFrame(step);
      else resolve();
    }
    requestAnimationFrame(step);
  });
}

async function flyTo(lat, lon, durationMs=2200){
  const target = latLonToVec3(lat, lon, 1.0).normalize();
  const zAxis = new THREE.Vector3(0, 0, 1);

  const qFrom = earth.quaternion.clone();
  const qTo = new THREE.Quaternion().setFromUnitVectors(target, zAxis).multiply(qFrom);

  const camFrom = camera.position.clone();
  const camTo = new THREE.Vector3(0, 0, 3.2);

  setMarker(lat, lon);

  await tween(durationMs, (k) => {
    THREE.Quaternion.slerp(qFrom, qTo, earth.quaternion, k);
    camera.position.lerpVectors(camFrom, camTo, k);
    camera.lookAt(0,0,0);
  });
}

function setClouds(on){
  if (cloudsTex) cloudsTex.visible = !!on;
}

// Live tweak helpers
function setShadeStrength(x){ uniforms.shadeStrength.value = Math.max(0, Math.min(1, x)); }
function setBrightness(x){ uniforms.brightness.value = Math.max(0, x); }

// DEV ONLY
window.flyTo = flyTo;
window.setMarker = setMarker;
window.setClouds = setClouds;
window.setShadeStrength = setShadeStrength;
window.setBrightness = setBrightness;

// Resize
function resize(){
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix()
}
window.addEventListener("resize", resize);

// Auto rotate for landing (earth rotates, clouds inherit)
let t0 = performance.now();
let autorotate = true;

function loadTexSafe(enable, url, fallbackUrl = "./textures/empty.png") {
  if (!enable){
    return loadTex(fallbackUrl);
  }
  return loadTex(url).catch((err) => {
    console.warn("Texture failed:", url, err);
    return loadTex(fallbackUrl);
  });
}

Promise.all([
  loadTex(LAND_MASK_URL),                        // required
  loadTexSafe(enableBorders, BORDERS_TEX_URL),   // optional
  loadTexSafe(enableData, DATA_TEX_URL),         // optional
  loadTex("./textures/marker.png"),
  loadTex(STICKER_TEX_URL), // NEW: overlay image
]).then(([landMask, bordersTex, dataTex, markerTex, overlayTex]) => {
  uniforms.landMask.value = landMask;
  uniforms.bordersTex.value = bordersTex;
  uniforms.dataTex.value = dataTex;

  // Overlay: screen-space sample
  overlayTex.wrapS = THREE.ClampToEdgeWrapping;
  overlayTex.wrapT = THREE.ClampToEdgeWrapping;
  overlayTex.minFilter = THREE.LinearFilter;
  overlayTex.magFilter = THREE.LinearFilter;

  // We sample with screenUV.y flipped in shader, so keep the texture unflipped
  overlayTex.flipY = false;
  overlayTex.needsUpdate = true;

  uniforms.overlayTex.value = overlayTex;

  // NEW: coastline edge thickness depends on actual texture resolution
  if (landMask?.image?.width && landMask?.image?.height) {
    uniforms.landTexel.value.set(1 / landMask.image.width, 1 / landMask.image.height);
  }

  marker.material.map = markerTex;
  marker.material.needsUpdate = true;

  canvas.classList.add("is-visible");

  animate();
  // revealClouds();
  revealData();
}).catch((err) => console.error("Texture load failed:", err));

function delay(ms){ return new Promise(r => setTimeout(r, ms)); }

async function revealClouds() {
  await delay(TIMING.globeFadeMs + TIMING.cloudsDelayAfterGlobeMs);
  if (!cloudsTex) return;          // not ready yet
  fadeMaterialOpacity(cloudsTex.material, 0.85, TIMING.cloudsFadeMs);
}

async function revealData() {
  await delay(TIMING.globeFadeMs + TIMING.dataDelayAfterGlobeMs);
  dataCycleT0 = (performance.now() - t0) / 1000;
}

// at top-level:
const CLOUD_DRIFT_SPEED = 0.01; // radians/sec

function animate(){
  requestAnimationFrame(animate);

  const t = (performance.now() - t0) / 1000;

  if(autorotate){
    earth.rotation.y = START_ROT_Y + t * 0.08;
  }

  if(marker.visible){
    const s = 0.18 * (1.0 + 0.10*Math.sin(t*2.2));
    marker.scale.set(s, s, s);
  }

  if (cloudsTex && cloudsTex.visible) {
    cloudsTex.rotation.y = t * CLOUD_DRIFT_SPEED; // local drift, Earth rotation is inherited
  }

  // Data Texture
  // e.g. 0..1..0 slow cycle
  const dt = (dataCycleT0 == null) ? 0 : Math.max(0, t - dataCycleT0);
  const raw = 0.5 + 0.5 * Math.sin(dt * 0.12 - Math.PI / 2); // starts at 0
  const bloom = raw * raw; // * raw; // bias toward 0
  uniforms.dataOpacity.value = bloom;

  // keep fixed; or you can slowly drift it if you like
  // uniforms.lightDir.value.set(-1.0, 0.25, 0.35).normalize();
  const lightCam = new THREE.Vector3(-0.85, 0.55, 1.25).normalize();
  const lightWorld = lightCam.clone().applyQuaternion(camera.quaternion);
  uniforms.lightDir.value.copy(lightWorld).normalize();

  renderer.render(scene, camera);
}
