// Loading clips and categories built by pipeline/build.py.
//
// A loaded clip is { id, category, description, fps, markers, frameCount,
// duration, data } where `data` is a Float32Array of frameCount * markers * 3
// values in metres (x forward, y up, z left).

const DATA = new URL("../../data/", import.meta.url);
const cache = new Map();

async function getJSON(path) {
  const res = await fetch(new URL(path, DATA));
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

/** @returns {Promise<{markers: string[], clips: {id: string, category: string}[]}>} */
export function loadIndex() {
  return getJSON("clips/index.json");
}

/** @returns {Promise<Record<string, string[]>>} category -> synonyms */
export async function loadCategories() {
  return (await getJSON("categories.json")).categories;
}

export function loadClip(id) {
  if (!cache.has(id)) {
    cache.set(id, getJSON(`clips/${id}.json`).then(toClip).catch((err) => {
      cache.delete(id);
      throw err;
    }));
  }
  return cache.get(id);
}

function toClip(raw) {
  const m = raw.markers.length;
  const data = new Float32Array(raw.frames.length * m * 3);
  raw.frames.forEach((frame, i) => {
    for (let j = 0; j < m * 3; j++) data[i * m * 3 + j] = frame[j] / 1000;
  });
  return {
    id: raw.id,
    category: raw.category,
    description: raw.description,
    fps: raw.fps,
    markers: raw.markers,
    frameCount: raw.frames.length,
    duration: raw.frames.length / raw.fps,
    data,
  };
}
