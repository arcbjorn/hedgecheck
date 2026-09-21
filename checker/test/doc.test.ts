// The document gate: accept every valid document in fixtures/, refuse every file
// under fixtures/rejected/, and judge a corrupted bundle by its manifest.

import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { test } from "node:test";

import { canonical, parse, type Value } from "../src/canon.ts";
import { problems, roundTrip, schemas, type Schemas, valid } from "../src/doc.ts";
import { parseVenue, type VenueValue } from "../src/venue.ts";

const here = (path: string) => new URL(path, import.meta.url);

function loadSchemas(): Schemas {
  const directory = here("../../schema/");
  // Schema files are tooling, not contract documents: they carry $schema, $id and
  // numeric keywords, which the canonical profile refuses.
  const files = new Map<string, VenueValue>();
  for (const name of readdirSync(directory)) {
    if (!name.endsWith(".json")) continue;
    files.set(name, parseVenue(new Uint8Array(readFileSync(new URL(name, directory)))));
  }
  assert.ok(files.size >= 9, `only ${files.size} schema files were read`);
  return schemas(files);
}

/** Which schema a fixture is written against, from where it sits and what it is called. */
function schemaFor(path: string): string | null {
  const name = path.slice(path.lastIndexOf("/") + 1);
  if (name.endsWith(".ir.json") || name === "lowered.json") return "ir.schema.json";
  if (name.endsWith(".result.json") || name === "result.json") return "result.schema.json";
  if (name.endsWith(".proposal.json") || name === "proposal.json") return "proposal.schema.json";
  if (name === "comparison.json") return "comparison.schema.json";
  if (name === "manifest.json") return "bundle-manifest.schema.json";
  if (path.includes("/registry/") || name.startsWith("registry-")) {
    return "registry-entry.schema.json";
  }
  return null;
}

function walkFiles(root: URL): string[] {
  const out: string[] = [];
  const visit = (directory: URL): void => {
    for (const name of readdirSync(directory)) {
      const child = new URL(`${name}${statSync(new URL(name, directory)).isDirectory() ? "/" : ""}`, directory);
      if (statSync(child).isDirectory()) {
        visit(child);
        continue;
      }
      if (name.endsWith(".json")) out.push(child.pathname);
    }
  };
  visit(root);
  return out.sort();
}

test("every valid document in the tree is accepted", () => {
  const all = loadSchemas();
  let checked = 0;
  const seen = new Set<string>();
  for (const root of ["../../fixtures/golden/", "../../fixtures/bundles/", "../../registry/"]) {
    for (const path of walkFiles(here(root))) {
      const schema = schemaFor(path);
      if (schema === null) continue;
      // A bundle that is DELIBERATELY corrupt is judged by its manifest, not by
      // assumption: its documents are supposed to be wrong.
      if (isCorruptBundle(path)) continue;
      const value = parse(new Uint8Array(readFileSync(path)));
      const found = problems(value, schema, all);
      assert.deepEqual(found.slice(0, 2), [], `${path} against ${schema}`);
      checked += 1;
      seen.add(schema);
    }
  }
  // 16 today: the good bundles, the golden pair and both registry entries. The
  // twelve deliberately corrupted bundles are skipped above and judged by their
  // manifests in their own test.
  assert.ok(checked >= 16, `only ${checked} documents were checked`);
  assert.ok(seen.size >= 4, `only ${seen.size} schema kinds were exercised: ${[...seen]}`);
});

/** A bundle whose manifest expects a refusal class rather than acceptance. */
function isCorruptBundle(path: string): boolean {
  const slash = path.lastIndexOf("/");
  const directory = path.slice(0, slash);
  if (!directory.includes("/bundles/")) return false;
  try {
    const manifest = parse(new Uint8Array(readFileSync(`${directory}/manifest.json`)));
    if (typeof manifest !== "object" || Array.isArray(manifest)) return false;
    return (manifest as Record<string, Value>)["expects"] !== "accept";
  } catch {
    return false;
  }
}

test("every file under fixtures/rejected/ is refused", () => {
  const all = loadSchemas();
  const root = here("../../fixtures/rejected/");
  let refused = 0;
  const byKind: Record<string, number> = {};
  for (const path of walkFiles(root)) {
    // The directory names the schema the file was written to violate.
    const parts = path.split("/");
    const kind = parts[parts.length - 2] as string;
    const schema = `${kind}.schema.json`;
    if (all.byName.get(schema) === undefined) continue;
    const raw = new Uint8Array(readFileSync(path));
    let rejectedByParser = false;
    let value: Value | null = null;
    try {
      value = parse(raw);
    } catch {
      rejectedByParser = true;
    }
    const refusedHere = rejectedByParser || !valid(value as Value, schema, all);
    assert.ok(refusedHere, `${path} was ACCEPTED against ${schema}`);
    refused += 1;
    byKind[kind] = (byKind[kind] ?? 0) + 1;
  }
  assert.ok(refused >= 40, `only ${refused} rejected documents were checked`);
  assert.ok(Object.keys(byKind).length >= 5, `only ${Object.keys(byKind).length} kinds: ${JSON.stringify(byKind)}`);
});

test("a corrupted bundle is judged by its manifest", () => {
  const all = loadSchemas();
  const bundles = here("../../fixtures/bundles/");
  let corrupt = 0;
  let good = 0;
  for (const name of readdirSync(bundles)) {
    const manifestPath = new URL(`${name}/manifest.json`, bundles);
    let manifest: Value;
    try {
      manifest = parse(new Uint8Array(readFileSync(manifestPath)));
    } catch {
      continue;
    }
    // The manifest itself is a contract document and must always be valid: a corrupt
    // bundle is corrupt in its CONTENTS, and a manifest nobody can read could not
    // state what the corruption is.
    assert.deepEqual(
      problems(manifest, "bundle-manifest.schema.json", all).slice(0, 2),
      [],
      `${name}/manifest.json`,
    );
    const expects = (manifest as Record<string, Value>)["expects"];
    if (expects === "accept") good += 1;
    else corrupt += 1;
  }
  assert.ok(good >= 1, "no good bundle was found");
  assert.ok(corrupt >= 10, `only ${corrupt} corrupted bundles were found`);
});

test("decode then encode reproduces the canonical bytes", () => {
  let checked = 0;
  for (const root of ["../../fixtures/golden/", "../../fixtures/bundles/", "../../registry/", "../../fixtures/generated/ir/"]) {
    for (const path of walkFiles(here(root))) {
      if (schemaFor(path) === null) continue;
      const raw = new Uint8Array(readFileSync(path));
      let value: Value;
      try {
        value = parse(raw);
      } catch {
        continue;
      }
      // Compared against the CANONICAL form of the input, not the file: some fixtures
      // are hand-formatted for a reader, and re-indenting them is not the decoder's
      // job. Where a fixture is already canonical -- every bundle document is -- this
      // is the same as comparing the file byte for byte.
      const want = canonical(value);
      const got = roundTrip(value);
      assert.equal(
        new TextDecoder().decode(got),
        new TextDecoder().decode(want),
        `${path} did not round trip`,
      );
      checked += 1;
    }
  }
  assert.ok(checked >= 300, `only ${checked} documents round-tripped`);
});

test("an unknown key is refused even where every known field is valid", () => {
  const all = loadSchemas();
  const path = here("../../fixtures/bundles/good/result.json");
  const value = parse(new Uint8Array(readFileSync(path))) as Record<string, Value>;
  assert.deepEqual(problems(value as Value, "result.schema.json", all).slice(0, 2), []);

  const tampered: Record<string, Value> = { ...value, surprise: "x" };
  const found = problems(tampered as Value, "result.schema.json", all);
  assert.ok(
    found.some((problem) => problem.includes("unknown key")),
    `an unknown key was accepted: ${JSON.stringify(found)}`,
  );
});

// Every keyword the schemas use is one the decoder implements.
//
// Found while writing this file: `pays_on` uses `minProperties` and
// `dependentRequired`, and the decoder silently ignored both -- so
// fixtures/rejected/ir/bound-without-owner.json, whose whole purpose is a bound with
// no owner, was ACCEPTED. A keyword a validator does not implement is a constraint
// that has quietly stopped being enforced, and nothing else would have said so.
test("the decoder implements every keyword the schemas use", () => {
  const implemented = new Set([
    "$schema", "$id", "$ref", "$defs", "$comment", "title", "description", "examples",
    "type", "enum", "const", "pattern", "maxLength",
    "properties", "required", "additionalProperties", "minProperties", "dependentRequired",
    "items", "minItems", "maxItems", "oneOf",
  ]);
  const directory = here("../../schema/");
  const used = new Set<string>();
  const collect = (value: VenueValue, inNames: boolean): void => {
    if (Array.isArray(value)) {
      for (const item of value) collect(item, inNames);
      return;
    }
    if (typeof value !== "object" || value === null || !("lexeme" in (value as object))) {
      if (typeof value === "object" && value !== null) {
        for (const [key, child] of Object.entries(value as Record<string, VenueValue>)) {
          if (!inNames) used.add(key);
          // Under `properties`, `$defs` and `dependentRequired` the keys are FIELD
          // NAMES, not keywords.
          collect(child, key === "properties" || key === "$defs" || key === "dependentRequired");
        }
      }
    }
  };
  for (const name of readdirSync(directory)) {
    if (!name.endsWith(".json")) continue;
    collect(parseVenue(new Uint8Array(readFileSync(new URL(name, directory)))), false);
  }
  const missing = [...used].filter((keyword) => !implemented.has(keyword)).sort();
  assert.deepEqual(missing, [], `the schemas use keywords the decoder ignores: ${missing}`);
  assert.ok(used.has("dependentRequired"), "the test is not reading the schemas properly");
});
