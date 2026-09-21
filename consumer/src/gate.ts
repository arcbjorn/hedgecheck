// The approval gate: one function between a certificate bundle and an order.
//
// PLAN section 7, the T3 row: "anything but `passes` produces zero downstream calls,
// asserted". This file is where that assertion has to hold, so everything here is
// arranged so that a downstream call is hard to reach and easy to prove absent.
//
// THE GATE RUNS ITS OWN COPY OF THE CHECKER. It imports `verify` from
// `checker/src/verify.ts` and re-derives the answer from the bundle's own bytes; it
// does not ask a service whether the bundle was fine, and it does not trust the
// result's own claims about itself. A gate that took someone's word for it would be
// the gate that the certificate exists to make unnecessary.
//
// THE CLOCK IS INJECTED. `policy.now` is a value the caller supplies, never
// `Date.now()`. A gate that read the clock could not be tested at the boundary of its
// own staleness rule, and an untestable boundary is where a stale bound gets through.
//
// NO SIGNING, NO KEYS, NO NETWORK. `place` is a parameter. This module never learns
// how an order is actually sent, which is what lets its tests run offline with a
// recording fake and count the calls.

import { type Bundle, type Options, type Outcome, verify } from "../../checker/src/verify.ts";

/** The order the cost bound assumes, exactly as the result states it. */
export interface OrderEnvelope {
  readonly coin: string;
  readonly side: string;
  readonly size: string;
  readonly limit_price: string;
  readonly time_in_force: string;
  readonly max_cost: string;
  readonly input_digest: string;
}

export interface Policy {
  /** The injected instant, in milliseconds since the epoch. Never read from a clock. */
  readonly now: bigint;
  /** How old a capture may be, in milliseconds. A capture exactly this old is stale. */
  readonly maxAgeMs: bigint;
  /** Options handed to the checker: the schemas, and the reviewed digests. */
  readonly checker?: Options;
  /**
   * The checker to run. Defaults to `verify` from `checker/src/verify.ts`, which is
   * what a real caller uses; it is a field so a test can supply one that throws.
   *
   * That case is not hypothetical and not reachable any other way: `verify` catches
   * its own faults and returns `ENGINE_DISAGREES` rather than throwing, so nothing a
   * bundle contains can make it throw. What CAN throw is the wiring -- a bad import,
   * an out-of-memory, a future checker that is less careful. The gate must return
   * "nothing was checked" for those rather than "the bundle was refused", because an
   * operator reading the second would go looking for a corruption that is not there.
   */
  readonly verifier?: Verifier;
}

/** What `verify` is, stated as a type so the gate can be handed a different one. */
export type Verifier = (bundle: Bundle, options: Options) => Promise<Outcome>;

/**
 * When the capture happened, as the CALLER states it.
 *
 * It is not in the bundle. `result.capture` records a skew, not an instant, and
 * PLAN section 4 is explicit that even the skew is an assertion no checker can
 * re-derive -- the contexts response carries no venue timestamp. So the gate cannot
 * take "when was this captured" from the evidence, and pretending otherwise would put
 * a number in the age test that nothing established. The caller states it, the gate
 * tests it, and the decision says which instant it used.
 */
export interface Capture {
  readonly capturedAtMs: bigint;
}

/**
 * THE GATE'S OWN GATE.
 *
 * `brand` is typed by a symbol that is declared in this module and exported from
 * nowhere. TypeScript identifies `unique symbol` types nominally, by declaration
 * site, so no other module can write the type of this field: it cannot name the
 * symbol, and a structurally identical symbol of its own is a different type. There
 * is therefore no object literal, no cast from a plain shape, and no helper anywhere
 * else in the program that produces an `Approved` -- only the one construction inside
 * `gate`, which sits after every condition has been checked.
 *
 * A caller that wants to place an order must hold one of these, and the only way to
 * hold one is to have called `gate` and had it say yes.
 */
const checked: unique symbol = Symbol("hedgecheck.checked");

export interface Approved {
  readonly approved: true;
  readonly brand: typeof checked;
  readonly envelope: OrderEnvelope;
  readonly placed: unknown;
}

export interface Refused {
  readonly approved: false;
  readonly reason: Reason;
  readonly detail: string;
}

export type Decision = Approved | Refused;

/** Why a gate said no. Closed, so a caller can branch without reading prose. */
export type Reason =
  | "CHECKER_REFUSED"
  | "CHECKER_THREW"
  | "NOT_PASSES"
  | "NO_ENVELOPE"
  | "DIGEST_MISMATCH"
  | "CAPTURE_STALE"
  | "UNREADABLE";

/** What actually sends the order. A parameter, so this module never sends anything. */
export type Place = (envelope: OrderEnvelope) => Promise<unknown>;

function no(reason: Reason, detail: string): Refused {
  return { approved: false, reason, detail };
}

/**
 * Run the checker over the bundle and place the order it authorises, or say why not.
 *
 * `place` is called at most once, and only when ALL of these hold:
 *
 *   1. the checker accepts the bundle,
 *   2. the verdict is `passes`,
 *   3. an order envelope is present,
 *   4. the envelope's `input_digest` is the result's own `input_digest`,
 *   5. the capture is strictly younger than `policy.maxAgeMs` against `policy.now`.
 *
 * In every other case the gate returns before reaching `place` and makes zero
 * downstream calls. There is exactly one call site for `place` in this file, and
 * every early return is above it, which is what makes "zero calls" a property of the
 * shape of this function rather than of a flag someone might forget to set.
 *
 * Conditions 2, 3 and 4 are also checked by the checker in condition 1, which does not
 * make them redundant here: PLAN section 7 records that removing one overlapping guard
 * changed nothing because another caught it, and only removing both let a corruption
 * through. The gate is the last thing before an order, so it re-states what it needs
 * rather than inheriting it.
 */
export async function gate(
  bundle: Bundle,
  policy: Policy,
  capture: Capture,
  place: Place,
): Promise<Decision> {
  // 1. The checker, run here, over these bytes.
  //
  // A checker that throws is not a checker that accepted. The catch is why the table
  // can drive a throwing checker through the gate at all, and the reason is its own,
  // so "it crashed" never arrives looking like "it said no".
  let accepted: boolean;
  let refusal = "";
  try {
    const outcome = await (policy.verifier ?? verify)(bundle, policy.checker ?? {});
    accepted = outcome.accepted;
    if (!outcome.accepted) {
      refusal = `${outcome.refusal.class} at ${outcome.refusal.at}: ${outcome.refusal.detail}`;
    }
  } catch (error) {
    return no("CHECKER_THREW", error instanceof Error ? error.message : String(error));
  }
  if (!accepted) return no("CHECKER_REFUSED", refusal);

  // 2-4. The result, read only after the checker has established it.
  let result: Record<string, unknown>;
  try {
    result = JSON.parse(new TextDecoder().decode(bundle.result)) as Record<string, unknown>;
  } catch (error) {
    return no("UNREADABLE", error instanceof Error ? error.message : String(error));
  }
  if (typeof result !== "object" || result === null || Array.isArray(result)) {
    return no("UNREADABLE", "the result is not an object");
  }

  if (result["model_result"] !== "passes") {
    return no("NOT_PASSES", `the verdict is ${String(result["model_result"])}`);
  }

  const raw = result["order_envelope"];
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return no("NO_ENVELOPE", "the result issued no order envelope");
  }
  const envelope = raw as unknown as OrderEnvelope;
  for (const field of ["coin", "side", "size", "limit_price", "time_in_force", "max_cost", "input_digest"] as const) {
    if (typeof envelope[field] !== "string") {
      return no("NO_ENVELOPE", `the envelope has no ${field}`);
    }
  }

  const stated = result["input_digest"];
  if (typeof stated !== "string" || stated === "") {
    return no("DIGEST_MISMATCH", "the result does not name its input digest");
  }
  if (envelope.input_digest !== stated) {
    return no(
      "DIGEST_MISMATCH",
      `the envelope belongs to ${envelope.input_digest.slice(0, 12)}, the result is ${stated.slice(0, 12)}`,
    );
  }

  // 5. Age, against the INJECTED instant. Exactly maxAgeMs old is stale: a bound that
  // has just reached its limit has reached it, and the comparison is `>=` so the
  // boundary is decided here rather than by whoever writes the next policy.
  const age = policy.now - capture.capturedAtMs;
  if (age >= policy.maxAgeMs) {
    return no("CAPTURE_STALE", `the capture is ${age}ms old, the policy allows under ${policy.maxAgeMs}ms`);
  }
  if (age < 0n) {
    return no("CAPTURE_STALE", `the capture is ${-age}ms in the future`);
  }

  // The one call site. Everything above returns before reaching it.
  const placed = await place(envelope);
  return { approved: true, brand: checked, envelope, placed };
}
