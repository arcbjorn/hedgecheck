// The claim "approved is unrepresentable without a check" is enforced, not asserted.
//
// `test/unrepresentable.ts` contains four ways someone might try to write an
// `Approved` without having called `gate`. This runs the type checker over it and
// fails if it SUCCEEDS. A brand that stops being nominal -- someone exports the
// symbol, or retypes the field as `symbol`, or drops it -- makes that file compile,
// and this test says so.
//
// Skipped when `deno` is not on the path, so the suite stays runnable without it;
// `make check` runs deno for the checker already, so the gate line is covered there.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));

test("an Approved cannot be written outside gate()", () => {
  const probe = spawnSync("deno", ["--version"], { encoding: "utf8" });
  if (probe.error !== undefined || probe.status !== 0) {
    return;
  }
  const run = spawnSync("deno", ["check", here("./unrepresentable.ts")], { encoding: "utf8" });
  assert.notEqual(
    run.status,
    0,
    "test/unrepresentable.ts compiled; the brand no longer makes Approved unrepresentable",
  );
  const output = `${run.stdout}${run.stderr}`;
  // Not merely "it failed": it failed for the four stated reasons. A syntax error in
  // that file would also make it fail, and would prove nothing.
  for (const expected of [
    "Property 'brand' is missing",
    "is not assignable to type 'typeof checked'",
    "is not assignable to type 'Decision'",
    "missing the following properties from type 'Approved'",
  ]) {
    assert.ok(output.includes(expected), `expected the compiler to say: ${expected}\n${output}`);
  }
});
