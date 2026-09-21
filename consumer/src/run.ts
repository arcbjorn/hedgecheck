// The one command the owner runs by hand.
//
//   node --experimental-strip-types consumer/src/run.ts --bundle DIR --network testnet
//
// It reads a bundle from disk, runs the gate, and places the envelope's order only if
// the gate approves AND --send was asked for.
//
// SENDING IS OPT-IN. Without --send this is a rehearsal. A flag that goes missing
// leaves the run harmless rather than armed, which is the only safe direction for a
// default when the cost of being wrong is a live order.
//
// THIS IS THE ONLY FILE THAT WIRES A REAL SENDER. Everywhere else `place` and `send`
// are parameters, so the tests cannot reach a venue even by mistake.

import { readdirSync, readFileSync, realpathSync } from "node:fs";
import { resolve, sep } from "node:path";
import { argv, env, exit, stdout } from "node:process";

import { parse, type Value } from "../../checker/src/canon.ts";
import { schemas, type Schemas } from "../../checker/src/doc.ts";
import { parseVenue, type VenueValue } from "../../checker/src/venue.ts";
import type { Bundle } from "../../checker/src/verify.ts";
import { gate, type OrderEnvelope } from "./gate.ts";
import { Exchanges, isNetwork, type Network, place } from "./place.ts";

class UsageError extends Error {}

/** Every argument this script understands. Anything else is a usage error. */
const VALUED = new Set(["bundle", "network", "captured-at"]);
const BARE = new Set(["send", "dry-run", "help"]);

const USAGE =
  "usage: run.ts --bundle DIR [--network testnet] [--captured-at MS] [--send]\n" +
  "  Without --send this is a rehearsal: the gate runs and nothing is sent.\n";

interface Args {
  readonly valued: ReadonlyMap<string, string>;
  readonly bare: ReadonlySet<string>;
}

/**
 * Parse the command line, REJECTING anything unrecognised.
 *
 * The audit found that `--dry-run=true`, `--dryrun` and `-dry-run` were all silently
 * ignored, so a mistyped safety flag armed a live send with no warning at all. An
 * unknown token is now a usage error: a command line that is not understood is not
 * run. Duplicates are refused too -- the operator's intent is ambiguous, and guessing
 * at it is how the last thing typed stops being the thing that governs.
 */
function parseArgs(tokens: readonly string[]): Args {
  const valued = new Map<string, string>();
  const bare = new Set<string>();

  for (let at = 0; at < tokens.length; at += 1) {
    const token = tokens[at] as string;
    if (!token.startsWith("--")) throw new UsageError(`unexpected argument ${JSON.stringify(token)}`);

    const name = token.slice(2);
    if (name.includes("=")) {
      // `--dry-run=true` is the shape that armed a live send, so it is named exactly
      // rather than lumped in with unknown arguments.
      const base = name.slice(0, name.indexOf("="));
      throw new UsageError(
        BARE.has(base)
          ? `--${base} takes no value; write ${JSON.stringify(`--${base}`)}, not ${JSON.stringify(token)}`
          : VALUED.has(base)
          ? `write ${JSON.stringify(`--${base} VALUE`)}, not ${JSON.stringify(token)}`
          : `unknown argument ${JSON.stringify(token)}`,
      );
    }
    if (BARE.has(name)) {
      if (bare.has(name)) throw new UsageError(`--${name} given more than once`);
      bare.add(name);
      continue;
    }
    if (!VALUED.has(name)) throw new UsageError(`unknown argument ${JSON.stringify(token)}`);
    if (valued.has(name)) throw new UsageError(`--${name} given more than once`);

    const value = tokens[at + 1];
    // A flag cannot be another flag's value: `--captured-at --send` used to make the
    // capture instant the literal string "--send" and crash inside BigInt.
    if (value === undefined || value.startsWith("--")) {
      throw new UsageError(`--${name} needs a value`);
    }
    valued.set(name, value);
    at += 1;
  }
  return { valued, bare };
}

/** A whole number of milliseconds, checked before `BigInt` is asked to convert it. */
function instant(text: string, what: string): bigint {
  if (!/^[0-9]+$/.test(text)) {
    throw new UsageError(`${what} must be whole milliseconds since the epoch, not ${JSON.stringify(text)}`);
  }
  return BigInt(text);
}

/**
 * A bundle directory, read as the checker wants it.
 *
 * Every path comes from the manifest, so every path is CONTAINED to the bundle
 * directory before it is opened. A manifest naming `../../../../etc/hosts` used to be
 * read, and the refusal then quoted that file's content back -- a read oracle. A
 * bundle is the unit of evidence this tool is built to hand to someone else, so its
 * own path strings are not trusted.
 */
function loadBundle(directory: string): Bundle {
  const root = realpathSync(resolve(directory));
  const read = (file: string): Uint8Array => {
    if (typeof file !== "string") throw new UsageError("a manifest path is not a string");
    const full = resolve(root, file);
    if (full !== root && !full.startsWith(root + sep)) {
      throw new UsageError(`manifest path ${JSON.stringify(file)} leaves the bundle directory`);
    }
    // realpath after resolve, so a symlink cannot step outside either.
    const real = realpathSync(full);
    if (real !== root && !real.startsWith(root + sep)) {
      throw new UsageError(`manifest path ${JSON.stringify(file)} resolves outside the bundle directory`);
    }
    return new Uint8Array(readFileSync(real));
  };

  const manifestBytes = read("manifest.json");
  const manifest = parse(manifestBytes) as Record<string, Value>;
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
    manifest: manifestBytes,
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

/**
 * The POST the venue actually receives.
 *
 * `redirect: "manual"` because fetch's default follows 307 and 308 by RE-SENDING the
 * body -- a second signed order from one `place`, which is exactly what the send-once
 * rule exists to prevent. For a request that may already have executed, a redirect is
 * indistinguishable from a retry, so the transport does not get to decide.
 */
async function post(url: string, body: string): Promise<{ status: number; body: string }> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    redirect: "manual",
  });
  if (response.status >= 300 && response.status < 400) {
    throw new Error(`the venue answered ${response.status}; the order was sent once and is not re-sent`);
  }
  return { status: response.status, body: await response.text() };
}

async function main(): Promise<number> {
  let args: Args;
  try {
    args = parseArgs(argv.slice(2));
  } catch (error) {
    stdout.write(`${error instanceof Error ? error.message : String(error)}\n${USAGE}`);
    return 2;
  }
  if (args.bare.has("help")) {
    stdout.write(USAGE);
    return 2;
  }

  const directory = args.valued.get("bundle");
  const networkText = args.valued.get("network") ?? "testnet";
  // `--dry-run` is still accepted and still means a rehearsal; it is now the default,
  // so it is kept only so an operator's habit does not become a usage error.
  const send = args.bare.has("send") && !args.bare.has("dry-run");

  if (directory === undefined) {
    stdout.write(`--bundle is required\n${USAGE}`);
    return 2;
  }
  // Own-property membership: `Exchanges["constructor"]` is not undefined, so an index
  // test used to let prototype names through to a signed order.
  if (!isNetwork(networkText)) {
    stdout.write(`network ${JSON.stringify(networkText)} is not one of mainnet, testnet\n`);
    return 2;
  }
  const network: Network = networkText;
  if (network === "mainnet") {
    // A deliberate stop. The runbook is a testnet procedure, and reaching mainnet
    // should take more than a flag typed in a hurry.
    stdout.write("mainnet is not run from this script. See consumer/RUNBOOK.md.\n");
    return 2;
  }

  // THE MODE IS STATED BEFORE THE GATE RUNS, on every run including refusals. The
  // audit found the rehearsal notice printed only inside the gate's callback, so a
  // mistyped flag looked identical on a refusal and only bit on the first approval.
  stdout.write(send ? "mode: LIVE SEND\n" : "mode: REHEARSAL, nothing will be sent\n");

  let bundle: Bundle;
  let capturedAtMs: bigint;
  try {
    // WHEN THE CAPTURE HAPPENED IS THE OPERATOR'S STATEMENT, not the bundle's. The
    // bundle records a skew, never an instant, so there is nothing here to re-derive
    // it from. Default: captured just now, which is the runbook's procedure.
    const capturedText = args.valued.get("captured-at");
    capturedAtMs = capturedText === undefined ? BigInt(Date.now()) : instant(capturedText, "--captured-at");
    bundle = loadBundle(directory);
  } catch (error) {
    // A fault BEFORE the gate. Reported in the same shape as a refusal, with its own
    // exit code, so "nothing was sent" is stated rather than left to be inferred from
    // a stack trace.
    stdout.write(`FAILED BEFORE THE GATE: ${error instanceof Error ? error.message : String(error)}\n`);
    stdout.write("orders sent: 0\n");
    return 3;
  }

  const sent: OrderEnvelope[] = [];
  let decision;
  try {
    decision = await gate(
      bundle,
      { now: BigInt(Date.now()), maxAgeMs: 15n * 60n * 1000n, checker: { schemas: loadSchemas(), allowlist: allowlist() } },
      { capturedAtMs },
      async (envelope) => {
        sent.push(envelope);
        if (!send) {
          stdout.write(`REHEARSAL, nothing sent: ${JSON.stringify(envelope)}\n`);
          return { status: 0, body: "" };
        }
        return await place(envelope, { network, env, nonceMs: BigInt(Date.now()), send: post });
      },
    );
  } catch (error) {
    // The gate is meant to return a Decision rather than throw, and the send is the
    // one thing under it that can. `sent.length` is the honest answer to the only
    // question that matters here, so it is printed rather than guessed at.
    stdout.write(`FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    stdout.write(`orders sent: ${sent.length}\n`);
    return 4;
  }

  if (!decision.approved) {
    stdout.write(`REFUSED ${decision.reason}: ${decision.detail}\n`);
    stdout.write(`orders sent: ${sent.length}\n`);
    return 1;
  }
  stdout.write(`APPROVED ${JSON.stringify(decision.envelope)}\n`);
  stdout.write(`venue answered: ${JSON.stringify(decision.placed)}\n`);
  stdout.write(`orders sent: ${send ? sent.length : 0}\n`);
  return 0;
}

const code = await main();
exit(code);
