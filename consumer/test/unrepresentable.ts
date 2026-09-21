// THE GATE'S OWN GATE, shown as code that does not compile.
//
// THIS FILE IS NOT MEANT TO TYPE-CHECK. It is the evidence for the claim that an
// `Approved` decision cannot be made without running the check, and the evidence is
// the compiler's refusal. `consumer/test/typegate.test.ts` runs `deno check` over it
// and FAILS IF IT SUCCEEDS, so the claim stops being true the moment the brand is
// weakened, and nobody has to remember to re-check by hand.
//
// It is `.ts` and not `.test.ts` so the node test runner does not execute it.
//
// The mechanism: `Approved.brand` is typed `typeof checked`, where `checked` is a
// `unique symbol` declared in `gate.ts` and exported from nowhere. TypeScript gives
// `unique symbol` a nominal identity tied to its declaration site, so:
//
//   - no other module can WRITE the type, because it cannot name `checked`;
//   - a symbol another module makes for itself has a different type, so it cannot
//     supply the field;
//   - `Approved` is an interface, not a class, so there is no constructor to call and
//     no subclass to make. The single construction site in `gate` is the only
//     expression in the program that can produce one, and it sits after every
//     condition has been checked.
//
// A cast (`as Approved`) still defeats it, as a cast defeats every type in
// TypeScript. That is why the runtime assertion is a call count in a table and not a
// type: the brand makes the wrong thing hard to write by accident, the table makes it
// impossible to do by mistake.

import type { Approved, Decision, OrderEnvelope } from "../src/gate.ts";

const envelope: OrderEnvelope = {
  coin: "#39710",
  side: "buy",
  size: "924",
  limit_price: "0.17399",
  time_in_force: "Ioc",
  max_cost: "160.76676",
  input_digest: "d".repeat(64),
};

// 1. An approval written as an object literal.
//
// error TS2741: Property 'brand' is missing in type
// '{ approved: true; envelope: OrderEnvelope; placed: null; }' but required in type
// 'Approved'.
export const forged: Approved = {
  approved: true,
  envelope,
  placed: null,
};

// 2. An approval with a brand of its own making.
//
// error TS2322: Type 'typeof mine' is not assignable to type 'unique symbol'. A
// unique symbol is identified by where it was declared, and this was declared here.
const mine: unique symbol = Symbol("hedgecheck.checked");
export const alsoForged: Approved = {
  approved: true,
  brand: mine,
  envelope,
  placed: null,
};

// 3. An approval smuggled in as a Decision, which is what a caller actually holds.
//
// error TS2322: the union narrows on `approved`, so the true branch is `Approved` and
// the missing brand is missing here too. Widening the field to `Decision` does not
// help: the shape still has to be one of the two variants.
export const smuggled: Decision = {
  approved: true,
  envelope,
  placed: null,
};

// 4. A caller that acts on "approved" without having checked.
//
// This is the one that matters, because it is the mistake someone would actually
// make: reading a flag off a value they were handed. The flag alone is not a type,
// so the narrowing gives them `Approved`, and they cannot build one.
export function actOnAFlag(decision: { approved: boolean }): Approved {
  if (decision.approved) {
    // error TS2739: Type '{ approved: boolean; }' is missing the following properties
    // from type 'Approved': brand, envelope, placed -- and 'approved: boolean' is not
    // assignable to 'approved: true' either.
    return decision;
  }
  throw new Error("not approved");
}
