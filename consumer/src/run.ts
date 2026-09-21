// The one command the owner runs by hand.
//
//   node --experimental-strip-types consumer/src/run.ts --bundle DIR --network testnet
//
// It reads a bundle from disk, runs the gate, and places the envelope's order only
// if the gate approves. Adding --dry-run does everything except send.
//
// THIS IS THE ONLY FILE THAT WIRES A REAL SENDER. Everywhere else `place` and `send`
// are parameters, so the tests cannot reach a venue even by mistake.

import { readdirSync, readFileSync } from "node:fs";
import { argv, env, exit, stdout } from "node:process";

import { parse, type Value } from "../../checker/src/canon.ts";
import { schemas, type Schemas } from "../../checker/src/doc.ts";
import { parseVenue, type VenueValue } from "../../checker/src/venue.ts";
import type { Bundle } from "../../checker/src/verify.ts";
import { gate, type OrderEnvelope } from "./gate.ts";
import { Exchanges, type Network, place } from "./place.ts";

function flag(name: string): string | undefined {
  const at = argv.indexOf(`--${name}`);
  return at < 0 ? undefined : argv[at + 1];
}

function has(name: string): boolean {
  return argv.includes(`--${name}`);
}

/** A bundle directory, read as the checker wants it. */
function loadBundle(directory: string): Bundle {
  const read = (file: string) => new Uint8Array(readFileSync(`${directory}/${file}`));
  const manifest = parse(read("manifest.json")) as Record<string, Value>;
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
    proposal: read(files["proposal"] as string),
    lowered: read(files["lowered"] as string),
    result: read(files["result"] as string),
    manifest: read("manifest.json"),
    snapshots,
    registry,
  };
}

/**
 * The schemas, so the document checks actually run.
 *
 * Omitting them makes `verify` skip those checks, which would be the gate approving
 * on a weaker question than the one it reports having asked.
 */
function loadSchemas(): Schemas {
  const directory = new URL("../../schema/", import.meta.url);
  const files = new Map<string, VenueValue>();
  for (const name of readdirSync(directory)) {
    if (name.endsWith(".json")) {
      files.set(name, parseVenue(new Uint8Array(readFileSync(new URL(name, directory)))));
    }
  }
  return schemas(files);
}

/** The allowlist the checker trusts, from the build. */
function allowlist(): Set<string> {
  try {
    const raw = readFileSync(new URL("../../checker/dist/allowlist.json", import.meta.url), "utf8");
    return new Set(JSON.parse(raw).reviewed as string[]);
  } catch {
    return new Set();
  }
}

async function main(): Promise<number> {
  const directory = flag("bundle");
  const network = (flag("network") ?? "testnet") as Network;
  const dryRun = has("dry-run");

  if (directory === undefined) {
    stdout.write("usage: run.ts --bundle DIR [--network testnet|mainnet] [--dry-run]\n");
    return 2;
  }
  if (Exchanges[network] === undefined) {
    stdout.write(`network ${network} is not one of mainnet, testnet\n`);
    return 2;
  }
  if (network === "mainnet") {
    // A deliberate stop. The runbook is a testnet procedure, and reaching mainnet
    // should take more than a flag typed in a hurry.
    stdout.write("mainnet is not run from this script. See consumer/RUNBOOK.md.\n");
    return 2;
  }

  // WHEN THE CAPTURE HAPPENED IS THE OPERATOR'S STATEMENT, not the bundle's. The
  // bundle records a skew, never an instant, so there is nothing here to re-derive it
  // from. Default: the operator captured just now, which is the runbook's procedure.
  const capturedText = flag("captured-at");
  const capturedAtMs = capturedText === undefined ? BigInt(Date.now()) : BigInt(capturedText);

  // The clock is read ONCE, here, and injected. Nothing downstream reads it.
  const now = BigInt(Date.now());

  const bundle = loadBundle(directory);
  const sent: OrderEnvelope[] = [];
  const decision = await gate(
    bundle,
    { now, maxAgeMs: 15n * 60n * 1000n, checker: { schemas: loadSchemas(), allowlist: allowlist() } },
    { capturedAtMs },
    async (envelope) => {
      sent.push(envelope);
      if (dryRun) {
        stdout.write(`DRY RUN, nothing sent: ${JSON.stringify(envelope)}\n`);
        return { status: 0, body: "" };
      }
      return await place(envelope, {
        network,
        env,
        nonceMs: BigInt(Date.now()),
        send: async (url, body) => {
          const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body,
          });
          return { status: response.status, body: await response.text() };
        },
      });
    },
  );

  if (!decision.approved) {
    stdout.write(`REFUSED ${decision.reason}: ${decision.detail}\n`);
    stdout.write(`orders sent: ${sent.length}\n`);
    return 1;
  }
  stdout.write(`APPROVED ${JSON.stringify(decision.envelope)}\n`);
  stdout.write(`venue answered: ${JSON.stringify(decision.placed)}\n`);
  return 0;
}

const code = await main();
exit(code);
