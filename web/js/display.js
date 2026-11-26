// The point-light display model: which dots exist at time t and where they
// appear on screen. Pure functions with no DOM access, so the game can reuse them.

/** Order in which dots are added when revealing a figure, least telling first. */
export const REVEAL_ORDER = [
  "lankle", "rwrist", "head", "rknee", "lelbow",
  "lowerback", "pelvis", "upperneck", "rankle", "lwrist",
  "upperback", "lknee", "relbow", "lowerneck", "neck",
  "rhip", "lshoulder", "lhip", "rshoulder", "lfoot",
  "rfoot", "rhand", "lhand", "ltoes", "rtoes",
  "rknuckles", "lknuckles", "rfingers", "lfingers", "rthumb", "lthumb",
];

/** Small seeded PRNG (mulberry32), so a noise pattern can be reproduced. */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Marker positions at time t (seconds, wrapped to the clip), linearly
 * interpolated between frames. Writes into `out` (Float32Array, markers*3).
 */
export function sample(clip, t, out = new Float32Array(clip.markers.length * 3)) {
  const n = clip.markers.length * 3;
  const f = ((t * clip.fps) % clip.frameCount + clip.frameCount) % clip.frameCount;
  const i0 = Math.floor(f);
  const i1 = (i0 + 1) % clip.frameCount;
  const k = i1 === 0 ? 0 : f - i0; // don't blend the last frame into the first
  const d = clip.data;
  for (let j = 0; j < n; j++) out[j] = d[i0 * n + j] * (1 - k) + d[i1 * n + j] * k;
  return out;
}

/** Per-marker mean offset from the pelvis over the clip, plus its bounding box. */
export function bodyStats(clip) {
  const m = clip.markers.length;
  const p = clip.markers.indexOf("pelvis");
  const mean = new Float32Array(m * 3);
  const lo = [Infinity, Infinity, Infinity];
  const hi = [-Infinity, -Infinity, -Infinity];
  for (let f = 0; f < clip.frameCount; f++) {
    const base = f * m * 3;
    for (let j = 0; j < m; j++) {
      for (let c = 0; c < 3; c++) {
        const rel = clip.data[base + j * 3 + c] - (c === 1 ? 0 : clip.data[base + p * 3 + c]);
        mean[j * 3 + c] += rel / clip.frameCount;
        lo[c] = Math.min(lo[c], rel);
        hi[c] = Math.max(hi[c], rel);
      }
    }
  }
  let maxY = 0;
  for (let i = 1; i < clip.data.length; i += 3) maxY = Math.max(maxY, clip.data[i]);
  // Region where noise dots are placed: the box around the average pose,
  // padded a little. (Using the full lo/hi range would spread noise over
  // everywhere the figure ever reaches, leaving the real figure as an
  // obvious dense cluster in the middle.)
  const spot = { lo: [Infinity, Infinity, Infinity], hi: [-Infinity, -Infinity, -Infinity] };
  for (let j = 0; j < m; j++) {
    for (let c = 0; c < 3; c++) {
      spot.lo[c] = Math.min(spot.lo[c], mean[j * 3 + c]);
      spot.hi[c] = Math.max(spot.hi[c], mean[j * 3 + c]);
    }
  }
  for (let c = 0; c < 3; c++) {
    const pad = Math.max(0.15, (spot.hi[c] - spot.lo[c]) * 0.15);
    spot.lo[c] -= pad;
    spot.hi[c] += pad;
  }
  spot.lo[1] = Math.max(0, spot.lo[1]);
  return { mean, lo, hi, spot, maxY };
}

/**
 * Distractor dots in the classic "scrambled walker" style: each copies the
 * local motion of a randomly chosen real marker but sits at a random place
 * within the body's bounding box and runs at a random time offset. They move
 * like body parts, so motion alone can't tell them apart from the figure.
 */
export function makeNoise(clip, stats, count, seed) {
  const r = rng(seed);
  const { lo, hi } = stats.spot;
  const dots = [];
  for (let i = 0; i < count; i++) {
    const marker = Math.floor(r() * clip.markers.length);
    const at = [0, 1, 2].map((c) => lo[c] + r() * (hi[c] - lo[c]));
    dots.push({ marker, phase: r() * clip.duration, at });
  }
  return dots;
}

/**
 * World-space positions of the visible dots at time t.
 * @param {object} opts { visible: Set<string>, noise: dot[], inPlace: boolean }
 * @returns {number[]} flat [x, y, z, ...]
 */
export function scene(clip, stats, t, opts, scratch = {}) {
  const m = clip.markers.length;
  const p = clip.markers.indexOf("pelvis");
  const now = (scratch.now = sample(clip, t, scratch.now));
  const ox = opts.inPlace ? now[p * 3] : 0;
  const oz = opts.inPlace ? now[p * 3 + 2] : 0;
  const pts = [];
  for (let j = 0; j < m; j++) {
    if (!opts.visible.has(clip.markers[j])) continue;
    pts.push(now[j * 3] - ox, now[j * 3 + 1], now[j * 3 + 2] - oz);
  }
  const other = (scratch.other ??= new Float32Array(m * 3));
  for (const d of opts.noise) {
    sample(clip, t + d.phase, other);
    const j = d.marker * 3;
    for (let c = 0; c < 3; c++) {
      // marker's motion about its own mean, placed at the dot's random spot
      const rel = other[j + c] - (c === 1 ? 0 : other[p * 3 + c]) - stats.mean[j + c];
      const anchor = c === 1 ? 0 : now[p * 3 + c] - (c === 0 ? ox : oz);
      pts.push(anchor + d.at[c] + rel);
    }
  }
  return pts;
}

/**
 * Orthographic camera. Azimuth 0 is a side view with the figure moving to the
 * right; 90 looks at its back, -90 at its front.
 */
export function makeCamera(clip, stats, { width, height, azimuth, inPlace, inverted }) {
  const a = (azimuth * Math.PI) / 180;
  const cos = Math.cos(a), sin = Math.sin(a);
  const toX = (x, z) => x * cos - z * sin;

  // Horizontal extent the camera has to keep in view.
  let minX = Infinity, maxX = -Infinity;
  const m = clip.markers.length;
  const p = clip.markers.indexOf("pelvis");
  for (let f = 0; f < clip.frameCount; f++) {
    const b = f * m * 3;
    const px = inPlace ? clip.data[b + p * 3] : 0;
    const pz = inPlace ? clip.data[b + p * 3 + 2] : 0;
    for (let j = 0; j < m; j++) {
      const sx = toX(clip.data[b + j * 3] - px, clip.data[b + j * 3 + 2] - pz);
      if (sx < minX) minX = sx;
      if (sx > maxX) maxX = sx;
    }
  }
  const margin = 0.12;
  const spanY = Math.max(stats.maxY, 1.0);
  const scale = Math.min(
    (height * (1 - 2 * margin)) / spanY,
    (width * (1 - 2 * margin)) / Math.max(maxX - minX, 0.5),
  );
  const cx = width / 2 - ((minX + maxX) / 2) * scale;
  const floor = height / 2 + (spanY / 2) * scale;

  return (pts) => {
    const out = new Float32Array((pts.length / 3) * 2);
    for (let i = 0, k = 0; i < pts.length; i += 3, k += 2) {
      out[k] = cx + toX(pts[i], pts[i + 2]) * scale;
      const y = pts[i + 1] * scale;
      out[k + 1] = inverted ? height - floor + y : floor - y;
    }
    return out;
  };
}
