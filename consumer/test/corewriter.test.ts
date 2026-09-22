// The CoreWriter encoding, against the venue's own worked example and the retained envelope.
//
// The layout is checked BYTE FOR BYTE rather than round-tripped through the same encoder: a
// test that re-encodes with the code under test confirms the code agrees with itself. The
// reference is the retained page's own `CoreWriterCaller` example, which spells the header out
// digit by digit for action 7 -- so the header this project writes for action 1 is checked
// against a layout somebody else documented.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ACTION_LIMIT_ORDER,
  boundedCost,
  CORE_WRITER,
  encodeLimitOrder,
  EncodeError,
  ENCODING_VERSION,
  orderFromEnvelope,
  scaled,
  TIF,
} from "../src/corewriter.ts";
import { assetId } from "../src/place.ts";

function hex(bytes: Uint8Array): string {
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

// The retained page: "the system contract is available at 0x3333...", "only version 1 is
// supported", tif "3 for Ioc". Pinned as constants because a change in any of them is a change
// in what this project would send, not a refactor.
test("the venue's own constants are what the retained page states", () => {
  assert.equal(CORE_WRITER, "0x3333333333333333333333333333333333333333");
  assert.equal(ENCODING_VERSION, 1);
  assert.equal(ACTION_LIMIT_ORDER, 1);
  assert.deepEqual({ ...TIF }, { Alo: 1, Gtc: 2, Ioc: 3 });
});

// THE HEADER LAYOUT, from the retained worked example. It builds a four-byte header for
// action 7 as data[0]=0x01, data[1]=0x00, data[2]=0x00, data[3]=0x07 -- version, then the
// action id as three big-endian bytes. Action 1 is therefore 01 00 00 01.
test("the header is the version and three big-endian action bytes", () => {
  const bytes = encodeLimitOrder({
    asset: 0,
    isBuy: false,
    limitPx: 0n,
    sz: 0n,
    reduceOnly: false,
    encodedTif: TIF.Ioc,
    cloid: 0n,
  });
  assert.equal(hex(bytes.slice(0, 4)), "01000001");
  // Seven static fields, one 32-byte word each, no head/tail split.
  assert.equal(bytes.length, 4 + 32 * 7);
});

// EVERY FIELD IN ITS OWN WORD, right-aligned big-endian, which is what ABI encoding does for
// a static type. The hex is COMPUTED in the assertion rather than written out: my first pass
// at 100,204,971, 17,399,000 and 92,400,000,000 by hand was wrong in all three, and a test
// whose expected value is a hand transcription tests the transcription.
test("each field is a right-aligned big-endian word", () => {
  const bytes = encodeLimitOrder({
    asset: 100_204_971,
    isBuy: true,
    limitPx: 17_399_000n,
    sz: 92_400_000_000n,
    reduceOnly: false,
    encodedTif: TIF.Ioc,
    cloid: 0n,
  });
  const word = (index: number) => hex(bytes.slice(4 + 32 * index, 4 + 32 * (index + 1)));
  assert.equal(word(0), (100_204_971).toString(16).padStart(64, "0"), "asset");
  assert.equal(word(1), "0".repeat(63) + "1", "isBuy true is one");
  assert.equal(word(2), (17_399_000).toString(16).padStart(64, "0"), "limitPx");
  assert.equal(word(3), (92_400_000_000).toString(16).padStart(64, "0"), "sz");
  assert.equal(word(4), "0".repeat(64), "reduceOnly false is zero");
  assert.equal(word(5), "0".repeat(63) + "3", "Ioc");
  assert.equal(word(6), "0".repeat(64), "no cloid");
});

// 10^8 FIXED POINT, EXACT OR REFUSED.
//
// The encoding is lossy for anything with more than eight decimals, so a value it cannot carry
// is refused rather than rounded: rounding would send an order about a number nobody
// established. Hand-derived: 0.17399 is 17,399,000 at 10^8, and 924 is 92,400,000,000.
test("a decimal scales exactly, and is refused when it cannot", () => {
  assert.equal(scaled("0.17399", "limit_price"), 17_399_000n);
  assert.equal(scaled("924", "size"), 92_400_000_000n);
  assert.equal(scaled("0", "size"), 0n);
  assert.equal(scaled("0.00000001", "limit_price"), 1n, "the smallest step the encoding carries");
  assert.throws(
    () => scaled("0.000000001", "limit_price"),
    (error: unknown) => error instanceof EncodeError && /9 decimals/.test(String(error)),
    "one digit past the scale is refused, not rounded",
  );
  for (const bad of ["", "abc", "-1", "1e9", " 1", "1.", ".1", "01"]) {
    assert.throws(
      () => scaled(bad, "size"),
      EncodeError,
      `${JSON.stringify(bad)} is not a non-negative decimal`,
    );
  }
});

// A field that does not fit its Solidity type is refused rather than truncated. `sz` is
// uint64, so 10^8 times a human size caps the size this can express -- and a silent wrap
// would send an order for a different amount entirely.
test("a field that does not fit its type is refused", () => {
  const base = {
    asset: 1,
    isBuy: true,
    limitPx: 1n,
    sz: 1n,
    reduceOnly: false,
    encodedTif: TIF.Ioc,
    cloid: 0n,
  };
  assert.throws(() => encodeLimitOrder({ ...base, sz: 1n << 64n }), EncodeError, "sz overflows uint64");
  assert.throws(() => encodeLimitOrder({ ...base, limitPx: 1n << 64n }), EncodeError, "limitPx overflows");
  assert.throws(() => encodeLimitOrder({ ...base, cloid: 1n << 128n }), EncodeError, "cloid overflows uint128");
  assert.throws(() => encodeLimitOrder({ ...base, asset: 2 ** 32 }), EncodeError, "asset overflows uint32");
  assert.throws(() => encodeLimitOrder({ ...base, encodedTif: 4 }), EncodeError, "4 is not a tif");
  assert.throws(() => encodeLimitOrder({ ...base, asset: 1.5 }), EncodeError, "asset is not an integer");
});

// BUY AND `Ioc` ONLY, because that is all an envelope can bound: it is the cost of one order,
// a buy of exactly its size, cancelled rather than rested. A resting order outlives the book
// that priced it.
test("only the order an envelope can bound is built", () => {
  const envelope = {
    coin: "#39710",
    side: "buy",
    size: "924",
    limit_price: "0.17399",
    time_in_force: "Ioc",
  };
  const order = orderFromEnvelope(envelope, assetId);
  assert.equal(order.asset, 100_039_710, "the coin's encoding plus 100,000,000");
  assert.equal(order.isBuy, true);
  assert.equal(order.limitPx, 17_399_000n);
  assert.equal(order.sz, 92_400_000_000n);
  assert.equal(order.reduceOnly, false);
  assert.equal(order.encodedTif, TIF.Ioc);
  assert.equal(order.cloid, 0n);

  assert.throws(
    () => orderFromEnvelope({ ...envelope, side: "sell" }, assetId),
    EncodeError,
    "a sell is not what an ask-side walk bounds",
  );
  assert.throws(
    () => orderFromEnvelope({ ...envelope, time_in_force: "Gtc" }, assetId),
    (error: unknown) => error instanceof EncodeError && /outlives the book/.test(String(error)),
    "a resting order is refused, with the reason",
  );
});

// THE COST BOUND NEEDS NO BOOK. An `Ioc` buy of `sz` at a limit of `limitPx` cannot spend more
// than their product, whatever the book looks like when it executes -- which is the whole
// reason a gate can live on chain.
//
// Hand-derived: 924 contracts at 0.17399 is 160.76676, and 160.76676 at 10^16 is
// 1,607,667,600,000,000,000 -- the product of the two scaled values, kept scaled so no
// division reintroduces the rounding the encoding refuses.
test("the bounded cost is the product, in the scaled domain", () => {
  const order = orderFromEnvelope({
    coin: "#39710",
    side: "buy",
    size: "924",
    limit_price: "0.17399",
    time_in_force: "Ioc",
  }, assetId);
  assert.equal(boundedCost(order), 17_399_000n * 92_400_000_000n);
  assert.equal(boundedCost(order), 1_607_667_600_000_000_000n);
  // And that really is 160.76676, the retained envelope's own max_cost, at 10^16.
  assert.equal(boundedCost(order), 16_076_676n * 10n ** 11n);
});
