// The CoreWriter action an order envelope describes, encoded as bytes.
//
// PURE. Bytes in, bytes out, no key, no signing, no network. This module says WHAT an
// on-chain limit order would be; it never sends one. The live order is the owner's, run by
// hand from the runbook, and nothing here can place it.
//
// Every fact below is from retained evidence at commit 085ccfb,
// `research/2026-09-18-decisions/interacting-with-hypercore.md`, quoted where it matters:
//
//   - the system contract is at 0x3333333333333333333333333333333333333333
//   - "Byte 1: Encoding version ... only version 1 is supported"
//   - "Bytes 2-4: Action ID ... decoded as a big-endian unsigned integer"
//   - "Remaining bytes ... the raw ABI encoding of a sequence of Solidity types"
//   - action 1 is a limit order: (asset, isBuy, limitPx, sz, reduceOnly, encodedTif, cloid)
//     as (uint32, bool, uint64, uint64, bool, uint8, uint128)
//   - "Tif encoding: 1 for Alo, 2 for Gtc, 3 for Ioc"
//   - "limitPx and sz should be sent as 10^8 * the human readable value"
//   - "order actions and vault transfers sent from CoreWriter are delayed onchain for a
//     few seconds"
//
// THE SCALE IS LOSSY AND THAT IS CHECKED, not assumed. 10^8 fixed point cannot represent a
// price with a longer expansion, so a value that does not survive it is REFUSED rather than
// rounded: rounding would send an order for a price nobody proved anything about. It does not
// bite on real data, because the envelope carries a displayed price and a sum of products
// rather than an average -- see `onchain_representable` in oracle/verify.py, which pins that
// the retained books need 10^5 at most.

/** The system contract. Retained evidence, `interacting-with-hypercore.md`. */
export const CORE_WRITER = "0x3333333333333333333333333333333333333333";

/** Only version 1 exists. A future version is a new observation, not a default. */
export const ENCODING_VERSION = 1;

/** Action 1: a limit order. */
export const ACTION_LIMIT_ORDER = 1;

/** The venue's own tif encoding. `Ioc` is the only one this project sends. */
export const TIF = { Alo: 1, Gtc: 2, Ioc: 3 } as const;

export class EncodeError extends Error {}

/** What one envelope becomes on chain, before encoding. */
export interface LimitOrder {
  readonly asset: number;
  readonly isBuy: boolean;
  /** 10^8 * the human-readable price, exact. */
  readonly limitPx: bigint;
  /** 10^8 * the human-readable size, exact. */
  readonly sz: bigint;
  readonly reduceOnly: boolean;
  readonly encodedTif: number;
  readonly cloid: bigint;
}

/** 10^8, as the venue's own encoding states. */
const DECIMALS = 8;

/**
 * A decimal string as 10^8 fixed point, or a refusal.
 *
 * REFUSED, never rounded. A price the encoding cannot carry is a price the chain would check
 * differently from the way the oracle proved it, and sending a rounded one would place an
 * order about a number nobody established. The envelope's own values survive -- `limit_price`
 * is a displayed price and `max_cost` a sum of (displayed price x whole contracts) -- so a
 * refusal here means something upstream changed.
 */
export function scaled(text: string, what: string): bigint {
  // The same grammar `place.ts` enforces on the same fields: a non-negative decimal, no
  // exponent, no sign, no whitespace. Parsed by DIGITS rather than through a number, because
  // the whole point is to avoid a float ever touching a quantity.
  const match = /^(0|[1-9][0-9]*)(?:\.([0-9]+))?$/.exec(text);
  if (match === null) {
    throw new EncodeError(`${what} ${JSON.stringify(text)} is not a non-negative decimal`);
  }
  const whole = match[1] as string;
  const fraction = match[2] ?? "";
  // REFUSED, never rounded. A value the encoding cannot carry is a value the chain would
  // check differently from the way the oracle proved it.
  if (fraction.length > DECIMALS) {
    throw new EncodeError(
      `${what} ${text} has ${fraction.length} decimals; 10^8 fixed point carries ${DECIMALS}, ` +
        `and rounding here would send an order about a number nobody established`,
    );
  }
  return BigInt(whole + fraction.padEnd(DECIMALS, "0"));
}

/** The 32-byte big-endian word ABI encoding uses for every one of these types. */
function word(value: bigint, bits: number, what: string): Uint8Array {
  if (value < 0n) {
    throw new EncodeError(`${what} is negative: ${value}`);
  }
  if (value >= 1n << BigInt(bits)) {
    throw new EncodeError(`${what} does not fit in uint${bits}: ${value}`);
  }
  const out = new Uint8Array(32);
  let rest = value;
  for (let index = 31; index >= 0 && rest > 0n; index -= 1) {
    out[index] = Number(rest & 0xffn);
    rest >>= 8n;
  }
  return out;
}

/**
 * The raw action bytes for a limit order.
 *
 * `0x01`, then the action id as three big-endian bytes, then `abi.encode` of the seven
 * fields. Every field is a static type, so the encoding is seven 32-byte words in order with
 * no head/tail split -- which is why this can be written without a general ABI encoder, and
 * why the worked example in the retained page does the same.
 */
export function encodeLimitOrder(order: LimitOrder): Uint8Array {
  if (!Number.isSafeInteger(order.asset) || order.asset < 0) {
    throw new EncodeError(`asset is not a non-negative integer: ${order.asset}`);
  }
  if (order.encodedTif !== TIF.Alo && order.encodedTif !== TIF.Gtc && order.encodedTif !== TIF.Ioc) {
    throw new EncodeError(`tif ${order.encodedTif} is not one of 1 (Alo), 2 (Gtc), 3 (Ioc)`);
  }
  const fields = [
    word(BigInt(order.asset), 32, "asset"),
    word(order.isBuy ? 1n : 0n, 8, "isBuy"),
    word(order.limitPx, 64, "limitPx"),
    word(order.sz, 64, "sz"),
    word(order.reduceOnly ? 1n : 0n, 8, "reduceOnly"),
    word(BigInt(order.encodedTif), 8, "encodedTif"),
    word(order.cloid, 128, "cloid"),
  ];
  const out = new Uint8Array(4 + 32 * fields.length);
  out[0] = ENCODING_VERSION;
  out[1] = (ACTION_LIMIT_ORDER >> 16) & 0xff;
  out[2] = (ACTION_LIMIT_ORDER >> 8) & 0xff;
  out[3] = ACTION_LIMIT_ORDER & 0xff;
  fields.forEach((field, index) => out.set(field, 4 + 32 * index));
  return out;
}

/**
 * The action an accepted envelope describes.
 *
 * BUY AND `Ioc` ONLY, because that is all an envelope can bound. The envelope is the cost of
 * ONE order: a buy of exactly its size, priced no worse than the highest level the walk
 * touched, and cancelled rather than rested. A resting order outlives the book that priced
 * it, so `Gtc` or `Alo` would make the bound a claim about evidence that has moved on.
 *
 * `reduceOnly` is false and `cloid` is zero: the envelope describes acquiring protection, not
 * closing a position, and a client order id is the caller's business rather than the bound's.
 */
export function orderFromEnvelope(envelope: {
  readonly coin: string;
  readonly side: string;
  readonly size: string;
  readonly limit_price: string;
  readonly time_in_force: string;
}, assetId: (coin: string) => number): LimitOrder {
  if (envelope.side !== "buy") {
    throw new EncodeError(`side is ${JSON.stringify(envelope.side)}, not buy`);
  }
  if (envelope.time_in_force !== "Ioc") {
    throw new EncodeError(
      `time in force is ${JSON.stringify(envelope.time_in_force)}, not Ioc; a resting order ` +
        `outlives the book that priced it, so the cost bound would stop being about the evidence`,
    );
  }
  return {
    asset: assetId(envelope.coin),
    isBuy: true,
    limitPx: scaled(envelope.limit_price, "limit_price"),
    sz: scaled(envelope.size, "size"),
    reduceOnly: false,
    encodedTif: TIF.Ioc,
    cloid: 0n,
  };
}

/**
 * What the chain can bound about cost, and what it cannot.
 *
 * ON CHAIN NO BOOK READ IS NEEDED: an `Ioc` buy of `sz` at a limit of `limitPx` cannot spend
 * more than `limitPx * sz`, whatever the book looks like when it executes. That is the whole
 * reason a gate can live on chain -- it needs the order, not the market.
 *
 * WHAT IT CANNOT UNDO: the order may fill PARTLY, or not at all. `Ioc` cancels the remainder,
 * so the holder can end up with less protection than the verdict assumed, and no on-chain gate
 * can prevent that -- the fill is decided after the gate has passed. A partial fill is a NEW
 * proposal, re-checked from the books as they then are; it is not a smaller version of the one
 * that was approved. And the action is "delayed onchain for a few seconds" before HyperCore
 * executes it, so the book that priced the bound is not the book that fills the order.
 */
export function boundedCost(order: LimitOrder): bigint {
  // 10^8 * 10^8, kept in the scaled domain: dividing here would reintroduce the rounding the
  // encoding refuses. A caller comparing against max_cost scales that the same way.
  return order.limitPx * order.sz;
}
