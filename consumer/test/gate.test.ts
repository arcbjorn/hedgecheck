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
        const decision = await gate(
          bundle,
          { ...base, verifier: () => Promise.resolve({ accepted: true as const }) },
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
        const decision = await gate(
          bundle,
          { ...base, verifier: () => Promise.resolve({ accepted: true as const }) },
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
        const decision = await gate(
          bundle,
          { ...base, verifier: () => Promise.resolve({ accepted: true as const }) },
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
        const decision = await gate(
          bundle,
          { ...base, verifier: () => Promise.resolve({ accepted: true as const }) },
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
        const decision = await gate(
          bundle,
          { ...base, verifier: () => Promise.resolve({ accepted: true as const }) },
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
        const decision = await gate(
          bundle,
          { ...base, verifier: () => Promise.resolve({ accepted: true as const }) },
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
    {
      // A checker that throws, supplied as the verifier.
      //
      // It cannot be provoked from the bundle: `verify` catches its own faults and
      // returns ENGINE_DISAGREES. Corrupting the bundle to make it fall over was
      // tried and produced CHECKER_REFUSED, which is the real checker behaving
      // correctly and this row proving nothing. So the throwing checker is injected.
      name: "a checker that throws",
      run: async (place) => {
        const decision = await gate(
          good.bundle,
          { ...base, verifier: () => Promise.reject(new Error("the checker fell over")) },
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
        const decision = await gate(
          good.bundle,
          {
            ...base,
            verifier: () => {
              throw new Error("the checker fell over before starting");
            },
          },
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
  const decision = await gate(
    good.bundle,
    { ...policy(), verifier: () => Promise.reject(new Error("the checker fell over")) },
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

/** The gate never reads a clock: a policy is the only source of "now". */
test("the gate reads no clock", () => {
  const source = readFileSync(here("../src/gate.ts"), "utf8").replace(/\/\/.*$/gm, "");
  for (const pattern of [/\bDate\b/, /\bperformance\b/, /\bhrtime\b/]) {
    assert.doesNotMatch(source, pattern, `gate.ts uses ${pattern}`);
  }
});

/** The gate signs nothing and sends nothing: `place` is the only way out. */
test("the gate has no way to send an order of its own", () => {
  const source = readFileSync(here("../src/gate.ts"), "utf8").replace(/\/\/.*$/gm, "");
  for (const pattern of [/\bfetch\b/, /\bXMLHttpRequest\b/, /\bWebSocket\b/, /\bsign\w*\(/, /\bprivateKey\b/, /\bmnemonic\b/, /["']node:/]) {
    assert.doesNotMatch(source, pattern, `gate.ts uses ${pattern}`);
  }
  // Exactly one call site, so "zero downstream calls" is a property of the shape of
  // the function and not of a flag every early return has to remember to set.
  const sites = source.match(/\bplace\(/g) ?? [];
  assert.equal(sites.length, 1, `gate.ts calls place at ${sites.length} sites`);
});

/** `place` is a parameter, and this task ships only the recording fake. */
test("nothing in consumer/src knows how to place a real order", () => {
  const names = readdirSync(here("../src/")).filter((name) => name.endsWith(".ts"));
  assert.deepEqual(names, ["gate.ts"], "consumer/src holds only the gate");
});
