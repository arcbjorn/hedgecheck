// An envelope becomes one venue order action, signed and sent.
//
// THE KEY COMES FROM THE ENVIRONMENT AND NOWHERE ELSE. It is read once, used once,
// and never returned, logged or stored. Nothing in this file prints a payload, and
// `consumer/test/no-key-leak.test.ts` greps the whole directory for another source.

import { secp256k1 } from "@noble/curves/secp256k1";
import { keccak_256 } from "@noble/hashes/sha3";

import type { OrderEnvelope } from "./gate.ts";

/** The variable the agent key is read from, and the only one. */
export const KEY_VARIABLE = "HEDGECHECK_AGENT_KEY";

export class PlaceError extends Error {}

/** Where an order goes. Two constants; an arbitrary URL stays impossible. */
export const Exchanges = {
  mainnet: "https://api.hyperliquid.xyz/exchange",
  testnet: "https://api.hyperliquid-testnet.xyz/exchange",
} as const;

export type Network = keyof typeof Exchanges;

/** What the venue answered, as bytes plus the status. Nothing is interpreted here. */
export interface Placed {
  readonly status: number;
  readonly body: string;
  readonly action: OrderAction;
}

/** One limit order in the venue's own shape. */
export interface OrderAction {
  readonly type: "order";
  readonly orders: readonly {
    readonly a: number;
    readonly b: boolean;
    readonly p: string;
    readonly s: string;
    readonly r: boolean;
    readonly t: { readonly limit: { readonly tif: "Ioc" } };
  }[];
  readonly grouping: "na";
}

/**
 * The asset id for an outcome coin.
 *
 * EVIDENCE section 4, verified: the encoding is `10*outcome + side`, a coin is
 * `#<encoding>`, and the asset id is `100,000,000 + encoding`. The coin already
 * carries the encoding, so the side is not re-derived here -- deriving it twice is
 * two chances to disagree about which instrument an order is for.
 */
export function assetId(coin: string): number {
  if (!/^#[0-9]{1,12}$/.test(coin)) {
    throw new PlaceError(`${JSON.stringify(coin)} is not an outcome coin`);
  }
  const encoding = Number(coin.slice(1));
  if (!Number.isSafeInteger(encoding)) {
    throw new PlaceError(`${coin} does not encode a safe integer`);
  }
  return 100_000_000 + encoding;
}

/**
 * The order action an envelope describes.
 *
 * Every field comes from the envelope. Nothing is defaulted, rounded or inferred:
 * the envelope is the statement of which order the cost bound is about, so an order
 * that differs from it in any field is an order the bound does not cover.
 */
export function actionFor(envelope: OrderEnvelope): OrderAction {
  if (envelope.side !== "buy") {
    throw new PlaceError(`side is ${JSON.stringify(envelope.side)}, and only buy is issued`);
  }
  if (envelope.time_in_force !== "Ioc") {
    throw new PlaceError(`time in force is ${JSON.stringify(envelope.time_in_force)}, not Ioc`);
  }
  return {
    type: "order",
    orders: [{
      a: assetId(envelope.coin),
      b: true,
      p: envelope.limit_price,
      s: envelope.size,
      r: false,
      t: { limit: { tif: "Ioc" } },
    }],
    grouping: "na",
  };
}

// ---------------------------------------------------------------- signing

/**
 * The action hash the venue signs over: msgpack of the action, the nonce, and the
 * vault address, then keccak-256.
 */
export function actionHash(action: OrderAction, nonce: bigint, vault: string | null): Uint8Array {
  const parts: Uint8Array[] = [msgpack(action), be64(nonce)];
  if (vault === null) {
    parts.push(Uint8Array.from([0x00]));
  } else {
    parts.push(Uint8Array.from([0x01]), hexBytes(vault));
  }
  return keccak_256(concat(parts));
}

/** The EIP-712 digest for a Hyperliquid agent signature. */
export function signingDigest(
  action: OrderAction,
  nonce: bigint,
  vault: string | null,
  network: Network,
): Uint8Array {
  const connection = actionHash(action, nonce, vault);
  const domain = eip712Domain();
  const message = keccak_256(concat([
    keccak_256(utf8("Agent(string source,bytes32 connectionId)")),
    keccak_256(utf8(network === "mainnet" ? "a" : "b")),
    connection,
  ]));
  return keccak_256(concat([Uint8Array.from([0x19, 0x01]), domain, message]));
}

function eip712Domain(): Uint8Array {
  // name "Exchange", version "1", chainId 1337, no verifying contract.
  return keccak_256(concat([
    keccak_256(utf8("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")),
    keccak_256(utf8("Exchange")),
    keccak_256(utf8("1")),
    be256(1337n),
    new Uint8Array(32),
  ]));
}

/** The signature, as the venue's JSON wants it. Never returns or logs the key. */
export function sign(digest: Uint8Array, key: Uint8Array): { r: string; s: string; v: number } {
  const signature = secp256k1.sign(digest, key, { prehash: false });
  return {
    r: `0x${signature.r.toString(16).padStart(64, "0")}`,
    s: `0x${signature.s.toString(16).padStart(64, "0")}`,
    v: 27 + signature.recovery,
  };
}

/**
 * The key, from the environment and nowhere else.
 *
 * Read through an injected `env` so a test can drive it without ever putting a real
 * key anywhere. The bytes are returned to one caller, which uses them once; nothing
 * caches them, and no error message contains them.
 */
export function agentKey(env: Record<string, string | undefined>): Uint8Array {
  const raw = env[KEY_VARIABLE];
  if (raw === undefined || raw === "") {
    throw new PlaceError(`${KEY_VARIABLE} is not set`);
  }
  const hex = raw.startsWith("0x") ? raw.slice(2) : raw;
  if (!/^[0-9a-fA-F]{64}$/.test(hex)) {
    // The value is NOT in the message. A malformed key is still a key.
    throw new PlaceError(`${KEY_VARIABLE} is not 32 bytes of hex`);
  }
  return hexBytes(`0x${hex}`);
}

// ---------------------------------------------------------------- sending

export interface PlaceOptions {
  readonly network: Network;
  readonly env: Record<string, string | undefined>;
  readonly nonceMs: bigint;
  readonly vault?: string | null;
  /** Injected, so a test drives a fake exchange and never a real one. */
  readonly send: (url: string, body: string) => Promise<{ status: number; body: string }>;
}

/**
 * Sign the envelope's order and send it once.
 *
 * ONCE. There is no retry here: an `Ioc` order that timed out may still have filled,
 * and a second send would be a second order. Recovery is the operator's, from the
 * runbook, after reading what actually filled.
 */
export async function place(envelope: OrderEnvelope, options: PlaceOptions): Promise<Placed> {
  const action = actionFor(envelope);
  const vault = options.vault ?? null;
  const digest = signingDigest(action, options.nonceMs, vault, options.network);
  const signature = sign(digest, agentKey(options.env));
  const body = JSON.stringify({
    action,
    nonce: Number(options.nonceMs),
    signature,
    vaultAddress: vault,
  });
  const response = await options.send(Exchanges[options.network], body);
  return { status: response.status, body: response.body, action };
}

// ---------------------------------------------------------------- encoding

function utf8(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

function concat(parts: readonly Uint8Array[]): Uint8Array {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

function hexBytes(hex: string): Uint8Array {
  const body = hex.startsWith("0x") ? hex.slice(2) : hex;
  const out = new Uint8Array(body.length / 2);
  for (let index = 0; index < out.length; index += 1) {
    out[index] = Number.parseInt(body.slice(index * 2, index * 2 + 2), 16);
  }
  return out;
}

function be64(value: bigint): Uint8Array {
  const out = new Uint8Array(8);
  for (let index = 7; index >= 0; index -= 1) {
    out[index] = Number(value & 0xffn);
    value >>= 8n;
  }
  return out;
}

function be256(value: bigint): Uint8Array {
  const out = new Uint8Array(32);
  for (let index = 31; index >= 0; index -= 1) {
    out[index] = Number(value & 0xffn);
    value >>= 8n;
  }
  return out;
}

/**
 * The msgpack subset the action needs: maps, arrays, strings, small ints, booleans.
 *
 * Written here rather than taken from a library because the alternative is another
 * dependency on the signing path, and the shapes this encodes are fixed by
 * `actionFor` above. Key order follows insertion order, which is what the venue
 * hashes.
 */
export function msgpack(value: unknown): Uint8Array {
  if (typeof value === "string") {
    const bytes = utf8(value);
    if (bytes.length < 32) return concat([Uint8Array.from([0xa0 | bytes.length]), bytes]);
    if (bytes.length < 256) return concat([Uint8Array.from([0xd9, bytes.length]), bytes]);
    return concat([Uint8Array.from([0xda, bytes.length >> 8, bytes.length & 0xff]), bytes]);
  }
  if (typeof value === "boolean") return Uint8Array.from([value ? 0xc3 : 0xc2]);
  if (value === null) return Uint8Array.from([0xc0]);
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || value < 0) {
      throw new PlaceError(`msgpack: ${value} is not a nonnegative safe integer`);
    }
    if (value < 128) return Uint8Array.from([value]);
    if (value < 256) return Uint8Array.from([0xcc, value]);
    if (value < 65536) return Uint8Array.from([0xcd, value >> 8, value & 0xff]);
    return Uint8Array.from([
      0xce, (value >>> 24) & 0xff, (value >>> 16) & 0xff, (value >>> 8) & 0xff, value & 0xff,
    ]);
  }
  if (Array.isArray(value)) {
    if (value.length >= 16) throw new PlaceError("msgpack: array too long for this subset");
    return concat([Uint8Array.from([0x90 | value.length]), ...value.map(msgpack)]);
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length >= 16) throw new PlaceError("msgpack: map too large for this subset");
    const parts: Uint8Array[] = [Uint8Array.from([0x80 | entries.length])];
    for (const [key, item] of entries) {
      parts.push(msgpack(key), msgpack(item));
    }
    return concat(parts);
  }
  throw new PlaceError(`msgpack: unsupported ${typeof value}`);
}
