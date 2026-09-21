// After a fill that is not the envelope's size, ask the question again.
//
// The output is the NEW PROPOSAL, and nothing else. Topping up is a new proposal
// through the same gate; unwinding is the consumer's policy. This module never
// places a second order and has no way to.

import { canonical, parse, type Value } from "../../checker/src/canon.ts";
import { format, parse as parseNumber, type Rational, cmp } from "../../checker/src/exact.ts";

export class RecheckError extends Error {}

export interface Fill {
  /** What actually filled, in contracts. */
  readonly size: string;
  /** The average price paid, as the venue reported it. */
  readonly avgPx: string;
}

/** What a fill means for the order that was placed. */
export type Outcome = "exact" | "partial" | "none" | "over";

export function classify(ordered: string, fill: Fill): Outcome {
  checkFill(fill);
  const want = parseNumber(ordered);
  const got = parseNumber(fill.size);
  const order = cmp(got, want);
  if (order === 0) return "exact";
  if (got.num === 0n) return "none";
  return order < 0 ? "partial" : "over";
}

/**
 * A fill the venue could actually have produced.
 *
 * Neither size nor price may be negative. A negative price enters the P&L as
 * `- size * price`, so it ADDS value: a partial fill that misses the objective by 515
 * can be made to clear it by a minus sign. A venue reporting a negative fill is a
 * venue whose account of the fill should stop the procedure, not feed it.
 */
function checkFill(fill: Fill): void {
  for (const [name, text] of [["size", fill.size], ["avgPx", fill.avgPx]] as const) {
    let value;
    try {
      value = parseNumber(normalise(text));
    } catch {
      throw new RecheckError(`the venue reported ${name} ${JSON.stringify(text)}, which is not a number`);
    }
    if (value.num < 0n) {
      throw new RecheckError(`the venue reported a negative ${name}, ${JSON.stringify(text)}`);
    }
  }
}

/**
 * The proposal to ask about what is actually held.
 *
 * Three things change and nothing else:
 *
 *   - the leg's size becomes what filled
 *   - the acquisition becomes `fixed` at the price actually paid, because a
 *     `book_walk` would RE-PRICE a purchase that has already happened
 *   - nothing else, and in particular NOT the baseline
 *
 * The baseline is inherited so the premium counts once. Re-reading it would value
 * the holding against a moment the money was not spent at, and the answer would be
 * about a different question from the one the order was placed to settle.
 */
export function proposalAfterFill(
  original: Uint8Array,
  legId: string,
  fill: Fill,
  ordered?: string,
): Uint8Array {
  checkFill(fill);
  // An Ioc cannot fill more than it asked for, so a venue saying it did is a venue
  // disagreeing with the order that was placed. That is the wrong moment to build a
  // re-check on the same account of events, so it stops here.
  if (ordered !== undefined && classify(ordered, fill) === "over") {
    throw new RecheckError(`the venue reported ${fill.size} filled against an order for ${ordered}`);
  }
  const document = parse(original);
  if (typeof document !== "object" || document === null || Array.isArray(document)) {
    throw new RecheckError("a proposal is an object");
  }
  const proposal = { ...(document as Record<string, Value>) };

  const legs = proposal["legs"];
  if (!Array.isArray(legs)) throw new RecheckError("a proposal has legs");

  // COUNTED, not flagged. With a boolean, two legs sharing an id were BOTH rewritten
  // to the filled size -- one fill of 7 contracts became a proposal claiming 7 on each
  // of two legs, on two different coins. An ambiguous lookup is refused exactly as an
  // absent one is.
  let found = 0;
  proposal["legs"] = legs.map((raw) => {
    if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return raw;
    const leg = raw as Record<string, Value>;
    if (leg["id"] !== legId) return raw;
    found += 1;
    return {
      ...leg,
      size: normalise(fill.size),
      acquisition: { kind: "fixed", price: normalise(fill.avgPx) },
    };
  });
  if (found === 0) throw new RecheckError(`the proposal has no leg ${legId}`);
  if (found > 1) throw new RecheckError(`the proposal has ${found} legs called ${legId}`);

  return canonical(proposal as Value);
}

/**
 * The canonical form of a number the venue sent, so "0.1740" becomes "0.174".
 *
 * The lenient path is ANCHORED. The old fallback applied a trailing-zero regex to any
 * string the grammar rejected, so it repaired malformed input into a number nobody
 * stated: "1.0.0" became 1, "0.174.0" became 0.174, "12.34.00" became 12.34. That is
 * a change of value, not a reading -- and truncation only ever shrinks a decimal
 * tail, so a lower price makes a position look better than it is.
 *
 * Now only a full-string decimal with trailing zeros is accepted, so the trimmed text
 * is the same number the venue wrote.
 */
function normalise(text: string): string {
  let value: Rational;
  try {
    value = parseNumber(text);
  } catch {
    // The fraction carries at least one digit, so "5." and "0." are malformed rather
    // than trailing-zero spellings. Group 2 is the fraction up to its last non-zero
    // digit, and is absent when the fraction is all zeros ("0.000" is the whole 0).
    const lenient = /^(-?(?:0|[1-9][0-9]*))\.(?:([0-9]*[1-9])0*|0+)$/.exec(text);
    if (lenient === null) {
      throw new RecheckError(`the venue sent ${JSON.stringify(text)}, which is not a number`);
    }
    const [, whole, fraction] = lenient;
    value = parseNumber(fraction === undefined ? whole as string : `${whole}.${fraction}`);
  }
  return format(value);
}
