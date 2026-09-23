# Evidence

Facts the plan depends on, with source and date. Revised 18 September 2026; §9
extended 19 September.

**[V]** reproduced offline by a verifier from retained bytes — API responses,
or official documentation pages retained as Markdown. It establishes what the API
returned, what the page said, or that arithmetic on them is exact — never that
the venue was right. · **[T]** official or third-party text, read on the date
given, not retained. · **[U]** unverified, an assumption, or an observed pattern
that does not establish a rule.

A universal negative ("none exists", "cannot be done") is only as wide as the
search behind it, so each one states its search scope.

The oracle, the conformance vectors and the schema checks are in the tree:
`make check`. Evidence packages are committed at `085ccfb`, not in the working
tree. Restore with `git checkout 085ccfb -- research/`, then:

```sh
python3 research/2026-09-15/verify.py             # 128 checks, 6 hashes
python3 research/2026-09-15-settlement/verify.py  # 222 checks, 13 hashes
python3 research/2026-09-18/verify.py             # 471 checks, 32 hashes + 14 re-verified
python3 research/2026-09-18-decisions/verify.py   # 82 checks, 6 official pages, name sweep
python3 research/oracle/verify.py                 # 4,077 checks — the first oracle, as committed; superseded by oracle/ in the tree
```

---

## 1. Contract rules

**[V] Canonical `priceBinary`** — text of the [contract specifications](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications) page, retained 18 Sep:

> settles to YES if and only if `markPrice0 + (settlementTime − t0)/(t1 − t0) · (markPrice1 − markPrice0) ≥ targetPrice`

`markPrice0`/`markPrice1` are the HyperCore mark updates immediately before and
after `settlementTime`. Not a TWAP, not a candle close, not the oracle. **The
comparison is inclusive**, so NO is its strict-below complement. This rule lives
only on that page: **[V]** none of the 18 templates mentions the recurring
families, so "the template text" is never the source for them.

**[V] Canonical `priceBucket`** (same page): three buckets, `< P1`, `[P1, P2)`,
`≥ P2`, "the same interpolation as binary markets", exactly one settling to 1. The
page's example is a `period:15m` series; only `1d` has been seen live **[U]**.
It is live for BTC as one question
with three named outcomes (`index:0..2`) and a fallback; index order matched the
documented bucket order in all three settlements observed (§2). The `index:0`
YES is a digital paying strictly below `P1` — **a protocol-settled instrument
struck about 2 % under the daily binary**, which reported the same settlement
price as the binary on all three days.

**[V] Deployer templates** — exact text from `outcomeTemplates`, byte-identical
on 15 and 18 Sep:

| Template | Text that fixes the payoff | Status in the plan |
|---|---|---|
| `binaryPrice` | "resolves to Yes if the {perp} price is **above** {threshold} at {time}" · "{seconds}-second TWAP of {priceDescription} price ending at {time}" | Computed once its reference is reviewed |
| `scalarPrice` | Long pays $1 "at or above {high}", $0 "at or below {low}", "$1 times (price − {low}) / ({high} − {low})" between; Short is the complement | Computed; **no instance was live in any retained catalogue** |
| `priceTouch` | touched once the TWAP "equals or crosses {target} at any time after this market is deployed" | Path-dependent: bounded, never computed as terminal |

Two differences from the canonical rule matter. The `binaryPrice` wording is
"above", not "at or above". And the observation is an *n*-second TWAP of a
**free-text** reference.

**[V] Deployer settlement is a submitted number, not a computation** ([deployer
actions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-4-deployer-actions),
marked "Testnet-only", retained 18 Sep). `settleOutcome` carries a
`settleFraction` the deployer chooses — "Standalone outcomes may settle to any
fraction" — and "`details` must be empty." Nothing on the page derives it from a
price. The only enforcement is: "Markets that contradict their template's
semantic restriction are considered malformed and slashable by validators."
Three consequences:

- A deployer leg pays what the deployer submits. Evaluating it "as written" is an
  assumption with an ID, not a fact about the protocol.
- **Which side owns the strike is not a rule waiting to be discovered.** It is
  each deployer's reading of "above", settlement by settlement.
- Fifteen live BTC markets name Pyth under a restriction that says "the price of
  a Hyperliquid perp". **[U]** whether validators would call that a contradiction;
  the text makes it a slashing question either way.

**[V] The reference is free text and already inconsistent.** Live BTC
`binaryPrice` instances on 18 Sep, by `priceDescription`, TWAP seconds and venue:

| `priceDescription` | TWAP | Venue | Instances |
|---|---:|---|---:|
| `the Pyth BTC/USD price` | 90 s | skew | 15 |
| `the Hyperliquid BTC perp trade` | 90 s | skew | 6 |
| `BTC-USDC perp mark` | 60 s | out | 1 |
| `BTC-USDC mark` | 1 s | out | 1 |

Every one carries the template metadata "This market must refer to the price of
a Hyperliquid perp." Fifteen name Pyth. Return `AMBIGUOUS_RULES` or an explicit
assumption; never resolve it silently.

**[V] The table above is a SAMPLE, not the distribution** (re-counted from the same
retained `outcome-meta.json`, 22 Sep). It lists 23 of **78** price-described outcomes.
The full count, by template and exact `priceDescription`:

| Template | `priceDescription` | TWAP | Instances |
|---|---|---:|---:|
| `binaryPrice` | `1-minute candle` | 300 s | **18** |
| `binaryPrice` | `the Pyth BTC/USD price` | 90 s | 15 |
| `binaryPrice` | `the Pyth US100 index price` | 90 s | 9 |
| `binaryPrice` | `the Pyth US500 index price` | 90 s | 9 |
| `binaryPrice` | `the Pyth HYPE/USD price` | 90 s | 9 |
| `priceTouch` | `BTC-USDC mark` | 1 s | 7 |
| `binaryPrice` | `the Hyperliquid BTC perp trade` | 90 s | 6 |
| `priceTouch` | `HYPE-USDC perp mark` | 1 s, 3 s | 2 |
| `binaryPrice` | `BTC-USDC mark` · `BTC-USDC perp mark` · `xyz:CL` | 1 s, 60 s, 1 s | 1 each |

Three things the earlier table hid, each of which changes what the registry must do:

- **The most common description names no venue at all.** `1-minute candle`, 18
  instances, is the single largest group and says neither a source nor a series. It
  cannot be mapped to `source:series:statistic[:window]` by any reading, so it is the
  clearest `AMBIGUOUS_RULES` case rather than an edge one.
- **The Pyth conflict is 42 instances, not 15.** US100, US500 and HYPE/USD are the same
  contradiction as BTC/USD: a Pyth series under a template restricted to "the price of a
  Hyperliquid perp".
- **`priceTouch` HAS live instances — 9 of them.** PLAN section 6 lists the family as
  "Bounded (§2), never computed as terminal", which reads as forward-looking; it is not.
  Nine outcomes on the 18 September catalogue carry it.

`xyz:CL` is retained as written. A description that is itself a bare identifier is
evidence about how little the field is constrained.

**[V] Structure** — text of the [HIP-4](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-4-outcome-markets) page, retained 18 Sep.
Fully collateralized, two-sided, no leverage, no liquidation — though the page
also says outcomes compose "with other primitives such as portfolio margin",
which T6 must read before assuming tokens never offset perp margin. Yes settles to
`settleFraction` quote tokens, No to `1 − settleFraction`. USDC on every market
observed. A long token's payoff is therefore bounded in `[0, size]` whatever else
is unknown about it — the fact that makes worst-casing an unreviewed leg sound.

---

## 2. Settlement observations

**[V] Twenty `priceBinary` settlements, five consecutive days, five rollovers.**
Target → reported price, with the side that paid:

| Expiry 06:00 UTC | BTC | ETH | SOL | HYPE |
|---|---|---|---|---|
| 14 Sep | 77,284 → 77,576.7 Y | 2,522.3 → 2,515.6 N | 101.76 → 101.0579 N | 79.348 → 79.546 Y |
| 15 Sep | 77,583 → 77,609 Y | 2,516 → 2,496 N | 101.07 → 101.31 Y | 79.546 → 79.7216 Y |
| 16 Sep | 77,616 → 75,941.6 N | 2,496.1 → 2,406 N | 101.32 → 97.19 N | 79.72 → 77.2439 N |
| 17 Sep | 75,941 → 76,297.9 Y | 2,406 → 2,436.5 Y | 97.19 → 99.506 Y | 77.244 → 78.711 Y |
| 18 Sep | 76,298 → 77,457.8 Y | 2,436.5 → 2,479.9 Y | 99.506 → 105.3626 Y | 78.711 → 87.7225 Y |
| 19 Sep (live) | 77,457 | 2,479.9 | 105.36 | 87.734 |

**What this does and does not test.** It tests that the API's `settleFraction`
agrees with the API's own reported price. It does **not** test inclusivity — no
instance settled at its target (closest: 3061, 26 USD), so all twenty agree
equally with a strict rule. It does not test interpolation — the price is the
venue's number (§5). Inclusivity rests on the official page alone.

**[U] Near-money resets.** Every new target sat within 0.02 % of the previous
reported settlement price, in all twenty rollover pairs. It is not a fixed
rounding of that price: 75,941.6 became 75,941 (rounding gives 75,942) while
77.2439 became 77.244 (truncation gives 77.243). The pattern is verified; the
algorithm, the deployment timestamp, and its continuation are not. Carry it as an
assumption with an ID and have the adapter detect deviation.

**[V] Three `priceBucket` settlements.**

| Expiry | Thresholds | Reported price | Paid |
|---|---|---:|---|
| 16 Sep | 76,063 / 79,168 | 75,941.6 | `index:0` (`< P1`) |
| 17 Sep | 74,422 / 77,460 | 76,297.9 | `index:1` (`[P1, P2)`) |
| 18 Sep | 74,772 / 77,824 | 77,457.8 | `index:1` |

Exactly the documented bucket paid each time and the fallback paid nothing.
**[U]** Thresholds sat within 1 USD of the binary target −2 % and +2 % in all
four instances seen; a pattern, not a rule. The `≥ P2` bucket has not been
observed paying.

**[V] Two proposals, one lesson.** Same holder in both — hypothetical, 0.1 BTC,
cap 1,000, floor 60,000, buying 1,000 NO.

| | 3061 (15 Sep) | 3253 (16 Sep) |
|---|---|---|
| NO ask at capture | 0.942, nineteen minutes before expiry | 0.975, eight hours before expiry |
| Settlement | 77,609 — 26 above target; NO paid nothing | 75,941.6 — below target; NO paid in full |
| Realized P&L | **−939.40**, inside the cap (`strike_reference`; no mark was retained) | **+82.96** (`analysis_time`, X0 = 75,362) |
| The check | fails: the floor breaches | fails on `[60000, 65112)`: floor −1,511.20 |

One hedge expired worthless and the outcome met the cap; the other paid in full
at a profit. **Both proposals fail, for the same reason: another admissible price
breaches the cap.** The realized outcome says nothing about either.

Instance 3061 timeline: 14 Sep 19:24 NO ask 0.055 for 1,000 — **[U]** transcribed,
bytes not retained · 19:30 BTC mark 79,087 — **[U]** not hashed, six minutes later
· 15 Sep 05:41 NO ask 0.942, bid 0.9275 — **[V]** · 06:00 settled YES at 77,609 —
**[V]**.

- **[V] The cliff.** Crossing the target by one dollar (77,583 → 77,582) moves
  combined P&L by **999.90** at 0.1 BTC and 1,000 contracts at 0.942. Sampling
  cannot see this.

**[V] Horizon exposure.** BTC fell 2.9 % in the sixteen hours after the 15 Sep
settlement. A holder "hedged for Tuesday" was covered at one observation time.

---

## 3. Feasibility and cost

**[V] General form**, one sized leg. Long exposure `q`, a digital paying 1
strictly below `K` bought at flat price `p`, floor `L`, inclusive cap, zero other
costs, `0 < p < 1`, baseline price `X0`:

```text
D = q(X0 − K)      baseline down to the strike; negative when the mark is below it
A = q(K − L)       strike down to the floor

n_min = max(0, (D + A − cap)/(1 − p))      binds at the floor
n_max = (cap − D)/p                        binds at the strike
feasible  ⟺  D + p·A ≤ cap
```

**What `D + p·A` is.** Two lines of algebra: the size that minimizes the worst
loss is `n* = A`, and the worst loss there is exactly `D + p·A` — **the best
worst-case this instrument can buy at that price.** Feasibility is that number
against the cap. It is also the infeasibility certificate: weights `(1 − p, p)`
on the strike and floor constraints cancel the size and leave
`−(D + p·A) ≥ −cap`. **[V]** on the golden case: `n* = 3,000`, loss `1,600`, and
2,999 and 3,001 are both worse. The earlier `q(K−L)p ≤ cap` is the `D = 0` case.

**[V] Depth.** With `C(n)` the cost of walking displayed asks:

```text
D + C(n)          ≤ cap
D + A + C(n) − n  ≤ cap
```

`C` is convex, so each constraint is concave in `n` and **the feasible sizes form
one interval**, found exactly by walking levels; the oracle asserts contiguity
rather than assuming it. **The asymmetry:** every displayed ask is at or above
the best ask, so depth only tightens both constraints — emptiness at the best ask
is final, while a non-empty window must be priced at the size requested. The
0.055 ask covered 1,000 contracts and cannot establish a window reaching 18,181.

**[V] The baseline is material.** Same proposal — 0.055 ask **[U]**, 1,000
contracts, 0.1 BTC, cap 1,000, floor 60,000:

| Baseline | Floor P&L | Headroom |
|---|---:|---:|
| `strike_reference` (K = 77,583) | −813.30 | 186.70 |
| `analysis_time` (X0 = 79,087) **[U]** | −963.70 | 36.30 |

Headroom differs by `D = 150.40`, over four times what remains. The arithmetic is
verified; both inputs are not. Hence a baseline is required, with no default.

**[V] Where 0.975 fails.** Premium 975 sits *inside* the cap, so the strike
constraint holds; the floor breaches. `PREMIUM_EXHAUSTS_BUDGET` would name the
wrong constraint. Under `analysis_time` the mark (75,362) was already below the
strike, so `D = −225.40`, and the best achievable worst loss was 1,492.16.

**[V] What satisfying the objective costs** — 18 Sep 07:17 UTC, mark 77,631.4,
0.1 BTC (7,763.14 USDC), cap 1,000, floor 60,000, `analysis_time`, displayed
depth, whole contracts. The first feasible windows observed with retained bytes:

| | Daily binary NO (3965) | Bucket-0 YES (3971) | Sell 0.0433 BTC, keep the cash |
|---|---:|---:|---:|
| Strike | 77,457 | 75,908 | — |
| Best ask | 0.451 × 36 | 0.17399 × 1,200 | — |
| Best achievable worst loss, `D + p·A` | 804.75 | 449.12 | 1,000 by construction |
| Passing sizes | 1,409 – 2,104 | 924 – 2,810 | — |
| **Cost of the smallest passing size** | **645.77 (8.3 %)** | **160.77 (2.1 %)** | 0 before trading costs |
| P&L if the price does not move | −645.77 | −160.77 | 0 |
| P&L at the strike | −663.21 | −333.11 | — |
| P&L at the floor | −999.91 | −999.91 | −1,000 |
| Makes money only | 69,999.09 – 77,457, or above 84,089.09 | 69,999.07 – 75,908, or above 79,239.07 | above the mark |
| Beats selling the BTC | below 77,457 or above 92,551.09 | below 75,908 or above 81,345.72 | — |

Both hedges **pass**. One costs four times the other for the same cap, and the
at-the-money one loses money at every price from its strike to an 8.3 % rally. A
verdict without this table tells the holder nothing they can act on. One
contract fewer fails in both cases.

---

## 4. Market structure

- **[V] Catalogue**, 18 Sep 07:17: 243 outcome entries, 25 questions, 3 deployers. By venue: `out` 99, `txyz` 88, `skew` 48, canonical 8 (four binaries, one bucket question of four). The count spans roles; it is not a count of liquid markets.
- **[T] Testnet lists the canonical families, at a DIFFERENT hour and with NO liquidity.** Read-only `POST https://api.hyperliquid-testnet.xyz/info`, 21 Sep, retained under `fixtures/testnet/2026-09-21/` with its request record. The catalogue has 601 outcomes and 108 questions, of which **5 recurring binaries** (BTC, ETH, SOL, HYPE, ZEC, all `expiry:20260922-0300`) and **1 recurring bucket** (BTC, `expiry:20260921-0600`, thresholds 79221/82454).
  - **The expiry hour is 03:00 UTC for binaries**, which resolves the earlier **[U]** note. The bucket is at 06:00, so the two are not merely a different hour: they are a different day AND hour.
  - **No expiry has both a binary and a bucket**, so the canonical comparison this system is built on does not exist on testnet today. `hedgecheck check --live --network testnet` correctly refuses with `no expiry with both a binary and a bucket for BTC` and spends one request.
  - **Both books are empty.** `#204891` (BTC binary NO) and `#203580` (BTC bucket0 YES) each return `0 bids, 0 asks`, 57 bytes. Retained as `binary-no.json` and `bucket0-yes.json`.
  - **Consequence for T3.** A testnet order cannot be depth-priced, because there is no depth. The live testnet run in `consumer/RUNBOOK.md` therefore exercises the ORDER PATH -- that a signed `Ioc` reaches the venue and what it answers -- and not the hedge check. Labelled **[T]**: it verifies testnet and says nothing about mainnet, per section 9.

- **[V] IDs rotate daily.** BTC binary: 2820, 3061, 3253, 3467, 3719, 3965. Settled instances are pruned from `outcomeMeta` yet retrievable by `settledOutcome` at least two days later; no listing endpoint for them is known **[U]**. Discover; never hard-code.
- **[V] One book, shown twice.** NO asks equal YES bids at `1 − price` with identical sizes and order counts (every level on 15 Sep; the first seven of twenty on 18 Sep across snapshots 2.2 s apart). The HIP-4 page says why: the two books "are merged to share liquidity… an order to buy Yes at price `p` is equivalent to an order to sell No at price `1-p`." Depth is never additive across the two coins.
- **[V] More than one way to acquire a payoff.** Official text: split USDC into YES + NO and sell the unwanted side; within a question, `negate` and `merge` convert between outcomes before settlement. A depth-priced cost must therefore **name its acquisition path**; the direct book is one path, not necessarily the cheapest.
- **[V] Depth is size-sensitive.** BTC NO, 15 Sep 05:41: 942.00 for 1,000, 1,416.70 for 1,500 — the marginal 500 cost 0.949 each. The bucket-0 book on 18 Sep held 2,400 contracts at 0.174, then nothing until 0.99999.
- **[V] Precision and size.** Books contain 0.00001 and 0.99999; every retained size is a whole contract. Guides claiming 0.001–0.999 and a 0.0001 tick are wrong or outdated.
- **[U] The lot rule is still not stated by the API.** `metaAndAssetCtxs` carries `szDecimals` for every entry in its 234-asset `universe`, but that universe holds **only perps** — no `#<encoding>` outcome coin appears in it, so its `szDecimals` says nothing about outcome sizing. No field in `outcomeMeta` describes lot or tick either. What is measured: **1,332 displayed levels across 35 books** (2 retained 18 Sep, 33 captured live 19–20 Sep) contain **zero** non-integer sizes. Whole contracts are what the venue displays; that they are what it *requires* remains **[U]** until an order is placed or the venue documents it. The oracle refuses a non-integral size, which is the conservative reading.
- **[U] Capture skew, proposed from measurement.** `metaAndAssetCtxs` carries no venue timestamp; `l2Book` carries `time`. So the only measurable skew in a captured set is a book's venue time minus our local retrieval time, which bundles clock error, latency and the gap between the two calls. **31 samples, 19–20 Sep** (`python3 spike/live.py skew`): min −796 ms, median −535 ms, max −291 ms; the contexts-to-book gap ran 1,817–2,048 ms at one request per 1.5 s. Every sample is negative, which is what latency predicts. The spike sets `MAX_SKEW_MS = 5000`, roughly six times the observed worst, and refuses a capture above it. Labelled **[U]**: the sample bytes were not retained, only the summary, and one machine on one network is not the distribution.

- **[V] Identifiers** ([asset ids](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/asset-ids) text, retained 18 Sep): encoding `10·outcome + side`; coin `#<encoding>`, token `+<encoding>`, asset id `100,000,000 + encoding`. Consistent with every retained book request.
- **[V] Fees** (official text, retained 18 Sep). Base rate: "Fees are currently zero for outcome markets for initial testing." Structure: users "pay the base outcome trading fee rate times `scale + max(scale, 1)`", the deployer receiving the `scale` part; "Maker rebates are never paid on outcome markets." So a `deployerFeeScale` of 1.0 means **twice** the base rate once it is non-zero. The catalogue carries `feeScale: "1.0"`, and `deployerFeeScale: "1.0"` on every `out` and `skew` outcome but on no `txyz` or canonical one — the fee surface already differs by venue. Carry zero as a dated assumption with an ID; it will change.
- **[T] Volume** (Liquidiction, 14 Sep): $283.3M all-time, $1.17M/24h, 1,878 daily unique traders, 202 open markets (197 deployer-settled). Tripled after the 29 Aug permissionless opening.
- **[T] Deployment.** Mainnet 2 May 2026; permissionless templates 29 Aug 2026 (500k HYPE stake, six-month lock, slashing by validator vote).

---

## 5. Settlement observability

**[T] No public API channel timestamps the mark** ([websocket](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions), 18 Sep).
`activeAssetCtx` and `fastAssetCtxs` — the mark-price channels — define no time
field; `bbo`, `l2Book` and `trades` do. **[U]** Observed cadence (a BTC context
about once per second, marks changing every one to three) — no bytes retained.

**Scope of the finding.** The interpolation rule cannot be replayed **from the
public info and WebSocket API**. Whether it can be replayed from node-level data
is **not examined [U]**: Hyperliquid publishes `asset_ctxs`, `explorer_blocks`,
`replica_cmds` and `misc_events_by_block` archives ("approximately once a
month… data may be missing", [historical data](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data), 18 Sep),
and anyone may run a non-validating node. Do not tell a Hyperliquid judge the
venue is unauditable; say which interface was examined.

So `research/observer.mjs` is **not independent** (same-venue data), has **no
characterised tolerance** (local receipt times), and is **not a daily job** (one
run, then `process.exit(0)`). It has not run across a real settlement.

---

## 6. HyperEVM, builder codes

For later tiers. **[V]** as official text retained 18 Sep; **[U]** as behaviour,
since nothing here has been exercised.

- **CoreWriter** sends HyperCore actions from HyperEVM. Action 1, limit order, takes `asset` as `uint32`; an outcome asset id (e.g. 100,039,651) fits. Action 17, "Outcome operation", covers `SplitOutcome`, `MergeOutcome`, `MergeQuestion`, `NegateOutcome`. "Order actions and vault transfers sent from CoreWriter are delayed onchain for a few seconds" — **not atomic** with the EVM transaction. **[U]** whether an outcome limit order through action 1 is accepted.
- **Read precompiles**: "perps positions, spot balances, vault equity, staking delegations, oracle prices, and the L1 block number." No book or BBO is listed. **[U]** `L1Read.sol` itself was not read.
- **Builder codes.** At most 0.1 % on perps and 1 % on spot; `ApproveBuilderFee` "must be signed by the user's main wallet"; the builder needs 100 USDC of perps account value; a user may hold ten approvals. The builder-codes page says they "do not apply to the buying side of spot trades"; the HIP-4 page says builders earn "on sell orders"; the deployer-actions page, marked Testnet-only, says they "can also be applied to buy orders for outcome orders… charged by the protocol on a best-effort basis." **[U]** which of these holds on mainnet. A hedge can in any case be acquired as a sell: split, then sell the other side.

---

## 7. Competition

**[T] Event** (rules PDF §5–8, 14, read 14 Sep; [FAQ](https://colosseum.com/hackathon) and [event page](https://colosseum.com/worldsfair) re-read 18 Sep).
Colosseum Crypto World's Fair, 14 Sep – 12 Oct 2026, closing 12 Oct 23:59 PT =
**13 Oct 06:59 UTC [V]**. One team per person, one submission per team; solo
entries allowed; an account per member before submitting.

**[T] Prizes.** General pool, open to every submission: Grand Champion $30,000,
twenty standout teams at $15,000, Public Goods $5,000, University $5,000. Track
prizes are "awarded in addition": Hyperliquid, Solana, Tempo, Zcash $100,000
across ten each. Hyperliquid: products "that integrate with Hypercore or
HyperEVM", supported by Hydromancer. Winners are interviewed for the accelerator
($250,000 pre-seed).

**[T] Two criteria lists.** Rules §8, binding: functionality, potential impact,
novelty, UX, open-source composability, business plan. FAQ, what reviewers
score: founder–market fit, insight, product and execution, market size, founder
communication, viability, **traction**. "Colosseum hackathons are for new
startups." Repositories are read for whether "significant work" was done during
the event, by the team; **language and framework are not judged**. Pre-existing
work must be disclosed; misrepresenting it disqualifies. Deliverables: repo, 2–3
min presentation, ≤3 min demo, team and integration details.

**[U] Track choice.** Hyperliquid on product fit. Entrant counts unknown.

**[T] Nijinn**, nearest neighbour (site, 14 Sep). Analytics only — "no
execution, custody or trading functionality." Polymarket and Kalshi; no
Hyperliquid mention, no documented API. Sizes from measured correlation; flags
binary payoff mismatch and resolution wording. Pro tier around Token2049
(6–7 Oct). **[U] Differentiation:** not documented to accept a stated objective,
evaluate a payoff across a domain, return a counterexample, or price the
alternatives — and absence of documentation is not proof of absence. Say "not
established from the reviewed public material."

Also: pytheum (Kalshi/Polymarket equivalence graph, MIT, MCP), RiskState,
AgentRisk, Outcome.xyz, Deribit, IBKR Risk Navigator, Blockaid.

**[V] Name availability**, 18 Sep — GitHub user and repository search, npm,
crates.io, PyPI, RDAP for `.com` `.xyz` `.ai` `.dev` `.app`, `whois.nic.io` for
`.io`; answers retained in `research/2026-09-18-decisions/`. The sweep reproduces
the 15 Sep table and says "taken" for its controls (`payoff`, `countersign`).

| Candidate | All eleven namespaces | Note |
|---|---|---|
| payoffbounds | free | The fallback if a change is ever required — [PLAN §12](./PLAN.md) |
| payoffbound | free | Reads as "bound to pay off" |
| payoffproof | free | Promises a proof about the world |
| lossbounds · pnlbounds · payoffverdict | free | Narrower than the product |
| hedgeassert | free | "Hedge" + a checking word, beside HedgeCheck LLC |
| payoffcheck | `.com` taken | |
| settlecheck | `.com` `.xyz` `.app` taken, 2 repositories | |

**[T] Collisions** (web search, 18 Sep). No product or company named
PayoffBounds was found. "Payoff" alone is crowded: Happy Money, formerly Payoff,
Inc., still sells "the Payoff Loan" — consumer lending, a different service. A
Polymarket-odds betting app on Robinhood Chain, a World's Fair track, was indexed
as "PayOff" at payoff.best; on 18 Sep the page titled itself "Poly". **[U]** No
trademark register was searched. X: `@payoffbounds` returned X's not-found page
on 18 Sep while `@colosseum` rendered a profile — observed in a browser, not
retained.

**[U] "HedgeCheck" and HedgeCheck LLC (Exiger-owned).** The firm was noted on
15 Sep and called a collision; nobody examined what it does, whether it holds a
mark, or whether anyone would confuse the two. The owner kept the name on 19 Sep.

**[U] Several tracks per submission.** Nothing authoritative found: the FAQ, the
event page and Colosseum's `hackathon-resources` repository are silent, and the
form sits behind an account. [PLAN §11](./PLAN.md) makes the answer irrelevant.

---

## 8. Deferred integrations

Recorded so they need not be re-derived. These are **[T]** notes from 14
September; nothing here is retained locally, so re-read the linked sources
before acting on any of it.

**[T] Tempo.** Mainnet chain id 4217, `https://rpc.tempo.xyz`; testnet Moderato
42431. Fees in USD TIP-20 tokens, ~$0.00003–$0.0006 per transfer. MPP: 402 with
`WWW-Authenticate: Payment`, retry with `Authorization: Payment`; Go SDK
`github.com/tempoxyz/mpp-go`. **No x402 facilitator settles on Tempo.**

**[T] Solana.** If built, a native SOL balance against the Hyperliquid SOL daily
(one basis hop), not wrapped BTC. `getTokenAccountsByOwner`, once per token
program. Public RPC is rate-limited; track providers are Helius, Triton One,
FluxRPC.

---

## 9. Known-wrong claims

Kept so they are not reintroduced. Everything from "The example result" down was
found on 18 Sep, the last four of those in revisions written that same day; the
next four on 19 Sep, in the plan's own design and the first oracle; the last on
20 Sep, found only by porting the kernel to a second language.

| Claim | Correction |
|---|---|
| "One dollar lower would have moved the result by 997.3" | That compared 77,609 → 77,582, a **27** dollar move. The threshold crossing is **999.90**. |
| NO settling worthless means the objective was missed | Realized P&L was **−939.40**, inside the cap. |
| `q(K−L)p ≤ cap` is the general feasibility form | It is the `D = 0` case. |
| Window at 0.055 runs 803–18,181 | The quote covered 1,000. Undepthed windows are indicative only. |
| `PREMIUM_EXHAUSTS_BUDGET` at 0.975 | Premium 975 is inside the cap; the floor breaches. |
| Observer is "the only independent check," accurate to "a few dollars" | Same-venue data, no timestamp, no characterised tolerance. |
| A "forty-line" checker confirms a verdict | A checker accepting the engine's own pieces cannot detect an omitted strike. |
| Unhedged failing set `S < 92,000` | `S < 90,000`; 92,000 wrongly included premium. |
| "Reduce the position by 0.03 BTC" | Leaves 2,800 loss at 60,000. Selling 0.075 and retaining cash meets the cap before costs. |
| `clearinghouseState` gives the exposure | That returns *perp* positions. Spot is `spotClearinghouseState`. |
| Testnet observation establishes mainnet fees | It verifies testnet. The official page says zero, for now (§4). |
| `verify.py` floor assertion (fixed 18 Sep) | Sign error `+A` for `−A`; passed even at `n = 0`. |
| The example result in `PLAN.md` §4 | Spliced three scenarios: the counterexample (90,000) lay in an interval the result omitted, the size window came from another quote, the times from a third instance. Its own checker should reject it. The example is now generated and machine-checked. |
| "The three live quotes under both baselines" | Only 0.055 was. 0.942 has no retained mark; 0.975 had one and was never evaluated with it. |
| "Eight settlements" verify the inclusive rule | None settled at its target. Twenty still do not. |
| "Template text" documents the recurring rule | No template mentions it. The source is the contract specifications page. |
| "No third party can replay the interpolation rule from public data" **[V]** | One API surface was examined; node data was not. A scoped finding, **[T]** (§5). |
| The daily binary is the first-release hedge | It is the worst-fitting canonical instrument for a loss cap: four times the cost of the bucket-0 YES for the same cap (§3). |
| "Settled inside **its owner's** loss cap" | There was no owner. Every holder here is hypothetical and is labeled so. |
| Equality on the deployer path is "unconfirmed", a rule to be learned from Skew | There is no rule to learn: deployers submit the fraction (§1). The strike is disputed by construction and is owned by neither side. |
| "A hedge purchase is a buy, so do not assume routed orders pay" | Official text says builder codes "can also be applied to buy orders for outcome orders" — on a Testnet-only page; mainnet is **[U]** (§6). |
| "`.io` and `.ai` inconclusive" | `.ai` answers over Identity Digital's RDAP, `.io` over `whois.nic.io`. rdap.org was the wrong place to ask. |
| "PayoffProof recommended" | It promises a proof about the world, which [PLAN §5](./PLAN.md) disclaims. |
| "'HedgeCheck' collides with HedgeCheck LLC — codename only", then a rename to PayoffBounds | An unexamined sentence from 15 Sep was treated as a requirement, and a rename was built on it. The name is HedgeCheck. |
| README: "189 checks" · PLAN: "no repository", "six days are gone" | 222 · a repository with no commits · four days, by the event clock. Counts and states are printed by a command, not remembered. |
| "Every supported price family is monotone in its reference", so a basis bound is a shift | The middle bucket is not monotone. Its worst case over a band `b` is `[P1 + b, P2 − b)`; either shift credits prices where it may pay nothing. Brute-forced 19 Sep against the oracle; reproducible, and a fixture from T1. |
| A reduced leg leaves "the verdict stands", so `fails` may rest on any bound | Only on a **tight** one. A bound no scenario attains proves nothing about failure, and a price alone is not a counterexample once a leg is bounded. |
| Go's `big.Rat` "parses both number forms natively" — offered as a reason | It also parses `"0x10"`, `"1e3"`, `"+5"`, `"1_000"`; Python's `Fraction` disagrees on some of them. Default JSON differs too: one object, three SHA-256 digests across Go, Python and JavaScript. Both run 19 Sep; both become fixtures in T1. |
| "An undeclared breakpoint is an error, not a wrong answer" | False for the first oracle. Its probe samples three points per interval; with a strike at 65,000 on `[60000, 110000]` omitted it raised nothing and returned failure `(60000, 67000)` for `[65000, 67000)` and infimum −4,200 for −3,700. `evaluate()` was never affected — it takes breakpoints from the legs' own constructors — but the guarantee was. Now a function cannot be separated from its breakpoints; `oracle/verify.py` asserts what the probe catches and what it cannot. |
| `oracle.infimum` reports an attaining price | **Found 20 Sep, porting to Go.** On a *flat open* piece it reported the excluded lower endpoint as attaining. Reproduced: an indicator paying 700 on `(-inf, 90000]` less a cost of 100 is flat at −100 on `(90000, 110000]` and 600 at 90000; `infimum` returned `value=-100, attained=True, price=90000`, where the function is 600. A witness built from it would name a price the objective is not violated at. The rule is now explicit: the smallest attaining price when the attaining set has a minimum, otherwise the midpoint of the first attaining open piece. **No committed fixture changed**, which is why it survived T1 — the shape was unreachable from every pinned case. |
| `reason_codes` had no defined order | **Found 20 Sep, porting evaluation to Go.** The verdict code and the reduction codes were appended by two separate loops, so the order they ended up in was an accident of which loop ran first — `['LOSS_BOUND_EXCEEDED', 'LEG_WORST_CASED_HORIZON']` rather than anything chosen. A second implementation would have picked a different accident and disagreed byte for byte on a result whose content was identical. The array is now **sorted**, and [ARCHITECTURE §4](./ARCHITECTURE.md) states the order of every array in a result so the question cannot recur. One fixture changed. |
| A clause's `on` interval was ignored | **Found 20 Sep, porting evaluation to Go.** The schema says "P&L >= min_pnl **on the interval**" and PLAN §2 calls the objective a lower envelope of `(interval, min_pnl)` clauses, but `oracle.evaluate` evaluated every clause over the whole domain. A clause asking for protection only above 95,000 was reported as failing at 60,000 — a failure the objective never asked about. No committed fixture had a clause with an `on` interval, so nothing caught it until a generator produced one. |
| A size window was sized against a profile the verdict does not use | **Found 20 Sep, by differential testing.** `_sized_leg_window` built its base from every other leg at **full value**, including legs the verdict had reduced to zero. So "the smallest size that meets the objective" was answered against a payoff the verdict refuses to count. Measured across the generated corpus: **1 of 7** such cases reported a smallest size whose worst P&L was **−4923.49676 against a −4000 cap** — a size that fails. The base is now the lower profile, and `oracle/verify.py` checks every reported size against it. |
| A test's own failure signal was swallowed by its own catch | **Found 22 Sep, by mutation.** The Solidity tests asserted reverts as `try gate.send(...) { revert Failed("was sent"); } catch {}`. If the call does NOT revert, the success branch raises `Failed` **inside the try block**, and the `catch` catches it — so the test passes either way. Three mutations came back green: removing the approval check, the price ceiling and the size ceiling, which are the three most important refusals in the contract. Found by running the mutations, not by rereading the tests. |
| Asserting that a call reverts is not asserting why | **Found 22 Sep, immediately after fixing the above.** With the catch bug repaired the same three mutations STILL escaped, for a different reason: an absent approval is the zero struct, so `limitPx` and `size` are both 0 and any positive order trips `PriceTooHigh` or `SizeTooLarge`. The send reverts either way, so each check masks the others and a test asking only "did it revert" cannot tell them apart. The assertions now require the revert SELECTOR, which distinguishes all three — the same lesson the synthesis fixtures needed, where `CERTIFICATE_WEIGHTS` could not tell an unknown site from a certificate that proves nothing. |
| A chain cannot check a certificate, so T7 was renamed rather than overstated | **Decided 22 Sep, before writing the Solidity.** The tier read "certificate checker on HyperEVM". Verifying a certificate means canonical JSON, exact rationals, piecewise profiles and infima — a fourth kernel implementation at enormous gas. But the binding reason is evidence, not cost: retained evidence lists the read precompiles as "perps positions, spot balances, vault equity, staking delegations, oracle prices, and the L1 block number" — **no order book**, so a contract cannot see the depth a cost bound was walked from, and nothing on chain can attest that some bytes are the venue's own response. What was built instead is an approved-order gate, and the tier now says so. |
| The on-chain encoding is lossy, and an earlier schema decision is why it does not bite | **Verified 22 Sep, from retained evidence, before building T7.** `interacting-with-hypercore.md` at `085ccfb` states that a CoreWriter limit order sends `limitPx` and `sz` as "10^8 * the human readable value" — a **lossy** encoding for anything not a multiple of 10^-8, which would mean the gate on chain checks a different number from the one the oracle proved. It does not happen, and not by luck: `defs.cost` carries a walked premium as a TOTAL rather than a per-unit price, "because a walk over several levels has no single price, and its average is a derived quantity that is usually a repeating decimal". The envelope follows — `limit_price` is the price of the highest level the walk TOUCHED, a displayed price, and `max_cost` is a sum of (displayed price × whole contracts) — so every value is a multiple of 10^-8. The average is what breaks: 1,409 contracts at 645.76904 averages 8072113/17612500, which no fixed point represents. Measured: **416 displayed numbers across the retained books, 0 violations, and the deepest needs 10^5** — five orders inside the venue's 10^8. `onchain_representable` pins both the property and the headroom, so a venue that starts quoting finer prices fails loudly rather than truncating silently. |
| T6 needed no new evidence; the retained text already settled it | **Found 22 Sep, by reading `085ccfb` before fetching anything.** The tier's exit criterion reads "liquidation semantics reviewed from official text", which looked like a research task. The retained page already says it: outcomes bring "an alternative form of derivative trading that **does not involve leverage or liquidations**". So the HEDGE cannot be liquidated and the thing being HEDGED can — which makes this an exposure rule, not a leg rule, and explains why `linear_spot` could not express it. What the retained text does NOT give is a maintenance-margin formula, so `liquidation_price` is **declared** rather than derived: computing one would be asserting arithmetic this project cannot show. Declared like a basis bound, with the reduction firing on it and the result naming the rule. |
| An adverse state said "valued at zero" where the margin was lost | **Found 22 Sep, by reading the generated fixture rather than the test result.** `liquidated_in_path` had no entry in either adverse-state map, so both fell through to the default wording, "the leg is valued at zero". Every test passed: the maps agree, the strings match, and the shape is right. But it is false — a liquidated position is worth **minus its margin**, and a reader told "zero" would think the holding merely stopped paying rather than that the margin was gone. The one thing a witness's adverse state exists to say is what went wrong, so a plausible-but-wrong sentence there is worse than a missing one. |
| An invented assumption passed the whole pipeline and reached the reader | **Found 22 Sep, by asking what enforces `common_reference`.** Nothing did — and nothing enforced the NAME either. `proposal.assumptions` is typed as any slug, so a proposal declaring `nothing_can_go_wrong` validated against the schema, lowered without complaint, and was **carried into the result's own `assumptions` list** beside `zero_base_fee` with equal standing. Verified end to end before the fix. An assumption is the one part of a result whose whole content is what it MEANS to a reader, so an uninterpretable name is worse than a missing one. The vocabulary is now closed in lowering — `ASSUMPTION_UNKNOWN`, the nineteenth refusal code — and mirrored in the engine, which the parity test forced: adding the code failed `make check` until both a fixture and a Go implementation existed. Kept out of the schema deliberately: narrowing `slug` to an enum would make previously-valid documents invalid, needing a new `schema_version` and every pinned document regenerated, and the vocabulary is a semantic rule like the family whitelist rather than a fact about JSON shape. It also catches the likelier fault — `zero_base_fees`, a near-miss typo, which used to pass and then fail the `zero_base_fee` requirement with a confusing message. |
| `common_reference` was an assumption nothing read | **Found and left as a NOTE, 22 Sep.** It appears in every replay proposal and no implementation consulted it. The temptation was to make it a gate; that would be wrong. The basis reduction rests on the RESOLVED references — what each leg's registry entry and the reference map say it is observed on — not on an assertion about them, so letting a declared `common_reference` switch it off would let a proposal assert its way out of the reduction that exists to catch exactly that error. It stays in the vocabulary because proposals carry it and a reader should be able to look it up, with its meaning recorded as what the holder BELIEVES rather than what the system checked. If it ever gates anything that will be a change with its own reason. |
| Byte equality would have been the wrong conformance bar for a solver | **Decided 22 Sep, before writing the Go solver rather than after a test failed.** Every other cross-implementation claim in this project is byte equality, because an evaluation has one answer. A linear program does not: its optimum is unique but its ARGMIN is not. Measured — two candidates with the same payoff at the same price, `(1250, 0)` and `(0, 1250)` are both optimal at a relaxed cost of 250, and which one returns depends on the pivot order; reordering the candidates flips it. A test demanding one of them would test the pivot rule. The bar is instead the **status** and the **relaxed optimum cost**, both determined facts about the program, with each implementation's own sizes then checked valid against the rows and each certificate checked to be a valid Farkas witness. Stronger than byte equality in the way that matters, and honest about what is genuinely determined. |
| A limit constraint was read as a point value | **Found 22 Sep, by writing the second implementation.** The checker's `rows` computed each site's value with a lookup at the price, but `above` and `below` sites are LIMITS, which differ from the point value wherever the function jumps — and a digital jumps at its strike, the one place that matters. So the constraint just below 90,000 said one contract pays **nothing** where it pays in full, and the two constraints at the strike then collapsed into one as duplicates. The oracle never had the bug because `atoms` hands it each open piece's own affine rule; the checker had to be told. Found because the two derivations were compared, not because either was read carefully. |
| A certificate site name depended on the walk order | **Found 22 Sep.** Deduplicating the constraint rows kept whichever NAME the walk reached first, and the two implementations walk differently: the domain's top comes out `below` from the oracle's atom walk and `at` from the checker's maximal-piece walk. Since the certificate names its sites, a weight on `110000 below` would not resolve against a checker calling it `110000 at` — the same implicit-contract problem that naming the sites was meant to remove, moved one level down. Both sides now apply one canonical rule: `at` before `below` before `above`, then sorted by price, so the row list is deterministic and the names agree. |
| A comment claimed a guard that did not exist | **Found 22 Sep, by checking it.** `checker/src/synthesis.ts` declares its own refusal-class list rather than importing `verify.ts`'s, and the comment explaining why said "oracle/verify.py checks that every class this file names is in that schema". Nothing did. The claim happened to be TRUE — all five are in `refusal.schema.json` — which is exactly why it would have survived until it was not. `synthesis_refusal_classes` now checks it in both directions: no class outside the frozen list, and none declared that the checker never returns. |
| A Go decoder read `pays_on` one level too deep | **Found 22 Sep, by the schema-parity test.** `readPaysOn` takes the PARENT reader and descends into `pays_on` itself; `doc.ReadSynthesis` passed it the child, so it looked for `pays_on.pays_on`. Four of the eight synthesis rejection fixtures were then refused for `request.candidates[0].pays_on.pays_on: missing` — a nonsense path — which means they were refused for the WRONG reason and would have been accepted once the shape was right. The Go tests were green throughout: `TestRefusesEveryRejectedDocument` asks only that a document be refused, not why. It was found by printing both sides' reasons and comparing them, which is what parity between two implementations actually means. |
| A validator call that silently did nothing | **Found 22 Sep.** A probe called `validate.validate(...)` guarded by `hasattr`, so when the real entry point turned out to be `validate.valid` the guard fell through and every document reported `problems=None` — three "passes" that established nothing. The same class as the reachability trap above: a check that cannot run is not a check that passed. Caught by asking the validator to refuse something it should refuse; five distinct corruptions then produced five distinct messages. |
| A duplicated function definition silently replaced a fix | **Found 22 Sep, twice in one sitting.** Inserting the synthesis block before an anchor that appeared more than once left `_simplex` and `constraints` each defined TWICE in `oracle/oracle.py`. Python binds the later definition, so every fix to the first was a no-op and every mutation of it passed: the simplex returned `(0, 0)` for a program whose only constraint is `n1 + n2 >= 10`, and a mutation that deleted the left-limit constraint rows showed no effect at all. Both looked like logic errors and neither was. The tell was a return arity that did not match the code being read. `oracle/verify.py` would not have caught it either — nothing asserted that a module defines each name once. Checked now with a one-line scan for duplicates during development; the real fix was removing them. |
| The reference map's own review was never enforced | **Found 22 Sep, closing T4.** `catalogue_reference` refused with "no **reviewed** mapping", but `reference_index` honoured every mapping whatever the document said about itself — the map sat at `state: draft` and resolved references anyway. It is not cosmetic: a mapping nobody reviewed can point a leg at the objective's OWN series, and then the basis reduction never fires. Measured on the 18 September bucket proposal, pointing a foreign series at `hl:perp:BTC:mark-interp` turns a `needs_review` worst case of −1,923.90676 into a `passes` at −999.90676 — the silent resolution PLAN §6 forbids by name. Both the oracle and the Go loader now require the seal (digest over the document without its `review` key, so a review cannot sign itself), and both were seen failing on a forged digest and on an edited mapping. The map is reviewed at `d2b36412`. |
| A size window was reported for a leg whose size is not separable | **Found 22 Sep, by building the first multi-leg band fixture.** A banded group is valued at the infimum of its SUMMED payoff over the band, so resizing one member moves the sum and with it the infimum — "the smallest size of this leg" presumes a separability the evaluator does not have. Measured on `good-basis-grouped`: sizing `binary-no` at 0 / 500 / 1409 / 3000 moves the group's value at 76,000 by exactly as much. Both implementations answered anyway and **disagreed about the base** — the oracle credited a banded sibling with zero, Go with its full unbanded payoff — so they reported different binding prices (60,000 and 75,908 versus 77,457) for one bundle. Neither was right; both now omit the window. It was invisible because every previous basis fixture was single-leg, where the question is well-posed. |
| No bundle carried a grouped band reduction | **Found 22 Sep.** `good-basis-band` and `good-basis-unbridged` are both single-leg, so no fixture had a `with` list and neither Go nor the TypeScript checker was ever held to agreeing with the oracle on grouping — the hardest part of the rule. `good-basis-grouped` is two real 18 September instances sharing one expiry (bucket 3971 YES and binary 3965 NO), each with its own retained book. It does **not** separate grouped from per-leg banding: both legs are monotone decreasing, and for same-direction legs the infimum of the sum IS the sum of infima — verified at bands of 100, 500, 1,000, 2,000 and 5,000, agreeing at every price. Separating them needs opposite-facing legs, and no retained book supports such a pair (binary YES would need coin `#39650`, bucket NO `#39711`; neither was captured), so that case stays synthetic in `basis_band`. The bundle pins the plumbing; the guard pins the arithmetic. |
| 42 Pyth instances refused over a contradiction that does not exist | **Found 22 Sep, by reading the retained template in full.** Four reference-map rows refused every Pyth-settled instance as `AMBIGUOUS_RULES`, holding that naming Pyth contradicts the metadata "This market must refer to the price of a Hyperliquid perp". It does not: that is `semanticRestriction`, constraining **`{perp}`** — the market's subject — while the same template says "Settlement is according to the {seconds}-second TWAP of **{priceDescription}** price ending at {time}". Two different fields; `priceDescription` is the settlement source by the template's own words. All 42 pair coherently (`perp:BTC` → Pyth BTC/USD, `perp:HYPE` → Pyth HYPE/USD, `perp:xyz:XYZ100` → Pyth US100, `perp:xyz:SP500` → Pyth US500). Two further errors in those rows: the count was recorded as **15, actually 42**, and the US100 row claimed "there is no Hyperliquid perp for US100 at all" when all nine carry `perp:xyz:XYZ100`. They are now `interpreted`, to `pyth:*` ids and never `hl:*` — mapping is not equating, and such a leg still earns `basis_unbridged` against a Hyperliquid objective. Refusing had discarded **54% of the live catalogue** to avoid a question the basis rule already answers. |
| A reviewed registry entry's seal was never checked on disk | **Found 22 Sep, while approving `template.priceTouch`.** `semantics_version` digests an entry WITHOUT its `review` key, so a review cannot sign itself and any edit voids it — the mechanism is sound and `canon.reviewed` implements it correctly. But the only caller that read the FILES was the replay guard, which is deliberately scoped to the families its two proposals name, so a newly reviewed family was sealed with nothing verifying the seal. **A forged digest (`0`×64) and an entry edited after review both passed the whole suite.** `review_seals` now reads the registry directory, checks every reviewed entry's digest against its own text, and proves the seal detects tampering by mutating each entry in memory. |
| The live testnet order was blocked on the wrong thing | **Corrected 22 Sep.** The gate section said testnet lists "no expiry carrying both a binary and a bucket". True, but not the blocker: **a bucket is not required.** Testnet carries no price bucket at all (only `policyRateBucket`), yet it carries strike LADDERS of binaries at one expiry — `BTC 20260921-1200` at 81,100 / 81,500 / 81,900, and five-strike ladders on `xyz:AAPL` and `xyz:XYZ100` — and long-plus-YES-plus-NO across two strikes is a hedge this project verifies. The shape is routine; the depth is not. Both retained testnet books are empty (0 bids, 0 asks), so a hedge priced by walking displayed asks refuses with `INSUFFICIENT_DEPTH`. `testnet_shape` in `oracle/verify.py` re-derives all of it from the retained catalogue, so the claim is checked rather than remembered. |
| A `fails` verdict named prices where the best case met the clause | **Found 22 Sep, by the Go engine's loose-bound audit.** The verdict already refused to fail on a loose bound per INTERVAL — it checked that the upper profile violates the clause *somewhere* in the failing interval — but it drew the WITNESS from the whole lower-profile interval. The lower profile can violate across a wider span than the upper one, and the surplus rests on the loose bound alone. On `case-0166` the lower profile failed across [60000, 95151.35] while the upper failed only on [60000, 65000), and the reported counterexample was **77575.675, where the best case is −657.5675 against a −1000 cap** — a price that meets the clause. Failures are now reported only on the established sub-intervals, each with its own witness. `established_failures` in `oracle/verify.py` checks the invariant directly on the evaluator, over every failing interval of every generated case, so regenerating the corpus cannot satisfy it. |
| An attaining price was the midpoint of an arbitrary fragment | **Found 22 Sep, by the two implementations disagreeing.** `infimum` iterated `atoms`, which splits at every breakpoint the function CARRIES — and a carried breakpoint need not be a kink: two legs whose payoffs cancel leave one behind with the same slope either side. So "the midpoint of the first attaining open piece" was the midpoint of a fragment of that piece. On `case-0266` the flat run (65000, 110000] carries a phantom mark at 77457, and the oracle reported **71228.5** where Go, which windows maximal pieces, reported **87500**. Both attain the same value, so no arithmetic check separated them. `infimum` now reads maximal pieces, and prefers an owned endpoint — the smallest attaining price — to the midpoint, which is what the docstring always said. |
| `size_window`'s binding sites were unpacked before being filtered | **Found 22 Sep.** `_sized_leg_window` wrote `for price, side in window["binding"] if price is not None`, but `size_window` returns `[low_site, high_site]` and leaves a SITE `None` when no constraint binds there — a wide cap binds at neither end, so the entry is `None`, not a pair with a `None` price. The filter ran after the unpacking and raised `TypeError`. It was invisible because `make_ir_cases.py` skips any shape the oracle raises on (`except Exception: continue`), so the crash silently **shrank the conformance corpus** rather than failing: the first generated shape hit it and was dropped. Fixing it recovered that case and displaced the corpus by one. Go used `*Site` pointers and never had the bug, which is why the two disagreed. |

---

## 10. Sources

Retained `POST https://api.hyperliquid.xyz/info` responses under
`research/2026-09-15/`, `research/2026-09-15-settlement/` and
`research/2026-09-18/`; retained official pages and the namespace sweep under
`research/2026-09-18-decisions/`. All with request records and SHA-256 hashes.

Official: [contract specs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications)
· [HIP-4](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-4-outcome-markets)
· [HIP-4 deployer actions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-4-deployer-actions)
· [websocket](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions)
· [asset ids](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/asset-ids)
· [tick and lot](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size)
· [historical data](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data)
· [HyperCore from HyperEVM](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/hyperevm/interacting-with-hypercore)
· [builder codes](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/builder-codes)
· [worldsfair](https://colosseum.com/worldsfair) · [hackathon FAQ](https://colosseum.com/hackathon)

Third-party: [reservoir](https://docs.hydromancer.xyz/reservoir) ·
[pytheum](https://github.com/pytheum/pytheum) ·
[hip4-kit](https://github.com/Arjun0606/hip4-kit) ·
[Outcome-xyz/hip4](https://github.com/Outcome-xyz/hip4) ·
[nijinn](https://nijinn.io/) · [tempo docs](https://tempo.xyz/developers/docs) ·
[mpp](https://mpp.dev/protocol)
