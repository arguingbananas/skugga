// Render the README demo animation: a point-light walker revealed one dot at a time.
//
//   npm run demo                 # writes docs/demo.webp
//   npm run demo -- frames/      # also keep the PNG frames there, for checking
//
// Frames are drawn in headless Chromium with the viewer's own display code
// (web/js/display.js), then packed into an animated WebP with img2webp
// (Debian/Ubuntu package: webp).

import { execFileSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import puppeteer from "puppeteer-core";
import { ROOT, chromePath, serve } from "./static-server.mjs";

const CLIP = "12_01";        // walk: the classic Johansson display
const W = 480, H = 320;      // output size in pixels
const FPS = 25;
const SECONDS = 9.5;
const FIRST_DOT_HOLD = 1.0;  // seconds showing a single dot before adding more
const DOT_EVERY = 0.42;      // seconds between added dots
const AZIMUTH = 30;          // slightly angled, so left and right limbs separate
const OUT = join(ROOT, "docs", "demo.webp");
const KEEP = process.argv[2] ? resolve(process.argv[2]) : null;

const { server, origin } = await serve();
const browser = await puppeteer.launch({ executablePath: chromePath(), args: ["--no-sandbox"] });
const tmp = mkdtempSync(join(tmpdir(), "skugga-demo-"));

try {
  const page = await browser.newPage();
  page.on("pageerror", (e) => { throw e; });
  await page.goto(`${origin}/web/`, { waitUntil: "domcontentloaded" });

  const frames = await page.evaluate(async (cfg) => {
    const { loadClip } = await import("./js/clips.js");
    const { REVEAL_ORDER, bodyStats, makeCamera, scene } = await import("./js/display.js");
    const clip = await loadClip(cfg.CLIP);
    const stats = bodyStats(clip);
    const camera = makeCamera(clip, stats, { width: cfg.W, height: cfg.H, azimuth: cfg.AZIMUTH, inPlace: true, inverted: false });

    const canvas = document.createElement("canvas");
    canvas.width = cfg.W;
    canvas.height = cfg.H;
    const ctx = canvas.getContext("2d");
    const total = cfg.FPS * cfg.SECONDS;
    const scratch = {};
    const out = [];

    // Timeline: start with as little as possible (one dot), add one joint at a
    // time, and show the answer once the whole figure is there. No noise: the
    // demo shows the README's "starts with as little information as possible".
    const n = REVEAL_ORDER.length;
    const revealEnd = cfg.FIRST_DOT_HOLD + (n - 1) * cfg.DOT_EVERY;
    for (let f = 0; f < total; f++) {
      const t = f / cfg.FPS;
      const dots = Math.min(n, 1 + Math.max(0, Math.floor((t - cfg.FIRST_DOT_HOLD) / cfg.DOT_EVERY) + 1));
      const p = (dots - 1) / (n - 1);
      const pts = scene(clip, stats, t, { visible: new Set(REVEAL_ORDER.slice(0, dots)), noise: [], inPlace: true }, scratch);
      const xy = camera(pts);

      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, cfg.W, cfg.H);
      ctx.fillStyle = "#fff";
      ctx.beginPath();
      for (let i = 0; i < xy.length; i += 2) {
        ctx.moveTo(xy[i] + 3.5, xy[i + 1]);
        ctx.arc(xy[i], xy[i + 1], 3.5, 0, Math.PI * 2);
      }
      ctx.fill();

      // Answer: "?" until the figure is complete, then the category fades in.
      ctx.font = "600 26px system-ui, sans-serif";
      ctx.textBaseline = "top";
      const shown = Math.min(1, Math.max(0, (t - revealEnd) / 0.4));
      if (shown < 1) {
        ctx.globalAlpha = 1 - shown;
        ctx.fillStyle = "#9097a3";
        ctx.fillText("?", 18, 16);
      }
      if (shown > 0) {
        ctx.globalAlpha = shown;
        ctx.fillStyle = "#f2c14e";
        ctx.fillText("walk", 18, 16);
      }
      ctx.globalAlpha = 1;

      // How much of the figure is showing.
      ctx.font = "14px system-ui, sans-serif";
      ctx.textBaseline = "bottom";
      ctx.fillStyle = "#9097a3";
      ctx.fillText(`${dots} / ${n} dots`, 18, cfg.H - 14);

      // Reveal progress bar along the bottom.
      ctx.fillStyle = "#222";
      ctx.fillRect(0, cfg.H - 4, cfg.W, 4);
      ctx.fillStyle = "#f2c14e";
      ctx.fillRect(0, cfg.H - 4, cfg.W * p, 4);

      out.push(canvas.toDataURL("image/png"));
    }
    return out;
  }, { CLIP, W, H, FPS, SECONDS, FIRST_DOT_HOLD, DOT_EVERY, AZIMUTH });

  const files = frames.map((url, i) => {
    const file = join(tmp, `f${String(i).padStart(4, "0")}.png`);
    writeFileSync(file, Buffer.from(url.split(",")[1], "base64"));
    return file;
  });

  mkdirSync(join(ROOT, "docs"), { recursive: true });
  // -lossy -q 60: dots on black compress well; -mixed lets each frame pick lossless if smaller.
  execFileSync("img2webp", ["-loop", "0", "-mixed", "-q", "60", "-m", "6", "-d", String(Math.round(1000 / FPS)), ...files, "-o", OUT], {
    stdio: ["ignore", "ignore", "inherit"],
  });
  if (KEEP) cpSync(tmp, KEEP, { recursive: true });
  console.log(`wrote ${OUT} (${frames.length} frames, ${(statSync(OUT).size / 1024).toFixed(0)} KB)`);
} finally {
  await browser.close();
  server.close();
  rmSync(tmp, { recursive: true, force: true });
}
