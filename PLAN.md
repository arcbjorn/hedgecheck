# PayoffBounds: plan

Formerly codenamed HedgeCheck; the directory keeps the codename. Authoritative:
this file and [EVIDENCE.md](./EVIDENCE.md) are the only planning documents.
Earlier revisions and the superseded 14–15 September documents were deleted on
18 September; their corrections survive in [EVIDENCE.md §9](./EVIDENCE.md).

18 Sep 2026. Status: four evidence packages and a reference oracle, each with a
verifier. **No engine, no application.** A Git repository with no commits.

**Sequencing is by dependency and risk, never by calendar.** The Colosseum close
is a fact ([EVIDENCE §7](./EVIDENCE.md)) that decides what is *submitted* (§11).
It does not decide what is built, or how well.

---

## 1. Product

An exact, inspectable answer to what a person asks before approving a hedge:

> *Do these exact terms, costs and holdings satisfy my objective — and what does
> satisfying it cost me, against what else I could do?*

Every check returns three things, never the first alone:

1. **Verdict.** `passes`, `fails` or `needs_review` against an explicit objective
   over a declared price domain, with an admissible witness per failing interval.
2. **The price of the verdict.** The whole payoff profile, the premium, the P&L if
   nothing moves, the break-evens.
3. **The alternatives.** The same objective through no hedge, through the smallest
   exposure reduction that meets it, and through every other supported instrument
   at displayed depth.

**Why all three.** On 18 Sep two canonical hedges both *pass* the same 1,000 USD
cap: one costs 645.77, the other 160.77, and the dearer one loses money at every
price from its strike to an 8.3 % rally ([EVIDENCE §3](./EVIDENCE.md)). A bare
`passes` would have approved either. **Why a check at all:** instance 3061 expired
worthless with the outcome inside the cap; instance 3253 paid in full at a profit;
both proposals fail, because another admissible price breaches the cap
([EVIDENCE §2](./EVIDENCE.md)). Checking the outcome tells you nothing; checking
the domain does.

Value comes from maintained contract interpretations, acquisition costs at
displayed depth, reproducible results, and a place in a real approval process —
not from the formula, which is one page.

**Never** — permanent, not deferred: probabilities, implied distributions,
expected values, percentage-coverage claims · a verdict that depends on a
statistical or language model · custody · "the only tool that."

---

## 2. Model

One exact core, plus a registry of small **sound reductions** that bring harder
cases into it. Nothing below needs a second engine.

**Core.** P&L is a function of one terminal reference price `S` on a closed domain
`[L, U]`. Every leg is piecewise affine with finitely many breakpoints, jumps
allowed, **each breakpoint owned by exactly one side**. The class is closed under
sums, so a portfolio of any number of legs is evaluated exactly.

| Element | Support |
|---|---|
| Exposure | Unleveraged linear holding, quantity ≥ 0, in an underlying with a canonical family (BTC, ETH, SOL, HYPE). Manual entry, then `spotClearinghouseState` |
| Legs | Any number of long outcome tokens; cash; existing tokens at an explicit analysis-time value, never at purchase cost |
| Families | §6. Canonical `priceBinary` and `priceBucket` first |
| Objective | A **lower envelope**: clauses `(interval, min_pnl)`, all of which must hold, plus an optional `max_premium`. A loss cap is the one-clause case |
| Baseline | **Required, no default**: `analysis_time` (a retained mark) or `explicit` (labeled; `strike_reference` is one explicit value) |
| Price | Explicit premium, or the cost of walking displayed asks at the size requested. The cost **names its acquisition path**: the direct book first; split-and-sell and `negate` paths later ([EVIDENCE §4](./EVIDENCE.md)) |
| Other costs | Explicit, or a reviewed bound with conservative semantics. Fees: `base rate × (scale + max(scale, 1))` with the outcome's own `deployerFeeScale`; the base rate, zero today, is a dated assumption with an ID |
| Sizes | Whole contracts, as observed; the lot rule is confirmed in T2 |

**Reductions.** Each is one reviewable rule, sound by construction, surfaced as a
reason code — never applied silently.

| Case | Reduction | Why it is sound |
|---|---|---|
| Leg observed at a time other than the objective's valuation time | Value the leg at its worst admissible payoff: **zero** | A long, fully collateralized token pays within `[0, size]`. One settling earlier may have paid nothing; one settling later has no guaranteed value yet |
| Leg or exposure on another reference, declared basis bound `b` | Shift the leg's payoff by `b` against the holder: a digital below `K` becomes a digital below `K − b`; a linear exposure loses `q·b` | Every supported price family is monotone in its reference, so the adverse end of the band is the worst case. No bound declared: worst-case the leg to zero |
| Deployer-settled leg | Evaluate as written **only** under the assumption `deployer_settles_as_written`; at the strike itself the leg pays the holder **nothing, on either side**. Without the assumption: zero | The deployer submits the fraction; nothing computes it ([EVIDENCE §1](./EVIDENCE.md)). "Above" is theirs to read, so the strike is owned by neither side |
| `priceTouch`, long YES | Lower-bound by the terminal digital at the target, on the same TWAP | A terminal observation at or through the target implies a touch |
| Isolated perp with a liquidation price inside the declared **path** domain | The leg is worth minus its isolated margin at **every** terminal price | The path may reach the liquidation price and recover. A terminal digital cannot hedge that, and the result says so exactly (T6) |
| Unreviewed or ambiguous family | Zero, or `needs_review` if the proposal cannot be represented at all | Same bound as the first row |

A reduced leg can never help a proposal pass; it can only fail to help.

---

## 3. Evaluation

Total wealth, including cash:

```text
P&L(S) = terminal asset value(S) + terminal cash and settlement proceeds(S)
       - initial total wealth - net external contributions
```

Premium applies **once**. Cash from selling exposure stays in.

Collect breakpoints; split the domain into atoms — each breakpoint, and each open
interval between neighbours; solve every affine inequality exactly; emit maximal
intervals with endpoint ownership and one admissible witness each: the attained
minimum, else the midpoint. **Never round before comparing, and never sample** —
sampling cannot see the 999.90 cliff at the strike. An undeclared breakpoint is
an error, not a wrong answer.

**Numbers** are exact strings: a terminating decimal when one exists, otherwise
`"p/q"` — a comparison boundary can be `268000/3`. Rounding is a display concern,
outward, and labeled.

Interval length is **not a probability**. Axis label: "scenario price."

### Golden cases

`S ∈ [60000, 110000]`, `P&L(S,n) = 0.1(S − 100000) + n·I(S < 90000) − 0.2n`,
objective `P&L ≥ −1000`. Every row is asserted by `research/oracle/verify.py` (restore from `085ccfb`).

| Input | Expected |
|---|---|
| No hedge | Failure `[60000, 90000)`; worst −4,000 |
| 1,000 contracts | Failures `[60000, 82000)` and `[90000, 92000)`; worst −3,200 |
| Exactly 82,000 or 92,000, n=1,000 | Meets the inclusive cap |
| Exactly 90,000, n=1,000 | −1,200; fails. One cent lower: −200.001 |
| Any size at 0.20 premium | None: needs `n ≥ 3,750` at the floor and `n ≤ 0` at the strike |
| Best size for minimum worst loss | 3,000 contracts; worst 1,600; 2,999 and 3,001 are worse |
| Sell 0.03 BTC, retain cash | Worst 2,800; fails |
| Sell 0.075 BTC, retain cash | 0.025 BTC left; worst 1,000; passes before costs |
| 1,000 contracts against selling 0.075 BTC | Better only on `(268000/3, 90000)` and `(308000/3, 110000]` |
| YES + NO, equal size | One flat piece worth the size, strike included |
| Three buckets, equal size | One flat piece: the buckets partition the domain |
| `q·(high − low)` scalar Shorts on a long `q` | Flat between `low` and `high` |
| Strike omitted from the breakpoints | Rejected |

Plus the live cases in [EVIDENCE §3](./EVIDENCE.md), asserted by
`research/2026-09-18/verify.py`: 3061 at 0.942, 3253 at 0.975 under
`analysis_time` with the mark below the strike, and the 18 Sep binary and bucket
windows at displayed depth, each failing with one contract fewer.

### Sizing

For one sized leg, `D + p·A` is the best worst-case the instrument can buy at
price `p`, reached at `n* = A`; feasibility is that number against the cap, and
the weights `(1 − p, p)` that produce it are the infeasibility certificate
([EVIDENCE §3](./EVIDENCE.md)). At displayed depth the cost is convex, so **the
passing sizes form one interval**, found by walking levels. Report which
constraint binds each end.

Lead with the asymmetry: **emptiness at the best ask is final**, because depth
only tightens both constraints. A non-empty window is a claim about the size
priced, and about nothing larger. Never call a window executable.

**Synthesis (T5)** is the same idea with several instruments. Breakpoints come
from strikes, not sizes, so "cheapest sizes meeting the envelope" is a linear
program with finitely many constraints, solved in exact arithmetic. Its dual
gives an infeasibility certificate the checker verifies by one multiplication.
It answers a stated objective; it is not advice.

---

## 4. Result contract

The example is a projection of `research/oracle/fixtures/golden-1000-contracts.result.json`.
It is generated, and `research/oracle/verify.py` fails if any field here differs.

```json
{
  "schema_version": "1",
  "units": {"money": "USDC", "price": "USDC per BTC", "exposure": "BTC", "size": "contracts"},
  "model_result": "fails",
  "execution_readiness": "not_evaluated",
  "evaluation_scope": "exhaustive_supported_terminal_model",
  "baseline": {"kind": "explicit", "price": "100000", "label": "synthetic"},
  "objective_valuation_time": "2026-01-02T06:00:00Z",
  "leg_observation_times": ["2026-01-02T06:00:00Z"],
  "worst_case": {"pnl": "-3200", "attained": true, "price": "60000"},
  "failing_intervals": [
    {"lower": "60000", "lower_inclusive": true, "upper": "82000", "upper_inclusive": false, "clause": "loss_cap", "witness": {"price": "60000", "pnl": "-3200"}},
    {"lower": "90000", "lower_inclusive": true, "upper": "92000", "upper_inclusive": false, "clause": "loss_cap", "witness": {"price": "90000", "pnl": "-1200"}}
  ],
  "profile": [
    {"lower": "60000", "lower_inclusive": true, "upper": "90000", "upper_inclusive": false, "slope": "0.1", "intercept": "-9200"},
    {"lower": "90000", "lower_inclusive": true, "upper": "110000", "upper_inclusive": true, "slope": "0.1", "intercept": "-10200"}
  ],
  "cost": {"premium": "200", "other_costs": "0", "pnl_at_baseline": "-200", "breakevens": ["102000"]},
  "reason_codes": ["LOSS_BOUND_EXCEEDED"],
  "assumptions": ["common_reference", "fixed_premium", "zero_other_costs"],
  "checks_not_performed": ["LIVE_EXECUTION", "PATH_RISK"]
}
```

The engine adds `comparisons` (no hedge; smallest exposure reduction; each other
supported instrument, with the exact intervals where the proposal is better and
worse), `size_window` with its binding constraints or its infeasibility
certificate, snapshot hashes, `semantics_version`, `engine_version`,
`input_digest`, `proposal_digest`. The result is immutable; an idempotent
response does not refresh its evidence.

**Reason codes:** `LOSS_BOUND_EXCEEDED` · `COST_BOUND_EXCEEDED` ·
`NO_FEASIBLE_SIZE_AT_PRICED_DEPTH` · `INSUFFICIENT_DEPTH` ·
`LEG_WORST_CASED_HORIZON` · `LEG_WORST_CASED_REFERENCE` · `LEG_BOUNDED_PATH` ·
`TARGET_NOT_YET_KNOWN` · `AMBIGUOUS_RULES` · `UNREVIEWED_FAMILY` ·
`BASELINE_MISSING` · `PREMIUM_EXHAUSTS_BUDGET`, the last **only** when premium
alone exceeds cap headroom at the strike.

**Horizon.** The model evaluates wealth at **one valuation time**, not the path —
so no `protection_ends_at`, no "hedged until 06:00." Show
`objective_valuation_time` and every leg's observation time, always. A mismatched
leg is worst-cased (§2) and the verdict stands on what remains. **Never substitute
the contract's time for the user's and report it as satisfying the request.**

| Situation | Behavior |
|---|---|
| Proven violation in the supported model | `fails`, a witness per failing interval |
| Objective met | `passes` — with the cost, the profile and the alternatives beside it |
| A leg was reduced (§2) | The verdict stands; the reason code names the leg and the rule |
| Proposal cannot be represented | `needs_review` plus the missing fields |
| Invalid request or computation failure | Technical error; **never** a fabricated verdict |
| Too little displayed depth | Execution blocked; the unknown remainder stays unknown |
| Old contract after rollover | Reject as candidate; preserve for replay |
| New quote changes premium | New normalized input and new result |

---

## 5. Certificates

A checker that re-adds the pieces **the engine emitted** cannot detect an engine
that omitted the strike. So it takes the normalized proposal, objective,
assumptions and reviewed semantics, and independently establishes: domain
coverage with no gap or overlap · endpoint ownership, including the strict
inequality at each strike · correspondence between proposal and pieces · the cost,
by re-walking the snapshot bytes · every comparison interval · every reduction,
against the registry rule it cites.

Asymmetric: **refuting a `fails` needs one counterexample; confirming a `passes`
needs exhaustive coverage.** Neither shows the venue data or our reading of the
contract was right — the certificate bounds the engine, not the world.

The checker shares the schema with the engine and nothing else: separate code,
ideally a separate author. Acceptance is behavioural: it must **reject corrupted
certificates**, and those fixtures come first — omitted strike · altered premium ·
changed objective · swapped endpoint ownership · truncated book · stale snapshot
hash · wrong semantics version · a reduction applied without its reason code · an
infeasibility certificate with a negative weight.

---

## 6. Semantics registry

One reviewed entry per family and version: source text with its hash or read
date, reviewer, payoff constructor, canonical reference id, observation rule,
endpoint ownership, known ambiguities, status. Instance ids are never in it.

| Family | Source | Reference | Status |
|---|---|---|---|
| `recurring.priceBinary` | Contract specifications, text retained | `hl:perp:BTC:mark-interp` | Computed; protocol-settled. Inclusivity rests on the text alone |
| `recurring.priceBucket` | Same page; index order **[V]** in three settlements | Same | Computed; protocol-settled. The top bucket has not been seen paying |
| `template.binaryPrice` | Template text **[V]** | Mapped from `priceDescription` | Computed under `deployer_settles_as_written`; strike owned by neither side |
| `template.scalarPrice` | Template text **[V]** | Same | Same assumption. Continuous, so no strike question. No live instance yet |
| `template.priceTouch` | Template text **[V]** | Same | Bounded (§2), never computed as terminal |
| Everything else | — | — | Refused |

**Reference ids** are `source:series:statistic[:window]`, never free text:
`hl:perp:BTC:mark-interp` · `hl:perp:BTC:mark-twap:60s` ·
`hl:perp:BTC:trade-twap:90s` · `pyth:BTC/USD:price-twap:90s`. The registry maps
each exact `(venue, priceDescription, seconds)` triple to one id. A mapping is
**interpreted** — the owner's reading, an assumption that surfaces in every
result — until the deployer confirms it in writing, when it becomes
**confirmed**. An unmapped string is an unreviewed reference: the leg is
worst-cased. Basis bounds between ids are declared by the user and never
defaulted; an observed historical deviation may be displayed, labeled as an
observation.

Family identifiers are whitelisted. Familiar tickers do not bypass validation. A
model may draft an entry for review; it is never in the evaluation path.

---

## 7. Build sequence

Each tier ships only through its gate. No tier has a date.

| | Deliverable | Gate |
|---|---|---|
| **T0** done | Evidence packages, reference oracle, fixtures | Five verifiers pass |
| **T1** | Engine and independent checker: multi-leg, envelope objective, profile, comparisons, sizing | Every fixture; every corrupted certificate rejected; engine, checker and oracle agree on generated cases |
| **T2** | Canonical live path: discover instances → preserve snapshots → cost at size → replay → one result screen ranking binary, bucket and exposure reduction | No hard-coded ids; replay reproduces bytes and digests; the 18 Sep case reproduces from its package |
| **T3** | A consumer: simulated approval gate, then a testnet order behind it with the order envelope the cost bound assumes, and a re-check after any partial fill | Anything but `passes` produces zero downstream calls, asserted; a partial fill triggers the re-check |
| **T4** | Deployer families, the reference registry, basis-shift reduction, `priceTouch` bound | Each reference string reviewed; Skew's written confirmation, or an explicit assumption with an ID |
| **T5** | Exact synthesis with infeasibility certificates | The checker verifies optimal structures and certificates alike |
| **T6** | Path reductions: isolated perps | Liquidation semantics reviewed from official text; every **[U]** it touches resolved |
| **T7** | Certificate checker on HyperEVM, gating CoreWriter orders | Both **[U]** items in [EVIDENCE §6](./EVIDENCE.md) resolved on testnet; the seconds-long order delay priced in |

T1 precedes T2 because the checker is what makes a live result worth showing. T3
precedes T4 because a real consumer tests the thesis, and the bucket family means
T2 already offers an instrument someone could want. **Demand evidence may reorder
T4–T7 (§8); nothing reorders T1–T3.**

**Three implementations, three languages, no shared code.** The engine in **Go**:
`math/big.Rat` is in the standard library and parses both number forms of §3
natively (`"0.17399"`, `"268000/3"` — checked), and it is the owner's most-used
language. The checker in **TypeScript** with native `BigInt`: the HIP-4 consumers
are TypeScript (hip4-kit, Outcome-xyz/hip4), and the only SDK that knows
`outcomeMeta` is `nktkas/hyperliquid`, which the T3 consumer uses for signing.
The oracle stays **Python**. All three must agree on every fixture. **The server
computes and the client verifies**: every result screen runs the checker in the
browser, so the certificate is exercised on every view and the engine never needs
to ship to the client. Rust was the alternative; its sum types and WASM target
are real advantages, but the second disappears under this split and the first
costs third-party crates in the evaluation path.

---

## 8. Demand

Unproven, and the documents so far have tested truth, not need. Treat every
statement here as a hypothesis.

A **qualified user** repeatedly builds positions that combine an exposure with
HIP-4 outcome contracts, holds an explicit bound they check today by hand or in
code, and can show the last one. Candidates: structured-position traders on the
HIP-4 front-ends · bot and agent developers with a signing step · vault builders
on HyperEVM · venues that want a payoff preview beside their order form.

Ask for artifacts, not opinions: the last proposal reviewed · the terms and price
assumptions checked · what could have been wrong even if the trade executed · the
spreadsheet or code used today · who would pay and for what · a second proposal
next week.

> **Gate: two qualified users each supplying a second real proposal, with at
> least one measurable effect on a decision or on review time.**

Working thresholds, not benchmarks: 8–12 qualified conversations, five real
proposals, two repeat users.

| Evidence | Branch |
|---|---|
| Gate met | Continue; let those users' families and objectives order T4–T7 |
| Interest, but in a case outside the current tier (perps, touch, another venue) | **Record it and reorder the tiers.** Such a person cannot validate the current tier, however engaged — and is the best evidence for the next |
| Supported cases are trivial to the people who have them | Narrow to the comparison and synthesis outputs, or stop |
| Thresholds reached with no repeat proposal | Pause development; publish the oracle, the evidence and the findings |

**Referral sources, not users:** `hip4-kit` author · Outcome.xyz maintainers ·
Skew (get `priceDescription` semantics in writing — itself evidence) · Hydromancer
· loris.tools and liquidiction · Chainstack and QuickNode guide authors (send the
precision correction, [EVIDENCE §4](./EVIDENCE.md)).

---

## 9. Business

No mechanism is established. What is known ([EVIDENCE §4, §6](./EVIDENCE.md)):
the base outcome fee is zero for now. Three official pages describe builder fees
on outcomes three ways; the most specific, marked Testnet-only, says they "can
also be applied to buy orders for outcome orders." **Exercise it on testnet in T3
before any claim**, and remember a hedge can also be acquired as a sell.

Hypotheses, in the order to test them: a paid pilot for one team and one family,
priced to cover interpretation maintenance · an embedded payoff preview for a
venue · builder fees on orders the consumer routes, once T3 has shown they are
charged.

```text
Monthly contribution = revenue − data and infrastructure − interpretation review
                     − adapter maintenance and support
```

Review labour is the dominant cost and per-call pricing does not cover it. Never
size this market from prediction-market volume; build it bottom-up from reachable
teams, checks per month, conversion and retention.

---

## 10. Demo and interview

Lead with the decision, not the settlement history: the proposal about to be
approved (instance discovered live, timestamped, baseline shown) → the objective
in full → the verdict and its witness → **the same objective through the binary,
the bucket and selling the BTC, side by side** → whether resizing helps, naming
the binding constraint → the consumer refusing to sign. **Then** 3061 and 3253, to
explain why outcomes prove nothing.

Two labeled modes, never mixed: explained fixture, and current-contract
inspection. Record a day with a non-empty window and a day with an empty one.

| Interview question | Honest answer, and the artifact |
|---|---|
| Which rule, and did you verify it? | The contract specifications page. Verified: twenty reported fractions agree with twenty reported prices. **Not** verified: inclusivity — none settled at its target — nor interpolation |
| Why not deployer markets? | Four different reference strings for one asset, fifteen naming Pyth under a "must be a Hyperliquid perp" restriction; the registry and the `priceTouch` bound |
| What happens at the threshold? | 999.90 for one dollar; endpoint ownership in the certificate |
| Can size fix it? | `D + p·A` against the cap; the window with its binding constraints; the certificate when it is empty |
| Is a passing hedge a good one? | No — the comparison table |
| Can anyone audit the settlement price? | Not from the public API; node data not examined. Say exactly that |
| What did you build during the event? | The commit history; research dated 14–18 Sep disclosed |
| Who used it? | Whatever §8 has produced, and nothing more |

---

## 11. Submission

Register on colosseum.com; every team member needs an account before submitting.
**Hyperliquid track only**, whatever the form allows: it is the one chain the
product integrates, the general pool is automatic, and claiming a track for a
deferred integration would break §13. Submit the tiers that are complete and verified at the close, with everything else
labeled proposed. Public repository, permissive license. Scope is never cut to
fit the date, and nothing unverified is presented as working.

---

## 12. Decisions

Decided 18 Sep, each on retained evidence ([EVIDENCE §1, §4, §6, §7](./EVIDENCE.md)).

| Decision | Outcome | Why |
|---|---|---|
| Name | **PayoffBounds** | "Proof" promises what §5 disclaims. "Bound" is the design's own noun — lower envelope, basis bound, bounded legs, "the certificate bounds the engine". The plural kills the reading "bound to pay off" that the singular invites. Free in all eleven namespaces; no product of that name found |
| Languages | Engine Go · checker TypeScript · oracle Python | §7 |
| Strike on the deployer path | Owned by neither side | It was never a rule to discover: deployers submit the fraction (§2) |
| Skew's written confirmation | Wanted, no longer blocking | It upgrades a reference mapping from interpreted to confirmed (§6); T4 proceeds under explicit assumptions without it |
| Reference identifiers and reviewer | `source:series:statistic[:window]`; the owner reviews, deployers confirm | §6 |
| Existing-token valuation | **Explicit only, no default**; bid-at-depth and mid are displayed as candidates. A re-check after a fill inherits the original baseline, so the premium counts once | The 18 Sep bucket-0 book bid 0.00002 against a best ask of 0.17399: any default would silently choose across a factor of about 8,700 |
| Fees | The official formula (§2); base rate as a dated assumption | No mainnet round trip is needed to learn a rate the docs state is zero |
| Tracks | Hyperliquid only | §11 |

Still open, and not decidable from this repository:

| Open | Owner | Blocks |
|---|---|---|
| How this entry shares time with Credence (Monad Metropolis, closing 13 Oct) and any other parallel entry | You | Everything |
| Register `payoffbounds` on GitHub, npm, crates.io, PyPI, `.com` and `.xyz`, and the X handle. A trademark search has not been done | You | Public repository |
| Testnet: an outcome limit order through CoreWriter action 1; whether any precompile exposes an outcome book; whether builder fees are charged on outcome buys | T3, T7 | T7 |

---

## 13. Standing rules

- Label every claim verified / third-party / unverified, with source and date.
- A universal negative states its search scope.
- "Not established from the reviewed public material," never "the only tool that."
- Run a command before documenting it. **Counts and example outputs in documents are printed or checked by a command, never remembered.**
- Every holder in an example is hypothetical and is called so.
- **No third-party dependency in the evaluation path of any implementation**: Python `fractions`, Go `math/big`, TypeScript `BigInt`.
- Instance IDs rotate: discover, never hard-code.
- Snapshots keep response bytes, endpoint, request body, retrieval time, hash.
- Assumptions and reductions carry IDs and surface in the result.
- Disclose pre-existing development.
