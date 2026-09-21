// The checker's acceptance test: accept every good bundle, refuse every corrupted
// one with exactly the class its manifest expects.
//
// A bundle's manifest states what it is. A test that assumed instead would be
// asserting its own belief about a fixture rather than the fixture's own claim.

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { canonical, digest, parse, type Value } from "../src/canon.ts";
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
 * A checker accepts a family only when the version the bundle pins is one IT was built
 * to trust, so the test states the versions each bundle pins -- read from the bundle
 * itself, never hard-coded. A checker whose allowlist lacks them is not broken: it is
 * a checker that was not told to trust that reading, which is the case the test below
 * covers.
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

// AN ALLOWLIST THAT LACKS THE PINNED VERSION IS NAMED AS SUCH.
//
// A good bundle, built against a reviewed copy, presented to a checker that was not
// told to trust that version. The checker reduces the leg under `unreviewed_family`
// and the bundle declares no such reduction, so the profile ALSO disagrees -- and the
// profile used to be the refusal reported: `PROFILE_COVERAGE at $result.profile`,
// which sends an operator hunting a broken payoff profile for a cause that is two
// steps upstream and entirely benign.
//
// The refusal must name the cause, and its detail must carry enough to act on: the
// family, the version, and the fact that this checker does not have it.
test("an unreviewed family is refused as an undeclared reduction, not a profile mismatch", async () => {
  const all = loadSchemas();
  let checked = 0;
  for (const loaded of everyBundle()) {
    if (loaded.expects !== "accept") continue;
    // A bundle already reduced for another reason is not this case: `horizon_mismatch`
    // takes priority in the rebuild, so `good-horizon` declares a reduction either way
    // and nothing disagrees. Skipping it keeps the test about the allowlist.
    const declared = parse(loaded.bundle.lowered) as Record<string, Value>;
    const rules = ((declared["reductions"] ?? []) as Value[])
      .map((entry) => (entry as Record<string, Value>)["rule"]);
    if (rules.length > 0) continue;

    // The ONLY difference from the accepting run: an empty allowlist.
    const outcome = await verify(loaded.bundle, { schemas: all, allowlist: new Set() });
    assert.equal(outcome.accepted, false, `${loaded.name} was accepted with an empty allowlist`);
    if (outcome.accepted) continue;

    assert.equal(
      outcome.refusal.class,
      "REDUCTION_UNDECLARED",
      `${loaded.name}: refused as ${outcome.refusal.class}, which points away from the allowlist`,
    );
    assert.equal(outcome.refusal.at, "$result.reductions", `${loaded.name}: refused at the wrong place`);

    // The detail is what the operator acts on, so it names all three things.
    const detail = outcome.refusal.detail;
    const proposal = parse(loaded.bundle.proposal) as Record<string, Value>;
    const leg = (proposal["legs"] as Value[])[0] as Record<string, Value>;
    assert.ok(detail.includes(leg["family"] as string), `${loaded.name}: the detail does not name the family`);
    assert.ok(
      detail.includes(leg["semantics_version"] as string),
      `${loaded.name}: the detail does not name the version`,
    );
    assert.ok(detail.includes("allowlist"), `${loaded.name}: the detail does not mention the allowlist`);
    checked += 1;
  }
  assert.ok(checked >= 2, `only ${checked} good bundles were checked against an empty allowlist`);
});

// ONLY A `computed` FAMILY HAS A TERMINAL PAYOFF TO CHECK.
//
// `bounded` means the payoff is not a function of the terminal price -- `priceTouch` is
// path-dependent, so a terminal-price kernel cannot evaluate it -- and `refused` means
// the registry has no established reading at all (PLAN section 6, "Everything else --
// Refused").
//
// Both were evaluated as if `computed`: a family the registry REFUSES produced a clean
// `passes`, with no reduction and no refusal. Both engines now refuse to lower one, so a
// bundle carrying a lowering for one did not come from an engine that agrees with this
// checker, and it is refused rather than checked.
test("a family that is not computed is refused, not evaluated", async () => {
  const all = loadSchemas();
  const directory = here("../../fixtures/bundles/");

  for (const status of ["bounded", "refused"]) {
    const loaded = loadBundle(directory, "good-envelope");
    // Rewrite the registry copy the bundle carries. The pin is over the entry WITHOUT
    // its review, so changing `status` moves the digest -- which is why the refusal
    // could arrive as a pin mismatch instead. Asserting the DETAIL below is what
    // separates the two.
    const rewritten = new Map<string, Uint8Array>();
    const versions = new Map<string, string>();
    for (const [family, raw] of loaded.bundle.registry) {
      const entry = parse(raw) as Record<string, Value>;
      const edited = { ...entry, status } as Record<string, Value>;
      rewritten.set(family, canonical(edited as Value));
      const withoutReview: Record<string, Value> = {};
      for (const [key, value] of Object.entries(edited)) {
        if (key !== "review") withoutReview[key] = value;
      }
      versions.set(family, await digest(withoutReview as Value));
    }
    // Repin the proposal at the edited entries, or the PIN check fires first and the
    // fixture proves the wrong thing -- the same reason `tools/make_refusals.py` has a
    // `repin` helper.
    const proposal = parse(loaded.bundle.proposal) as Record<string, Value>;
    const legs = (proposal["legs"] as Value[]).map((raw) => {
      const leg = raw as Record<string, Value>;
      return { ...leg, semantics_version: versions.get(leg["family"] as string) as string };
    });
    const repinned = canonical({ ...proposal, legs } as Value);

    const outcome = await verify(
      { ...loaded.bundle, proposal: repinned, registry: rewritten },
      { schemas: all, allowlist: new Set(versions.values()) },
    );

    assert.equal(outcome.accepted, false, `a ${status} family was accepted`);
    if (outcome.accepted) continue;
    assert.equal(outcome.refusal.class, "SEMANTICS_PIN", `a ${status} family gave ${outcome.refusal.class}`);
    assert.ok(
      outcome.refusal.detail.includes(status),
      `the refusal does not say the status is ${status}: ${outcome.refusal.detail}`,
    );
  }
});

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
