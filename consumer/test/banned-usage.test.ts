// The key never reaches an error, tested by RUNNING the path rather than reading it.
//
// The source scan in `place.test.ts` looks for patterns like `readFileSync(...key)`.
// It could not have caught the real leak found in the audit, where a third-party
// curve library interpolated an out-of-range key into its own thrown message and the
// runbook's `2>&1` carried it into a retained log. A property about what happens at
// runtime has to be asserted at runtime.

import assert from "node:assert/strict";
import { test } from "node:test";

import { agentKey, KEY_VARIABLE, place, PlaceError, sign } from "../src/place.ts";
import type { OrderEnvelope } from "../src/gate.ts";

const ENVELOPE: OrderEnvelope = {
  coin: "#39710",
  side: "buy",
  size: "924",
  limit_price: "0.17399",
  time_in_force: "Ioc",
  max_cost: "160.76676",
  input_digest: "a".repeat(64),
};

/** The secp256k1 group order, written out so the test does not ask the code for it. */
const N = "fffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141";

/**
 * Key-shaped values that are hex-valid but NOT valid keys.
 *
 * Each is 64 hex characters, so `agentKey`'s shape test passes and the range test is
 * the only thing between them and the curve library. None was ever a key.
 */
const OUT_OF_RANGE: [string, string][] = [
  ["zero", "0".repeat(64)],
  ["exactly the order", N],
  ["above the order", "f".repeat(64)],
  ["all ones", "f".repeat(63) + "e"],
];

// The audit's finding, as a test. Distinctive values, so a leak cannot hide behind a
// coincidence: every character of the value is checked for in every form it could
// plausibly take.
test("an out-of-range key never appears in any error, in any encoding", async () => {
  for (const [label, key] of OUT_OF_RANGE) {
    let caught: unknown;
    try {
      await place(ENVELOPE, {
        network: "testnet",
        env: { [KEY_VARIABLE]: key },
        nonceMs: 1n,
        send: async () => {
          assert.fail(`${label}: an order was SENT for an invalid key`);
        },
      });
      assert.fail(`${label} was accepted as a key`);
    } catch (error) {
      if (error instanceof assert.AssertionError) throw error;
      caught = error;
    }

    const error = caught as Error;
    const text = `${error.message}\n${error.stack ?? ""}`;
    assert.ok(error instanceof PlaceError, `${label}: a library error escaped: ${error.message}`);

    // Not `includes(key)` alone -- that is blind to every re-encoding. The decimal
    // form is the one the curve library actually printed.
    const decimal = BigInt(`0x${key}`).toString(10);
    assert.ok(!text.includes(key), `${label}: the hex key is in the error`);
    assert.ok(!text.toLowerCase().includes(key.toLowerCase()), `${label}: the key is in the error`);
    if (decimal.length > 8) {
      assert.ok(!text.includes(decimal), `${label}: the decimal key is in the error`);
    }
    assert.ok(!text.includes(btoa(key)), `${label}: a base64 of the key is in the error`);
  }
});

// THE RANGE IS CHECKED, NOT JUST THE SHAPE.
//
// `^[0-9a-fA-F]{64}$` is a shape test; secp256k1 needs 1 <= k < n. Without the range
// check these reach the curve library, which is where the leak came from -- so the
// check is asserted directly rather than only through its consequence.
test("a hex-valid key outside the curve range is refused by agentKey", () => {
  for (const [label, key] of OUT_OF_RANGE) {
    assert.throws(
      () => agentKey({ [KEY_VARIABLE]: key }),
      PlaceError,
      `${label} was accepted as a key`,
    );
  }
  // And one inside the range is still accepted, so the check is not simply refusing
  // everything.
  assert.equal(agentKey({ [KEY_VARIABLE]: `0x${"11".repeat(32)}` }).length, 32);
});

// A leak of a PREFIX is still a leak. The old assertion used fixtures shorter than
// the slice it checked for, so it only appeared to cover this.
test("no prefix of a malformed key reaches an error", () => {
  // 64 distinct-looking hex characters, never a key, with no repeating run that
  // could match by accident.
  const distinctive = "0123456789abcdef".repeat(4);
  for (const bad of [distinctive, `0x${distinctive}`, distinctive.slice(0, 62), `${distinctive}ff`]) {
    try {
      agentKey({ [KEY_VARIABLE]: bad });
      // A well-formed in-range value is allowed to succeed; it must not have leaked.
    } catch (error) {
      const text = `${(error as Error).message}\n${(error as Error).stack ?? ""}`;
      for (let length = 8; length <= bad.length; length += 8) {
        const prefix = bad.slice(0, length);
        assert.ok(!text.includes(prefix), `a ${length}-character prefix reached the error`);
      }
    }
  }
});

// The wrapper around the curve library, directly: whatever it throws, the value does
// not come out with it.
test("a curve library failure is replaced, never wrapped", () => {
  const key = new Uint8Array(32); // zero: the curve rejects it
  try {
    sign(new Uint8Array(32), key);
    assert.fail("signing with a zero key succeeded");
  } catch (error) {
    assert.ok(error instanceof PlaceError, "the library's own error escaped");
    const text = `${(error as Error).message}\n${(error as Error).stack ?? ""}`;
    // The library's message names the curve order; ours must not carry it through.
    assert.ok(!text.includes("1 <= n <"), "the library's message was re-thrown");
    assert.equal((error as Error).message, "signing failed; the key was rejected by the curve");
  }
});
