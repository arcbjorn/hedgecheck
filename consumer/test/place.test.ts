// The order path, against a fake exchange only.

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { test } from "node:test";

import type { OrderEnvelope } from "../src/gate.ts";
import {
  actionFor,
  agentKey,
  assetId,
  Exchanges,
  isNetwork,
  KEY_VARIABLE,
  msgpack,
  place,
  PlaceError,
} from "../src/place.ts";
import { BANNED, SKIPPED } from "./banned.ts";
import { FakeExchange, filledSize, SCENARIOS } from "./fake-exchange.ts";
import { code } from "./source.ts";

// A key that was never a key: 32 bytes of hex, generated here as a constant so
// nothing in this repository ever holds a real one.
const NOT_A_KEY = `0x${"11".repeat(32)}`;

const ENVELOPE: OrderEnvelope = {
  coin: "#39710",
  side: "buy",
  size: "924",
  limit_price: "0.17399",
  time_in_force: "Ioc",
  max_cost: "160.76676",
  input_digest: "a".repeat(64),
};

function options(exchange: FakeExchange, env: Record<string, string | undefined> = {}) {
  return {
    network: "testnet" as const,
    env: { [KEY_VARIABLE]: NOT_A_KEY, ...env },
    nonceMs: 1_789_000_000_000n,
    send: exchange.send,
  };
}

// The asset id rule, EVIDENCE section 4: 100,000,000 + (10*outcome + side).
// Hand-derived here, not taken from the code under test.
test("the asset id is the encoding plus 100,000,000", () => {
  assert.equal(assetId("#39710"), 100_039_710); // bucket0 3971 YES
  assert.equal(assetId("#39651"), 100_039_651); // binary 3965 NO
  assert.equal(assetId("#204891"), 100_204_891); // testnet binary 20489 NO
  for (const bad of ["BTC", "#", "39710", "#abc", "#-1", "", "#1e5"]) {
    assert.throws(() => assetId(bad), PlaceError, `${bad} was accepted as a coin`);
  }
});

// THE ORDER EQUALS THE ENVELOPE, FIELD FOR FIELD.
//
// The envelope is the statement of which order the cost bound is about. An order
// that differs from it anywhere is an order the bound does not cover, so this
// compares every field rather than spot-checking.
test("the order sent is the envelope, field for field", async () => {
  const exchange = new FakeExchange();
  exchange.script("full-fill");
  const placed = await place(ENVELOPE, options(exchange));

  assert.equal(exchange.requests.length, 1);
  const sent = JSON.parse(exchange.requests[0]!.body);
  const order = sent.action.orders[0];

  assert.equal(order.a, assetId(ENVELOPE.coin), "asset");
  assert.equal(order.b, true, "buy");
  assert.equal(order.p, ENVELOPE.limit_price, "limit price");
  assert.equal(order.s, ENVELOPE.size, "size");
  assert.equal(order.r, false, "reduce only");
  assert.equal(order.t.limit.tif, "Ioc", "time in force");
  assert.equal(sent.action.grouping, "na");
  assert.equal(sent.action.orders.length, 1, "exactly one order");

  // And it went to the testnet exchange, not mainnet.
  assert.equal(exchange.requests[0]!.url, Exchanges.testnet);
  assert.equal(placed.status, 200);
  assert.equal(filledSize(placed.body), ENVELOPE.size);
});

// A non-buy or non-Ioc envelope is refused BEFORE anything is signed or sent.
test("an envelope that is not a buy Ioc is refused before sending", async () => {
  const exchange = new FakeExchange();
  for (const bad of [
    { ...ENVELOPE, side: "sell" },
    { ...ENVELOPE, time_in_force: "Gtc" },
    { ...ENVELOPE, time_in_force: "Alo" },
  ]) {
    await assert.rejects(() => place(bad, options(exchange)), PlaceError);
  }
  assert.equal(exchange.requests.length, 0, "something was sent for a refused envelope");
});

// NOTHING IS SENT TWICE ON A TIMEOUT.
//
// An Ioc order that timed out may still have filled. A retry would be a second
// order, and no amount of care downstream can unfill the first.
test("a timeout sends once and does not retry", async () => {
  const exchange = new FakeExchange();
  exchange.script("timeout");
  await assert.rejects(() => place(ENVELOPE, options(exchange)), /hang up/);
  assert.equal(exchange.requests.length, 1, "a timeout caused more than one send");

  // Nor does a second call quietly become a retry of the first: it is a new order,
  // and the caller had to ask for it.
  exchange.script("full-fill");
  await place(ENVELOPE, options(exchange));
  assert.equal(exchange.requests.length, 2);
});

// ONE place() CALL IS ONE REQUEST, WHATEVER THE VENUE ANSWERS.
//
// The timeout test below covers the THROW path only. Every scenario used to answer
// 200 -- including `rejected` -- so a retry conditioned on the status was never
// exercised, and that is the shape anyone would actually write one in. The sweep is
// over every scenario the fake can produce, so a scenario added later is covered
// without anyone remembering to add it here.
test("one place call is one request, across every scenario", async () => {
  for (const scenario of SCENARIOS) {
    const exchange = new FakeExchange();
    exchange.script(scenario, "300");
    try {
      await place(ENVELOPE, options(exchange));
    } catch {
      // A throwing scenario is still exactly one request; that is the point.
    }
    assert.equal(exchange.requests.length, 1, `${scenario} did not send exactly once`);
  }
});

// A duplicate answer to one request is still one request.
test("a duplicate response does not mean a duplicate order", async () => {
  const exchange = new FakeExchange();
  exchange.script("duplicate");
  const first = await place(ENVELOPE, options(exchange));
  assert.equal(exchange.requests.length, 1);
  assert.equal(filledSize(first.body), ENVELOPE.size);
});

// Every scenario the venue can answer with, and what the caller reads from it.
test("every scripted scenario is read correctly", async () => {
  const cases: [Parameters<FakeExchange["script"]>[0], string, string][] = [
    ["full-fill", "924", "924"],
    ["partial-fill", "300", "300"],
    ["no-fill", "0", "0"],
    ["rejected", "0", "0"],
  ];
  for (const [scenario, scripted, wantFilled] of cases) {
    const exchange = new FakeExchange();
    exchange.script(scenario, scripted);
    const placed = await place(ENVELOPE, options(exchange));
    assert.equal(filledSize(placed.body), wantFilled, `${scenario} filled`);
    assert.equal(exchange.requests.length, 1, `${scenario} sent once`);
  }
});

// A HASHING ENCODER REFUSES WHAT IT CANNOT REPRESENT.
//
// The str16 branch took `length >> 8` and `length & 0xff`, which silently became
// length mod 65536 above 65535. The header then declared a different length than the
// payload carried, so a spec decoder read a SHORTER string than keccak-256 covered --
// the signature over one action, the venue parsing another.
test("msgpack refuses what it cannot encode rather than lying about a length", () => {
  // The boundary, hand-derived from the msgpack spec: 0xda carries a 2-byte
  // big-endian length, so 65535 is the last representable string.
  const ok = msgpack("x".repeat(65535));
  assert.equal(ok[0], 0xda, "a 65535-byte string is not str16");
  assert.equal(((ok[1] as number) << 8) | (ok[2] as number), 65535, "the declared length is wrong");
  assert.equal(ok.length, 65535 + 3, "the payload does not match the header");

  assert.throws(() => msgpack("x".repeat(65536)), PlaceError, "a 65536-byte string was encoded");

  // Non-plain objects are refused too: Object.entries sees a Date as {} and a
  // Uint8Array as {"0":..}, so they used to encode as something wrong.
  assert.throws(() => msgpack(new Date(0)), PlaceError, "a Date was encoded");
  assert.throws(() => msgpack(Uint8Array.from([1, 2])), PlaceError, "a Uint8Array was encoded");
});

// Every field the envelope carries into the signed action is checked here, because
// this is the declared field-for-field boundary. It used to accept "", "abc" and
// "1e9999" and hand them to the signer.
test("actionFor refuses a size or price that is not a decimal", () => {
  for (const bad of ["", "abc", "-1", "1e9999", "0x10", " 1", "1 ", "1/2", "."]) {
    assert.throws(() => actionFor({ ...ENVELOPE, size: bad }), PlaceError, `size ${JSON.stringify(bad)}`);
    assert.throws(
      () => actionFor({ ...ENVELOPE, limit_price: bad }),
      PlaceError,
      `price ${JSON.stringify(bad)}`,
    );
  }
  assert.doesNotThrow(() => actionFor(ENVELOPE));
});

// A nonce is HASHED as an exact 64-bit integer and TRANSMITTED through JSON, which is
// lossy above 2^53. Both must come from one value or the signature covers a number
// the venue never sees.
test("a nonce that JSON cannot carry intact is refused", async () => {
  const exchange = new FakeExchange();
  exchange.script("full-fill");
  for (const bad of [BigInt(Number.MAX_SAFE_INTEGER) + 1n, 2n ** 63n, -1n]) {
    await assert.rejects(
      () => place(ENVELOPE, { ...options(exchange), nonceMs: bad }),
      PlaceError,
      `nonce ${bad} was accepted`,
    );
  }
  assert.equal(exchange.requests.length, 0, "an order was sent for a bad nonce");
});

// An unknown network cannot borrow the testnet signing domain. `network === "mainnet"
// ? "a" : "b"` gave every other string a VALID testnet signature.
test("only the two known networks have a signing domain", () => {
  assert.ok(isNetwork("mainnet") && isNetwork("testnet"));
  for (const bad of ["constructor", "__proto__", "toString", "valueOf", "hasOwnProperty", "banana"]) {
    assert.equal(isNetwork(bad), false, `${bad} was accepted as a network`);
  }
});

// THE KEY COMES FROM THE ENVIRONMENT AND NOWHERE ELSE.
test("the key is read only from the environment, and never appears in an error", () => {
  assert.throws(() => agentKey({}), /is not set/);
  assert.throws(() => agentKey({ [KEY_VARIABLE]: "" }), /is not set/);

  for (const bad of ["0x12", "nothex", "11".repeat(31), `0x${"11".repeat(33)}`]) {
    try {
      agentKey({ [KEY_VARIABLE]: bad });
      assert.fail(`${bad} was accepted as a key`);
    } catch (error) {
      const message = String(error);
      // The VALUE is not in the message. A malformed key is still a key.
      assert.ok(!message.includes(bad), `the error quotes the key: ${message}`);
    }
  }
  // A well-formed one is 32 bytes and is not returned as text.
  const key = agentKey({ [KEY_VARIABLE]: NOT_A_KEY });
  assert.equal(key.length, 32);
});

// Signing is deterministic for a given action and nonce, so the same envelope twice
// is the same bytes -- which is what makes a duplicate detectable.
test("the signed body is deterministic for one envelope and nonce", async () => {
  const first = new FakeExchange();
  const second = new FakeExchange();
  await place(ENVELOPE, options(first));
  await place(ENVELOPE, options(second));
  assert.equal(first.requests[0]!.body, second.requests[0]!.body);
});

// A different nonce gives a different signature, so a replay of one body is not
// silently valid for another moment.
test("a different nonce changes the signature", async () => {
  const first = new FakeExchange();
  const second = new FakeExchange();
  await place(ENVELOPE, { ...options(first), nonceMs: 1n });
  await place(ENVELOPE, { ...options(second), nonceMs: 2n });
  const a = JSON.parse(first.requests[0]!.body).signature;
  const b = JSON.parse(second.requests[0]!.body).signature;
  assert.notEqual(a.r, b.r, "the same signature for two nonces");
});

// NO FILE UNDER consumer/ READS A KEY FROM ANYWHERE BUT THE ENVIRONMENT, AND NONE
// LOGS THE ENVIRONMENT.
test("nothing in consumer/ reads a key from outside the environment", () => {
  const root = new URL("../", import.meta.url);
  const scanned: string[] = [];
  const visit = (directory: URL): void => {
    for (const name of readdirSync(directory)) {
      if (name === "node_modules") continue;
      const child = new URL(`${name}${statSync(new URL(name, directory)).isDirectory() ? "/" : ""}`, directory);
      if (statSync(child).isDirectory()) {
        visit(child);
        continue;
      }
      if (!name.endsWith(".ts")) continue;
      // Exactly one file is skipped: the one that quotes the patterns.
      if (name === SKIPPED) continue;
      const source = code(child);
      scanned.push(name);
      for (const [pattern, why] of BANNED) {
        assert.doesNotMatch(source, pattern, `${name} ${why}`);
      }
    }
  };
  visit(root);

  // THE SET, NOT A COUNT. `scanned >= 4` was satisfied by 5 of 9 files, so the walk
  // could lose the whole of `src/` -- every production module -- and still pass. An
  // exact set makes a dropped directory impossible to miss, the way the module
  // inventory in gate.test.ts already does.
  assert.deepEqual(scanned.sort(), [
    "banned-usage.test.ts",
    "fake-exchange.ts",
    "gate.test.ts",
    "gate.ts",
    "place.test.ts",
    "place.ts",
    "recheck.test.ts",
    "recheck.ts",
    "run.ts",
    "source.ts",
    "typegate.test.ts",
    "unrepresentable.ts",
  ], "the scan is not looking at the files it should");
});
