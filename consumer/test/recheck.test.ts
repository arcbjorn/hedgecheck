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
// Hand-derived from fixtures/bundles/good/, not from any implementation. EXACT, as
// rationals -- an earlier version of this comment wrote the rounded -999.91 with an
// equals sign, which is a discrepancy the next reader would have chased:
//   quantity 0.1, baseline 77631.4, floor 60000, cap -1000, price 0.17399
//   at 924: 0.1*(60000-77631.4) + 924 - 924*0.17399 = -24997669/25000 = -999.90676
//   at 300: 0.1*(60000-77631.4) + 300 - 300*0.17399 =  -1515337/1000  = -1515.337
//
// The 924 case clears the cap by 0.09324 on a scale of ~1000 -- under 0.01%. That is
// decisive (double precision is off by ~5.7e-13, eleven orders of magnitude clear)
// but THIN: a fixture edit nudging the baseline or the price by a fraction of a
// percent flips it, and the assertion below says so rather than failing obscurely.
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

// A NEGATIVE FILL IS REFUSED, NOT RECORDED.
//
// A negative price enters the P&L as `- size * price`, so it ADDS value: the 300-lot
// partial below misses the objective by 515, and a price of -5 makes it clear. The
// flagship test above only ever feeds well-formed positive fills, so it cannot see
// this.
test("a negative size or price is refused rather than written into a proposal", () => {
  for (const fill of [
    { size: "-300", avgPx: "0.17399" },
    { size: "300", avgPx: "-0.17399" },
    { size: "300", avgPx: "-5" },
    { size: "-1", avgPx: "-1" },
  ]) {
    assert.throws(
      () => proposalAfterFill(original(), "bucket0-yes", fill),
      RecheckError,
      `${JSON.stringify(fill)} was accepted`,
    );
  }
  // And classify refuses it too, rather than calling it an ordinary partial.
  assert.throws(() => classify("924", { size: "-5", avgPx: "1" }), RecheckError);
});

// AN AMBIGUOUS LOOKUP IS REFUSED EXACTLY AS AN ABSENT ONE IS.
//
// `found` used to be a boolean, so the map rewrote EVERY leg sharing the id: one fill
// of 7 contracts became a proposal claiming 7 on each of two legs, on two coins.
test("two legs sharing an id are refused, not both rewritten", () => {
  const document = parse(original()) as Record<string, Value>;
  const legs = document["legs"] as Value[];
  const first = legs[0] as Record<string, Value>;
  const twin = { ...first, instance: { ...(first["instance"] as Record<string, Value>), coin: "#99999" } };
  document["legs"] = [first, twin];
  const doubled = canonical(document as Value);

  assert.throws(
    () => proposalAfterFill(doubled, "bucket0-yes", { size: "7", avgPx: "0.17399" }),
    RecheckError,
    "a duplicated leg id was accepted",
  );
});

// AN OVER-FILL STOPS THE PROCEDURE when the ordered size is known.
//
// An Ioc cannot fill more than it asked for, so a venue saying it did is a venue
// disagreeing with the order that was placed -- the wrong moment to build a re-check
// on that same account of events.
test("a fill larger than the order is refused when the order is known", () => {
  assert.throws(
    () => proposalAfterFill(original(), "bucket0-yes", { size: "1000", avgPx: "0.17399" }, "924"),
    RecheckError,
  );
  // Without the ordered size there is nothing to compare against, and the fill is
  // taken at face value; the caller that knows the size is the one that must pass it.
  assert.doesNotThrow(
    () => proposalAfterFill(original(), "bucket0-yes", { size: "1000", avgPx: "0.17399" }),
  );
});

// THE LENIENT READING IS ANCHORED: it accepts trailing zeros and nothing else.
//
// The old fallback applied a trailing-zero regex to anything the grammar rejected, so
// it REPAIRED malformed text into a number nobody stated -- "1.0.0" became 1, and
// "0.174.0" became 0.174. Truncation only ever shrinks a decimal tail, so a lower
// recorded price makes the position look better than it is.
test("a malformed venue number is refused, never repaired", () => {
  for (const bad of ["1.0.0", "0.174.0", "12.34.00", "5.", "0.", "1.0.000", "1..0", ".5", ""]) {
    assert.throws(
      () => proposalAfterFill(original(), "bucket0-yes", { size: "300", avgPx: bad }),
      RecheckError,
      `${JSON.stringify(bad)} was accepted as a price`,
    );
  }
  // Genuine trailing zeros are still a reading, not a change of value.
  for (const [sent, want] of [["0.17400", "0.174"], ["1200.0", "1200"], ["300.0", "300"], ["0.000", "0"]] as const) {
    const after = proposalAfterFill(original(), "bucket0-yes", { size: "300", avgPx: sent });
    assert.equal((legOf(after)["acquisition"] as Record<string, Value>)["price"], want, `${sent} was misread`);
  }

  // AND THE VALUE, not merely that something refused. A loose reading turns "5." into
  // 5 and "1.0.0" into 1 WITHOUT throwing, so a test that only catches an error is
  // satisfied by the wrong implementation. Each malformed price is checked for the
  // number it must never silently become.
  for (const [bad, mustNotBecome] of [["5.", "5"], ["1.0.0", "1"], ["0.174.0", "0.174"], ["12.34.00", "12.34"]] as const) {
    let price: unknown = null;
    try {
      price = legOf(proposalAfterFill(original(), "bucket0-yes", { size: "300", avgPx: bad }));
      price = (price as Record<string, Value>)["acquisition"];
      price = (price as Record<string, Value>)["price"];
    } catch {
      continue; // Refused, which is the correct outcome.
    }
    assert.fail(`${JSON.stringify(bad)} was silently read as ${String(price)} (must not become ${mustNotBecome})`);
  }
});

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
