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
const STICKER_TEX_URL = `./textures/sphere_outline.png`; // <-- put your transparent PNG here
const CLOUD_TEX_URL = `./textures/clouds_${size}.${ext}`;

// Invert land/border mask (ocean=white, land=black)
const MASK_INVERT = 1.0;

const COLORS = {
  ocean: 0xF0F0F0,   // light grey
  land:  0xFFFFFF,   // same as ocean; land will be shown via coastline outline
  coast: 0x1A1A1A,   // coastline stroke
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

  // NEW: screen-space overlay (sampled in fragment shader)
  overlayTex: { value: null },
  overlayOpacity: { value: 1.0 }, // 0..1
  overlayScale:   { value: 0.825 },              // < 1 => smaller, > 1 => larger
  overlayOffset:  { value: new THREE.Vector2(0, 0) }, // in UV units
  overlayViewport: { value: new THREE.Vector2(1, 1) },

  oceanColor: { value: new THREE.Color(COLORS.ocean) },
  landColor:  { value: new THREE.Color(COLORS.land)  },
  // Coastline
  coastColor: { value: new THREE.Color(COLORS.coast) },

  // NEW: used to compute coastline thickness in UV space
  landTexel:  { value: new THREE.Vector2(1 / 2048, 1 / 1024) }, // overwritten after texture load

  // Make terminator visible: light comes from the side a bit
  lightDir: { value: new THREE.Vector3( -0.85, 0.55, 1.25 ).normalize() },

  maskInvert: { value: MASK_INVERT },

  // We'll rely on halftone for shading, so keep the smooth shading minimal.
  shadeStrength: { value: 0.0 },
  brightness:    { value: 1.0 },

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

  // NEW: overlay sampled in screen space
  uniform sampler2D overlayTex;
  uniform float overlayOpacity;
  uniform float overlayScale;
  uniform vec2 overlayOffset;
  uniform vec2 overlayViewport;

  uniform vec3 oceanColor;
  uniform vec3 landColor;
  uniform vec3 coastColor;

  uniform vec3 lightDir;

  uniform float maskInvert;
  uniform float shadeStrength;
  uniform float brightness;

  uniform vec2  landTexel;

  uniform float shadeGain;
  uniform float shadeBias;
  uniform float shadow2Start;

  uniform float coastStrength;
  uniform float coastSoftness;

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
    shade = pow(shade, 0.85);

    // Optional smooth shading (kept mostly off by default)
    float sphereShade = mix(0.92, 1.08, day);
    base *= mix(1.0, sphereShade, shadeStrength);

    // Coastline outline on top
    float coast = coastline(vUv);
    // soften a touch near poles to avoid noisy sampling at extreme UV squeeze
    float poleFade = smoothstep(1.0, 0.68, abs(vUv.y * 2.0 - 1.0));
    float ca = pow(coast * poleFade, coastSoftness) * coastStrength;
    base = mix(base, coastColor, ca);
    vec3 outRgb = base * brightness;

    // Screen-space UV in [0,1]
    vec2 screenUV = (vClipPos.xy / vClipPos.w) * 0.5 + 0.5;
    // Most PNGs are authored top-left origin
    screenUV.y = 1.0 - screenUV.y;
    // Scale around center (0.5,0.5)
    // Aspect-correct scale around center so circles stay circles even if viewport isn't square.
    vec2 centered = screenUV - 0.5;

    // Apply scale on overlay image
    float ratio = overlayViewport.y / overlayViewport.x;
    centered.x /= overlayScale * ratio;
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
  camera.updateProjectionMatrix();

  // IMPORTANT: initialize/update this on load too (not only on resize)
  uniforms.overlayViewport.value.set(w, h);
}
window.addEventListener("resize", resize);

resize();
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
  loadTex("./textures/marker.png"),
  loadTex(STICKER_TEX_URL),
]).then(([landMask, markerTex, overlayTex]) => {
  uniforms.landMask.value = landMask;

  // Overlay: screen-space sample
  overlayTex.wrapS = THREE.ClampToEdgeWrapping;
  overlayTex.wrapT = THREE.ClampToEdgeWrapping;
  overlayTex.minFilter = THREE.LinearFilter;
  overlayTex.magFilter = THREE.LinearFilter;

  // We sample with screenUV.y flipped in shader, so keep the texture unflipped
  overlayTex.flipY = false;
  overlayTex.needsUpdate = true;

  const sz = renderer.getSize(new THREE.Vector2());
  uniforms.overlayViewport.value.copy(sz);

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

  // Keep fixed; or you can slowly drift it if you like
  // uniforms.lightDir.value.set(-1.0, 0.25, 0.35).normalize();
  const lightCam = new THREE.Vector3(-0.85, 0.55, 1.25).normalize();
  const lightWorld = lightCam.clone().applyQuaternion(camera.quaternion);
  uniforms.lightDir.value.copy(lightWorld).normalize();

  renderer.render(scene, camera);
}
