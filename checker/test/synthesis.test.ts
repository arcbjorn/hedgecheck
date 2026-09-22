// The synthesis gate: every answer in fixtures/synthesis is accepted, or refused with
// exactly the class its `.expects` file names.
//
// The checker is asked the same QUESTION the oracle was, not handed its answer. It rebuilds
// the constraint rows from the base and candidates the document carries, through its own
// kernel and its own maximal-piece derivation -- a different route from the oracle's atom
// walk. Agreement between two derivations is evidence; agreement between one derivation and
// a copy of itself is not.
//
// And it never solves. A feasible answer is one evaluation of the rows; an infeasible one is
// one multiplication of the certificate.

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";

import { parse as parseCanonical } from "../src/canon.ts";
import { format, parse as parseNumber } from "../src/exact.ts";
import { cash, indicator, finite, linear, NEG_INF, POS_INF, sum } from "../src/pwa.ts";
import { rows, verifySynthesis } from "../src/synthesis.ts";

const DIRECTORY = "../fixtures/synthesis";

interface Fixture {
  readonly name: string;
  readonly expects: string;
  readonly why: string;
  /**
   * A substring the refusal's own message must contain, where the CLASS cannot tell two
   * faults apart. An unknown certificate site and a certificate that proves nothing are both
   * CERTIFICATE_WEIGHTS, so a checker that silently ignored an unknown site would still
   * refuse -- by the later b.y test, for the wrong reason. The class alone cannot see that.
   */
  readonly detail: string | undefined;
}

function fixtures(): Fixture[] {
  const names = readdirSync(DIRECTORY)
    .filter((name) => name.endsWith(".json"))
    .map((name) => name.slice(0, -".json".length))
    .sort();
  return names.map((name) => {
    const lines = readFileSync(`${DIRECTORY}/${name}.expects`, "utf8").split("\n");
    const detail = (lines[2] ?? "").trim();
    return {
      name,
      expects: lines[0] as string,
      why: (lines[1] ?? "") as string,
      detail: detail === "" ? undefined : detail,
    };
  });
}

test("every synthesis answer is accepted or refused with its stated class", () => {
  const found = fixtures();
  assert.ok(found.length >= 12, `only ${found.length} synthesis fixtures; the set is meant to be broad`);
  let accepted = 0;
  const classes = new Set<string>();
  let detailed = 0;
  for (const { name, expects, why, detail } of found) {
    const document = parseCanonical(readFileSync(`${DIRECTORY}/${name}.json`));
    const outcome = verifySynthesis(document);
    if (expects === "accept") {
      assert.ok(
        outcome.accepted,
        `${name} must be accepted (${why}) but was refused: ${
          outcome.accepted ? "" : `${outcome.refusal.class} at ${outcome.refusal.at}: ${outcome.refusal.detail}`
        }`,
      );
      accepted += 1;
      continue;
    }
    assert.ok(!outcome.accepted, `${name} was ACCEPTED; it must be refused: ${why}`);
    assert.equal(
      outcome.refusal.class,
      expects,
      `${name} expects ${expects}, the checker said ${outcome.refusal.class}: ${outcome.refusal.detail}`,
    );
    classes.add(expects);
    if (detail !== undefined) {
      assert.ok(
        outcome.refusal.detail.includes(detail),
        `${name} must be refused for "${detail}" but said: ${outcome.refusal.detail}`,
      );
      detailed += 1;
    }
  }
  assert.ok(detailed >= 6, `only ${detailed} fixtures pin the refusal's reason, not just its class`);
  assert.ok(accepted >= 3, `only ${accepted} accepted answers; a checker that refuses everything proves nothing`);
  assert.ok(classes.size >= 3, `only ${classes.size} refusal classes exercised`);
});

// The rows are the CONSTRAINT SET, and this checker must find the same one the oracle does.
// Pinned by hand rather than against the oracle's output: the PLAN section 3 program is
// 0.1 BTC from 100,000 over [60,000, 110,000] with one digital below 90,000, and its four
// distinct constraints are the domain floor, both sides of the strike, and the domain top.
test("the rows are the four distinct constraints of the PLAN section 3 program", () => {
  const base = linear(parseNumber("0.1"), parseNumber("100000"));
  const unit = indicator(parseNumber("1"), NEG_INF, finite(parseNumber("90000"), false));
  const derived = rows(base, [unit], parseNumber("60000"), parseNumber("110000"));
  const shown = derived.map((row) => [
    format(row.price),
    row.side,
    format(row.alpha),
    format(row.coefficients[0] as ReturnType<typeof parseNumber>),
  ]);
  // Canonical order: by price, then `at` before `below` before `above`. At the strike both
  // constraints survive -- `at` where the digital has expired and pays nothing, `below`
  // where it still pays in full.
  assert.deepEqual(shown, [
    ["60000", "at", "-4000", "1"],
    ["90000", "at", "-1000", "0"],
    ["90000", "below", "-1000", "1"],
    ["110000", "at", "1000", "0"],
  ]);
});

// BOTH constraints at the strike survive deduplication, because they are different
// inequalities: below it the digital pays, at it the digital does not.
test("deduplication keeps distinct constraints at one price", () => {
  const base = linear(parseNumber("0.1"), parseNumber("100000"));
  const unit = indicator(parseNumber("1"), NEG_INF, finite(parseNumber("90000"), false));
  const derived = rows(base, [unit], parseNumber("60000"), parseNumber("110000"));
  const strike = derived
    .filter((row) => format(row.price) === "90000")
    .map((row) => [row.side, format(row.coefficients[0] as ReturnType<typeof parseNumber>)])
    .sort();
  assert.deepEqual(strike, [["at", "0"], ["below", "1"]]);
});

// A LIMIT ROW'S ALPHA IS A LIMIT, not the value at the price.
//
// A base that jumps -- a position already held -- has a different value just below its
// strike than at it. Hand-derived: 0.1 BTC from 100,000 plus 500 contracts paying below
// 85,000, so at 85,000 exactly the held position has expired and the base is
// 0.1*(85,000-100,000) = -1,500, while just below it the position still pays 500 and the
// base is -1,000. Reading the point value for the `below` row would make the constraint say
// the protection is gone where it is still paying.
test("a limit row's alpha is the limit, not the point value", () => {
  const base = sum([
    linear(parseNumber("0.1"), parseNumber("100000")),
    indicator(parseNumber("500"), NEG_INF, finite(parseNumber("85000"), false)),
  ]);
  const unit = indicator(parseNumber("1"), NEG_INF, finite(parseNumber("90000"), false));
  const derived = rows(base, [unit], parseNumber("60000"), parseNumber("110000"));
  const shown = derived
    .filter((row) => format(row.price) === "85000")
    .map((row) => [row.side, format(row.alpha)])
    .sort();
  assert.deepEqual(shown, [["at", "-1500"], ["below", "-1000"]]);
});

// And a UNIT's coefficient is a limit too, at its own strike: below 90,000 one contract pays
// 1, at 90,000 it pays nothing. This is the row that decides whether protection counts.
test("a limit row's coefficient is the limit, not the point value", () => {
  const base = linear(parseNumber("0.1"), parseNumber("100000"));
  const unit = indicator(parseNumber("1"), NEG_INF, finite(parseNumber("90000"), false));
  const derived = rows(base, [unit], parseNumber("60000"), parseNumber("110000"));
  const shown = derived
    .filter((row) => format(row.price) === "90000")
    .map((row) => [row.side, format(row.coefficients[0] as ReturnType<typeof parseNumber>)])
    .sort();
  assert.deepEqual(shown, [["at", "0"], ["below", "1"]]);
});

// A base kind the good fixtures do not reach on its own: cash already paid shifts the whole
// profile, and a checker that ignored it would size a holder as better off than they are.
test("the base reads every kind it accepts", () => {
  const withCash = sum([
    linear(parseNumber("0.1"), parseNumber("100000")),
    cash(parseNumber("-500")),
  ]);
  const unit = indicator(parseNumber("1"), NEG_INF, finite(parseNumber("90000"), false));
  const derived = rows(withCash, [unit], parseNumber("60000"), parseNumber("110000"));
  const floorRow = derived.find((row) => format(row.price) === "60000");
  // Hand-derived: 0.1 * (60,000 - 100,000) - 500 = -4,500.
  assert.equal(format(floorRow?.alpha as ReturnType<typeof parseNumber>), "-4500");
});
