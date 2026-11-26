// Smoke test for the viewer in headless Chromium.
//
//   npm run smoke                    # assertions only
//   npm run smoke -- path/to/shots   # also save screenshots there
//
// Uses the system Chromium (override with CHROME_PATH). Serves the repo from
// a throwaway local server on 127.0.0.1.

import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import puppeteer from "puppeteer-core";
import { ROOT, chromePath, serve } from "../tools/static-server.mjs";

const SHOTS = process.argv[2] ? resolve(process.argv[2]) : null;

const results = [];
async function check(name, fn) {
  try {
    await fn();
    results.push(["ok", name]);
  } catch (err) {
    results.push(["FAIL", `${name}: ${err.message}`]);
  }
}

const { server, origin } = await serve();
const base = `${origin}/web/`;
const browser = await puppeteer.launch({
  executablePath: chromePath(),
  args: ["--no-sandbox"],
  defaultViewport: { width: 1200, height: 760 },
});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && !m.text().startsWith("Failed to load resource") && errors.push(m.text()));
page.on("response", (r) => r.status() >= 400 && errors.push(`HTTP ${r.status()}: ${r.url()}`));
page.on("requestfailed", (r) => errors.push(`request failed: ${r.url()}`));

const shot = async (name) => {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, `${name}.png`) });
};
const litPixels = () => page.$eval("#canvas", (c) => {
  const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
  let n = 0;
  for (let i = 0; i < d.length; i += 4) if (d[i] > 128) n++;
  return n;
});
const text = (sel) => page.$eval(sel, (e) => e.textContent);
const value = (sel) => page.$eval(sel, (e) => e.value);
// The clip has loaded and at least one frame has been drawn since (drawing
// happens on animation frames, so waiting for the text alone races it).
const loaded = async () => {
  await page.waitForFunction(() => document.querySelector("#answer-cat").textContent !== "");
  await page.evaluate(() => new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok))));
};

await check("loads and lists all clips", async () => {
  await page.goto(`${base}#02_01`);
  await loaded();
  const options = await page.$$eval("#clip option", (o) => o.length);
  const index = JSON.parse(readFileSync(join(ROOT, "data", "clips", "index.json"), "utf8"));
  assert.equal(options, index.clips.length);
  assert.equal(await text("#answer-cat"), "walk");
  await shot("01-walk");
});

await check("draws dots", async () => {
  assert.ok((await litPixels()) > 200, "canvas looks empty");
});

await check("arrow keys change clip and URL", async () => {
  await page.keyboard.press("ArrowRight");
  await page.waitForFunction(() => location.hash === "#07_01");
  await page.keyboard.press("ArrowLeft");
  await page.waitForFunction(() => location.hash === "#02_01");
});

await check("random hides the answer everywhere", async () => {
  await page.keyboard.press("r");
  await page.waitForFunction(() => location.hash !== "#02_01");
  await loaded();
  assert.equal(await text("#answer-cat"), "?");
  const labels = await page.$$eval("#clip option", (o) => o.map((x) => x.textContent));
  assert.ok(labels.every((l) => /^Clip \d+$/.test(l)), "clip list still shows ids");
  assert.equal(await page.$$eval("#clip optgroup", (g) => g.length), 0, "categories still in list");
  await shot("02-hidden");
  await page.keyboard.press("h");
  assert.notEqual(await text("#answer-cat"), "?");
});

await check("noise adds dots", async () => {
  await page.goto(`${base}?paused=1&t=1&noise=0#13_17`);
  await loaded();
  const before = await litPixels();
  await page.goto(`${base}?paused=1&t=1&noise=40#13_17`);
  await loaded();
  const after = await litPixels();
  assert.ok(after > before * 2, `noise barely changed the picture (${before} -> ${after})`);
  await shot("03-boxing-noise40");
});

await check("upside down flips the figure", async () => {
  const headY = async (inv) => {
    await page.goto(`${base}?paused=1&t=0.5&dots=1&inv=${inv}#02_01`);
    await loaded();
    // with dots=1 only the first reveal dot (left ankle) is drawn: find its height
    return page.$eval("#canvas", (c) => {
      const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
      for (let i = 0; i < d.length; i += 4) if (d[i] > 128) return Math.floor(i / 4 / c.width) / c.height;
      return -1;
    });
  };
  const up = await headY(0);
  const down = await headY(1);
  assert.ok(up > 0.6 && down < 0.4, `ankle at ${up.toFixed(2)} upright, ${down.toFixed(2)} inverted`);
  await shot("04-inverted-1dot");
});

await check("auto-reveal ends with all dots, no noise, upright, answer shown", async () => {
  await page.goto(`${base}?noise=40&inv=1&hide=1#09_01`);
  await loaded();
  await page.$eval("#reveal-secs", (e) => { e.value = 5; e.dispatchEvent(new Event("input")); });
  await page.keyboard.press("v");
  await new Promise((r) => setTimeout(r, 1500));
  assert.ok(+(await value("#dots")) < 31, "dots should still be partial early on");
  await shot("05-reveal-early");
  await page.waitForFunction(() => document.querySelector("#reveal-bar").hidden, { timeout: 8000 });
  assert.equal(await value("#dots"), "31");
  assert.equal(await value("#noise"), "0");
  assert.equal(await page.$eval("#inverted", (e) => e.checked), false);
  assert.equal(await text("#answer-cat"), "run");
  await shot("06-reveal-done");
});

await check("keeps up 50+ fps with 80 noise dots", async () => {
  await page.goto(`${base}?noise=80#55_02`);
  await loaded();
  const fps = await page.evaluate(() => new Promise((ok) => {
    let n = 0;
    const t0 = performance.now();
    const tick = () => (performance.now() - t0 < 1000 ? (n++, requestAnimationFrame(tick)) : ok(n));
    requestAnimationFrame(tick);
  }));
  assert.ok(fps >= 50, `${fps} fps`);
});

await check("every clip loads and draws", async () => {
  const ids = await page.$$eval("#clip option", (o) => o.map((x) => x.value));
  for (const id of ids) {
    await page.goto(`${base}?paused=1&t=0.5#${id}`);
    await loaded();
    assert.ok((await litPixels()) > 100, `${id} looks empty`);
  }
});

await check("no console errors", async () => {
  assert.deepEqual(errors, []);
});

await check("narrow (phone) layout has no horizontal scroll", async () => {
  await page.setViewport({ width: 390, height: 844 });
  await page.goto(`${base}#02_01`);
  await loaded();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  assert.ok(overflow <= 0, `page is ${overflow}px too wide`);
  await shot("07-phone");
});

await browser.close();
server.close();
for (const [status, msg] of results) console.log(`${status.padEnd(4)} ${msg}`);
const failed = results.filter(([s]) => s === "FAIL").length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
