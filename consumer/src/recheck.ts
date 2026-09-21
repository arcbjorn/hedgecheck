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
  const want = parseNumber(ordered);
  const got = parseNumber(fill.size);
  const order = cmp(got, want);
  if (order === 0) return "exact";
  if (got.num === 0n) return "none";
  return order < 0 ? "partial" : "over";
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
export function proposalAfterFill(original: Uint8Array, legId: string, fill: Fill): Uint8Array {
  const document = parse(original);
  if (typeof document !== "object" || document === null || Array.isArray(document)) {
    throw new RecheckError("a proposal is an object");
  }
  const proposal = { ...(document as Record<string, Value>) };

  const legs = proposal["legs"];
  if (!Array.isArray(legs)) throw new RecheckError("a proposal has legs");

  let found = false;
  proposal["legs"] = legs.map((raw) => {
    if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return raw;
    const leg = raw as Record<string, Value>;
    if (leg["id"] !== legId) return raw;
    found = true;
    return {
      ...leg,
      size: normalise(fill.size),
      acquisition: { kind: "fixed", price: normalise(fill.avgPx) },
    };
  });
  if (!found) throw new RecheckError(`the proposal has no leg ${legId}`);

  return canonical(proposal as Value);
}

/** The canonical form of a number the venue sent, so "0.1740" becomes "0.174". */
function normalise(text: string): string {
  let value: Rational;
  try {
    value = parseNumber(text);
  } catch {
    // The venue's own text, outside the grammar. Trailing zeros are the usual
    // reason ("1200.0"), and trimming them is a reading, not a change of value.
    const trimmed = text.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
    value = parseNumber(trimmed);
  }
  return format(value);
}
