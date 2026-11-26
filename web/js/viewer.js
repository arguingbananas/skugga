// Viewer page: browse clips and try out reveal settings.

import { loadClip, loadIndex } from "./clips.js";
import { REVEAL_ORDER, bodyStats, makeCamera, makeNoise, scene } from "./display.js";

const $ = (id) => document.getElementById(id);
const el = {
  canvas: $("canvas"), clip: $("clip"), prev: $("prev"), next: $("next"), random: $("random"),
  hide: $("hide"), answer: $("answer"), answerCat: $("answer-cat"), answerDesc: $("answer-desc"),
  play: $("play"), time: $("time"), speed: $("speed"), dots: $("dots"), markers: $("markers"),
  noise: $("noise"), reseed: $("reseed"), inverted: $("inverted"), revealSecs: $("reveal-secs"),
  reveal: $("reveal"), revealBar: $("reveal-bar"), revealFill: $("reveal-fill"),
  azimuth: $("azimuth"), inplace: $("inplace"), size: $("size"), status: $("status"),
};
const ctx = el.canvas.getContext("2d");

const state = {
  index: [],       // [{id, category}]
  clip: null,
  stats: null,
  t: 0,
  playing: true,
  visible: new Set(REVEAL_ORDER),
  noise: [],
  seed: 1 + Math.floor(Math.random() * 1e6), // ?seed= pins it
  camera: null,
  reveal: null,    // { start, secs, noiseFrom, inverted } while auto-revealing
  size: { w: 1, h: 1 },
};
const scratch = {};

// ---------- setup

async function init() {
  const index = await loadIndex();
  state.index = index.clips;
  buildMarkerChecks();
  applyQuery();
  buildClipSelect();
  bindControls();
  new ResizeObserver(resize).observe(el.canvas);
  resize();
  const fromHash = decodeURIComponent(location.hash.slice(1));
  await selectClip(state.index.some((c) => c.id === fromHash) ? fromHash : state.index[0].id);
  const t = Number(new URLSearchParams(location.search).get("t"));
  if (t > 0) state.t = t % state.clip.duration;
  requestAnimationFrame(frame);
}

/**
 * Starting settings from the query string, for sharing a setup or testing:
 * ?dots=5&noise=30&seed=2&inv=1&az=90&travel=1&speed=0.5&size=6&hide=1&t=1.2&paused=1
 */
function applyQuery() {
  const q = new URLSearchParams(location.search);
  const num = (key, input) => { if (q.has(key) && !isNaN(+q.get(key))) input.value = q.get(key); };
  const flag = (key) => q.has(key) && q.get(key) !== "0";
  num("noise", el.noise);
  num("az", el.azimuth);
  num("speed", el.speed);
  num("size", el.size);
  if (q.has("seed")) state.seed = Number(q.get("seed")) || 1;
  if (flag("inv")) el.inverted.checked = true;
  if (flag("travel")) el.inplace.checked = false;
  if (flag("hide")) el.hide.checked = true;
  if (flag("paused")) { state.playing = false; el.play.textContent = "Play"; }
  if (q.has("dots")) setDots(Math.max(0, Math.min(REVEAL_ORDER.length, Math.round(+q.get("dots")) || 0)));
  syncOutputs();
}

function buildClipSelect() {
  el.clip.replaceChildren();
  if (el.hide.checked) {
    // No categories in the list while the answer is hidden.
    state.index.forEach((c, i) => el.clip.add(new Option(`Clip ${i + 1}`, c.id)));
  } else {
    const groups = new Map();
    for (const c of state.index) {
      if (!groups.has(c.category)) {
        const g = document.createElement("optgroup");
        g.label = c.category;
        groups.set(c.category, g);
        el.clip.append(g);
      }
      groups.get(c.category).append(new Option(`${c.id}`, c.id));
    }
  }
  if (state.clip) el.clip.value = state.clip.id;
}

function buildMarkerChecks() {
  for (const name of REVEAL_ORDER) {
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = true;
    box.dataset.marker = name;
    box.addEventListener("change", () => {
      box.checked ? state.visible.add(name) : state.visible.delete(name);
      el.dots.value = state.visible.size;
      syncOutputs();
    });
    label.append(box, name);
    el.markers.append(label);
  }
}

function bindControls() {
  el.clip.addEventListener("change", () => selectClip(el.clip.value));
  el.prev.addEventListener("click", () => step(-1));
  el.next.addEventListener("click", () => step(1));
  el.random.addEventListener("click", randomClip);
  el.hide.addEventListener("change", () => { buildClipSelect(); showAnswer(); });
  el.answer.addEventListener("click", () => { if (el.hide.checked) { el.hide.checked = false; buildClipSelect(); showAnswer(); } });
  el.play.addEventListener("click", togglePlay);
  el.time.addEventListener("input", () => {
    state.t = (el.time.value / 1000) * state.clip.duration;
  });
  el.dots.addEventListener("input", () => setDots(+el.dots.value));
  el.noise.addEventListener("input", rebuildNoise);
  el.reseed.addEventListener("click", () => { state.seed++; rebuildNoise(); });
  el.reveal.addEventListener("click", toggleReveal);
  for (const input of [el.azimuth, el.inplace, el.inverted]) input.addEventListener("input", updateCamera);
  for (const input of [el.speed, el.size, el.revealSecs]) input.addEventListener("input", syncOutputs);

  addEventListener("keydown", (e) => {
    if (e.target.closest("select, input[type=text]") || e.ctrlKey || e.metaKey || e.altKey) return;
    const actions = {
      " ": togglePlay,
      ArrowLeft: () => step(-1),
      ArrowRight: () => step(1),
      r: randomClip,
      h: () => { el.hide.checked = !el.hide.checked; buildClipSelect(); showAnswer(); },
      i: () => { el.inverted.checked = !el.inverted.checked; updateCamera(); },
      v: toggleReveal,
    };
    const fn = actions[e.key.length === 1 ? e.key.toLowerCase() : e.key];
    if (fn) { e.preventDefault(); fn(); }
  });
}

// ---------- actions

async function selectClip(id) {
  el.status.textContent = "Loading…";
  try {
    const clip = await loadClip(id);
    state.clip = clip;
    state.stats = bodyStats(clip);
    state.t = 0;
    el.clip.value = id;
    history.replaceState(null, "", `#${encodeURIComponent(id)}`);
    rebuildNoise();
    updateCamera();
    showAnswer();
    el.status.textContent = "";
  } catch (err) {
    el.status.textContent = `Could not load ${id}: ${err.message}`;
  }
}

function step(delta) {
  const i = state.index.findIndex((c) => c.id === state.clip?.id);
  const n = state.index.length;
  selectClip(state.index[(i + delta + n) % n].id);
}

function randomClip() {
  const others = state.index.filter((c) => c.id !== state.clip?.id);
  el.hide.checked = true;
  buildClipSelect();
  selectClip(others[Math.floor(Math.random() * others.length)].id);
}

function togglePlay() {
  state.playing = !state.playing;
  el.play.textContent = state.playing ? "Pause" : "Play";
}

function setDots(n) {
  state.visible = new Set(REVEAL_ORDER.slice(0, n));
  for (const box of el.markers.querySelectorAll("input")) box.checked = state.visible.has(box.dataset.marker);
  el.dots.value = n;
  syncOutputs();
}

function rebuildNoise() {
  if (!state.clip) return;
  state.noise = makeNoise(state.clip, state.stats, +el.noise.value, state.seed);
  syncOutputs();
}

function toggleReveal() {
  if (state.reveal) return endReveal();
  state.reveal = {
    start: performance.now(),
    secs: +el.revealSecs.value,
    noiseFrom: +el.noise.value,
    inverted: el.inverted.checked,
  };
  state.t = 0;
  if (!state.playing) togglePlay();
  el.reveal.textContent = "Stop auto-reveal";
  el.revealBar.hidden = false;
}

function endReveal() {
  state.reveal = null;
  el.reveal.textContent = "Start auto-reveal";
  el.revealBar.hidden = true;
}

/** Auto-reveal: dots 2 → 15 and noise → 0 over the chosen time; flip upright halfway. */
function tickReveal(now) {
  const r = state.reveal;
  const p = Math.min(1, (now - r.start) / 1000 / r.secs);
  const dots = Math.round(2 + p * (REVEAL_ORDER.length - 2));
  if (dots !== state.visible.size) setDots(dots);
  const noise = Math.round(r.noiseFrom * (1 - p));
  if (noise !== +el.noise.value) { el.noise.value = noise; rebuildNoise(); }
  if (r.inverted && p >= 0.5 && el.inverted.checked) { el.inverted.checked = false; updateCamera(); }
  el.revealFill.style.width = `${p * 100}%`;
  if (p >= 1) {
    endReveal();
    if (el.hide.checked) { el.hide.checked = false; buildClipSelect(); showAnswer(); }
  }
}

function showAnswer() {
  if (!state.clip) return;
  const hidden = el.hide.checked;
  // Don't leave the answer in the DOM while hidden: blur can fail to render
  // and screen readers would read it out.
  el.answerCat.textContent = hidden ? "?" : state.clip.category;
  el.answerDesc.textContent = hidden ? "Click or press H to show the answer" : `CMU ${state.clip.id}: ${state.clip.description}`;
  el.answer.classList.toggle("hidden", hidden);
}

function updateCamera() {
  if (!state.clip) return;
  state.camera = makeCamera(state.clip, state.stats, {
    width: state.size.w,
    height: state.size.h,
    azimuth: +el.azimuth.value,
    inPlace: el.inplace.checked,
    inverted: el.inverted.checked,
  });
  syncOutputs();
}

function resize() {
  const dpr = devicePixelRatio || 1;
  const { clientWidth: w, clientHeight: h } = el.canvas;
  el.canvas.width = Math.round(w * dpr);
  el.canvas.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  state.size = { w, h };
  updateCamera();
}

function syncOutputs() {
  const out = (id, text) => { $(id).value = text; };
  out("speed-out", `${(+el.speed.value).toFixed(2)}×`);
  out("dots-out", `${state.visible.size} / ${REVEAL_ORDER.length}`);
  out("noise-out", el.noise.value);
  out("azimuth-out", `${el.azimuth.value}°`);
  out("size-out", el.size.value);
  out("reveal-out", `${el.revealSecs.value} s`);
}

// ---------- render loop

let last = performance.now();
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  if (state.clip) {
    if (state.playing) state.t = (state.t + dt * +el.speed.value) % state.clip.duration;
    if (state.reveal) tickReveal(now);
    draw();
    el.time.value = Math.round((state.t / state.clip.duration) * 1000);
    $("time-out").value = `${state.t.toFixed(1)} / ${state.clip.duration.toFixed(1)} s`;
  }
  requestAnimationFrame(frame);
}

function draw() {
  const { w, h } = state.size;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, w, h);
  const pts = scene(state.clip, state.stats, state.t, {
    visible: state.visible,
    noise: state.noise,
    inPlace: el.inplace.checked,
  }, scratch);
  const xy = state.camera(pts);
  const r = +el.size.value;
  ctx.fillStyle = "#fff";
  ctx.beginPath();
  for (let i = 0; i < xy.length; i += 2) {
    ctx.moveTo(xy[i] + r, xy[i + 1]);
    ctx.arc(xy[i], xy[i + 1], r, 0, Math.PI * 2);
  }
  ctx.fill();
}

init().catch((err) => {
  el.status.textContent = `Failed to start: ${err.message}`;
  console.error(err);
});
