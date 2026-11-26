// Smoke test for the game: three phones play a whole (short) game in
// headless Chromium against the real server.
//
//   npm run smoke:game                   # assertions only
//   npm run smoke:game -- path/to/shots  # also save screenshots there
//
// tests/game_launcher.py starts the server with fast timings and 3 rounds:
//   round 1: Ben guesses wrong, Ana right; Cy joins late and must wait
//   round 2: everyone guesses wrong; Ben reloads his page
//   round 3: nobody guesses (time runs out)
// then the final scores and Play again, with Cy playing.

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { chromePath } from "../tools/static-server.mjs";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const SHOTS = process.argv[2] ? resolve(process.argv[2]) : null;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const server = spawn("python3", [join(HERE, "game_launcher.py")], { stdio: ["ignore", "pipe", "inherit"] });
const port = await new Promise((ok, fail) => {
  createInterface({ input: server.stdout }).once("line", ok);
  server.once("exit", (code) => fail(new Error(`server exited (${code})`)));
});
const base = `http://127.0.0.1:${port}/`;
const browser = await puppeteer.launch({ executablePath: chromePath(), args: ["--no-sandbox"] });

const errors = [];
const stats = { trackRequests: 0, trackRefused: 0 };
const results = [];
async function check(name, fn) {
  try {
    await fn();
    results.push(["ok", name]);
  } catch (err) {
    results.push(["FAIL", `${name}: ${err.message.split("\n")[0]}`]);
  }
}

/** The server's view, from the test-only route. */
const truth = () => fetch(base + "test/answer").then((r) => r.json());
async function until(cond, what, ms = 30_000) {
  const end = Date.now() + ms;
  for (;;) {
    const t = await truth();
    if (cond(t)) return t;
    if (Date.now() > end) throw new Error(`timed out waiting for ${what} (at ${t.status}, round ${t.round})`);
    await wait(40);
  }
}

async function phone(name) {
  const context = await browser.createBrowserContext();   // own storage, like a separate phone
  const page = await context.newPage();
  await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
  page.on("pageerror", (e) => errors.push(`${name}: ${e.message}`));
  page.on("console", (m) => {
    // A dot asked for a moment early is refused (403) and retried: expected.
    if (m.type() === "error" && !/status of 403/.test(m.text())) errors.push(`${name}: ${m.text()}`);
  });
  page.on("response", (r) => {
    if (!r.url().includes("/marker/")) return;
    stats.trackRequests++;
    if (r.status() === 403) stats.trackRefused++;
    else if (!r.ok()) errors.push(`${name}: ${r.status()} ${r.url()}`);
  });
  await page.goto(base);
  await page.waitForSelector("#join-name", { visible: true });
  await page.type("#join-name", name);
  await page.click("#join-form button");
  await page.waitForSelector("#scores li.me", { visible: true });
  return page;
}

const text = (page, sel) => page.$eval(sel, (e) => e.textContent);
/** [[name, score], ...] as a phone shows them, without the "you"/"leader" tags. */
const scoreboard = (page) => page.$$eval("#scores li", (lis) => lis.map((li) => [
  li.querySelector(".name").firstChild.textContent, Number(li.querySelector(".score").textContent)]));
const visible = (page, sel) => page.$eval(sel, (e) => !e.closest("[hidden]"));
const shot = async (page, name) => SHOTS && page.screenshot({ path: join(SHOTS, `${name}.png`) });
const litPixels = (page) => page.$eval("#canvas", (c) => {
  const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
  let n = 0;
  for (let i = 0; i < d.length; i += 4) if (d[i] > 128) n++;
  return n;
});
async function guess(page, words) {
  await page.waitForSelector("#guess:not([disabled])");
  await page.type("#guess", words);
  await page.click("#guess-form button");
}

if (SHOTS) mkdirSync(SHOTS, { recursive: true });
let ana, ben, cy;
try {
  await check("two phones join; the first leads and starts", async () => {
    ana = await phone("Ana");
    ben = await phone("Ben");
    await ana.waitForSelector("#start-btn:not([disabled])", { visible: true });
    assert.equal(await visible(ben, "#start-btn"), false, "Ben shouldn't see Start");
    assert.match(await text(ben, "#lobby-note"), /Waiting for Ana/);
    await shot(ana, "1-lobby");
    await ana.click("#start-btn");
    await until((t) => t.status === "countdown", "the countdown");
  });

  await check("round 1: dots appear, a wrong guess puts Ben out, Ana scores", async () => {
    await until((t) => t.status === "reveal", "round 1");
    await wait(500);                                  // ~3 dots
    assert.ok((await litPixels(ana)) > 50, "no dots drawn");
    assert.match(await text(ana, "#dots-line"), /\d+ \/ 15 dots.*pts/);
    const { category } = await truth();
    // A wrong guess for sure: another category's name (a made-up phrase can
    // be read as a typo of a synonym, e.g. "weaving" as "waving").
    const wrong = category === "walk" ? "run" : "walk";
    await guess(ben, wrong);
    await ben.waitForFunction(() => /isn't it/.test(document.querySelector("#guess-status").textContent));
    assert.equal(await ben.$eval("#guess", (e) => e.disabled), true, "Ben can guess again");
    await ana.waitForFunction(() => document.querySelector("#scores li:not(.me)")?.classList.contains("out"));
    await shot(ben, "2-wrong-guess");
    await guess(ana, category);
    await until((t) => t.status === "answer", "the answer");
    await ana.waitForFunction(() => !document.querySelector("#answer").hidden);
    assert.equal((await text(ana, "#answer-category")).toLowerCase(), category);
    assert.match(await text(ana, "#answer-result"), /Ana got it: \+\d+/);
    await ben.waitForFunction((w) => document.querySelector("#answer-guesses").textContent.includes(`${w} ✗`), {}, wrong);
    await shot(ana, "3-answer");
  });

  await check("a late joiner waits for the next game", async () => {
    cy = await phone("Cy");
    await cy.waitForFunction(() => /next game/.test(document.querySelector("#scores li.me").textContent));
    await until((t) => t.status === "reveal" && t.round === 2, "round 2");
    await cy.waitForFunction(() => document.querySelector("#guess").disabled);
    assert.match(await text(cy, "#guess-status"), /next game/);
  });

  await check("round 2: everyone guessing wrong ends the round", async () => {
    await guess(ana, "zzz");
    await guess(ben, "qqq");
    const t = await until((x) => x.status === "answer" && x.round === 2, "round 2's answer");
    assert.equal(t.round, 2);
    await ben.waitForFunction(() => /Everyone guessed wrong/.test(document.querySelector("#answer-result").textContent));
  });

  await check("reloading a phone keeps the player and score", async () => {
    const before = await scoreboard(ana);
    await ben.reload();
    await ben.waitForSelector("#scores li.me", { visible: true });
    assert.match(await text(ben, "#scores li.me"), /Ben/);
    assert.deepEqual(await scoreboard(ben), before, "scores differ after reload");
    assert.ok(before.find(([n]) => n === "Ana")[1] > 0, "Ana's round-1 points missing");
  });

  await check("round 3: nobody guesses, time runs out", async () => {
    await until((t) => t.status === "answer" && t.round === 3, "round 3's answer");
    await ana.waitForFunction(() => /Nobody got it/.test(document.querySelector("#answer-result").textContent));
  });

  await check("final scores, then Play again with the late joiner", async () => {
    await until((t) => t.status === "final", "the final scores");
    await ana.waitForSelector("#again-btn:not([disabled])", { visible: true });
    assert.match(await text(ana, "#final-title"), /Ana wins!/);
    assert.equal(await visible(ben, "#again-btn"), false, "Ben shouldn't see Play again");
    await shot(ana, "4-final");
    await ana.click("#again-btn");
    await until((t) => t.status === "countdown", "a new game");
    await cy.waitForFunction(() => !/next game/.test(document.querySelector("#scores li.me").textContent));
    assert.ok((await scoreboard(cy)).every(([, score]) => score === 0), "scores weren't reset");
  });

  await check("no page errors, and every dot request was answered", async () => {
    assert.deepEqual(errors, []);
    assert.ok(stats.trackRequests >= 15, `only ${stats.trackRequests} dot requests`);
    // Refusals are a phone's clock being a moment early; a few are normal.
    assert.ok(stats.trackRefused <= stats.trackRequests / 10, `${stats.trackRefused} of ${stats.trackRequests} refused`);
  });
} finally {
  await browser.close();
  server.kill();
}

for (const [status, msg] of results) console.log(`${status.padEnd(4)} ${msg}`);
const failed = results.filter(([s]) => s === "FAIL").length;
console.log(`\n${results.length - failed}/${results.length} passed  (dot requests: ${stats.trackRequests}, refused early: ${stats.trackRefused})`);
process.exit(failed ? 1 : 0);
