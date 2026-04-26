/**
 * Patches the compiled maplibre-gl dist bundle with globe-mode fixes.
 * Run automatically via `npm postinstall`.
 *
 * Fix C – Hillshade pole-cap triangle fan artifacts
 *   C1: Disables pole-mesh extension for the hillshade render pass by setting
 *       the extendToPoles flag (arg 4) to false in getMeshFromTileID.
 *       The hillshade DEM tiles do not have meaningful data at ±85°–90°, so
 *       the 5° polar cap renders without hillshade shading (background colour
 *       shows through), which is acceptable and avoids triangle-fan artefacts.
 *   C3: Discards hillshade fragments whose v_pos.y falls outside [0,1] as a
 *       safety guard in case any out-of-range UV slips through.
 *   C4: Pins raster (warming texture) pole-cap UV x to 0.5 so the raster
 *       layer samples the centre column rather than garbled coordinates.
 *
 * Fix D – Black ring artifact at ~85°N/S on globe
 *   Adds v_mercator_y varying to the line shaders and discards fragments
 *   whose Mercator Y falls outside the visible tile band (< 0.031 or > 0.969).
 *
 * Fix E – Seam lines at ±175° longitude on globe
 *   Adds v_mercator_x varying to the line shaders; the varying is set to the
 *   actual Mercator X only for vertices at tile boundaries (pos.x < 1 or
 *   > 8190) and to 0.5 elsewhere, then discards fragments outside [0.02, 0.98].
 */

'use strict';

const fs = require('fs');
const path = require('path');

const DIST = path.resolve(__dirname, '..', 'node_modules', 'maplibre-gl', 'dist', 'maplibre-gl.js');

function applyPatch(content, oldStr, newStr, name) {
  const count = content.split(oldStr).length - 1;
  if (count === 0) {
    if (content.includes(newStr)) {
      console.log(`  ✓ ${name} (already applied)`);
    } else {
      console.error(`  ✗ ${name}: neither old nor new string found in bundle`);
      process.exit(1);
    }
    return content;
  }
  const label = count > 1 ? `${count} occurrences` : '1 occurrence';
  console.log(`  ✓ ${name} (${label})`);
  return content.split(oldStr).join(newStr);
}

console.log('Patching maplibre-gl dist bundle (v5.21.0)…');
let c = fs.readFileSync(DIST, 'utf8');

// ── Fix C: hillshade / raster pole-cap fixes ───────────────────────────────

// C1 – hillshade: disable pole-mesh extension
//   Sets extendToPoles=false (arg 4 → !1) in the hillshade render call.
//   In 5.21.0+ the minifier inlined the generateBorders variable as !1 and
//   already emits !1 for extendToPoles, so the fix is upstream and we skip.
if (c.includes('getMeshFromTileID(u,p.canonical,!1,!1,"raster")')) {
  console.log('  ✓ C1: hillshade – disable pole-mesh extension (already upstream in 5.21.0+)');
} else {
  c = applyPatch(c,
    'getMeshFromTileID(u,p.canonical,n,!0,"raster")',
    'getMeshFromTileID(u,p.canonical,n,!1,"raster")',
    'C1: hillshade – disable pole-mesh extension',
  );
}

// C3 – hillshade fragment: discard only truly out-of-range UVs
//   (v_pos.y outside [0,1] – plain texture bounds guard, no sentinel needed)
c = applyPatch(c,
  'highlights[0]*highlight;}void main() {vec4 pixel=texture(u_image,v_pos)',
  'highlights[0]*highlight;}void main() {if (v_pos.y < 0.0 || v_pos.y > 1.0) discard;vec4 pixel=texture(u_image,v_pos)',
  'C3: hillshade fragment – discard out-of-range UV',
);

// C4 – raster vertex: pin pole-cap UV x to 0.5 (centre longitude) so the
//      raster layer samples a valid pixel rather than out-of-range coordinates
c = applyPatch(c,
  '\\n#ifdef GLOBE\\nif (a_pos.y <-32767.5) {v_pos0.y=0.0;}if (a_pos.y > 32766.5) {v_pos0.y=1.0;}\\n#endif\\n',
  '\\n#ifdef GLOBE\\nif (a_pos.y <-32767.5) {v_pos0.y=0.0;v_pos0.x=0.5;}if (a_pos.y > 32766.5) {v_pos0.y=1.0;v_pos0.x=0.5;}\\n#endif\\n',
  'C4: raster vertex – centre-pin UV for pole vertices',
);

// ── Fix D+E: line shader – polar ring + antimeridian seam lines ────────────

// DE1 – line vertex: declare v_mercator_y and v_mercator_x varyings
//   The dist bundle contains 5+ line vertex shader variants (line, lineGradient,
//   lineSDF, …).  Use a broad anchor (the GLOBE depth-declaration block) so
//   this patch hits every variant, not just the one that has 'v_linesofar'.
c = applyPatch(c,
  '#ifdef GLOBE\\nout float v_depth;\\n#endif\\n',
  '#ifdef GLOBE\\nout float v_depth;\\nout float v_mercator_y;\\nout float v_mercator_x;\\n#endif\\n',
  'DE1: line vertex – declare v_mercator_y/x varyings (all variants)',
);

// DE2 – line vertex: compute v_mercator_y/x in main()
//   v_mercator_y: Mercator Y of the vertex (for polar-ring discard)
//   v_mercator_x: Mercator X only for tile-boundary vertices (pos.x < 1 or
//                 > 8190); set to safe 0.5 for all other vertices so the
//                 fragment discard never fires on interior coastlines
c = applyPatch(c,
  'gl_Position=projected_with_extrude;\\n#ifdef GLOBE\\nv_depth=gl_Position.z/gl_Position.w;\\n#endif\\n',
  'gl_Position=projected_with_extrude;\\n#ifdef GLOBE\\nv_mercator_y=u_projection_tile_mercator_coords.y+u_projection_tile_mercator_coords.w*pos.y;\\nv_mercator_x=(pos.x<1.0||pos.x>8190.0)?(u_projection_tile_mercator_coords.x+u_projection_tile_mercator_coords.z*pos.x):0.5;\\nv_depth=gl_Position.z/gl_Position.w;\\n#endif\\n',
  'DE2: line vertex – compute v_mercator_y/x',
);

// DE3 – line fragment: declare in v_mercator_y and v_mercator_x
c = applyPatch(c,
  'in float v_gamma_scale;\\n#ifdef GLOBE\\nin float v_depth;\\n#endif\\n',
  'in float v_gamma_scale;\\n#ifdef GLOBE\\nin float v_depth;\\nin float v_mercator_y;\\nin float v_mercator_x;\\n#endif\\n',
  'DE3: line fragment – declare in v_mercator_y/x',
);

// DE4 – line fragment: discard polar-ring and antimeridian-seam fragments
//   Polar ring (Fix D):  v_mercator_y outside [0.031, 0.969] ≈ ±84° latitude
//   Seam lines (Fix E):  v_mercator_x outside [0.02, 0.98] (only fires for
//                        tile-boundary vertices thanks to the 0.5 default above)
c = applyPatch(c,
  'fragColor=color*(alpha*opacity);\\n#ifdef GLOBE\\nif (v_depth > 1.0) {discard;}\\n#endif\\n',
  'fragColor=color*(alpha*opacity);\\n#ifdef GLOBE\\nif (v_depth > 1.0) {discard;}\\nif (v_mercator_y < 0.031 || v_mercator_y > 0.969) {discard;}\\nif (v_mercator_x < 0.02 || v_mercator_x > 0.98) {discard;}\\n#endif\\n',
  'DE4: line fragment – polar ring + seam discard',
);

fs.writeFileSync(DIST, c, 'utf8');
console.log('Done.');
