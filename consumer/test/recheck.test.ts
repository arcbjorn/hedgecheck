// The re-check after a fill that is not the envelope's size.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { canonical, parse, type Value } from "../../checker/src/canon.ts";
import { classify, proposalAfterFill, RecheckError } from "../src/recheck.ts";

const here = (path: string) => new URL(path, import.meta.url);
const original = () => new Uint8Array(readFileSync(here("../../fixtures/bundles/good/proposal.json")));
const text = (bytes: Uint8Array) => new TextDecoder().decode(bytes);

function legOf(bytes: Uint8Array): Record<string, Value> {
  const document = parse(bytes) as Record<string, Value>;
  return (document["legs"] as Value[])[0] as Record<string, Value>;
}

test("a fill is classified against what was ordered", () => {
  assert.equal(classify("924", { size: "924", avgPx: "0.17399" }), "exact");
  assert.equal(classify("924", { size: "300", avgPx: "0.17399" }), "partial");
  assert.equal(classify("924", { size: "0", avgPx: "0" }), "none");
  assert.equal(classify("924", { size: "1000", avgPx: "0.17399" }), "over");
  // The venue's own spelling of a whole number.
  assert.equal(classify("924", { size: "924.0", avgPx: "0.17399" }), "exact");
});

// THE NEW PROPOSAL IS ABOUT WHAT IS ACTUALLY HELD.
//
// Three things change: the size, the acquisition, and nothing else.
test("the new proposal holds what filled, at the price paid", () => {
  const after = proposalAfterFill(original(), "bucket0-yes", { size: "300", avgPx: "0.17399" });
  const leg = legOf(after);
  assert.equal(leg["size"], "300");
  // Compared field by field: canon.parse builds objects with a NULL prototype, so
  // deepStrictEqual against a plain literal fails on the prototype alone. The null
  // prototype is the point -- it is what stops `__proto__` in a document reaching
  // Object.prototype -- so the test bends, not the parser.
  const acquisition = leg["acquisition"] as Record<string, Value>;
  assert.equal(acquisition["kind"], "fixed");
  assert.equal(acquisition["price"], "0.17399");
  assert.deepEqual(Object.keys(acquisition).sort(), ["kind", "price"]);
});

// THE BASELINE IS INHERITED, so the premium counts once.
//
// Re-reading it would value the holding against a moment the money was not spent
// at, and the answer would be about a different question from the one the order was
// placed to settle.
test("the baseline and everything else are inherited unchanged", () => {
  const before = parse(original()) as Record<string, Value>;
  const after = parse(proposalAfterFill(original(), "bucket0-yes", {
    size: "300",
    avgPx: "0.17399",
  })) as Record<string, Value>;

  assert.deepEqual(after["baseline"], before["baseline"], "the baseline moved");
  for (const field of [
    "schema_version", "units", "domain", "exposure", "objective",
    "objective_valuation_time", "other_costs", "assumptions",
  ]) {
    assert.deepEqual(after[field], before[field], `${field} changed`);
  }

  // And the leg changed in exactly two fields.
  const legBefore = legOf(original());
  const legAfter = legOf(canonical(after as Value));
  const changed = Object.keys(legAfter).filter(
    (key) => JSON.stringify(legAfter[key]) !== JSON.stringify(legBefore[key]),
  ).sort();
  assert.deepEqual(changed, ["acquisition", "size"], `the leg changed in ${changed}`);
});

// A book_walk would RE-PRICE a purchase that already happened.
test("the acquisition becomes fixed, never a fresh walk", () => {
  assert.equal((legOf(original())["acquisition"] as Record<string, Value>)["kind"], "book_walk");
  const after = proposalAfterFill(original(), "bucket0-yes", { size: "300", avgPx: "0.174" });
  const acquisition = legOf(after)["acquisition"] as Record<string, Value>;
  assert.equal(acquisition["kind"], "fixed");
  assert.equal(acquisition["snapshot"], undefined, "a fixed acquisition still cites a book");
});

// THE CASE THE PLAN EXISTS FOR.
//
// Hand-derived from fixtures/bundles/good/, not from any implementation:
//   quantity 0.1, baseline 77631.4, floor 60000, cap -1000, price 0.17399
//   at 924 contracts: 0.1*(60000-77631.4) + 924 - 924*0.17399 = -999.91  >= -1000
//   at 300 contracts: 0.1*(60000-77631.4) + 300 - 300*0.17399 = -1515.34 <  -1000
//
// So a partial fill below the smallest passing size leaves a position that does NOT
// meet the objective, and the re-check must say so rather than inheriting the
// verdict the full size earned.
test("a partial fill below the smallest passing size does not pass", () => {
  const after = proposalAfterFill(original(), "bucket0-yes", { size: "300", avgPx: "0.17399" });
  const leg = legOf(after);

  // The proposal now describes 300 contracts, which is below the 924 the original
  // was sized at.
  assert.equal(leg["size"], "300");
  assert.equal(legOf(original())["size"], "924");

  // The arithmetic, redone here from the document's own numbers.
  const document = parse(after) as Record<string, Value>;
  const exposure = document["exposure"] as Record<string, Value>;
  const domain = document["domain"] as Record<string, Value>;
  const baseline = document["baseline"] as Record<string, Value>;
  const clause = (document["objective"] as Value[])[0] as Record<string, Value>;

  const quantity = ratio(exposure["quantity"] as string);
  const floor = ratio(domain["lower"] as string);
  const base = ratio(baseline["price"] as string);
  const cap = ratio(clause["min_pnl"] as string);
  const size = ratio(leg["size"] as string);
  const price = ratio((leg["acquisition"] as Record<string, Value>)["price"] as string);

  // P&L at the floor: the holding's loss, plus the contracts' payoff, minus premium.
  const pnl = quantity * (floor - base) + size - size * price;
  assert.ok(pnl < cap, `at the floor the position gives ${pnl}, which meets the cap ${cap}`);

  // And the full size would have met it, so the difference is the fill and not the
  // fixture.
  const full = ratio("924");
  const pnlFull = quantity * (floor - base) + full - full * price;
  assert.ok(pnlFull >= cap, "the full size does not meet the cap either; the fixture moved");
});

/** A rational from canonical text, as a JavaScript number is not allowed to be. */
function ratio(value: string): number {
  // Only used for the inequality above, where the magnitudes are far from any
  // precision boundary. The engine and the checker do this exactly; this is a test
  // asserting a direction, not a document.
  if (value.includes("/")) {
    const [num, den] = value.split("/");
    return Number(num) / Number(den);
  }
  return Number(value);
}

test("a leg the proposal does not have is refused", () => {
  assert.throws(
    () => proposalAfterFill(original(), "no-such-leg", { size: "1", avgPx: "0.1" }),
    RecheckError,
  );
});

// The venue's spelling is read, not adopted: "1200.0" is the number 1200.
test("a venue number is normalised to its canonical form", () => {
  const after = proposalAfterFill(original(), "bucket0-yes", { size: "300.0", avgPx: "0.17400" });
  const leg = legOf(after);
  assert.equal(leg["size"], "300");
  assert.equal((leg["acquisition"] as Record<string, Value>)["price"], "0.174");
});

// The result is canonical bytes, so it can be digested and checked like any other
// proposal.
test("the new proposal is canonical", () => {
  const after = proposalAfterFill(original(), "bucket0-yes", { size: "300", avgPx: "0.17399" });
  assert.equal(text(canonical(parse(after))), text(after));
});
