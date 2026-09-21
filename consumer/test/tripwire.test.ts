// The gate reaches no network and reads no clock, PROVEN BY RUNNING IT.
//
// The source greps in `gate.test.ts` are lints. They read text, so they are defeated by
// anything that does not look like what they search for -- `globalThis["fet"+"ch"]` is
// the standard example, and the audit confirmed it passes every pattern. That is fine
// for catching an accident and worthless as a proof.
//
// This installs tripwires on the globals a network call or a clock read must go
// through, drives every row of the gate table, and counts. A call is caught whatever
// its spelling, because the count is on the function that would actually run.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { parse, type Value } from "../../checker/src/canon.ts";
import { schemas, type Schemas } from "../../checker/src/doc.ts";
import { parseVenue, type VenueValue } from "../../checker/src/venue.ts";
import type { Bundle } from "../../checker/src/verify.ts";
import { type Capture, gate, type OrderEnvelope, type Place, type Policy } from "../src/gate.ts";
import { code } from "./source.ts";

const here = (path: string) => new URL(path, import.meta.url);

interface Tripped {
  readonly network: string[];
  readonly clock: string[];
}

/**
 * Run `body` with `fetch`, `Date.now`, `performance.now` and `setTimeout` instrumented.
 *
 * Restored in a `finally`, so a failing assertion cannot leave the process with a
 * patched clock and make every later test lie.
 */
async function withTripwires<T>(body: () => Promise<T>): Promise<{ value: T; tripped: Tripped }> {
  const network: string[] = [];
  const clock: string[] = [];

  const realFetch = globalThis.fetch;
  const realNow = Date.now;
  const realPerf = globalThis.performance?.now;
  const realTimeout = globalThis.setTimeout;
  const realXHR = (globalThis as Record<string, unknown>)["XMLHttpRequest"];
  const realWS = (globalThis as Record<string, unknown>)["WebSocket"];

  globalThis.fetch = (() => {
    network.push("fetch");
    throw new Error("tripwire: fetch was called");
  }) as typeof fetch;
  (globalThis as Record<string, unknown>)["XMLHttpRequest"] = function () {
    network.push("XMLHttpRequest");
    throw new Error("tripwire: XMLHttpRequest was constructed");
  };
  (globalThis as Record<string, unknown>)["WebSocket"] = function () {
    network.push("WebSocket");
    throw new Error("tripwire: WebSocket was constructed");
  };
  Date.now = () => {
    clock.push("Date.now");
    return 0;
  };
  if (globalThis.performance !== undefined) {
    globalThis.performance.now = () => {
      clock.push("performance.now");
      return 0;
    };
  }
  globalThis.setTimeout = ((handler: TimerHandler, ms?: number, ...rest: unknown[]) => {
    clock.push("setTimeout");
    return realTimeout(handler as () => void, ms, ...rest);
  }) as typeof setTimeout;

  try {
    const value = await body();
    return { value, tripped: { network, clock } };
  } finally {
    globalThis.fetch = realFetch;
    Date.now = realNow;
    if (realPerf !== undefined && globalThis.performance !== undefined) {
      globalThis.performance.now = realPerf;
    }
    globalThis.setTimeout = realTimeout;
    (globalThis as Record<string, unknown>)["XMLHttpRequest"] = realXHR;
    (globalThis as Record<string, unknown>)["WebSocket"] = realWS;
  }
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
  const allowlist = new Set<string>();
  for (const rawLeg of (parse(proposalRaw) as Record<string, Value>)["legs"] as Value[]) {
    allowlist.add((rawLeg as Record<string, Value>)["semantics_version"] as string);
  }
  return {
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

const CAPTURED_AT = 1_789_715_838_660n;
const CAPTURE: Capture = { capturedAtMs: CAPTURED_AT };

function policy(allowlist: Set<string>): Policy {
  return {
    now: CAPTURED_AT + 29_999n,
    maxAgeMs: 30_000n,
    checker: { schemas: loadSchemas(), allowlist },
  };
}

// EVERY REFUSING ROW: zero network calls, zero clock reads.
//
// The clock matters as much as the network here. `gate` takes `policy.now` as a value
// precisely so its staleness rule can be tested at the boundary; a gate that read a
// clock of its own would make that boundary untestable, and this counts the reads
// rather than grepping for the word `Date`.
test("no refusing bundle touches the network or reads a clock", async () => {
  let rows = 0;
  for (const name of everyBundle()) {
    const loaded = loadBundle(name);
    if (loaded.expects === "accept") continue;
    const calls: OrderEnvelope[] = [];
    const place: Place = async (envelope) => {
      calls.push(envelope);
      return { ok: true };
    };

    const { value: decision, tripped } = await withTripwires(() =>
      gate(loaded.bundle, policy(loaded.allowlist), CAPTURE, place)
    );

    assert.equal(decision.approved, false, `${name} was approved`);
    assert.equal(calls.length, 0, `${name} reached the downstream call`);
    assert.deepEqual(tripped.network, [], `${name} touched the network: ${tripped.network}`);
    assert.deepEqual(tripped.clock, [], `${name} read a clock: ${tripped.clock}`);
    rows += 1;
  }
  assert.ok(rows >= 12, `only ${rows} refusing bundles were driven under tripwires`);
});

// THE APPROVING ROW: exactly one place call, and still no clock of its own.
//
// The gate is handed `policy.now`; if it reads a clock anyway, the instant it tested
// staleness against is not the one the caller stated.
test("the approving bundle places once and reads only the injected clock", async () => {
  const loaded = loadBundle("good-envelope");
  const calls: OrderEnvelope[] = [];
  const place: Place = async (envelope) => {
    calls.push(envelope);
    return { ok: true };
  };

  const { value: decision, tripped } = await withTripwires(() =>
    gate(loaded.bundle, policy(loaded.allowlist), CAPTURE, place)
  );

  assert.equal(decision.approved, true, decision.approved ? "" : `${decision.reason}: ${decision.detail}`);
  assert.equal(calls.length, 1, `the approving row made ${calls.length} downstream calls`);
  assert.deepEqual(tripped.network, [], `the gate touched the network: ${tripped.network}`);
  assert.deepEqual(tripped.clock, [], `the gate read a clock: ${tripped.clock}`);
});

// THE TRIPWIRES CATCH WHAT NOTHING ELSE DOES.
//
// The argument for the harness, stated exactly. `globalThis["fet"+"ch"]()` matches none
// of the source patterns -- asserted below against those same patterns. A behavioural
// test catches it only if the call CHANGES something: a fetch to an unreachable host
// throws, the approving row fails, and the table goes red for the wrong reason.
//
// Wrap that call in `try {} catch {}` and behaviour is identical. Verified by mutation:
// a silent obfuscated fetch inserted into `gate.ts` leaves the greps AND every
// behavioural test green, and only this harness turns red -- because the count is on
// the function that runs, not on the text that spells it or the damage it happens to do.
test("an obfuscated fetch evades the greps and is caught by the tripwire", async () => {
  const obfuscated = 'await (globalThis as any)["fet"+"ch"]("https://api.hyperliquid.xyz/exchange");';

  // The grep patterns, exactly as the lint applies them.
  for (const pattern of [/\bfetch\b/, /\bXMLHttpRequest\b/, /\bWebSocket\b/, /["']node:/]) {
    assert.doesNotMatch(obfuscated, pattern, `the lint would have caught ${pattern}; pick a better example`);
  }

  // And the tripwire catches the same call when it actually runs.
  const { tripped } = await withTripwires(async () => {
    try {
      await (globalThis as unknown as Record<string, () => Promise<unknown>>)["fet" + "ch"]!();
    } catch {
      // The tripwire throws by design; the count is what is asserted.
    }
  });
  assert.deepEqual(tripped.network, ["fetch"], "the tripwire missed an obfuscated fetch");
});

// The tripwires are restored, so a later test cannot inherit a patched clock.
test("the tripwires are removed afterwards", async () => {
  const before = Date.now;
  await withTripwires(async () => {
    assert.notEqual(Date.now, before, "the clock was not instrumented at all");
  });
  assert.equal(Date.now, before, "Date.now was left patched");
  assert.equal(typeof globalThis.fetch, "function", "fetch was left patched");
  // A real clock reads a real instant.
  assert.ok(Date.now() > 1_700_000_000_000, "Date.now does not return a real instant");
});

// The greps stay, as lints. This asserts they are still applied, so relabelling them
// in ARCHITECTURE.md does not quietly become deleting them.
test("the source lints are still in place", () => {
  const gateTest = code(here("./gate.test.ts"));
  for (const expected of ["/\\bfetch\\b/", "gate.ts uses"]) {
    assert.ok(gateTest.includes(expected), `the lint text ${expected} is gone from gate.test.ts`);
  }
});
