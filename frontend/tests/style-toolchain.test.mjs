import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("the locked stylesheet toolchain uses Tailwind 4's Vite integration", () => {
  const manifest = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.match(manifest.devDependencies.tailwindcss, /^(?:\^|~)?4\./);
  assert.ok(manifest.devDependencies["@tailwindcss/vite"]);
  assert.equal(manifest.devDependencies.autoprefixer, undefined);
  const vite = readFileSync(new URL("../vite.config.ts", import.meta.url), "utf8");
  assert.match(vite, /tailwindcss\(\)/);
});

test("Tailwind explicitly loads the existing brand theme and preserves base form styling", () => {
  const css = readFileSync(new URL("../src/index.css", import.meta.url), "utf8");
  assert.match(css, /@import "tailwindcss"/);
  assert.match(css, /@config "\.\.\/tailwind.config.js"/);
  assert.match(css, /input::placeholder/);
  assert.match(css, /cursor: pointer/);
});
