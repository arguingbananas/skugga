// ESLint config (flat format). `npm run lint` runs it with pyflakes.
import js from "@eslint/js";
import globals from "globals";

export default [
  { ignores: ["node_modules/", "data/", "docs/"] },
  js.configs.recommended,
  {
    // The viewer and game: ES modules in the browser.
    files: ["web/**/*.js"],
    languageOptions: { sourceType: "module", globals: globals.browser },
  },
  {
    // Tests and tools run in Node, but also hand functions to the browser
    // through puppeteer's page.evaluate, so both sets of globals apply.
    files: ["tests/**/*.mjs", "tools/**/*.mjs", "eslint.config.js"],
    languageOptions: { sourceType: "module", globals: { ...globals.node, ...globals.browser } },
  },
];
