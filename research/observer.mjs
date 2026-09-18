// Approximate settlement consistency observer for Hyperliquid recurring outcome markets.
//
// Records mark-price updates for the given perps over a window around a settlement
// time, then recomputes the official recurring-outcome rule (linear interpolation
// between the mark updates immediately before and after the settlement time) and,
// after settlement, compares the estimate with the venue's reported price.
//
// Zero dependencies. Requires Node 22 or later (global WebSocket).
//
//   node research/observer.mjs                 # next 06:00:00 UTC, BTC ETH SOL HYPE
//   node research/observer.mjs 2026-09-16T06:00:00Z BTC,ETH
//
// WHAT THIS IS NOT (see strategy-addendum-2026-09-15.md section 4.2):
//
//   - Not an independent check. The mark series and the reported settlement both
//     come from the same venue, so this detects internal inconsistency only. It
//     cannot corroborate the venue against any outside source.
//   - Not accurate to a known tolerance. The activeAssetCtx payload carries no
//     server timestamp, so timestamps below are LOCAL RECEIPT TIMES. The
//     receipt-time neighbours of the settlement instant need not be the
//     protocol's settlement neighbours. No tolerance has been characterised, so
//     do not quote an expected agreement in dollars until one has been measured
//     across many real crossings.
//   - Not a daily job. main() writes one result and calls process.exit(0).
//     Running it under nohup gives ONE run, not a schedule. Samples are also held
//     in memory until a single terminal write, so a mid-window failure loses the
//     capture. Durable incremental capture and scheduling are separate work.
//
// It has been exercised against a live subscription but not across a real 06:00
// UTC crossing. Optional for the first release; treat its first real run as a test.
//
// The one durable finding here is about the venue, not about this script: because
// the public payload carries no server timestamp, no third party can replay the
// interpolation rule from public data.

import { writeFileSync } from "node:fs";

const INFO = "https://api.hyperliquid.xyz/info";
const WS = "wss://api.hyperliquid.xyz/ws";

function nextSixUtc() {
  const now = new Date();
  const t = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 6, 0, 0, 0));
  if (t <= now) t.setUTCDate(t.getUTCDate() + 1);
  return t;
}

const target = process.argv[2] ? new Date(process.argv[2]) : nextSixUtc();
const coins = (process.argv[3] || "BTC,ETH,SOL,HYPE").split(",");
const windowMs = 5 * 60 * 1000;
const T = target.getTime();
const stamp = target.toISOString().replace(/[-:]/g, "").slice(0, 13);
const out = `research/observer-${stamp}.json`;

async function info(body) {
  const r = await fetch(INFO, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  return r.json();
}

function parseDescription(d) {
  return Object.fromEntries(d.split("|").map((kv) => kv.split(/:(.*)/s).slice(0, 2)));
}

const samples = Object.fromEntries(coins.map((c) => [c, []]));
let ws;

function connect() {
  ws = new WebSocket(WS);
  ws.onopen = () => coins.forEach((coin) => ws.send(JSON.stringify({ method: "subscribe", subscription: { type: "activeAssetCtx", coin } })));
  ws.onmessage = (ev) => {
    const now = Date.now();
    const d = JSON.parse(ev.data);
    if (d.channel !== "activeAssetCtx") return;
    const { coin, ctx } = d.data;
    if (!samples[coin]) return;
    if (now >= T - windowMs && now <= T + windowMs) samples[coin].push({ t: now, mark: ctx.markPx, oracle: ctx.oraclePx });
  };
  ws.onclose = () => { if (Date.now() < T + windowMs) setTimeout(connect, 1000); };
  ws.onerror = () => {};
}

function interpolate(list) {
  const before = [...list].reverse().find((s) => s.t < T);
  const after = list.find((s) => s.t >= T);
  if (!before || !after) return null;
  const m0 = Number(before.mark), m1 = Number(after.mark);
  const price = after.t === before.t ? m0 : m0 + ((T - before.t) / (after.t - before.t)) * (m1 - m0);
  return { price, before, after, gapMs: after.t - before.t };
}

async function main() {
  const meta = await info({ type: "outcomeMeta" });
  const instances = {};
  for (const o of meta.outcomes) {
    if (o.name !== "Recurring") continue;
    const spec = parseDescription(o.description);
    const expiry = spec.expiry; // YYYYMMDD-HHMM UTC
    const expiryMs = Date.UTC(+expiry.slice(0, 4), +expiry.slice(4, 6) - 1, +expiry.slice(6, 8), +expiry.slice(9, 11), +expiry.slice(11, 13));
    if (expiryMs === T && coins.includes(spec.underlying)) instances[spec.underlying] = { outcome: o.outcome, target: spec.targetPrice, description: o.description };
  }
  console.log(`target ${target.toISOString()} instances ${JSON.stringify(instances)}`);
  connect();
  await new Promise((r) => setTimeout(r, Math.max(0, T + windowMs - Date.now())));
  try { ws.close(); } catch {}

  const estimates = {};
  for (const coin of coins) {
    const est = interpolate(samples[coin]);
    const inst = instances[coin];
    estimates[coin] = {
      instance: inst || null,
      samples: samples[coin].length,
      estimate: est,
      impliedYes: est && inst ? est.price >= Number(inst.target) : null,
    };
    console.log(coin, est ? `estimate ${est.price.toFixed(4)} (gap ${est.gapMs} ms, ${samples[coin].length} samples)` : "no bracketing samples", inst ? `target ${inst.target}` : "no instance");
  }

  // Poll the venue's settlement for up to 30 minutes and record the comparison.
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    let pending = false;
    for (const coin of coins) {
      const e = estimates[coin];
      if (!e.instance || e.venue) continue;
      const s = await info({ type: "settledOutcome", outcome: e.instance.outcome });
      if (s && s.details && String(s.details).startsWith("price:")) {
        const venuePrice = Number(String(s.details).slice(6));
        e.venue = { settleFraction: s.settleFraction, price: venuePrice, difference: e.estimate ? e.estimate.price - venuePrice : null };
        console.log(coin, `venue ${venuePrice} fraction ${s.settleFraction}`, e.estimate ? `difference ${(e.estimate.price - venuePrice).toFixed(4)}` : "");
      } else pending = true;
    }
    if (!pending) break;
    await new Promise((r) => setTimeout(r, 30 * 1000));
  }
  writeFileSync(out, JSON.stringify({ target: target.toISOString(), recordedAt: new Date().toISOString(), windowMs, estimates, samples }, null, 1));
  console.log(`wrote ${out}`);
  process.exit(0);
}

main().catch((e) => { console.error(e); process.exit(1); });
