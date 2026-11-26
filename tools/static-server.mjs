// Tiny static file server for the repo, bound to 127.0.0.1 on a free port.
// Used by the smoke test and the demo renderer.

import { execSync } from "node:child_process";
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = resolve(fileURLToPath(import.meta.url), "../..");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

/** @returns {Promise<{server: import("node:http").Server, origin: string}>} */
export function serve() {
  const server = createServer((req, res) => {
    const path = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname));
    let file = join(ROOT, path);
    if (file !== ROOT && !file.startsWith(ROOT + sep)) return res.writeHead(403).end();
    if (existsSync(file) && statSync(file).isDirectory()) file = join(file, "index.html");
    if (!existsSync(file)) return res.writeHead(404).end();
    res.writeHead(200, { "Content-Type": TYPES[extname(file)] ?? "application/octet-stream" });
    createReadStream(file).pipe(res);
  });
  return new Promise((ok) =>
    server.listen(0, "127.0.0.1", () => ok({ server, origin: `http://127.0.0.1:${server.address().port}` })),
  );
}

/** Path to a Chromium/Chrome binary: $CHROME_PATH or the first one on PATH. */
export function chromePath() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  return execSync("command -v chromium || command -v chromium-browser || command -v google-chrome", {
    shell: "/bin/sh",
  }).toString().trim();
}
