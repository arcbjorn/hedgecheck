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
  KEY_VARIABLE,
  place,
  PlaceError,
} from "../src/place.ts";
import { FakeExchange, filledSize } from "./fake-exchange.ts";

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
  const banned: [RegExp, string][] = [
    [/readFileSync\s*\([^)]*key/i, "reads a key from a file"],
    [/console\.[a-z]+\([^)]*process\.env/i, "logs the environment"],
    [/console\.[a-z]+\([^)]*\bkey\b/i, "logs something called a key"],
    [/JSON\.stringify\s*\(\s*process\.env/i, "serialises the environment"],
    [/\bprocess\.env\b(?!\s*\))/, "reads process.env directly rather than an injected env"],
  ];
  let scanned = 0;
  const visit = (directory: URL): void => {
    for (const name of readdirSync(directory)) {
      if (name === "node_modules") continue;
      const child = new URL(`${name}${statSync(new URL(name, directory)).isDirectory() ? "/" : ""}`, directory);
      if (statSync(child).isDirectory()) {
        visit(child);
        continue;
      }
      if (!name.endsWith(".ts")) continue;
      // This file names the patterns it bans, so it cannot scan itself.
      if (name === "place.test.ts") continue;
      const source = readFileSync(child, "utf8").replace(/\/\/.*$/gm, "");
      scanned += 1;
      for (const [pattern, why] of banned) {
        assert.doesNotMatch(source, pattern, `${name} ${why}`);
      }
    }
  };
  visit(root);
  assert.ok(scanned >= 4, `only ${scanned} files were scanned`);
});
