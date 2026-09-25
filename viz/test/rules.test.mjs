// The owner's standing rules, checked mechanically over the source tree.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { execFileSync } from "node:child_process";

const root = new URL("../", import.meta.url);
const read = (rel) => readFileSync(new URL(rel, root), "utf8");
const sources = readdirSync(new URL("src/", root)).filter((f) => f.endsWith(".ts"));

test("source is TypeScript, compiled by typescript 7.0.2", () => {
  const pkg = JSON.parse(read("package.json"));
  assert.equal(pkg.devDependencies.typescript, "7.0.2", "exact pin");
  assert.deepEqual(Object.keys(pkg.dependencies ?? {}), [], "no runtime dependencies");
  const out = execFileSync(process.execPath, [new URL("node_modules/typescript/bin/tsc", root).pathname, "--version"], { encoding: "utf8" });
  assert.match(out, /7\.0\.2/);
  const tsconfig = JSON.parse(read("tsconfig.json"));
  assert.equal(tsconfig.compilerOptions.strict, true);
  assert.ok(sources.length >= 8);
});

test("no innerHTML, no Math.random, no eval in the source", () => {
  for (const f of sources) {
    const text = read(`src/${f}`).replace(/\/\/.*$/gm, "");
    assert.ok(!/\binnerHTML\b|\bouterHTML\b|insertAdjacentHTML/.test(text), `${f} writes HTML`);
    assert.ok(!/Math\.random\s*\(/.test(text), `${f} uses Math.random`);
    assert.ok(!/\beval\s*\(|new Function\s*\(/.test(text), `${f} evaluates code`);
  }
});

test("no CSS transitions or animations: motion is physics", () => {
  const css = read("style.css").replace(/\/\*[\s\S]*?\*\//g, "");
  assert.ok(!/\btransition\s*:|\banimation\s*:|@keyframes|scroll-behavior\s*:\s*smooth/.test(css));
  for (const f of sources) {
    const text = read(`src/${f}`);
    assert.ok(!/\.animate\s*\(|requestAnimationFrame\s*\(\s*\(\s*\)\s*=>\s*.*lerp/i.test(text), `${f} animates`);
  }
});

test("index.html loads only local files (no CDN)", () => {
  const html = read("index.html");
  const refs = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map((m) => m[1]);
  assert.ok(refs.length > 0);
  for (const r of refs) assert.ok(!/^(https?:)?\/\//.test(r), `external reference ${r}`);
});

test("colours live in style.css only (the canvas reads them back)", () => {
  for (const f of sources) {
    if (f === "theme.ts") continue; // documented fallbacks only
    const text = read(`src/${f}`);
    assert.ok(!/#[0-9a-fA-F]{6}\b/.test(text), `${f} hard-codes a colour`);
  }
  const css = read("style.css");
  for (const token of ["--surface", "--ink", "--ink-2", "--muted", "--hairline", "--accent", "--accent-2", "--coverage-ramp"]) {
    assert.ok(css.includes(`${token}:`), `style.css defines ${token}`);
  }
  assert.ok(css.includes(':root:not([data-theme="light"])') && css.includes(':root[data-theme="dark"]'), "dark set under both scopes");
});
