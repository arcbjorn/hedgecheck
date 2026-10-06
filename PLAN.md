# HedgeCheck: plan

Authoritative for what is built, why, and in what order. [EVIDENCE.md](./EVIDENCE.md) holds the
facts; [ARCHITECTURE.md](./ARCHITECTURE.md) says how it is built.
Earlier revisions and the superseded 14–15 September documents were deleted on
18 September; their corrections survive in [EVIDENCE.md §9](./EVIDENCE.md).

19 Sep 2026. Status: four evidence packages with verifiers, committed at
`085ccfb` and deliberately kept out of the working tree. In the tree: the
architecture as a running skeleton — draft schemas, the oracle kernel, the
number and canonical-JSON spine in Python, Go and TypeScript, two draft registry
entries — behind one command, `make check`. **No engine, no application.**

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
| Sizes | Whole contracts, as observed; the lot rule is confirmed in T1 |

**Reductions.** Each is one reviewable rule, sound by construction, surfaced as a
reason code — never applied silently.

| Case | Reduction | Why it is sound |
|---|---|---|
| Leg observed at a time other than the objective's valuation time | Value the leg at its worst admissible payoff: **zero** | A long, fully collateralized token pays within `[0, size]`. One settling earlier may have paid nothing; one settling later has no guaranteed value yet |
| Legs or exposure on another reference, declared basis bound `b` | Group legs by reference and take the **infimum of the group's summed payoff over the band** `[S − b, S + b]`. For a monotone payoff that is a shift — a digital below `K` becomes one below `K − b`; a linear exposure loses `q·b`. For the middle bucket it is not: `[P1, P2)` **shrinks from both sides** to `[P1 + b, P2 − b)` | The infimum over a declared band is a lower bound by definition, and piecewise affine again. A plain shift over-credits the middle bucket at prices where it may pay nothing (checked by brute force, 19 Sep). No bound declared: zero |
| Deployer-settled leg | Evaluate as written **only** under the assumption `deployer_settles_as_written`; at the strike itself the leg pays the holder **nothing, on either side**. Without the assumption: zero | The deployer submits the fraction; nothing computes it ([EVIDENCE §1](./EVIDENCE.md)). "Above" is theirs to read, so the strike is owned by neither side |
| `priceTouch`, long YES, **touch window covering the valuation time** | Lower-bound by the inclusive terminal digital at the target, on the same TWAP. Direction is the side the reference sits on while the market is still unsettled. **It is a REDUCTION, not a payoff**: it is derived in lowering from the baseline and declared as a rule with a reason code, so `pays_on` keeps transcribing the entry and a reviewer still reads one place to know what a leg pays | A terminal observation at or through the target implies a touch — checked by brute force over 4,000 paths, both directions, and the bound never exceeded the true payoff. A window that ends before the valuation time falls under the first row instead. The direction cannot live in the entry: two rows selected by `index` would work, but `index` is a term checked against the catalogue and a touch instance carries none, so it would mean inventing a term the venue never sent |
| Isolated perp with a liquidation price inside the declared **path** domain — every price between now and the valuation time, so it contains the current price and the terminal domain | The leg is worth minus its isolated margin at **every** terminal price | The path may reach the liquidation price and recover. A terminal digital cannot hedge that, and the result says so exactly (T6) |
| Unreviewed or ambiguous family | Zero, or `needs_review` if the proposal cannot be represented at all | Same bound as the first row |

Every reduction is a **lower bound**, so it can never turn a failing proposal
into a passing one. Each also declares whether it is **tight** — attained by a
nameable admissible state: the other price the leg observes, the adverse end of
the band, the deployer's adverse reading, the path that touches and recovers — or
**loose**, like valuing an unreviewed family at zero. §4 needs the distinction: a
bound nobody can attain proves nothing about failure.

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
minimum, else the midpoint. **A witness is a price plus the adverse state of every
reduced leg**, so that the unreduced payoff can be evaluated there; a price alone
is not a counterexample once any leg has been bounded. **Never round before comparing, and never sample** —
sampling cannot see the 999.90 cliff at the strike. **A function is never
separated from its breakpoints:** nothing accepts them as a separate argument,
so a strike cannot be omitted. The first oracle did accept them, and the claim
made here — that an undeclared breakpoint is an error — was false: its probe
missed a strike in the outer third of the domain and returned a wrong answer
silently ([EVIDENCE §9](./EVIDENCE.md)).

**Numbers** are exact strings: a terminating decimal when one exists, otherwise
`"p/q"` — a comparison boundary can be `268000/3`. Rounding is a display concern,
outward, and labeled. **One grammar, enforced before any library parser sees the
string:** `-?(0|[1-9][0-9]*)(\.[0-9]+)?` or `-?(0|[1-9][0-9]*)/[1-9][0-9]*`, then
reduced to canonical form before digesting. The libraries disagree with the
grammar and with each other (checked 19 Sep): Go's `big.Rat` reads `"0x10"` as 16
and `"0b101/3"` as 5/3, Python's `Fraction` rejects both but accepts `" 5"`, and
both accept `"1e3"`, `"+5"`, `".5"`, `"1_000"`, `"05"`. An approval gate whose two
halves parse the same string differently is a defect, not a nuance.

Interval length is **not a probability**. Axis label: "scenario price."

### Golden cases

`S ∈ [60000, 110000]`, `P&L(S,n) = 0.1(S − 100000) + n·I(S < 90000) − 0.2n`,
objective `P&L ≥ −1000`. Every row is asserted by `oracle/verify.py`, which
`make check` runs.

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
| A strike in the outer third of the domain, n=1,000, cap 3,500 | Failure `[65000, 67000)`; worst −3,700 at the strike. The case the first oracle got wrong |
| Deployer reading: strict below plus strict above | At the strike neither side is paid; the strike is a piece of its own |
| Band infimum, band `b` | Below `K` → below `K − b` · at or above `K` → at or above `K + b` · `[P1, P2)` → `[P1 + b, P2 − b)` · linear loses `q·b` · on an asymmetric tent it equals the hand-derived form, whose breakpoint at 102 is a crossing of two lines, not a shifted strike |

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
Sizes are whole contracts, so the program is a relaxation: round, **re-check the
rounded structure with the evaluator**, and claim infeasibility only when the
relaxation itself is infeasible. It answers a stated objective; it is not advice.

---

## 4. Result contract

The example is a projection of `fixtures/golden/1000-contracts.result.json`. It
is generated, and `make check` fails if any field here differs.

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

A complete result carries three more things, none of which the synthetic fixture
above needs:

- **`comparisons`** — `no_hedge`, and `smallest_reduction`: keep the largest holding that still meets the cap, sell the rest at the baseline, hold the cash. It costs no premium, so it is the benchmark a paid hedge has to beat. Each gives the exact intervals where the proposal is better and worse.
- **`size_windows`** — per book-walked leg: the exact bounds, the whole-contract window inside them, and which site binds each end. An empty window at a flat price carries the Farkas weights `(1−p, p)` that prove no size works.
- **`reductions`** and **`upper_profile`** — present when a lowering rule lowered a leg's value. The verdict rests on the lower profile; the upper profile is the best the proposal could be, since a long fully collateralized token is worth at most its size ([EVIDENCE §1](./EVIDENCE.md)).

**A loose bound can never fail a proposal.** Each reduction declares whether it is
`tight`. A violation the upper profile shares is real whatever the bounded legs
are worth, so it is a `failing_interval`. A violation that rests only on a loose
rule proves nothing about the real payoff: it becomes an `undecided_interval`
naming the legs responsible, and the verdict is `needs_review`. Once any leg has
been bounded, a price alone is not a counterexample, so each witness carries the
`adverse_states` that produced it.

**Comparing instruments is a separate document**
(`schema/comparison.schema.json`), built from N independent results and citing
each by `ir_digest` without restating its numbers. A result stays about one
proposal and stays independently checkable; a checker verifies the results first,
then re-derives the ranking. Only results sharing an objective, domain, baseline
and valuation time may be compared, and only passing candidates are ranked.

**`capture`** records how the evidence was gathered: the worst skew the capturer
measured across the snapshots in this result, the bound it refused above, and who
measured it. It is an **assertion, not a derivation** — the contexts response carries
no venue timestamp ([EVIDENCE §4](./EVIDENCE.md)), so the spread between a book's
venue clock and the baseline's retrieval cannot be re-derived from the bytes by
anyone, including a checker. Recording it makes a wide or stale capture visible; it
does not make it verified, and nothing here pretends otherwise.

The result also carries snapshot hashes, `semantics_version`, `engine_version`,
and three digests — `proposal_digest` of what was asked, `ir_digest` of what it
was lowered to, `input_digest` of everything that determines the result
([ARCHITECTURE §2](./ARCHITECTURE.md)). The result is immutable; an idempotent
response does not refresh its evidence.

**Digests are SHA-256 over RFC 8785 canonical JSON**, and every value is a string,
so number serialization never arises. The defaults do not agree (checked 19 Sep):
for `{"label": "cap <1000 & é"}` Go escapes `<` and `&`, Python escapes `é`,
JavaScript escapes neither — three digests for one object. The golden fixture is
plain ASCII and would never notice, so `fixtures/vectors/` carries 48 cases with
exactly those characters, and all three implementations reproduce them. The
profile is stricter than the RFC, each restriction closing a measured
disagreement ([ARCHITECTURE §5](./ARCHITECTURE.md)).

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
| The lower-bound profile meets the objective everywhere | `passes` — proven, with the cost, the profile and the alternatives beside it |
| A scenario violates it using only **tight** bounds (§2) | `fails` — proven, a witness per failing interval, each carrying its adverse states |
| The only violations depend on a **loose** bound | `needs_review`, with the undecided intervals and the legs responsible. **`fails` is never asserted from a bound no scenario attains** |
| Any leg was reduced | The reason code names the leg and the rule, whatever the verdict |
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
against the registry rule it cites · every witness, by evaluating the
**unreduced** payoff at its price and adverse states.

Asymmetric: **refuting a `fails` needs one counterexample; confirming a `passes`
needs exhaustive coverage.** Neither shows the venue data or our reading of the
contract was right — the certificate bounds the engine, not the world.

The checker shares the schema with the engine and nothing else: separate code,
ideally a separate author. Acceptance is behavioural: it must **reject corrupted
certificates**, and those fixtures come first — omitted strike · altered premium ·
changed objective · swapped endpoint ownership · truncated book · stale snapshot
hash · wrong semantics version · a reduction applied without its reason code · a
witness whose adverse state is inadmissible · a middle bucket shifted instead of
shrunk · an infeasibility certificate with a negative weight. Beside them, the
**rejected inputs**: every number string above that a library accepts and the
grammar does not.

---

## 6. Semantics registry

One reviewed entry per family and version: source text with its hash or read
date, reviewer, payoff constructor, canonical reference id, observation rule,
endpoint ownership, known ambiguities, status. Instance ids are never in it.

| Family | Source | Reference | Status |
|---|---|---|---|
| `recurring.priceBinary` | Contract specifications, text retained | `hl:perp:BTC:mark-interp` | Computed; protocol-settled. Inclusivity rests on the text alone |
| `recurring.priceBucket` | Same page; index order **[V]** in three settlements | Same | Computed; protocol-settled. The top bucket has not been seen paying |
| `template.binaryPrice` | Template text **[V]** | Mapped from `priceDescription` | Computed under `deployer_settles_as_written`; strike owned by neither side. **Reviewed 22 Sep** on those two judgements: 'above' is strict, so a holder of both sides is paid nothing at exactly one price; and the payoff holds only under that assumption, which is **[U]** because `settleFraction` is submitted rather than computed |
| `template.scalarPrice` | Template text **[V]** | Same | Same assumption. Continuous, so no strike question. No live instance yet |
| `template.priceTouch` | Template text **[V]** | Same | Bounded (§2), never computed as terminal. The bound is **implemented** (22 Sep) and **dominated by `deployer_settled`**, so it reaches no verdict today — see the `bounded` note below. **Reviewed 22 Sep**, digest `c09b0058`, once the bound existed to make a review mean something: the owner reviewed the path-dependence, the bound's direction derivation, and that the payoff rows are a bound and not the payoff. The dominance is deliberately NOT in the entry — it is how two reductions compose, which is the evaluator's rule, not a fact about the contract. See §2's touch row and ARCHITECTURE §7 |
| Everything else | — | — | Refused |

**`status` decides whether a family is evaluated at all**, and all three implementations
agree on it:

- **`computed`** — the payoff is a function of the terminal price, so the kernel
  evaluates it.
- **`bounded`** — it is not. `priceTouch` is path-dependent: whether the price ever
  touched a level is not recoverable from where it ended. §2 gives the bound — the
  inclusive terminal digital at the target, on the side the reference must travel — and
  **it is now implemented** (`lower.touch_bound`, 22 Sep): a `bounded` family named in
  `BOUNDED_FAMILIES` is lowered under its bound, and one that is not is still **refused**
  (`UNSUPPORTED_FAMILY`), because a bound that does not exist cannot be applied.
  Evaluating a bounded family as terminal would over-credit it at prices it may never
  have touched. **Nine live instances carry it** on the 18 September catalogue (EVIDENCE
  §1, re-counted 22 Sep). This line said “no such family exists yet”, which was wrong:
  the refusal was right, the reason given for it was not.

  **AND THE BOUND IS CURRENTLY UNREACHABLE — built, correct and dominated.** A zeroing
  rule beats a bound: `deployer_settled` says the leg may pay nothing at any price, while
  `price_touch` says it is worth at least the terminal digital, and the LOWER of the two
  is the one a verdict may rest on. Crediting the bound over a zeroing rule would raise
  the lower profile on a leg that may pay nothing — the one direction that can turn a
  failing proposal into a passing one. In the registry as it stands `bounded` and
  `deployer` **coincide exactly**: the only bounded family is deployer-settled, so the
  bound reaches no verdict at all. It is pinned that way on purpose, so the day a
  protocol-settled bounded family appears the arithmetic is already right, and until then
  nobody reads the touch machinery as doing work it is not doing. `price_touch_lowering`
  in `oracle/verify.py` holds both halves: the leg is worth its bound when the bound is
  its only reduction, and worth zero the moment any zeroing rule applies.
- **`refused`** — the registry has no reading. A **refusal, not a reduction**: a
  reduction still produces a verdict, and there is no verdict to produce about a payoff
  nobody has read. Worst-casing it to zero would answer a question declared
  unanswerable; `needs_review` would invite review of a reading that does not exist.

Both non-`computed` values were evaluated as if `computed` until 21 Sep — a family the
registry REFUSES produced a clean `passes`. Fixtures
`fixtures/refusals/family-bounded-not-computed` and `family-status-refused` hold it.

**The map is REVIEWED** (22 Sep, digest `d2b36412`), and that review is load-bearing:
`reference_index` returns nothing for a document whose seal does not hold, so every
deployer-templated leg then refuses with `AMBIGUOUS_RULES` rather than resolving. Until
22 Sep nothing checked it — every mapping was honoured whatever the document said about
itself, while the refusal message read "no REVIEWED mapping", a word the code did not mean.
It is not cosmetic: a mapping nobody reviewed can point a leg at the objective's OWN series,
and then the basis reduction never fires. Measured on the 18 September bucket proposal, that
turns a `needs_review` worst case of −1,923.90676 into a `passes` at −999.90676. Both the
oracle and the Go loader enforce it, and both were seen failing on a forged digest and on an
edited mapping.

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

**THE 42 PYTH INSTANCES ARE MAPPED, ruled 22 Sep.** They are 42 of the 78 templated
instances on the 18 September catalogue — 15 BTC/USD, 9 HYPE/USD, 9 US100, 9 US500, all on
venue `skew` at 90 seconds — and four map rows had refused them all as `AMBIGUOUS_RULES`,
on the ground that naming Pyth contradicts the template metadata "This market must refer to
the price of a Hyperliquid perp".

**There is no contradiction, and the retained template text settles it.** The full
`binaryPrice` description reads "Settlement is according to the {seconds}-second TWAP of
{priceDescription} price ending at {time}" — so `priceDescription` **is** the settlement
source, whatever it names. The restriction is `semanticRestriction` and constrains `{perp}`,
the market's *subject*, which is a different template field. Every one of the 42 pairs
coherently: `perp:BTC` settling on Pyth BTC/USD, `perp:HYPE` on Pyth HYPE/USD,
`perp:xyz:XYZ100` on Pyth US100, `perp:xyz:SP500` on Pyth US500. Evidence:
`research/2026-09-18/outcome-templates.json` at commit 085ccfb.

Two corrections to what those rows claimed: the count was **42, not 15**; and the US100 row
said "there is no Hyperliquid perp for US100 at all", which is wrong on the data — all nine
carry `perp:xyz:XYZ100`.

They are mapped **`interpreted`**, to `pyth:*` ids and never to `hl:*`. Mapping them does
not make them comparable: a leg observed on `pyth:BTC/USD:price-twap:90s` against an
objective stated on `hl:perp:BTC:mark-interp` earns **`basis_unbridged`** and is worth zero
unless the owner declares a bound — verified on outcome 3069. That is the honest answer, and
it is why refusing was the wrong one: refusing discarded 54% of the live catalogue to avoid a
question the basis rule already answers correctly. What stays ambiguous is what genuinely
names no series: `1-minute candle` (18 instances, no source, no instrument, and a 300-second
window contradicting its own stated period) and `xyz:CL` (1, a bare ticker). 19 of 78.

**THE ASSUMPTION VOCABULARY IS CLOSED**, from 22 Sep. An assumption is the one part of a
result whose entire content is what it MEANS to a reader, so a name nobody can interpret is
worse than a missing one. Until this rule, `proposal.assumptions` was typed as any slug and
nothing checked the name: a proposal declaring `nothing_can_go_wrong` validated, lowered, and
was carried into the result's own list beside `zero_base_fee` with equal standing. Three names
are defined, each with what declaring it asserts, and lowering refuses anything else with
**`ASSUMPTION_UNKNOWN`**:

| Assumption | What declaring it asserts | Enforced by |
|---|---|---|
| `zero_base_fee` | the venue charges no base fee on an outcome trade | lowering requires it: a cost bound read off a book is wrong by the fee if there is one |
| `deployer_settles_as_written` | the deployer settles as the template is written | `template.*` registry entries require it; `settleFraction` is submitted, not computed (EVIDENCE §1) |
| `common_reference` | the holder BELIEVES every leg is observed on the objective's series | nothing — it is a note, deliberately |

**`common_reference` is a note and not a gate.** The basis reduction rests on the RESOLVED
references, not on an assertion about them, so letting a declaration switch it off would let a
proposal assert its way out of the reduction that exists to catch exactly that error. It stays
in the vocabulary because proposals carry it and a reader should be able to look it up.

Enforced in lowering rather than the schema: narrowing `slug` to an enum would make
previously-valid documents invalid, needing a new `schema_version` and every pinned document
regenerated, and the vocabulary is a semantic rule like the family whitelist rather than a fact
about JSON shape. Both the oracle and the engine carry the list, and `oracle/verify.py` checks
they are the same list and that every name in it is actually used by something.

Family identifiers are whitelisted. Familiar tickers do not bypass validation. A
model may draft an entry for review; it is never in the evaluation path.

---

## 7. Build sequence

Each tier ships only through its gate. No tier has a date.

| | Deliverable | Gate |
|---|---|---|
| **T0** done | Evidence packages, reference oracle, one fixture — at `085ccfb` | Five verifiers pass after the restore |
| **T1** Contract, on real data — **done, 19 Sep** | The live canonical check end to end **on the oracle**: discover instances → coherent snapshots → proposal → lowering → verdict, cost, alternatives → replay. Schema v1 frozen ([schema/CHANGES.md](./schema/CHANGES.md)). Fixtures: the 18 Sep replay, a 19 Sep live capture, fourteen certificate bundles. | Every line proved by a command, below |
| **T2** Engine — **done, 21 Sep** | Go. A **pure evaluator** — library and CLI, proposal and snapshots in, result out, no I/O — then the live adapter, the service, and one result screen ordering binary, bucket and exposure reduction by the cost of the smallest passing size | **Frozen v1 schemas, not drafts: a shape change now needs a new `schema_version` and a row in `schema/CHANGES.md`.** A snapshot's hash says nothing about its shape, so a leg citing the catalogue where a book belongs is refused, never a crash (T1 found this by crashing). Byte-identical results to the fixtures; agreement with the oracle on generated primitives; replay from stored snapshots reproduces the result byte for byte; T1's adapter deleted |
| **T3** Checker and consumer — **done, 21 Sep, except the live testnet order** | TypeScript checker, run by the result screen on every view. Then a simulated approval gate, then a **testnet** order behind it, with the order envelope the cost bound assumes, and a re-check after any partial fill | Returns the closed classes in `refusal.schema.json`, so a disagreement with `oracle/refuse.py` is a real one. **A checker that re-adds the pieces the engine emitted proves nothing** — it must establish domain coverage, endpoint ownership and proposal-to-pieces correspondence independently, and evaluate each witness on the *unreduced* payoff. Every corrupted certificate and rejected input refused; engine and checker agree on every fixture; anything but `passes` produces zero downstream calls, asserted; a partial fill triggers the re-check, whose result — top up as a new proposal, or unwind — is the consumer's policy and never the gate's |
| **T4** — **done, 22 Sep** | Deployer families, the reference registry, the band reduction, the `priceTouch` bound | Each reference string reviewed; **every deployer-settled payoff reduced, not assumed** — `settleFraction` is submitted, so no confirmation from a deployer can bind their next settlement or anyone else's (EVIDENCE §1, and the corrected belief in §9). A deployer leg is worst-cased under a loose rule, so it can make a proposal need review and can never make one fail; fixtures for the shrunk middle bucket and for mixed legs on one foreign reference |
| **T5** — **done, 22 Sep** | Exact synthesis with infeasibility certificates | The checker verifies optimal structures and certificates alike; every rounded structure re-checked. **Built so far:** `constraints` turns the objective into exact finite rows (verified against the kernel's own infimum, not asserted), `_simplex` solves the relaxation in exact rationals under Bland's rule, and its phase-one dual is the Farkas certificate — checked as `y >= 0`, `A^T y <= 0`, `b . y > 0` rather than trusted. Rounding is UP and the rounded structure is re-checked, so `rounding_failed` says the search found nothing and never "nothing exists". §3's worked example reproduces: infeasible, and §3's own two-row certificate is valid on these rows. **Document and schema done 22 Sep:** `schema/synthesis.schema.json` is the eleventh schema, carrying the QUESTION as well as the answer — a checker that re-added the numbers the solver emitted would be confirming arithmetic, not verifying a claim — and carrying no solver state, since a certificate needing the search replayed would not be a certificate. The certificate's weights NAME their sites and are sparse, so row order is not an implicit contract between three implementations. Go reads it (`doc.ReadSynthesis`), and both sides refuse the same eight malformed documents for the same reasons. Two candidates at once is exercised: at a −2,000 cap the answer is a MIXTURE (250 at 90,000, 2,000 at 80,000, cost 250) and no pure position in the cheaper strike meets that cap at any size — which is the answer per-leg sizing cannot reach. **The checker verifies it, 22 Sep — T5's exit criterion.** `checker/src/synthesis.ts` rebuilds the constraint rows from the base and candidates the document carries, through its own kernel and its own MAXIMAL-PIECE derivation rather than the oracle's atom walk, and never solves: a feasible answer is one evaluation of the rows at the reported sizes, an infeasible one is one multiplication of the certificate. 20 fixtures — 5 answers accepted, 15 corruptions each refused with exactly its class, and 9 of them with the refusal's own REASON pinned too, because `CERTIFICATE_WEIGHTS` cannot tell an unknown site from a certificate that proves nothing. Building it found two real defects, both listed in [EVIDENCE §9](./EVIDENCE.md). **The Go engine solves too** (`engine/synthesise`), so all three implementations do their own job on synthesis: the oracle is the reference, the engine answers, the checker verifies. Go derives its rows from maximal pieces like the checker and unlike the oracle's atom walk, and all three independently pin the PLAN §3 program to the same four constraints. **The bar for agreeing is NOT byte equality**, decided before writing it: an LP's optimum is unique but its ARGMIN is not, so two implementations can return different optimal vertices and both be right. Measured: with two candidates at the same price, `(1250, 0)` and `(0, 1250)` are both optimal at a relaxed cost of 250, and which one comes back depends on the pivot order. Demanding one of them would test the pivot rule rather than the arithmetic. So the bar is **(status, relaxed optimum cost)** — both determined facts about the program — with each implementation's own answer then checked VALID against the rows rather than compared to the other's. Byte equality stays the bar for evaluation, where the answer really is unique. **125 questions**, of which 120 are drawn by the same explicit LCG the kernel cases use — so the three agree on programs none of their authors chose, which is what evaluation has had since T2 and synthesis lacked until now. Every infeasible answer's certificate is checked valid on both sides, which is what reaches the flipped-row sign correction: 562 of the corpus's 686 rows flip, and 2 of the 64 carried weights sit on one |
| **T6** — **done, 22 Sep** | Path reductions: isolated perps | Liquidation semantics reviewed from official text, portfolio margin included; every **[U]** it touches resolved. **Resolved from RETAINED evidence, with no new fetch:** `085ccfb` records that outcomes "do not involve leverage or liquidations", so the HEDGE is safe and the EXPOSURE is not — which is why this is an exposure rule and why `linear_spot` could never express it. `proposal.exposure` gains an `isolated_perp` branch carrying `liquidation_price` and `isolated_margin`, both ADDITIVE so `schema_version` stays `"1"`. **`liquidation_price` is declared, never derived**: no maintenance-margin formula has been read from official text here, and computing one would be asserting arithmetic this project cannot show — so it is declared like a basis bound and the reduction fires on it. The path domain IS derived: the hull of the terminal domain and the baseline, since the path passes through the one and reaches the other. With the liquidation price inside it the holding is worth minus its margin at **every** terminal price, and the rule is **TIGHT** — the adverse state is admissible, not merely unproven, so unlike `price_touch` it can and does fail a proposal. All three implementations derive it independently; `fixtures/bundles/good-liquidated` is the only good bundle that fails for a reason on the exposure rather than on a leg |
| **T7** — gate done 22 Sep, live order outstanding. **AND THE TIER IS RENAMED**: a chain cannot check a certificate, so calling it that overstated what was built. It is an APPROVED-ORDER GATE | ~~Certificate checker~~ **Approved-order gate** on HyperEVM, gating CoreWriter orders. On-chain the cost is bounded by `limit price × size`, so **no book read is needed** | An outcome limit order through CoreWriter accepted on testnet; the seconds-long delay priced in; stated plainly that an `Ioc` order can fill partly and no on-chain gate can undo that. **All three claims in that criterion are now VERIFIED from retained evidence** (`085ccfb`, `interacting-with-hypercore.md`): the delay is the venue's own, and stated with its reason — order actions from CoreWriter "are delayed onchain for a few seconds" so HyperEVM gives no latency advantage; the cost bound holds because the order carries both `limitPx` and `sz`, so a gate needs the order and not the market; and `Ioc` is the venue's own tif, whose remainder is cancelled. **`consumer/src/corewriter.ts`** encodes action 1 — `0x01`, three big-endian action bytes, then seven 32-byte ABI words — checked against the retained page's own worked example rather than round-tripped through itself. It is PURE, and that is proved rather than asserted: the same scan that holds `gate.ts` to no fetch, no signing and no key now covers it. **`onchain/src/ApprovedOrderGate.sol`** holds an owner-set allowlist of approved certificate digests and sends a CoreWriter action only when it is the order that digest authorised — at no worse a price, no larger a size, and no more than the approved cost, all integer comparisons in the scaled domain. Its Solidity encoder and the TypeScript one in `consumer/` produce **byte-identical** actions, pinned.

**WHY IT IS NOT A CERTIFICATE CHECKER, and the tier is renamed rather than the claim stretched.** Verifying a certificate means rebuilding the payoff profile and re-deriving the verdict — canonical JSON, exact rationals, piecewise functions, infima. That is a fourth kernel at enormous gas. And it could not be sound even then: **the evidence cannot be established on chain.** A cost bound is walked from an order book, and retained evidence lists the read precompiles as "perps positions, spot balances, vault equity, staking delegations, oracle prices, and the L1 block number" — no order book. So the trust boundary is stated instead of hidden: the owner checks the certificate off chain with `checker/`, approves its digest, and the gate holds the order to it. That replaces "trust whoever calls the sender" with "trust the digest the owner approved" — a real reduction, not a proof.

No dependencies: `forge-std` is not used, so the tests are plain Solidity, and the target is skipped with a notice where `forge` is absent. **Outstanding:** the live order, which stays the owner's to run by hand |

**T1's gate, line by line.** Each line and the command that proves it. Run
`make check` to run them all.

| Gate line | Command | What it prints |
|---|---|---|
| No hard-coded ids | `cd engine && go test ./discover/... .` | discovery finds the live instruments in a retained catalogue without being told which they are, and `TestNoLiteralInstrumentsOutsideTests` refuses any outcome id or coin literal in non-test source |
| Snapshots in one result retrieved within a stated skew, recorded in it | `python3 oracle/verify.py` | The good bundle's result carries `capture`: −687 ms against a 5,000 ms bound, over the 2 snapshots it lists. **It is an assertion, not a derivation** — see §4 |
| Replaying the 18 Sep package reproduces the table in [EVIDENCE §3](./EVIDENCE.md) | `python3 oracle/verify.py` | `the 18 September replay` agrees: both premiums, P&L at baseline, strike and floor, both size windows, both crossovers |
| Every fixture validates against the schema | `python3 tools/validate.py` | `27 contract documents valid, 36 mutations refused` |
| Each expected result is pinned by hand-derived assertions | `python3 oracle/verify.py` | Constants transcribed from `git show 085ccfb:research/2026-09-18/verify.py`, where they were hand-derived; an independent recomputation reproduced all 34 |
| One command runs everything, this file's guard included | `make check` | `all checks passed`, including the guard that compares this file's example block with the generated fixture |

Two things T1 did **not** establish, stated because the gate did not ask and a
reader would assume otherwise: at T1 the registry entries were still **model drafts**,
so every live result was `needs_review` (the owner reviewed both on 21 Sep — see T3
below); and `oracle/refuse.py` is a reference, not the checker T3 builds.

**What T1 taught, and what it changes.** Four things, each learned by being wrong
about it first; the T2 and T3 rows above carry the consequences.

1. **A hash identifies bytes, not a shape.** A leg citing the catalogue where a
   book belongs crashed lowering with `KeyError: 'levels'`. Every snapshot a tier
   reads must be shape-checked before it is indexed. T2 inherits this at every
   adapter boundary.
2. **The result contract was a third larger than anyone predicted.** `size_windows`,
   `comparisons.smallest_reduction`, `reductions`, `upper_profile` and `capture` all
   arrived from real questions, not from design. Freezing v1 before the contract met
   live data would have frozen it wrong — which is exactly why T1 ran first, and why
   T2 now builds against a shape that has been used.
3. **A guard that overlaps another proves less than it looks.** Removing the profile
   coverage check alone did not make any fixture pass: endpoint ownership caught it.
   Only removing both let a corrupted bundle through. T3 should expect the same of
   its checker and test removals in pairs, not singly.
4. **Some claims can never be re-derived, and must say so.** `capture` records a skew
   no checker can confirm, because the contexts response carries no venue timestamp.
   T2 and T3 must carry it without implying it was verified. A field that looks
   checked but is not is worse than one that is plainly asserted.

**Why T1 runs on the oracle.** A contract frozen before it meets live data gets
frozen wrong, and then implemented wrong three times. The oracle is already exact
and is the most-verified thing here; `capture.py` and the 18 Sep verifier are
most of a live path already. So the first tier is a spike that does two jobs:
it fixes the schema against real catalogues, books and holdings, and it puts a
real check in front of a qualified user (§8) before two more implementations
exist. Its adapter is throwaway and T2 deletes it; the oracle stays. The earlier
order — engine and checker first, "because the checker is what makes a live
result worth showing" — was wrong: a person needs a correct result, which the
oracle gives; a *machine* needs the checker, and the machine arrives in T3.
**Demand evidence may reorder T4–T7 (§8); nothing reorders T1–T3.**

**Two full implementations and one oracle, three languages, no shared code.** The
engine in **Go**: `math/big.Rat` is in the standard library, behind the grammar
of §3, and Go is the owner's most-used language. The checker in **TypeScript**
with native `BigInt`: the HIP-4 consumers are TypeScript (hip4-kit,
Outcome-xyz/hip4), and the only SDK that knows `outcomeMeta` is
`nktkas/hyperliquid`, which the T3 consumer uses for signing. The oracle stays
**Python** and stays small: it owns the kernel — failing sets, infima, profiles,
size windows, the band infimum — and lowering for the canonical families only,
which is what T1 needs to fix expected results. Its scope stops there. Generated
cases are compared across all three at the level of the kernel; whole results are
compared between engine and checker ([ARCHITECTURE §6](./ARCHITECTURE.md)). **The server computes and
the client verifies**, so the certificate is exercised on every view and the
engine never ships to the client. Rust was the alternative; its sum types and
WASM target are real advantages, but the second disappears under this split and
the first costs third-party crates in the evaluation path.

**Shape of the tree**, and of the system, is in [ARCHITECTURE.md](./ARCHITECTURE.md):
a proposal written in contract families is *lowered* to four exact primitives and
a kernel evaluates those; every reduction of §2 is one lowering rule. Evidence
packages stay in history; a fixture copied from one cites the source file's
SHA-256, so its provenance is checkable against `085ccfb`.

**Keys.** T3 is the first tier that signs anything. Testnet only, an agent wallet
only, never a main-wallet key on disk; `ApproveBuilderFee` needs the main wallet
and is done by hand.

**Closing T2 and T3, 21 Sep.** Both gates pass under `make check`. What closed them,
and what each tier learned by being wrong first:

- **T2's gap audit (8b)** ran last, and it was the part with no adversarial coverage.
  It found the service open to any web page the operator visits: a cross-origin
  `text/plain` POST returned 200 and the check RAN, `Host` was not validated so a
  DNS-rebound name was served as localhost, and a result file swapped on disk was
  served as authentic. Binding to `127.0.0.1` keeps other MACHINES out, not other
  PAGES. Also: the purity guard banned `os` and `net` but not impure packages of this
  project's own, so the kernel could import `store` and stay green; and three enums the
  schemas constrain were read by Go as bare strings, one of them the field that says
  whether an order envelope may exist. Report:
  `hc-audit-t3-report/09-t2-gap-audit-8b.md`.
- **T3's adversarial audit** found the gate could place an order the checker never
  verified (`bundle.result` read twice, so an accessor could answer differently the
  second time: verified 924 contracts, placed 999999), and the private key printed in
  decimal into the log the runbook tells the operator to retain. Reports `03`–`08`.
- **The lesson both tiers share.** A guard that reads SOURCE TEXT is a lint, not a
  proof. Measured rather than assumed: an obfuscated `fetch` wrapped in `try/catch`
  passes every grep AND every behavioural test, and only the runtime tripwire harness
  catches it. §7's "Lints and proofs" in ARCHITECTURE.md carries this.
- **The registry.** The owner reviewed both entries on 21 Sep, weighing and accepting
  the `[U]` on bucket index order for testnet. The allowlist carries both digests and a
  good bundle now reaches `APPROVED`. A review cannot sign itself — the digest is taken
  over the entry WITHOUT its `review` key — and editing a reviewed entry invalidates it,
  both verified by mutation.

**What T3 has NOT established, and will not until the owner runs it.** The live testnet
order. It is the one step no agent performs, and `consumer/RUNBOOK.md` is written for a
human to follow with a key in their environment. Two things about it are worth stating
where the gate is, not only in the runbook:

- **It cannot be run today, and the binding reason is liquidity after all.** Corrected
  22 Sep. What was written here — "no expiry carrying both a binary and a bucket" — is true
  but was the wrong blocker, because **a bucket is not required.** Testnet carries no price
  bucket of any kind (the only `*Bucket` outcomes are `policyRateBucket`, on Fed rates), but
  it does carry **strike ladders of binaries at one expiry**: `BTC` at `20260921-1200` has
  three at 81,100 / 81,500 / 81,900, same 90-second TWAP, same `priceDescription`; both
  `xyz:AAPL` and `xyz:XYZ100` at `20260921-1900` have five each. A long position plus YES at
  one strike and NO at another is a hedge this project verifies, and it needs no bucket. So
  the market SHAPE exists on testnet routinely. **Re-measured 23 Sep: THE BLOCKER IS GONE, and
  the 22 Sep claim was a measurement bug of mine, not a fact about the venue.** The probe asked
  for `#10218` — the raw outcome id — where the coin is `'#' + (10*outcome + side)`; a wrong
  coin answers `null`, which the probe reported as an empty book. `discover.go` had the rule
  right. Swept properly (`tools/sweep_testnet.py`, all 618 outcomes, both sides): **114 of
  1,236 books quoted, 56 structured price markets, 28 of their books quoted.** `xyz:AAPL` at
  `20260923-1900` has five strikes with asks on both sides at several; `BTC 70000` at
  `20260930-1200` is quoted on both. The two retained instances have separately EXPIRED
  (`null`, not empty — different facts). The remaining quoted depth is World Cup and CPI
  markets, which lowering refuses as price legs rather than inventing a series for.
  Meanwhile every bundle in
  the repository is built from MAINNET books and carries coin `#39710`, asset id
  `100,039,710`; testnet's outcomes are 10217–20497, a disjoint range. **Aiming an
  existing bundle at testnet would sign an order for an instrument that does not exist
  there** — and the gate cannot catch it, because the bundle is internally consistent
  and the check is sound. `run.ts` now refuses `--send` without an explicit
  `--bundle-is-for-this-network`, since nothing inside a bundle records its network.
- **The blocker is discovery, not liquidity — found 23 Sep by RUNNING the live path.**
  `hedgecheck check --live --network testnet` refuses with
  `no expiry with both a binary and a bucket for BTC`,
  because `engine/discover/discover.go` requires both and testnet carries no price bucket at
  all. The sentence above — that a ladder hedge "needs no bucket" — is true of
  the EVALUATOR and false of DISCOVERY, and three days of liquidity claims were aimed at the
  wrong thing. Measured exhaustively: of 56 structured price markets, 17 lower, 14 have asks,
  10 do both, and all 10 are `xyz:*` referenced to Pyth — so they earn `basis_unbridged`,
  yield `needs_review`, and the gate refuses them. The one BTC ladder that lowers cleanly
  (`'the Hyperliquid BTC perp trade'` @90s, `20260923-1200`, three strikes, already mapped) has
  0 bids and 0 asks on all six sides. **Supporting the ladder shape in discovery is a design
  change and the owner's call; it is not a fix to make quietly.**
- **The live path returned its first PASSING verdict on 5 October, and it is retained.**
  `check --live --network mainnet` on BTC at a 2,000 cap: **987 contracts, premium 350.3793,
  worst case −1,999.3793** attained at the floor, inside the cap by 62 cents. Spot 86,360 sat
  ABOVE the target 85,749, so the NO leg was out of the money and asked **0.3547** — against
  0.99999 for the eleven preceding days, when every cap was correctly refused. The bundle is
  `fixtures/live/2026-10-05/`, each snapshot digested as `sha256` of the venue's bytes exactly
  as they arrived, and `python3 tools/replay_live.py fixtures/live/2026-10-05` rebuilds a store
  from those bytes and replays byte-identically with no network. `make check` holds the figures
  against the bytes AND against the hand arithmetic, both candidate worst cases derived
  separately so the binding price is identified rather than assumed. **This does not close the
  T7 criterion**, which asks for an order ACCEPTED on testnet; it settles everything up to the
  send, on a book nobody had seen before.
- **The ladder is not being built, decided 24 Sep, and the reason is that it was scoped
  against a premise that turned out false.** It was proposed to route around discovery's
  binary-and-bucket requirement on testnet. But **mainnet pairs a binary and a bucket at one
  expiry every day** — `20260919-0600`, `20260920-0600`, `20260921-0600` in the three retained
  catalogues and `20260924-0600` live — so the full pipeline already runs end to end on mainnet,
  read-only, with no code change. The road the ladder was a detour around is open. Scope was
  also understated when it was proposed: `discover.Candidates` returns two *alternatives* and
  `run.go` builds one SINGLE-LEG proposal from each, so a ladder is a multi-leg proposal
  builder plus a screen change plus new lowering paths, in all three implementations or the
  conformance guarantee breaks — the most exactness-critical code in the project. And it would
  not have helped today regardless: the current refusal is about PRICE, not shape. Every
  recurring binary NO across BTC, ETH, SOL and HYPE is in the money at 0.98–0.99999, and the
  only genuinely quoted BTC bucket side is index 1, which pays when price RISES into
  84,823–88,286 — the wrong direction for a long holder, and cheap precisely because it
  probably will not pay. `discover.go` taking `named[0]` is correct: index 0 is the leg that
  pays on a fall. A ladder over those same books inherits the same prices and the same
  refusal. If a real use case appears it should be re-scoped from scratch, because this
  scoping was wrong.
- Everything up to the send is proved offline against a fake exchange: the envelope, the
  msgpack encoding and EIP-712 digest (both derived by hand from their specs and matched
  byte for byte), one send with no retry, and a re-check after a partial fill.

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
| Why not deployer markets? | Four different reference strings for one asset, **42 of 78** settling on Pyth while the template restricts the SUBJECT to a Hyperliquid perp; the registry, the reference map and the `priceTouch` bound |
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
deferred integration would break §13. Submit the tiers that are complete and
verified at the close, with everything else labeled proposed. Public repository, permissive license. Scope is never cut to
fit the date, and nothing unverified is presented as working.

---

## 12. Decisions

Decided 18 Sep, each on retained evidence ([EVIDENCE §1, §4, §6, §7](./EVIDENCE.md)).

| Decision | Outcome | Why |
|---|---|---|
| Name | **HedgeCheck** | The owner's call, 19 Sep: it says what the product does, and this is a hackathon project. A firm called HedgeCheck LLC exists ([EVIDENCE §7](./EVIDENCE.md)); that was noted on 15 Sep and never examined. If Colosseum asks for a change, PayoffBounds was free everywhere on 18 Sep |
| Languages | Engine Go · checker TypeScript · oracle Python | §7 |
| Build order, revised 19 Sep | The contract is frozen on real data, on the oracle, before the engine and the checker exist | §7. It reverses the 18 Sep order |
| Architecture, 19 Sep | A compiler: proposal → lowered proposal → result. One digital primitive whose endpoint ownership is data. A function never separated from its breakpoints | [ARCHITECTURE.md](./ARCHITECTURE.md). The conformance spine exists in all three languages before any engine does, because that seam was the measured risk |
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
| Testnet: an outcome limit order through CoreWriter action 1; whether builder fees are charged on outcome buys. Whether a precompile exposes an outcome book no longer matters (§7, T7) | T3, T7 | T7 |

---

## 13. Standing rules

- Label every claim verified / third-party / unverified, with source and date.
- A universal negative states its search scope.
- "Not established from the reviewed public material," never "the only tool that."
- Run a command before documenting it. **Counts and example outputs in documents are printed or checked by a command, never remembered.**
- Every holder in an example is hypothetical and is called so.
- **No third-party dependency in the evaluation path of any implementation**: Python `fractions`, Go `math/big`, TypeScript `BigInt`.
- **One number grammar and one canonical JSON form across every implementation**, fixed by vectors, never by a library's defaults.
- The evaluator performs no I/O. Adapters fetch and normalize; the evaluator only computes. **Boundaries are held by tests, and a guard is trusted only after it has been seen to fail.**
- A function is never separated from its breakpoints.
- A rule that lowers a leg's value is a reduction: it is a lower bound, it says whether it is tight, and it can construct its adverse state.
- Instance IDs rotate: discover, never hard-code.
- Snapshots keep response bytes, endpoint, request body, retrieval time, hash.
- Assumptions and reductions carry IDs and surface in the result.
- Disclose pre-existing development.
