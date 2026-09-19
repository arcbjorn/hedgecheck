import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { canonical, digest, parse as parseJson, CanonError } from "../src/canon.ts";
import { format, parse as parseNumber, NumberError } from "../src/exact.ts";

const vectors = (name: string) => JSON.parse(readFileSync(new URL(`../../fixtures/vectors/${name}.json`, import.meta.url), "utf8")).vectors;

const bytes = (hex: string): Uint8Array => Uint8Array.from(hex.match(/../g) ?? [], (pair) => Number.parseInt(pair, 16));

test("numbers: the grammar and the canonical form", () => {
  const rows = vectors("numbers");
  assert.ok(rows.length > 0);
  for (const row of rows) {
    let out: string | undefined;
    try {
      out = format(parseNumber(row.input));
    } catch (error) {
      assert.ok(error instanceof NumberError, `${JSON.stringify(row.input)}: unexpected ${error}`);
    }
    assert.equal(out !== undefined, row.accepted, `${JSON.stringify(row.input)}: accepted`);
    if (row.accepted) assert.equal(out, row.canonical, `${JSON.stringify(row.input)}: canonical`);
  }
});

test("canonical JSON: the profile, the bytes and the digest", async () => {
  const rows = vectors("canonical-json");
  assert.ok(rows.length > 0);
  for (const row of rows) {
    let value;
    try {
      value = parseJson(bytes(row.input_hex));
    } catch (error) {
      assert.ok(error instanceof CanonError, `${row.name}: unexpected ${error}`);
    }
    assert.equal(value !== undefined, row.accepted, `${row.name}: accepted`);
    if (value === undefined) continue;
    assert.equal(new TextDecoder().decode(canonical(value)), row.canonical, `${row.name}: canonical`);
    assert.equal(await digest(value), row.sha256, `${row.name}: digest`);
  }
});
