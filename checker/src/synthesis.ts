// The synthesis checker: accept a synthesis answer, or refuse it with a class from the
// closed list in schema/refusal.schema.json.
//
// IT REBUILDS THE PROGRAM. The rows come from this checker's own kernel, from the base and
// candidates the document carries, and never from anything the solver wrote down. A checker
// that re-added the solver's numbers would be confirming arithmetic rather than verifying a
// claim, so nothing here reads `sizes` or `certificate` to decide what the constraints are.
//
// IT NEVER SOLVES. A feasible answer is checked by one evaluation of the rows at the
// reported sizes; an infeasible one by one multiplication of the certificate. That is the
// whole point of a certificate: if checking needed the search replayed, the search would be
// the verification and the certificate would be decoration.
//
// The rows are derived from MAXIMAL PIECES, which is a different route from the oracle's
// atom walk. Both must reach the same constraints for the same input, and that agreement is
// evidence precisely because the derivations differ.

import {
  add,
  ceilLot,
  cmp,
  equals,
  format,
  lt,
  lte,
  mul,
  neg,
  parse as parseNumber,
  type Rational,
  sign,
  sub,
  ZERO,
} from "./exact.ts";
import {
  cash,
  finite,
  type Fn,
  indicator,
  linear,
  NEG_INF,
  POS_INF,
  profile,
  sum,
} from "./pwa.ts";
import { listAt, objectAt, optional, stringAt } from "./doc.ts";
import type { Value } from "./canon.ts";

/**
 * A class from the closed list in schema/refusal.schema.json. Declared here rather than
 * imported from verify.ts: that module checks a certificate BUNDLE, this one checks a
 * synthesis answer, and importing its types would make the two depend on each other for
 * nothing. The list is the same closed list, and `refusal.schema.json` is what holds them
 * to it -- oracle/verify.py checks that every class this file names is in that schema.
 */
export type SynthesisRefusalClass =
  | "OBJECTIVE_MISMATCH"
  | "VERDICT_MISMATCH"
  | "SIZE_WINDOW"
  | "COST_MISMATCH"
  | "CERTIFICATE_WEIGHTS";

export interface SynthesisRefusal {
  readonly class: SynthesisRefusalClass;
  readonly at: string;
  readonly detail: string;
}

/** One constraint: `alpha + sum(coefficients[i] * n[i]) >= floor`, at a named site. */
export interface Row {
  readonly price: Rational;
  readonly side: "at" | "above" | "below";
  readonly alpha: Rational;
  readonly coefficients: readonly Rational[];
}

export type SynthesisOutcome =
  | { readonly accepted: true }
  | { readonly accepted: false; readonly refusal: SynthesisRefusal };

function refuse(cls: SynthesisRefusalClass, at: string, detail: string): SynthesisOutcome {
  return { accepted: false, refusal: { class: cls, at, detail } };
}

function paysOnBounds(on: { [key: string]: Value }): [ReturnType<typeof finite> | typeof NEG_INF, ReturnType<typeof finite> | typeof POS_INF] {
  const lo = on["lower"] === undefined
    ? NEG_INF
    : finite(parseNumber(String(on["lower"])), on["lower_inclusive"] === true);
  const hi = on["upper"] === undefined
    ? POS_INF
    : finite(parseNumber(String(on["upper"])), on["upper_inclusive"] === true);
  return [lo, hi];
}

/** One term of the holder's existing position, as this checker reads it. */
function basePart(part: { [key: string]: Value }): Fn {
  const kind = String(part["kind"]);
  if (kind === "linear") {
    return linear(parseNumber(String(part["quantity"])), parseNumber(String(part["baseline"])));
  }
  if (kind === "indicator") {
    const [lo, hi] = paysOnBounds(objectAt(part as Value, ["pays_on"]));
    return indicator(parseNumber(String(part["size"])), lo, hi);
  }
  if (kind === "cash") {
    return cash(parseNumber(String(part["amount"])));
  }
  throw new Error(`unsupported base part: ${kind}`);
}

/**
 * The objective as finitely many exact rows, derived from MAXIMAL PIECES.
 *
 * For fixed sizes the P&L is affine on every piece, so the objective holds on a piece
 * exactly when it holds at the piece's ends -- and a piece end is a constraint whether the
 * end is owned or approached, because `>=` is closed: if the limit meets the floor then so
 * does every interior price, and if it does not, prices arbitrarily close to it violate the
 * objective.
 *
 * An OWNED end is an `at` site: the value is attained there. An UNOWNED end is `above` (a
 * limit from the right of the piece's low end) or `below` (from the left of its high end).
 * A jump makes the three different numbers, which is why the side is part of the site.
 *
 * The breakpoint set does not depend on the sizes -- it is the strikes, which come from the
 * instruments' own terms -- so one walk with unit sizes gives the rows for the whole family.
 * That is what makes "cheapest sizes meeting the objective" a program with fixed rows.
 */
export function rows(
  base: Fn,
  units: readonly Fn[],
  lower: Rational,
  upper: Rational,
): Row[] {
  const combined = sum([base, ...units]);
  // THE NAME IS CANONICAL, not whichever the walk reached first. `at` is preferred: a
  // constraint the function ATTAINS at a price is primarily a fact about that price, while
  // `above` and `below` are limits that only need naming where they differ from the value.
  // Without the rule the surviving name depends on the walk -- the domain's top comes out
  // `at` from a maximal-piece walk and `below` from an atom walk -- and the certificate
  // names its sites, so the two implementations could not resolve each other's.
  const SIDE_ORDER: Record<string, number> = { at: 0, below: 1, above: 2 };
  const best = new Map<string, Row>();
  const push = (price: Rational, side: "at" | "above" | "below") => {
    // THE VALUE ON THE RIGHT SIDE OF THE JUMP. An `at` site is the value attained at the
    // price; `above` and `below` are the LIMITS from the right and the left, which differ
    // wherever the function jumps -- and a digital jumps at its strike, which is the one
    // place that matters most. Reading the point value for a `below` site made the strike's
    // constraint say the digital pays nothing just below it, when it pays in full.
    const alpha = valueOf(base, price, side);
    const coefficients = units.map((unit) => valueOf(unit, price, side));
    // DISTINCT CONSTRAINTS ONLY. A price where the function is continuous yields the same
    // inequality from two adjacent pieces; the same inequality written twice says nothing
    // more than once, and a duplicate site name would make a certificate weight ambiguous.
    // The key is the WHOLE constraint, so two rows at one price with different coefficients
    // both survive -- which is the case at a strike, where the digital pays on one side.
    const key = [format(alpha), ...coefficients.map(format)].join("|");
    const held = best.get(key);
    if (held !== undefined && (SIDE_ORDER[held.side] as number) <= (SIDE_ORDER[side] as number)) {
      return;
    }
    best.set(key, { price, side, alpha, coefficients });
  };
  for (const piece of profile(combined, lower, upper)) {
    push(piece.lower, piece.lowerInclusive ? "at" : "above");
    if (!equals(piece.lower, piece.upper)) {
      push(piece.upper, piece.upperInclusive ? "at" : "below");
    }
  }
  // In price order, then by side, so the row list is deterministic.
  return [...best.values()].sort((a, b) => {
    const byPrice = cmp(a.price, b.price);
    if (byPrice !== 0) return byPrice;
    return (SIDE_ORDER[a.side] as number) - (SIDE_ORDER[b.side] as number);
  });
}

/**
 * What one unit of `f` is worth at `price`, from a given side.
 *
 * `at` is the value the function attains there: the piece that OWNS the price.
 * `above` is the limit from the right and `below` from the left, taken by evaluating the
 * affine rule of the piece on that side at the endpoint -- which is not the same number
 * wherever `f` jumps. A digital jumps at its strike, so this is the difference between
 * "the protection pays" and "the protection has expired worthless".
 */
function valueOf(f: Fn, price: Rational, side: "at" | "above" | "below"): Rational {
  for (const piece of f.pieces) {
    const loBelow = piece.lo.value === null || lt(piece.lo.value, price);
    const hiAbove = piece.hi.value === null || lt(price, piece.hi.value);
    const owns = (loBelow || (equals(piece.lo.value as Rational, price) && piece.lo.closed)) &&
      (hiAbove || (equals(piece.hi.value as Rational, price) && piece.hi.closed));
    // `below` wants the piece whose interior lies to the LEFT of the price, so the price is
    // its high end; `above` wants the one whose interior lies to the right.
    const leftOf = loBelow && (piece.hi.value !== null && equals(piece.hi.value, price));
    const rightOf = hiAbove && (piece.lo.value !== null && equals(piece.lo.value, price));
    const wanted = side === "at" ? owns : side === "below" ? leftOf : rightOf;
    if (wanted) return add(mul(piece.slope, price), piece.intercept);
  }
  // A side that has no piece falls back to the owning one: at the domain's own ends there is
  // nothing beyond, and the limit from inside is the value there.
  for (const piece of f.pieces) {
    const afterLo = piece.lo.value === null || lt(piece.lo.value, price) ||
      (equals(piece.lo.value, price) && piece.lo.closed);
    const beforeHi = piece.hi.value === null || lt(price, piece.hi.value) ||
      (equals(piece.hi.value, price) && piece.hi.closed);
    if (afterLo && beforeHi) return add(mul(piece.slope, price), piece.intercept);
  }
  throw new Error(`no piece covers ${format(price)}`);
}

/**
 * Check one synthesis answer.
 *
 * The document has already been validated against schema/synthesis.schema.json by the
 * caller; this establishes what the schema cannot, which is whether the answer is TRUE.
 */
export function verifySynthesis(document: Value): SynthesisOutcome {
  const request = objectAt(document, ["request"]);
  const objective = objectAt(document, ["request", "objective"]);
  const floor = parseNumber(String(objective["min_pnl"]));
  const domain = objectAt(document, ["request", "domain"]);
  const lower = parseNumber(String(domain["lower"]));
  const upper = parseNumber(String(domain["upper"]));
  if (!lt(lower, upper)) {
    return refuse("OBJECTIVE_MISMATCH", "$.request.domain", "the domain is empty");
  }

  const baseParts = listAt(document, ["request", "base"]);
  const base = baseParts.length === 0
    ? cash(ZERO)
    : sum(baseParts.map((part) => basePart(part as { [key: string]: Value })));

  const candidates = listAt(document, ["request", "candidates"]);
  const units: Fn[] = [];
  const prices: Rational[] = [];
  const ids: string[] = [];
  for (const raw of candidates) {
    const candidate = raw as { [key: string]: Value };
    const [lo, hi] = paysOnBounds(objectAt(raw, ["pays_on"]));
    units.push(indicator(parseNumber("1"), lo, hi));
    prices.push(parseNumber(String(candidate["price"])));
    ids.push(String(candidate["id"]));
  }

  // THE PREMIUM IS PART OF THE CONSTRAINT. Buying n contracts costs n*price whatever the
  // price does, so what one contract is worth at a site is its payoff NET of its price.
  // Leaving it out lets the program buy protection for free.
  const derived = rows(base, units, lower, upper).map((row) => ({
    ...row,
    coefficients: row.coefficients.map((value, index) => sub(value, prices[index] as Rational)),
  }));

  const status = stringAt(document, ["status"]);
  if (status === "feasible") {
    return checkFeasible(document, derived, ids, prices, floor);
  }
  if (status === "infeasible") {
    return checkCertificate(document, derived, floor);
  }
  // `rounding_failed` claims nothing about existence, so there is nothing to establish
  // beyond what the schema already did: the relaxed point is carried and no sizes are.
  if (optional(document, ["sizes"]) !== undefined) {
    return refuse("VERDICT_MISMATCH", "$.sizes",
      "a refused rounding reports sizes, which it did not establish");
  }
  return { accepted: true };
}

function checkFeasible(
  document: Value,
  derived: readonly Row[],
  ids: readonly string[],
  prices: readonly Rational[],
  floor: Rational,
): SynthesisOutcome {
  const reported = listAt(document, ["sizes"]);
  if (reported.length !== ids.length) {
    return refuse("SIZE_WINDOW", "$.sizes",
      `${reported.length} sizes for ${ids.length} candidates`);
  }
  const sizes: Rational[] = [];
  for (let index = 0; index < reported.length; index += 1) {
    const entry = reported[index] as { [key: string]: Value };
    // ORDER IS PART OF THE CLAIM, because the coefficients are positional. A size naming a
    // different candidate than the row it is checked against would be checked against the
    // wrong payoff.
    if (String(entry["candidate"]) !== ids[index]) {
      return refuse("SIZE_WINDOW", `$.sizes[${index}].candidate`,
        `names ${String(entry["candidate"])}, the request's candidate ${index} is ${ids[index]}`);
    }
    const size = parseNumber(String(entry["size"]));
    if (sign(size) < 0) {
      return refuse("SIZE_WINDOW", `$.sizes[${index}].size`, "a negative size");
    }
    sizes.push(size);
  }

  // THE RE-CHECK, done here rather than trusted: every row, at the reported sizes.
  for (const row of derived) {
    let value = row.alpha;
    for (let index = 0; index < sizes.length; index += 1) {
      value = add(value, mul(row.coefficients[index] as Rational, sizes[index] as Rational));
    }
    if (lt(value, floor)) {
      return refuse("SIZE_WINDOW", `$.sizes`,
        `at ${format(row.price)} (${row.side}) the structure is worth ${format(value)}, ` +
          `which misses the floor of ${format(floor)}`);
    }
  }

  // The cost is what the reported sizes cost at the request's own prices.
  const stated = optional(document, ["cost"]);
  if (stated === undefined) {
    return refuse("COST_MISMATCH", "$.cost", "a feasible answer does not say what it costs");
  }
  let cost = ZERO;
  for (let index = 0; index < sizes.length; index += 1) {
    cost = add(cost, mul(prices[index] as Rational, sizes[index] as Rational));
  }
  if (!equals(parseNumber(String(stated)), cost)) {
    return refuse("COST_MISMATCH", "$.cost",
      `states ${String(stated)}, the sizes at the request's prices cost ${format(cost)}`);
  }

  // A SIZE MUST BE A WHOLE LOT. The program solves over the rationals and the answer is
  // rounded; a reported size that is not a multiple of the lot was never a tradeable
  // structure, whatever it is worth.
  const lotText = optional(document, ["request", "lot"]);
  const lot = lotText === undefined ? parseNumber("1") : parseNumber(String(lotText));
  if (sign(lot) > 0) {
    for (let index = 0; index < sizes.length; index += 1) {
      const size = sizes[index] as Rational;
      if (!equals(ceilLot(size, lot), size)) {
        return refuse("SIZE_WINDOW", `$.sizes[${index}].size`,
          `${format(size)} is not a whole multiple of the lot ${format(lot)}`);
      }
    }
  }
  return { accepted: true };
}

function checkCertificate(
  document: Value,
  derived: readonly Row[],
  floor: Rational,
): SynthesisOutcome {
  const weights = listAt(document, ["certificate", "weights"]);
  // The rows this checker derived, by site. A weight naming a site that is not among them
  // is a certificate about a different program.
  const index = new Map<string, Row>();
  for (const row of derived) index.set(`${format(row.price)}|${row.side}`, row);

  const y = new Map<string, Rational>();
  for (let position = 0; position < weights.length; position += 1) {
    const entry = weights[position] as { [key: string]: Value };
    const key = `${format(parseNumber(String(entry["price"])))}|${String(entry["side"])}`;
    const row = index.get(key);
    if (row === undefined) {
      return refuse("CERTIFICATE_WEIGHTS", `$.certificate.weights[${position}]`,
        `names the site ${key.replace("|", " ")}, which is not a row of this program`);
    }
    if (y.has(key)) {
      return refuse("CERTIFICATE_WEIGHTS", `$.certificate.weights[${position}]`,
        `names the site ${key.replace("|", " ")} twice`);
    }
    const weight = parseNumber(String(entry["weight"]));
    // NON-NEGATIVE, and a zero weight says nothing, so it has no business being carried.
    if (sign(weight) <= 0) {
      return refuse("CERTIFICATE_WEIGHTS", `$.certificate.weights[${position}].weight`,
        `${format(weight)} is not strictly positive`);
    }
    y.set(key, weight);
  }

  // FARKAS, by one multiplication. With rows `alpha_j + a_j . n >= floor`, written as
  // `a_j . n >= floor - alpha_j`, a non-negative y with `A^T y <= 0` and `b . y > 0` says
  // no non-negative n satisfies them: the weighted sum demands something strictly positive
  // from a combination that can deliver at most zero.
  const columns = (derived[0]?.coefficients.length ?? 0);
  for (let column = 0; column < columns; column += 1) {
    let total = ZERO;
    for (const row of derived) {
      const weight = y.get(`${format(row.price)}|${row.side}`);
      if (weight === undefined) continue;
      total = add(total, mul(weight, row.coefficients[column] as Rational));
    }
    if (sign(total) > 0) {
      return refuse("CERTIFICATE_WEIGHTS", "$.certificate.weights",
        `column ${column} of A^T y is ${format(total)}, which is positive, so the weights ` +
          `do not cancel the sizes`);
    }
  }
  let right = ZERO;
  for (const row of derived) {
    const weight = y.get(`${format(row.price)}|${row.side}`);
    if (weight === undefined) continue;
    right = add(right, mul(weight, sub(floor, row.alpha)));
  }
  if (sign(right) <= 0) {
    return refuse("CERTIFICATE_WEIGHTS", "$.certificate.weights",
      `b . y is ${format(right)}, which is not positive, so the rows are not contradictory`);
  }
  return { accepted: true };
}
