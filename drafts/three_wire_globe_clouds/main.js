import * as THREE from "https://esm.sh/three@0.160.0";
import { OrbitControls } from "https://esm.sh/three@0.160.0/examples/jsm/controls/OrbitControls.js";

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

// const BORDERS_TEX_URL = "./borders_4096x2048.png";   // optional RGBA (alpha=borders)
// const DATA_TEX_URL    = "./data_4096x2048.webp";   // optional RGBA (alpha=overlay strength)
// const DATA_TEX_URL    = "./empty.png";   // optional RGBA (alpha=overlay strength)

let dataCycleT0 = null; // seconds, set when data is revealed

const enableBorders = true;
const enableData = true;

const TIMING = {
  globeFadeMs: 4000,

  cloudsDelayAfterGlobeMs: 1000,
  cloudsFadeMs: 4000,

  dataDelayAfterGlobeMs: 2000,
};

let dataBaseOpacity = 1.0;

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

const size = (Math.min(innerWidth, innerHeight) < 700) ? 2048 : 4096;

const ext = (await supportsAvif()) ? "avif" : "webp";
const LAND_MASK_URL = `./land_${size}.${ext}`;
const CLOUD_TEX_URL = `./clouds_${size}.${ext}`;

const smallSize = (Math.min(innerWidth, innerHeight) < 700) ? 1024 : 2048;
const BORDERS_TEX_URL = `./borders_${size}.webp`; // Borders in webp for sharpness

const DATA_TEX_URL = `./data_${smallSize}.${ext}`;

// Your mask is inverted (ocean=white, land=black) => set to 1.0
const MASK_INVERT = 1.0;

const COLORS = {
  ocean: 0xE0E0E0,
  land:  0x5C85C6,
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

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.enablePan = false;
controls.minDistance = 2.6;
controls.maxDistance = 6.5;
controls.rotateSpeed = 0.55;

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

  cloudsTex.material.opacity = 0.0;
  cloudsTex.visible = true;          // important: must be drawn to upload to GPU
});

// Map look controls
const uniforms = {
  landMask: { value: null },
  bordersTex: { value: null },
  dataTex: { value: null },

  oceanColor: { value: new THREE.Color(COLORS.ocean) },
  landColor:  { value: new THREE.Color(COLORS.land)  },
  gridColor:  { value: new THREE.Color(COLORS.grid)  },
  borderColor:{ value: new THREE.Color(COLORS.border) },
  lightDir:   { value: new THREE.Vector3().copy(sun.position).normalize() },

  maskInvert: { value: MASK_INVERT },

  // 0 = perfectly flat map
  shadeStrength: { value: 0.2 },
  // global lift to match your editorial background
  brightness:    { value: 1.05 },

  gridEveryDeg: { value: 10.0 },
  gridWidth:    { value: 0.010 },
  gridOpacity:  { value: 0.20 },

  bordersOpacity: { value: 0.22 },
  dataStrength:   { value: 1.0},
  dataOpacity: { value: 0.0 }, // or start at 0.0 if you want to fade it in later
  dataTint: { value: new THREE.Color(1, 1, 1) }, // starts neutral
};

const earthMat = new THREE.ShaderMaterial({
  uniforms,
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
    uniform vec3 dataTint;

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

      // optional sphere shading
      vec3 N = normalize(vNormalW);
      float ndl = dot(N, normalize(lightDir));
      float day = saturatef(ndl * 0.8 + 0.25);
      float sphereShade = mix(0.85, 1.15, day);
      base *= mix(1.0, sphereShade, shadeStrength);

      // brightness lift
      base *= brightness;

      // grid
      float linesLon = 360.0 / gridEveryDeg;
      float linesLat = 180.0 / gridEveryDeg;

      float poleFade = smoothstep(1.0, 0.72, abs(vUv.y * 2.0 - 1.0));
      float glon = gridLine(vUv.x, linesLon, gridWidth);
      float glat = gridLine(vUv.y, linesLat, gridWidth);
      float g = max(glon, glat) * gridOpacity * poleFade;

      // borders
      float ba = texture2D(bordersTex, vUv).a * bordersOpacity * poleFade;

      // optional data overlay
      vec4 d = texture2D(dataTex, vUv);      
      vec3 dcol = d.rgb * dataTint;
      vec3 dataColor = d.rgb;
      float da = d.a * dataStrength * dataOpacity;  // 0..1
      vec3 withData = mix(base, dataColor, da);

      vec3 withBorders = mix(withData, borderColor, ba);
      vec3 withGrid = mix(withBorders, gridColor, g);

      gl_FragColor = vec4(withGrid, 1.0);

      // IMPORTANT: ShaderMaterial does NOT automatically apply output color space conversion.
      #include <colorspace_fragment>
    }
  `,
});

const earth = new THREE.Mesh(new THREE.SphereGeometry(1.0, 256, 256), earthMat);
scene.add(earth);

let cloudsTex = null;

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
    controls.update();
  });
}

function setClouds(on){
  if (cloudsTex) cloudsTex.visible = !!on;
}

// Live tweak helpers
function setShadeStrength(x){ uniforms.shadeStrength.value = Math.max(0, Math.min(1, x)); }
function setBrightness(x){ uniforms.brightness.value = Math.max(0, x); }

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
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);

// Auto rotate for landing (earth rotates, clouds inherit)
let t0 = performance.now();
let autorotate = true;
renderer.domElement.addEventListener("dblclick", () => { autorotate = !autorotate; });

function loadTexSafe(enable, url, fallbackUrl = "./empty.png") {
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
  loadTex("./marker.png"),
]).then(([landMask, bordersTex, dataTex, markerTex]) => {
  uniforms.landMask.value = landMask;
  uniforms.bordersTex.value = bordersTex;
  uniforms.dataTex.value = dataTex;

  marker.material.map = markerTex;
  marker.material.needsUpdate = true;

  canvas.classList.add("is-visible");

  animate();
  revealClouds();
  revealData();
}).catch((err) => console.error("Texture load failed:", err));

function delay(ms){ return new Promise(r => setTimeout(r, ms)); }

async function revealClouds() {
  await delay(TIMING.globeFadeMs + TIMING.cloudsDelayAfterGlobeMs);
  if (!cloudsTex) return;          // not ready yet
  fadeMaterialOpacity(cloudsTex.material, 0.85, TIMING.cloudsFadeMs);
}

function fadeNumber(setter, from, to, ms=700) {
  const t0 = performance.now();
  function step(now){
    const x = Math.min(1, (now - t0)/ms);
    const k = 1 - Math.pow(1 - x, 3);
    setter(from + (to - from) * k);
    if (x < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

async function revealData() {
  await delay(TIMING.globeFadeMs + TIMING.dataDelayAfterGlobeMs);
  dataCycleT0 = performance.now() / 1000;
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
  uniforms.dataOpacity.value = dataBaseOpacity * bloom;

  uniforms.lightDir.value.copy(sun.position).normalize();

  controls.update();
  renderer.render(scene, camera);
}
