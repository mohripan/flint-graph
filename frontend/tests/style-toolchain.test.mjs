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

test("the Studio panel clips what it contains, so the page never gets a second scrollbar", () => {
  const css = readFileSync(new URL("../src/narrative/studio.css", import.meta.url), "utf8");
  const panel = css.match(/^\.narrative-studio \{([^}]*)\}/m);
  assert.ok(panel, "the panel's rule exists");
  // Absolutely positioned descendants, such as hidden radios in a long form, are only clipped
  // by an overflow container that is also positioned.
  assert.match(panel[1], /position:relative/);
  assert.match(panel[1], /overflow:auto/);
});
