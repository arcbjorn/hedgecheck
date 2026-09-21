// Venue JSON: as strict as canon about syntax, and never a float.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { parse as parseCanonical } from "../src/canon.ts";
import {
  at,
  isNumber,
  numberLexeme,
  parseVenue,
  quantityText,
  VenueError,
  type VenueValue,
} from "../src/venue.ts";

const here = (path: string) => new URL(path, import.meta.url);
const bytes = (text: string) => new TextEncoder().encode(text);

test("every retained snapshot parses, and canon refuses them", () => {
  const days = readdirSync(here("../../fixtures/replay/"));
  assert.ok(days.length > 0, "the test is not looking where it should");
  let snapshots = 0;
  let numbers = 0;
  let nulls = 0;
  for (const day of days) {
    for (const name of readdirSync(here(`../../fixtures/replay/${day}/`))) {
      if (!name.endsWith(".json")) continue;
      if (/\.(request|proposal|run|result|ir)\.json$/.test(name)) continue;
      const raw = readFileSync(here(`../../fixtures/replay/${day}/${name}`));
      const parsed = parseVenue(new Uint8Array(raw));
      snapshots += 1;
      const counted = count(parsed);
      numbers += counted.numbers;
      nulls += counted.nulls;
      // The same bytes are OUTSIDE the canonical profile. If canon accepted them the
      // second parser would have no reason to exist.
      assert.throws(
        () => parseCanonical(new Uint8Array(raw)),
        `${name} was accepted by the canonical parser`,
      );
    }
  }
  assert.ok(snapshots >= 4, `only ${snapshots} snapshots were read`);
  assert.ok(numbers > 0, "no JSON number was seen, so the relaxation is untested");
  assert.ok(nulls > 0, "no null was seen, so the relaxation is untested");
});

function count(value: VenueValue): { numbers: number; nulls: number } {
  if (value === null) return { numbers: 0, nulls: 1 };
  if (isNumber(value)) return { numbers: 1, nulls: 0 };
  if (Array.isArray(value)) {
    return value.reduce(
      (total, item) => {
        const inner = count(item);
        return { numbers: total.numbers + inner.numbers, nulls: total.nulls + inner.nulls };
      },
      { numbers: 0, nulls: 0 },
    );
  }
  if (typeof value === "object") {
    return Object.values(value).reduce(
      (total, item) => {
        const inner = count(item);
        return { numbers: total.numbers + inner.numbers, nulls: total.nulls + inner.nulls };
      },
      { numbers: 0, nulls: 0 },
    );
  }
  return { numbers: 0, nulls: 0 };
}

test("a number keeps its lexeme exactly and is never converted", () => {
  // Each of these loses information through a JavaScript number. The lexeme does not.
  const cases = [
    "1200.0",
    "0.1",
    "1e3",
    "1.2E+3",
    "-0.00000000000000000001",
    "123456789012345678901234567890",
    "0.30000000000000004",
    "9007199254740993",
    "-0",
  ];
  for (const lexeme of cases) {
    const parsed = parseVenue(bytes(`{"n":${lexeme}}`));
    const found = at(parsed, ["n"]);
    assert.equal(numberLexeme(found as VenueValue), lexeme, `${lexeme} did not survive`);
  }
});

test("a quantity is read only from a string field", () => {
  const parsed = parseVenue(bytes(`{"px":"0.17399","sz":1200.0,"time":1789715834738}`));
  assert.equal(quantityText(parsed, ["px"]), "0.17399");
  // A number is refused even though it could be converted. The conversion is the
  // thing that must not happen.
  assert.throws(() => quantityText(parsed, ["sz"]), /only from a string field/);
  assert.throws(() => quantityText(parsed, ["time"]), /only from a string field/);
  assert.throws(() => quantityText(parsed, ["absent"]), VenueError);
});

test("syntax is as strict as canon", () => {
  const refused: [string, string][] = [
    ['{"a":1,"a":2}', "duplicate key"],
    ['{"a":01}', "leading zero"],
    ['{"a":.5}', "bare decimal point"],
    ['{"a":+1}', "leading plus"],
    ['{"a":1.}', "trailing decimal point"],
    ['{"a":Infinity}', "Infinity"],
    ['{"a":NaN}', "NaN"],
    ['{"a":0x10}', "hex"],
    ['{"a":"\\ud800"}', "a lone high surrogate"],
    ['{"a":"\\udc00"}', "a lone low surrogate"],
    ['{"a":"rawcontrol"}', "a raw control character"],
    ['{"a":1}{"b":2}', "trailing text"],
    ["{", "an unterminated object"],
    ['{"a":}', "a missing value"],
    ["[1,]", "a trailing comma"],
    ['{"a" 1}', "a missing colon"],
  ];
  for (const [text, what] of refused) {
    assert.throws(() => parseVenue(bytes(text)), VenueError, `${what} was accepted`);
  }

  // A byte order mark, which is not whitespace.
  assert.throws(() => parseVenue(new Uint8Array([0xef, 0xbb, 0xbf, 0x7b, 0x7d])), VenueError);
  // Invalid UTF-8.
  assert.throws(() => parseVenue(new Uint8Array([0x7b, 0x22, 0xff, 0x22, 0x7d])), VenueError);

  // Nesting is bounded, so a hostile snapshot cannot exhaust the stack.
  const deep = `${"[".repeat(200)}${"]".repeat(200)}`;
  assert.throws(() => parseVenue(bytes(deep)), /nested deeper/);
});

test("venue keys are data, not a path to Object.prototype", () => {
  const parsed = parseVenue(
    bytes('{"__proto__":{"polluted":"yes"},"constructor":"x","toString":"y"}'),
  );
  assert.equal(quantityText(parsed, ["constructor"]), "x");
  assert.equal(quantityText(parsed, ["toString"]), "y");
  // Nothing reached the prototype: a fresh object is unaffected.
  const bystander: Record<string, unknown> = {};
  assert.equal(bystander["polluted"], undefined, "Object.prototype was polluted");
  assert.equal(({} as Record<string, unknown>)["polluted"], undefined);
});

test("camelCase keys are accepted here and refused by canon", () => {
  const text = '{"dayNtlVlm":"1.0","marginTableId":5,"isDelisted":null}';
  const parsed = parseVenue(bytes(text));
  assert.equal(quantityText(parsed, ["dayNtlVlm"]), "1.0");
  assert.equal(at(parsed, ["isDelisted"]), null);
  assert.throws(() => parseCanonical(bytes(text)), /key outside/);
});
