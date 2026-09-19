import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

const here = (path: string) => new URL(path, import.meta.url);

test("the package has no dependencies", () => {
  const manifest = JSON.parse(readFileSync(here("../package.json"), "utf8"));
  for (const field of ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"]) {
    assert.equal(manifest[field], undefined, `${field} must stay absent`);
  }
});

test("sources are runtime-neutral, import only each other, and never touch floating point", () => {
  const files = readdirSync(here("../src/")).filter((name) => name.endsWith(".ts"));
  assert.ok(files.length > 0, "the test is not looking where it should");
  const banned = [/\bparseFloat\b/, /\bparseInt\b/, /\bNumber\(/, /\bMath\./, /\.toFixed\(/, /\brequire\(/, /\bprocess\./, /\bDeno\./, /\bBun\./, /["']node:/, /\bJSON\.parse\b/];
  for (const name of files) {
    const source = readFileSync(here(`../src/${name}`), "utf8");
    const code = source.replace(/\/\/.*$/gm, "");
    for (const match of code.matchAll(/(?:from|import\()\s*["']([^"']+)["']/g)) {
      assert.match(match[1] as string, /^\.\/[a-z-]+\.ts$/, `${name} imports ${match[1]}`);
    }
    for (const pattern of banned) {
      assert.doesNotMatch(code, pattern, `${name} uses ${pattern}`);
    }
    for (const syntax of [/\benum\s/, /\bnamespace\s/, /constructor\s*\([^)]*\b(?:public|private|protected|readonly)\s/]) {
      assert.doesNotMatch(code, syntax, `${name} uses non-erasable syntax ${syntax}`);
    }
  }
});
