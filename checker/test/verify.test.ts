// The checker's acceptance test: accept every good bundle, refuse every corrupted
// one with exactly the class its manifest expects.
//
// A bundle's manifest states what it is. A test that assumed instead would be
// asserting its own belief about a fixture rather than the fixture's own claim.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { parse, type Value } from "../src/canon.ts";
import { schemas, type Schemas } from "../src/doc.ts";
import { parseVenue, type VenueValue } from "../src/venue.ts";
import { type Bundle, verify } from "../src/verify.ts";

const here = (path: string) => new URL(path, import.meta.url);

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
}

function loadBundle(directory: URL, name: string): Loaded {
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
  return {
    name,
    expects: manifest["expects"] as string,
    bundle: {
      proposal: read(files["proposal"] as string),
      lowered: read(files["lowered"] as string),
      result: read(files["result"] as string),
      manifest: manifestRaw,
      snapshots,
      registry,
    },
  };
}

function everyBundle(): Loaded[] {
  const directory = here("../../fixtures/bundles/");
  return readdirSync(directory)
    .filter((name) => !name.startsWith("."))
    .sort()
    .map((name) => loadBundle(directory, name));
}

/**
 * The allowlist for these bundles.
 *
 * The committed registry entries are DRAFTS, so a checker with an empty allowlist is
 * correct and every bundle would reduce by `unreviewed_family`. The good bundles were
 * built against reviewed copies, so the test states the versions they pin -- read
 * from the bundles themselves, not hard-coded.
 */
async function allowlistFor(loaded: Loaded): Promise<Set<string>> {
  const proposal = parse(loaded.bundle.proposal) as Record<string, Value>;
  const out = new Set<string>();
  for (const rawLeg of proposal["legs"] as Value[]) {
    const leg = rawLeg as Record<string, Value>;
    out.add(leg["semantics_version"] as string);
  }
  return out;
}

test("every good bundle is accepted", async () => {
  const all = loadSchemas();
  let accepted = 0;
  for (const loaded of everyBundle()) {
    if (loaded.expects !== "accept") continue;
    const outcome = await verify(loaded.bundle, {
      schemas: all,
      allowlist: await allowlistFor(loaded),
    });
    assert.ok(
      outcome.accepted,
      `${loaded.name} was refused: ${outcome.accepted ? "" : `${outcome.refusal.class} at ${outcome.refusal.at}: ${outcome.refusal.detail}`}`,
    );
    accepted += 1;
  }
  assert.ok(accepted >= 2, `only ${accepted} good bundles were checked`);
});

test("every corrupted bundle is refused with its stated class", async () => {
  const all = loadSchemas();
  const wrong: string[] = [];
  let refused = 0;
  for (const loaded of everyBundle()) {
    if (loaded.expects === "accept") continue;
    const outcome = await verify(loaded.bundle, {
      schemas: all,
      allowlist: await allowlistFor(loaded),
    });
    if (outcome.accepted) {
      wrong.push(`${loaded.name}: ACCEPTED, expected ${loaded.expects}`);
      continue;
    }
    if (outcome.refusal.class !== loaded.expects) {
      wrong.push(
        `${loaded.name}: refused ${outcome.refusal.class}, expected ${loaded.expects} ` +
          `(${outcome.refusal.at}: ${outcome.refusal.detail})`,
      );
      continue;
    }
    refused += 1;
  }
  assert.deepEqual(wrong, [], `${wrong.length} bundles refused with the wrong class`);
  assert.ok(refused >= 10, `only ${refused} corrupted bundles were checked`);
});

test("the checker never returns accept for a bundle it cannot read", async () => {
  const all = loadSchemas();
  const [first] = everyBundle();
  assert.ok(first !== undefined);
  const broken: Bundle = { ...first.bundle, result: new TextEncoder().encode("{") };
  const outcome = await verify(broken, { schemas: all });
  assert.equal(outcome.accepted, false, "an unreadable result was accepted");
});

// Bundles the GO CLI builds are accepted.
//
// The committed bundles were generated once; these are built by the engine now, from
// the replay proposals, with `--reviewed`. Accepting them is the cross-implementation
// claim: the engine wrote a result and an independent checker re-derived it from the
// proposal and the snapshots alone.
//
// Skipped when the directory is absent, so `make check` stays offline and needs no
// build step; the T3 gate runs it explicitly.
test("bundles the Go CLI builds are accepted", async () => {
  const root = process.env["HEDGECHECK_CLI_BUNDLES"];
  if (root === undefined) {
    return;
  }
  const all = loadSchemas();
  let accepted = 0;
  for (const name of readdirSync(root).sort()) {
    const loaded = loadBundle(new URL(`file://${root}/`), name);
    const outcome = await verify(loaded.bundle, {
      schemas: all,
      allowlist: await allowlistFor(loaded),
    });
    assert.ok(
      outcome.accepted,
      `${name} was refused: ${outcome.accepted ? "" : `${outcome.refusal.class} at ${outcome.refusal.at}: ${outcome.refusal.detail}`}`,
    );
    accepted += 1;
  }
  assert.ok(accepted >= 3, `only ${accepted} CLI bundles were checked`);
});
