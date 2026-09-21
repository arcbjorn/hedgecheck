// Assert the negative.
//
// PLAN section 7, the T3 row: "anything but `passes` produces zero downstream calls,
// asserted". The assertion is a count, not a mood: the recording fake below counts
// every call it receives, and every row of the table asserts EXACTLY ZERO except the
// one good row, which asserts EXACTLY ONE.
//
// A test that asserted "no order was placed" by checking the decision would be
// checking the gate's opinion of itself. This checks what actually reached the other
// side.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { parse, type Value } from "../../checker/src/canon.ts";
import { schemas, type Schemas } from "../../checker/src/doc.ts";
import { parseVenue, type VenueValue } from "../../checker/src/venue.ts";
import type { Bundle } from "../../checker/src/verify.ts";
import { type Capture, gate, type OrderEnvelope, type Place, type Policy, type Reason } from "../src/gate.ts";
import { gateWith, type Verifier } from "../src/testing.ts";
import { code } from "./source.ts";

const here = (path: string) => new URL(path, import.meta.url);

/** The recording fake. It is the whole point of the table, so it does nothing else. */
class Recorder {
  readonly calls: OrderEnvelope[] = [];
  readonly place: Place = async (envelope: OrderEnvelope) => {
    this.calls.push(envelope);
    return { ok: true };
  };
}

function loadSchemas(): Schemas {
  const directory = here("../../schema/");
  const files = new Map<string, VenueValue>();
  for (const name of readdirSync(directory)) {
    if (name.endsWith(".json")) {
      files.set(name, parseVenue(new Uint8Array(readFileSync(new URL(name, directory)))));
    }
  }
  return schemas(files);
}

interface Loaded {
  readonly name: string;
  readonly expects: string;
  readonly bundle: Bundle;
  readonly allowlist: Set<string>;
}

function loadBundle(name: string): Loaded {
  const directory = here("../../fixtures/bundles/");
  const read = (file: string) => new Uint8Array(readFileSync(new URL(`${name}/${file}`, directory)));
  const manifestRaw = read("manifest.json");
  const manifest = parse(manifestRaw) as Record<string, Value>;
  const files = manifest["files"] as Record<string, Value>;

  const snapshots = new Map<string, Uint8Array>();
  for (const entry of files["snapshots"] as Value[]) {
    const item = entry as Record<string, Value>;
    snapshots.set(item["sha256"] as string, read(item["path"] as string));
  }
  const registry = new Map<string, Uint8Array>();
  for (const entry of files["registry"] as Value[]) {
    const item = entry as Record<string, Value>;
    registry.set(item["family"] as string, read(item["path"] as string));
  }
  const proposalRaw = read(files["proposal"] as string);
  const proposal = parse(proposalRaw) as Record<string, Value>;
  const allowlist = new Set<string>();
  for (const rawLeg of proposal["legs"] as Value[]) {
    allowlist.add((rawLeg as Record<string, Value>)["semantics_version"] as string);
  }
  return {
    name,
    expects: manifest["expects"] as string,
    allowlist,
    bundle: {
      proposal: proposalRaw,
      lowered: read(files["lowered"] as string),
      result: read(files["result"] as string),
      manifest: manifestRaw,
      snapshots,
      registry,
    },
  };
}

function everyBundle(): string[] {
  return readdirSync(here("../../fixtures/bundles/")).filter((name) => !name.startsWith(".")).sort();
}

/** Rewrite the result document of a bundle. Used only to build negative rows. */
function withResult(bundle: Bundle, change: (result: Record<string, unknown>) => void): Bundle {
  const result = JSON.parse(new TextDecoder().decode(bundle.result)) as Record<string, unknown>;
  change(result);
  return { ...bundle, result: new TextEncoder().encode(JSON.stringify(result)) };
}

/**
 * A checker that accepts, handing back the result document the bundle actually holds.
 *
 * `verify` returns the value it established, so a stub must too -- otherwise the gate
 * reads a result nobody supplied. Parsed with the strict canonical parser, the same one
 * the real checker uses, so these rows exercise the gate's own conditions rather than a
 * shape only this file can produce.
 */
function acceptsWith(bundle: Bundle): Verifier {
  return () => Promise.resolve({
    accepted: true as const,
    result: parse(bundle.result) as Record<string, Value>,
  });
}

// The capture instant and the policy.
//
// HAND-CHOSEN, and injected. 1_789_715_838_660 is the `time` field the venue put on
// the bucket book in fixtures/replay/2026-09-18/book-bucket0-3971-yes.json, so the
// numbers below are an age in milliseconds against a real capture rather than a
// round number that happens to work.
const CAPTURED_AT = 1_789_715_838_660n;
const MAX_AGE = 30_000n;
const FRESH: Policy = { now: CAPTURED_AT + 29_999n, maxAgeMs: MAX_AGE };
const CAPTURE: Capture = { capturedAtMs: CAPTURED_AT };

function policy(over: Partial<Policy> = {}): Policy {
  return { ...FRESH, checker: { schemas: loadSchemas() }, ...over };
}

test("the good bundle places exactly one order, and it is the envelope", async () => {
  const loaded = loadBundle("good-envelope");
  const recorder = new Recorder();
  const decision = await gate(
    loaded.bundle,
    { ...policy(), checker: { schemas: loadSchemas(), allowlist: loaded.allowlist } },
    CAPTURE,
    recorder.place,
  );

  assert.equal(decision.approved, true, decision.approved ? "" : `${decision.reason}: ${decision.detail}`);
  assert.equal(recorder.calls.length, 1, "exactly one downstream call");

  // The order placed is the one the result authorised, field for field. A gate that
  // placed a DIFFERENT order after an accepted check would pass every count above.
  const placed = recorder.calls[0] as OrderEnvelope;
  assert.equal(placed.coin, "#39710");
  assert.equal(placed.side, "buy");
  assert.equal(placed.size, "924");
  // Hand-derived from the retained book: the asks are 0.17399 x 1200, 0.174 x 1200,
  // 0.99999 x 100000, and 924 <= 1200, so the walk begins and ends in the first
  // level. 924 x 17399 = 15659100 + 417576 = 16076676 in units of 1e-5.
  assert.equal(placed.limit_price, "0.17399");
  assert.equal(placed.max_cost, "160.76676");
  assert.equal(placed.time_in_force, "Ioc");
});

/**
 * Every corrupted bundle, driven through the gate.
 *
 * Not a sample: the directory is read, and every bundle whose manifest does not say
 * `accept` is a row. A corruption added later is a row later, without anyone
 * remembering to add it here.
 */
test("no corrupted bundle reaches the downstream call", async () => {
  const all = loadSchemas();
  let rows = 0;
  for (const name of everyBundle()) {
    const loaded = loadBundle(name);
    if (loaded.expects === "accept") continue;
    const recorder = new Recorder();
    const decision = await gate(
      loaded.bundle,
      { ...policy(), checker: { schemas: all, allowlist: loaded.allowlist } },
      CAPTURE,
      recorder.place,
    );
    assert.equal(decision.approved, false, `${name} was approved`);
    assert.equal(recorder.calls.length, 0, `${name} made ${recorder.calls.length} downstream calls`);
    rows += 1;
  }
  assert.ok(rows >= 12, `only ${rows} corrupted bundles were driven through the gate`);
});

/** The table. One row per way the gate must say no, each asserting zero calls. */
test("the table: every refusal makes zero downstream calls", async () => {
  const all = loadSchemas();
  const good = loadBundle("good-envelope");
  const horizon = loadBundle("good-horizon");
  const base = { ...policy(), checker: { schemas: all, allowlist: good.allowlist } };

  const rows: { name: string; run: (place: Place) => Promise<{ reason?: Reason }> }[] = [
    {
      // A verdict of `fails`: the good-horizon bundle really does fail, so this row
      // is a whole answer the engine produced, not a document edited to look like one.
      name: "a fails",
      run: async (place) => {
        const decision = await gate(
          horizon.bundle,
          { ...base, checker: { schemas: all, allowlist: horizon.allowlist } },
          CAPTURE,
          place,
        );
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      // A `fails` THAT STILL CARRIES AN ENVELOPE.
      //
      // The row above does not isolate the verdict condition: good-horizon has no
      // envelope either, so deleting the verdict check from the gate still refuses it
      // as NO_ENVELOPE. Found by mutation -- PLAN section 7's fourth lesson, that a
      // guard overlapping another proves less than it looks. This row leaves the
      // envelope in place so the verdict is the only thing standing between the
      // bundle and an order, and runs the checker without schemas so the gate answers
      // rather than the checker.
      name: "a fails that still carries an envelope",
      run: async (place) => {
        const bundle = withResult(good.bundle, (result) => {
          result["model_result"] = "fails";
        });
        const decision = await gateWith(
          acceptsWith(bundle),
          bundle,
          base,
          CAPTURE,
          place,
        );
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      // And a `needs_review` that still carries an envelope, for the same reason.
      name: "a needs_review that still carries an envelope",
      run: async (place) => {
        const bundle = withResult(good.bundle, (result) => {
          result["model_result"] = "needs_review";
        });
        const decision = await gateWith(
          acceptsWith(bundle),
          bundle,
          base,
          CAPTURE,
          place,
        );
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      // The checker refuses this one before the verdict is ever read, which is the
      // point: the gate's first condition is the checker's answer, not the result's.
      name: "a needs_review",
      run: async (place) => {
        // An EMPTY allowlist makes the registry entries unreviewed, and an unreviewed
        // family is a loose reduction, so the honest verdict is needs_review while
        // the result still says passes. The checker sees the disagreement.
        const decision = await gate(good.bundle, { ...base, checker: { schemas: all } }, CAPTURE, place);
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      name: "a stale capture",
      run: async (place) => {
        const decision = await gate(good.bundle, { ...base, now: CAPTURED_AT + MAX_AGE }, CAPTURE, place);
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      name: "a capture one millisecond staler than the policy allows",
      run: async (place) => {
        const decision = await gate(good.bundle, { ...base, now: CAPTURED_AT + MAX_AGE + 1n }, CAPTURE, place);
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      name: "a capture in the future",
      run: async (place) => {
        const decision = await gate(good.bundle, { ...base, now: CAPTURED_AT - 1n }, CAPTURE, place);
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      name: "a mismatched digest, with the checker refusing it too",
      run: async (place) => {
        const bundle = withResult(good.bundle, (result) => {
          (result["order_envelope"] as Record<string, unknown>)["input_digest"] = "f".repeat(64);
        });
        const decision = await gate(bundle, { ...base, checker: { allowlist: good.allowlist } }, CAPTURE, place);
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      // THE SAME MISMATCH, WITH THE CHECKER OUT OF THE WAY.
      //
      // The row above does not isolate the gate's condition 4: the checker's own
      // compareEnvelope catches the swapped digest first, so deleting the gate's
      // check changes nothing there. Found by mutation. Here the verifier is an
      // accepting stub, which is the whole point -- the gate must not rely on the
      // checker having looked, because the gate is the last thing before an order
      // and a future checker might not check this at all.
      name: "a mismatched digest the checker did not catch",
      run: async (place) => {
        const bundle = withResult(good.bundle, (result) => {
          (result["order_envelope"] as Record<string, unknown>)["input_digest"] = "f".repeat(64);
        });
        const decision = await gateWith(
          acceptsWith(bundle),
          bundle,
          base,
          CAPTURE,
          place,
        );
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      // And a result with no input_digest at all, which the gate must also refuse:
      // an envelope whose result does not name itself belongs to nothing.
      name: "an envelope whose result names no input digest",
      run: async (place) => {
        const bundle = withResult(good.bundle, (result) => {
          delete result["input_digest"];
        });
        const decision = await gateWith(
          acceptsWith(bundle),
          bundle,
          base,
          CAPTURE,
          place,
        );
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      name: "a missing envelope",
      run: async (place) => {
        const bundle = withResult(good.bundle, (result) => {
          delete result["order_envelope"];
          result["execution_readiness"] = "not_evaluated";
        });
        const decision = await gate(bundle, { ...base, checker: { allowlist: good.allowlist } }, CAPTURE, place);
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      // The same, with an accepting stub, so the gate's condition 3 is the only
      // thing between a passing result and an order.
      name: "a missing envelope the checker did not catch",
      run: async (place) => {
        const bundle = withResult(good.bundle, (result) => {
          delete result["order_envelope"];
        });
        const decision = await gateWith(
          acceptsWith(bundle),
          bundle,
          base,
          CAPTURE,
          place,
        );
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      name: "an envelope missing a field",
      run: async (place) => {
        const bundle = withResult(good.bundle, (result) => {
          delete (result["order_envelope"] as Record<string, unknown>)["limit_price"];
        });
        const decision = await gate(bundle, { ...base, checker: { allowlist: good.allowlist } }, CAPTURE, place);
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      // The same, with an accepting stub. Without this the gate's field check is
      // shadowed by the checker's schema check and mutation does not reach it.
      //
      // It matters on its own: `place` is handed this object, and a fake in a test
      // will happily record an envelope with an undefined limit where a real venue
      // client would send a malformed order or throw halfway through.
      name: "an envelope missing a field the checker did not catch",
      run: async (place) => {
        const bundle = withResult(good.bundle, (result) => {
          delete (result["order_envelope"] as Record<string, unknown>)["limit_price"];
        });
        const decision = await gateWith(
          acceptsWith(bundle),
          bundle,
          base,
          CAPTURE,
          place,
        );
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      name: "a result that is not readable at all",
      run: async (place) => {
        const bundle = { ...good.bundle, result: new TextEncoder().encode("{") };
        const decision = await gate(bundle, { ...base, checker: { allowlist: good.allowlist } }, CAPTURE, place);
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    // A result that PARSES but is not an object. `null` is the one that matters: with
    // the guard removed the gate throws an uncaught TypeError out of the function
    // rather than returning a Decision, and run.ts has no catch around the gate call.
    // The accepting stub is what isolates the gate's own condition here.
    ...(["null", "[1,2,3]", "42", '"a string"', "true"].map((text) => ({
      name: `a result that parses to ${text}`,
      run: async (place: Place) => {
        const bundle = { ...good.bundle, result: new TextEncoder().encode(text) };
        const decision = await gateWith(
          (async () => ({ accepted: true, result: null })) as unknown as Verifier,
          bundle,
          base,
          CAPTURE,
          place,
        );
        return decision.approved ? {} : { reason: decision.reason };
      },
    }))),
    {
      // A checker that throws, supplied as the verifier.
      //
      // It cannot be provoked from the bundle: `verify` catches its own faults and
      // returns ENGINE_DISAGREES. Corrupting the bundle to make it fall over was
      // tried and produced CHECKER_REFUSED, which is the real checker behaving
      // correctly and this row proving nothing. So the throwing checker is injected.
      name: "a checker that throws",
      run: async (place) => {
        const decision = await gateWith(
          () => Promise.reject(new Error("the checker fell over")),
          good.bundle,
          base,
          CAPTURE,
          place,
        );
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
    {
      // And one that throws synchronously, which is a different path through the
      // await: a function that never returns a promise at all.
      name: "a checker that throws before it returns a promise",
      run: async (place) => {
        const decision = await gateWith(
          () => {
            throw new Error("the checker fell over before starting");
          },
          good.bundle,
          base,
          CAPTURE,
          place,
        );
        return decision.approved ? {} : { reason: decision.reason };
      },
    },
  ];

  const approved: string[] = [];
  const called: string[] = [];
  for (const row of rows) {
    const recorder = new Recorder();
    const outcome = await row.run(recorder.place);
    if (outcome.reason === undefined) approved.push(row.name);
    if (recorder.calls.length !== 0) called.push(`${row.name}: ${recorder.calls.length} calls`);
  }
  assert.deepEqual(approved, [], `${approved.length} rows were approved`);
  assert.deepEqual(called, [], `${called.length} rows reached the downstream call`);
});

/**
 * The checker's own answer, reached through the gate.
 *
 * `verify` throwing is caught as CHECKER_THREW and never as an acceptance. This is
 * separate from the table because the table only counts calls, and a gate that
 * returned CHECKER_REFUSED for a crash would still count zero -- and would tell an
 * operator the bundle was bad when in fact nothing was checked.
 */
test("a checker that throws is CHECKER_THREW, not CHECKER_REFUSED", async () => {
  const good = loadBundle("good-envelope");
  const recorder = new Recorder();
  const decision = await gateWith(
    () => Promise.reject(new Error("the checker fell over")),
    good.bundle,
    policy(),
    CAPTURE,
    recorder.place,
  );
  assert.equal(decision.approved, false);
  assert.equal(decision.approved ? "" : decision.reason, "CHECKER_THREW");
  assert.equal(decision.approved ? "" : decision.detail, "the checker fell over");
  assert.equal(recorder.calls.length, 0);
});

// And the real checker does NOT throw, which is why the row above has to inject one.
// If verify ever starts throwing, this fails and the comment above stops being true.
test("the real checker refuses rather than throwing", async () => {
  const good = loadBundle("good-envelope");
  const exploding: ReadonlyMap<string, Uint8Array> = new Proxy(new Map<string, Uint8Array>(), {
    get() {
      throw new Error("the snapshots fell over");
    },
  });
  const recorder = new Recorder();
  const decision = await gate(
    { ...good.bundle, snapshots: exploding },
    policy(),
    CAPTURE,
    recorder.place,
  );
  assert.equal(decision.approved, false);
  assert.equal(decision.approved ? "" : decision.reason, "CHECKER_REFUSED");
  assert.equal(recorder.calls.length, 0);
});

/** The boundary of the age rule, stated as three adjacent instants. */
test("the age boundary is decided by the policy, not by rounding", async () => {
  const good = loadBundle("good-envelope");
  const checker = { schemas: loadSchemas(), allowlist: good.allowlist };
  for (const row of [
    { now: CAPTURED_AT + MAX_AGE - 1n, approved: true },
    { now: CAPTURED_AT + MAX_AGE, approved: false },
    { now: CAPTURED_AT + MAX_AGE + 1n, approved: false },
  ]) {
    const recorder = new Recorder();
    const decision = await gate(
      good.bundle,
      { now: row.now, maxAgeMs: MAX_AGE, checker },
      CAPTURE,
      recorder.place,
    );
    assert.equal(decision.approved, row.approved, `at ${row.now - CAPTURED_AT}ms old`);
    assert.equal(recorder.calls.length, row.approved ? 1 : 0, `at ${row.now - CAPTURED_AT}ms old`);
  }
});

// THE GATE READS THE BUNDLE ONCE, SO WHAT WAS VERIFIED IS WHAT IS USED.
//
// `Bundle` is an interface, so a caller can supply accessors. `bundle.result` was
// read twice -- once by the checker, once by the gate -- and a getter answering
// differently the second time made the gate place an order the checker never saw:
// verified 924 contracts at 0.17399, placed 999999 at 0.99999, `approved: true`.
test("a bundle field that changes between reads cannot change the order", async () => {
  const good = loadBundle("good-envelope");
  const genuine = good.bundle.result;
  const swapped = withResult(good.bundle, (result) => {
    const envelope = result["order_envelope"] as Record<string, unknown>;
    envelope["size"] = "999999";
    envelope["limit_price"] = "0.99999";
    envelope["max_cost"] = "999999";
  }).result;

  let reads = 0;
  const trap: Bundle = {
    proposal: good.bundle.proposal,
    lowered: good.bundle.lowered,
    manifest: good.bundle.manifest,
    snapshots: good.bundle.snapshots,
    registry: good.bundle.registry,
    get result() {
      reads += 1;
      return reads === 1 ? genuine : swapped;
    },
  };

  const recorder = new Recorder();
  const decision = await gate(
    trap,
    { ...policy(), checker: { schemas: loadSchemas(), allowlist: good.allowlist } },
    CAPTURE,
    recorder.place,
  );

  assert.equal(reads, 1, `the gate read bundle.result ${reads} times; it must read it once`);
  if (decision.approved) {
    const placed = recorder.calls[0] as OrderEnvelope;
    assert.equal(placed.size, "924", "the order placed is not the one the checker verified");
    assert.equal(placed.limit_price, "0.17399", "the price placed is not the one verified");
    assert.equal(placed.max_cost, "160.76676", "the cost bound placed is not the one verified");
  }
});

// THE POLICY'S NUMBERS ARE CHECKED, BECAUSE TYPES ERASE.
//
// `maxAgeMs` is typed bigint but arrives from a caller. A bigint/number comparison is
// legal in JavaScript and any comparison against NaN is false, so `undefined` -- what
// a typo'd key produces -- made `age >= maxAgeMs` false and removed the staleness
// rule entirely. A capture a YEAR old placed an order.
test("a policy that is not bigints refuses, and places nothing", async () => {
  const good = loadBundle("good-envelope");
  const base = { ...policy(), checker: { schemas: loadSchemas(), allowlist: good.allowlist } };
  const YEAR = 31_536_000_000n;
  const stale: Capture = { capturedAtMs: CAPTURED_AT - YEAR };

  for (const bad of [undefined, Number.NaN, Number.POSITIVE_INFINITY, 900_000, "900000"]) {
    const recorder = new Recorder();
    const decision = await gate(
      good.bundle,
      { ...base, now: CAPTURED_AT, maxAgeMs: bad as unknown as bigint },
      stale,
      recorder.place,
    );
    assert.equal(decision.approved, false, `maxAgeMs=${String(bad)} approved a year-old capture`);
    assert.equal(recorder.calls.length, 0, `maxAgeMs=${String(bad)} placed an order`);
  }

  // And a non-bigint instant is refused rather than throwing out of the gate.
  for (const field of ["now", "capturedAtMs"] as const) {
    const recorder = new Recorder();
    const decision = await gate(
      good.bundle,
      { ...base, ...(field === "now" ? { now: Date.now() as unknown as bigint } : {}) },
      field === "capturedAtMs" ? ({ capturedAtMs: Date.now() } as unknown as Capture) : CAPTURE,
      recorder.place,
    );
    assert.equal(decision.approved, false, `a number ${field} was approved`);
    assert.equal(recorder.calls.length, 0, `a number ${field} placed an order`);
  }
});

// THE BRAND COMMENT STAYS TRUE.
//
// It claims two things a future edit could quietly falsify: that nothing reads `.brand`
// at runtime, and that it is constructed after `place()` returns. If either changes, the
// comment becomes a false claim in the file that authorises orders -- which is what it
// was before the audit -- so both are asserted rather than trusted.
test("the brand is advisory: nothing reads it, and it is built after place returns", () => {
  const source = code(here("../src/gate.ts"));

  // Read nowhere. The declaration and the single construction are the only mentions.
  const mentions = source.match(/\bbrand\b/g) ?? [];
  assert.equal(mentions.length, 2, `brand appears ${mentions.length} times in code, want 2`);
  assert.match(source, /readonly brand: typeof checked;/, "the brand field is gone");
  assert.match(source, /brand: checked/, "the brand construction is gone");

  // Constructed AFTER the order is sent, so it could not gate one even if read.
  const send = source.indexOf("await place(envelope)");
  const build = source.indexOf("brand: checked");
  assert.ok(send > 0 && build > 0, "the call site or the construction moved");
  assert.ok(build > send, "the brand is now built before place() returns; the comment is stale");
});

/** The gate never reads a clock: a policy is the only source of "now". */
test("the gate reads no clock", () => {
  const source = code(here("../src/gate.ts"));
  for (const pattern of [/\bDate\b/, /\bperformance\b/, /\bhrtime\b/]) {
    assert.doesNotMatch(source, pattern, `gate.ts uses ${pattern}`);
  }
});

/** The gate signs nothing and sends nothing: `place` is the only way out. */
test("the gate has no way to send an order of its own", () => {
  const source = code(here("../src/gate.ts"));
  for (const pattern of [/\bfetch\b/, /\bXMLHttpRequest\b/, /\bWebSocket\b/, /\bsign\w*\(/, /\bprivateKey\b/, /\bmnemonic\b/, /["']node:/]) {
    assert.doesNotMatch(source, pattern, `gate.ts uses ${pattern}`);
  }
  // Exactly one call site, so "zero downstream calls" is a property of the shape of
  // the function and not of a flag every early return has to remember to set.
  const sites = source.match(/\bplace\(/g) ?? [];
  assert.equal(sites.length, 1, `gate.ts calls place at ${sites.length} sites`);
});

// `place` is a parameter of the gate. place.ts exists and can reach a venue, but
// gate.ts must not import it: the gate decides, the sender sends, and a gate that
// could construct its own sender could place without deciding.
test("the gate cannot reach a sender of its own", () => {
  const source = readFileSync(here("../src/gate.ts"), "utf8");
  assert.doesNotMatch(source, /from\s*["']\.\/place\.ts["']/, "gate.ts imports place.ts");
  const names = readdirSync(here("../src/")).filter((name) => name.endsWith(".ts")).sort();
  assert.deepEqual(
    names,
    ["gate.ts", "place.ts", "recheck.ts", "run.ts", "testing.ts"],
    "consumer/src holds an unexpected module",
  );
  // Nor does the gate reach the re-check: a gate that could re-propose after a fill
  // could place again on its own, and topping up is the caller's decision.
  assert.doesNotMatch(source, /from\s*["']\.\/recheck\.ts["']/, "gate.ts imports recheck.ts");
});

// RUN.TS IS THE ONLY FILE THAT WIRES A REAL SENDER.
//
// It is in the inventory above because composing the gate with the sender is its
// whole purpose. That is only safe while it stays the ONLY one, so the property is
// asserted rather than left to the reading of the list: every other module keeps
// `send` a parameter, and nothing but run.ts can reach the network by itself.
test("only run.ts can reach a venue, and only through the gate", () => {
  for (const name of ["gate.ts", "place.ts", "recheck.ts"]) {
    assert.doesNotMatch(code(here(`../src/${name}`)), /\bfetch\s*\(/, `${name} calls fetch`);
  }

  // And run.ts sends only inside the gate's callback. COUNTED, not pattern-matched:
  // the old regex was anchored to one line and three leading keywords, so the same
  // call spread across lines -- ordinary formatting, or a `prettier` pass -- slipped
  // past it while placing an order on a refusal. A count is spelling-independent.
  // THE INJECTABLE GATE IS OUT OF RUN.TS'S REACH.
  //
  // `gateWith` takes the checker as a parameter, so a caller holding it can supply one
  // that always accepts. It lived in `Policy.verifier` -- in the signature run.ts
  // itself calls -- and now lives in `testing.ts`, which the production path must not
  // import. Nor may it reach `gateWith` by any other spelling.
  const run = code(here("../src/run.ts"));
  assert.doesNotMatch(run, /["']\.\/testing\.ts["']/, "run.ts imports the test-only gate");
  assert.doesNotMatch(run, /\bgateWith\b/, "run.ts names the injectable gate");
  assert.match(run, /\bgate\s*\(/, "run.ts does not call the gate");
  const calls = run.match(/\bplace\s*\(/g) ?? [];
  assert.equal(calls.length, 1, `run.ts calls place at ${calls.length} sites, not 1`);
  // The one call is the gate's fourth argument, so the approval is on its path.
  assert.match(run, /await\s+gate\s*\([\s\S]*\bplace\s*\(/, "the place call is not inside the gate call");
});
