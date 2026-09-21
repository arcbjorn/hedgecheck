# HedgeCheck: architecture

How the system is built. [PLAN.md](./PLAN.md) says what, why and in what order;
[EVIDENCE.md](./EVIDENCE.md) holds the facts. Where this file and the plan
disagree about *order or scope*, the plan wins; about *structure*, this file does.

19 Sep 2026, **T1 closed.** What exists is one complete check, on real data, on
the oracle: the contract as **frozen v1 schemas**, discovery that names no ids,
lowering from retained bytes, an exact result with its cost, sizing, alternatives
and witnesses, a reference refuser that refuses fourteen certificate bundles by
class, and a live path that captures and replays byte for byte. The conformance
spine stands in three languages; **the engine and the checker do not exist yet**
— T2 and T3 build them. Everything below marked with a tier is design.

```sh
make check    # vectors, bundles, schemas, oracle, Go, TypeScript. Offline, no install
```

---

## 1. Shape

A compiler. A proposal written in terms of contract families is **lowered** to a
small exact intermediate form; a **kernel** evaluates that form and knows nothing
about venues, families or the network.

```text
 venue API ──adapter──▶ snapshots (bytes, by SHA-256)
                              │
 request ──normalize──▶ PROPOSAL ──lower──▶ LOWERED PROPOSAL ──evaluate──▶ findings ──assemble──▶ RESULT
 (families, instances,     │   ▲  registry     (primitives only:            (failing sets,          (verdict, cost,
  snapshot hashes)         │   │  reductions    linear, cash,                infima, windows,        alternatives,
                           │   │  cost walks    indicator, ramp)             comparisons)            certificate)
                           │   └── semantics registry (reviewed data)
                           └──────────────────────────────────────────────────────────────▶ CHECKER
                                                         re-lowers, re-evaluates, accepts or refuses
```

Three consequences carry the design:

- **Every hard case is a lowering rule, not a second engine.** A horizon mismatch,
  a foreign reference, a deployer's reading, a touch contract, a liquidatable perp:
  each rewrites legs into the same four primitives (§4).
- **The kernel is small enough to write three times.** Lowering is written twice.
  Nothing else needs independence (§6).
- **The checker has a seam to cut at.** It verifies the lowering and the
  evaluation separately, so a wrong registry reading and a wrong computation are
  different failures with different evidence.

---

## 2. Documents

Four contract documents, each with a draft schema in `schema/`. All are inside
the canonical JSON profile (§5): no numbers, no nulls, no user-chosen keys.

| Document | Schema | Holds | Digest |
|---|---|---|---|
| Proposal | `proposal.schema.json` | Exposure, legs **by family and instance**, sizes, objective, baseline, assumptions, basis bounds; snapshots cited by SHA-256 | `proposal_digest` |
| Lowered proposal | `ir.schema.json` | Primitives with fixed costs, clauses, domain, baseline price, and the list of reductions applied | `ir_digest` |
| Result | `result.schema.json` | Verdict, witnesses, profile, cost, comparisons, reason codes, assumptions, digests | — |
| Registry entry | `registry-entry.schema.json` | One reviewed reading of one family, as data | `semantics_version` |
| Comparison | `comparison.schema.json` | N results ranked against each other, cited by `ir_digest` | — |

`semantics_version` is the canonical digest of a registry entry **without its
`review` key**, so a proposal pins a reading rather than a review state: the owner
marking an entry reviewed does not move the pin. `review.digest` records which
`semantics_version` was reviewed, and an entry counts as reviewed only when its
state is `reviewed` **and** that digest still matches. Editing the semantics
therefore silently un-reviews the entry rather than carrying an approval forward.

A **comparison** never restates a result's numbers. It cites each by `ir_digest`
and repeats only the terms its candidates must share — objective, domain,
baseline, valuation time — so a checker can confirm they answer the same question
without opening them. Each result therefore stays about one proposal and stays
independently checkable, and the ranking is re-derived rather than trusted. Only
passing candidates are ranked: a cost that bought an unestablished result has no
place in an ordering by cost.

**Capture provenance.** A result records `capture`: the worst skew the capturer
measured across its snapshots, the bound it refused above, and who measured it. This
is an **assertion, not a derivation**. The contexts response carries no venue
timestamp ([EVIDENCE §4](./EVIDENCE.md)), so the spread between a book's venue clock
and the baseline's retrieval is measurable only at capture time and can never be
re-derived from the bytes. Recording it makes the claim visible to a reader and to a
checker; neither can confirm it, and the documents say so rather than implying the
kernel established it. A result also lists the `snapshots` it rests on, which a
checker *can* re-derive and compare.

`input_digest` covers everything that determines a result except the engine:
`proposal_digest`, the snapshot hashes, the `semantics_version` of each entry
used, and the schema version. Same `input_digest`, same `engine_version` ⇒ the
same result, byte for byte. A result is immutable; a new quote is a new input.

A **snapshot record** (`snapshot-record.schema.json`) sits beside retained
response bytes. It is evidence, not contract: hashed as a file, never
canonicalized, and it keeps the JSON numbers the venue's API requires. The schema
matches all 50 records retained at `085ccfb`.

A **run document** (`var/store/runs/<input_digest>.json`) is the same kind of
thing: an operational record of one capture, written so a replay can recompute it
without fetching. It is **not** a contract document and is held to no schema. It
could not be canonical even if it wanted to be — it keys `digests` and `skew` by
leg id, and a leg id may contain a hyphen (`[a-z][a-z0-9-]*`) where a canonical key
may not (`[a-z][a-z0-9_]*`), and it carries venue timestamps as JSON numbers where
the profile demands exact strings. Both canonical readers refuse it, correctly.
What *is* canonical is every result embedded inside it: those carry the digests a
replay checks and go through the strict reader, so the envelope is untrusted and
its contents are not.

**The schemas are frozen at v1.** They met real data before freezing: the 18
September replay proposals were lowered and evaluated against the retained
catalogue, mark and books, and the certificate bundles were built from the
results. Every change since `062a245` is in [schema/CHANGES.md](./schema/CHANGES.md)
with the case that forced it, and `make check` fails if a schema file changes
while that log does not.

---

## 3. Kernel

One exact algebra of functions of a single reference price on a closed domain.

**Vocabulary.** `linear(quantity, baseline)` · `cash(amount)` ·
`indicator(size, interval)` · `ramp(size, low, high, direction)`. An `indicator`
pays on an interval **whose endpoint ownership is data**: canonical NO is
`(−∞, K)`, canonical YES `[K, ∞)`, the middle bucket `[P1, P2)`, a deployer
binary `(−∞, K)` and `(K, ∞)` with the strike owned by neither. There is no
convention to get wrong, and no fifth primitive for a new digital.

**Operations.** Sum and difference · atoms (each breakpoint, each open interval
between neighbours) · maximal affine pieces with ownership · infimum, with whether
and where it is attained · the exact set where a function is below a threshold ·
an admissible witness · the band infimum `inf over [S − b, S + b]` · the size
window under a convex displayed-depth cost. Comparisons between alternatives are
the below-set of a difference. That is the whole kernel.

**Representation rule.** *A function is never separated from its breakpoints.*
In the engine and the checker a function **is** its list of pieces. In the oracle
it is an `Fn` — a rule plus the breakpoints it is affine between — built only by
constructors and sums; no evaluation function accepts breakpoints as an argument.
The first oracle did, and its affinity probe was described as turning an omitted
breakpoint into an error. It does not: the probe samples three points per
interval, so a strike in the outer third of the domain was missed silently and
gave a wrong failing set and a wrong infimum (EVIDENCE §9). The probe stays, as a
tripwire for a constructor that hides a kink; `oracle/verify.py` asserts both what
it catches and what it cannot.

Exact arithmetic throughout: Python `fractions`, Go `math/big`, TypeScript
`BigInt`. No floating point anywhere in an evaluation path, enforced (§7).

---

## 4. Lowering

Lowering turns a proposal into a lowered proposal, deterministically, from three
inputs only: the proposal, the registry entries it pins, the snapshot bytes it
cites. It has four steps.

1. **Resolve.** Each leg names a family, a side, its terms, and the
   `semantics_version` it was written against; a pin that no longer matches the
   entry's semantics is refused, `SEMANTICS_PIN_MISMATCH`. The registry entry maps
   `(side[, index])` to one or more `indicator`s over the leg's terms — NO on the
   middle bucket is two. An entry that is not reviewed — state not `reviewed`, or a
   `review.digest` that no longer matches its `semantics_version` — is refused:
   `UNREVIEWED_FAMILY`.

   An entry that is not reviewed is **not** refused: it is reduced by
   `unreviewed_family`, which values the leg at zero while its premium still
   counts. That rule is loose, so the proposal can need review but can never fail
   on it. Refusal is reserved for a proposal that cannot be lowered at all — a
   stale pin, terms that disagree with the catalogue, a book too thin for the size.

   The instance is then checked against the catalogue the proposal cites: the
   outcome exists, its description matches the leg's terms field by field (for a
   bucket, the thresholds on the parent question and the outcome's position among
   its named outcomes), and the coin equals `#` + `10*outcome + side`. The kernel's
   numbers come from the catalogue, not from the leg.
2. **Price.** A `fixed` acquisition is taken as given. A `book_walk` re-walks the
   cited snapshot at the requested size along the named path and carries the result
   as an **exact total with provenance** — `{kind: walked, total, path, snapshot}` —
   not as a per-unit price: a walk over several levels has no single price, and its
   average is derived rather than observed. Displayed depth that cannot fill the
   size is refused, `INSUFFICIENT_DEPTH`. Fees from the official formula with the
   outcome's own `deployerFeeScale` are T2; today pricing at displayed asks requires
   the dated `zero_base_fee` assumption, and its absence is refused. The kernel
   never sees a book — except the size window, which receives the levels as exact
   data.

   The baseline is re-read from the cited contexts snapshot and refused on a
   mismatch, so a hand-edited price cannot reach the kernel. The lowered proposal
   keeps the baseline's `source`, so a checker can read it again.
3. **Reduce.** Rules that lower a leg's value, applied in a fixed order and listed
   in the lowered proposal. Each is a lower bound, declares whether it is
   **tight**, and can construct its adverse state.

   | Rule | Rewrites | Tight? | Adverse state | Tier |
   |---|---|---|---|---|
   | `horizon_mismatch` | the leg → nothing | yes | the leg's own observation pays zero | T1 |
   | `unreviewed_family` | the leg → nothing | **no** | — | T1 |
   | `unreviewed_reference` | the leg → nothing | **no** | — | T4 |
   | `basis_band` | each group of legs on one foreign reference → the band infimum of their sum | yes | the reference value in the band that attains it | T4 |
   | `deployer_strike` | the strike → owned by neither side; requires `deployer_settles_as_written` | yes | the deployer reads equality against the holder | T4 |
   | `touch_terminal_bound` | long touch-YES → inclusive terminal indicator, if its window covers the valuation time | yes | the path touches only at the end | T4 |
   | `perp_margin_at_risk` | an isolated perp liquidatable inside the path domain → minus its margin, everywhere | yes | the path reaches liquidation and recovers | T6 |

4. **Normalize.** Canonical numbers, sorted where order is not meaning, digests.

**Every array's order is decided, and the decision is here.** Two implementations
must agree byte for byte, so an order left to whichever loop happened to run first is
a disagreement waiting to happen.

| Array | Order | Why |
|---|---|---|
| `profile`, `upper_profile` | ascending price | It *is* the function, read left to right |
| `failing_intervals`, `undecided_intervals` | clause order, then ascending price | A reader walks the domain upward, one clause at a time |
| `cost.breakevens` | ascending price | Follows the profile |
| `reductions` | leg order, then rule order within a leg | Follows the legs; lowering emits them that way |
| `adverse_states` | the reductions' order | Follows the reductions |
| `size_windows` | leg order | Follows the legs |
| `assumptions` | the proposal's own order | The proposal states them; a result does not reorder what it was asked |
| `responsible_legs`, `snapshots`, `semantics_version` | **sorted** | Sets, with no order of their own |
| `reason_codes` | **sorted** | A verdict code and reduction codes concatenated: the join order was an accident of the loop, so it is sorted (changed 20 Sep; see EVIDENCE §9) |
| comparison `candidates` | caller order | The caller's list |
| comparison `ranking` | ascending cost | The ranking is the point |

Every reduction gives two profiles. The **lower** profile values each reduced leg
at zero and is what a verdict rests on; the **upper** profile credits it with its
full size, which a long fully collateralized token can never exceed
([EVIDENCE §1](./EVIDENCE.md)). With no reductions the two coincide.

| Where the violation lives | Verdict |
|---|---|
| Lower and upper profile alike | `fails`, with a witness carrying each leg's adverse state |
| Lower profile only, every responsible rule **tight** | `fails` — the adverse state is admissible, not merely unproven |
| Lower profile only, some responsible rule **loose** | `needs_review`, with `undecided_intervals` naming the legs |

**A loose bound can never produce a failing interval.** It is a statement about
what has not been established, not about what the contract pays.

The band infimum is a group operation on purpose. Evaluated leg by leg it is
sound but loose; on the group's sum it is exact. And it is not a shift: the middle
bucket `[P1, P2)` shrinks from both sides to `[P1 + b, P2 − b)`, which
`oracle/verify.py` checks against closed forms and against brute force, including
a case whose true breakpoints are a crossing of two candidate lines.

**Verdict.** `passes` when the lower-bound profile meets every clause. `fails`
when a scenario violates one using only tight rules; its witness is a price *and*
the adverse state of each reduced leg, so the unreduced payoff can be evaluated
there. `needs_review` when the only violations rest on a loose rule, or the
proposal cannot be represented. `fails` is never asserted from a bound no
scenario attains.

---

## 5. Conformance spine

The part every implementation must agree on before any of them computes a payoff.
**Built, in all three languages, against hand-written vectors.**

**Numbers.** One grammar, enforced before any library parser:
`-?(0|[1-9][0-9]*)(\.[0-9]+)?` or `-?(0|[1-9][0-9]*)/[1-9][0-9]*`, at most 80
characters; canonical form is a terminating decimal when one exists, else `p/q`
in lowest terms. 55 vectors. The libraries are not the specification: `big.Rat`
reads `"0x10"` as 16, `Fraction` accepts `" 5"` and Arabic-Indic digits, both
accept `"1e3"` and `"1_000"`.

**Canonical JSON.** A strict profile of RFC 8785: UTF-8 without a BOM; only
objects, arrays, strings and booleans; keys matching `[a-z][a-z0-9_]*`, unique;
well-formed Unicode; nesting at most 32. On that domain the output is exactly
RFC 8785. Digests are SHA-256 of the canonical bytes. 48 vectors, 33 of them
rejections. Each restriction closes a measured or documented disagreement:

| Restriction | Because |
|---|---|
| No numbers, no null | Number serialization is where RFC 8785 implementations differ; every quantity is an exact string anyway |
| Keys are schema-defined ASCII | Key order then needs no UTF-16 rule, and no document has user-chosen keys |
| No U+FFFD in any string | Go's `encoding/json` substitutes it silently for an escaped lone surrogate, so two implementations could digest different strings |
| No BOM | Python's `json.loads` accepts one from bytes; Go rejects it |
| Duplicate keys rejected | Every standard parser takes the last one silently. `JSON.parse` cannot do otherwise, so the checker has its own parser |
| Depth counts every value | A scalar at depth 33 is rejected like a container at depth 33, so the three counters cannot drift |

Expected canonical text is written by hand in `tools/make_vectors.py`; no
implementation produces it, and one digest is pinned to the system `shasum`.
Implementations agree with the vectors, never the other way round.

---

## 6. Who checks whom

| | Oracle · Python | Engine · Go | Checker · TypeScript |
|---|---|---|---|
| Numbers, canonical JSON | built | built | built |
| Kernel | built | T2 | T3 |
| Lowering | built, canonical families | T2, T4 | T3, T4 |
| Sizing, alternatives, reductions | built | T2 | T3 |
| Refusing a certificate bundle | built, **reference only** | — | T3, the real one |
| Assembly, service, storage | — | T2 | — |
| Verifying a result in the browser | — | — | T3 |

- **Generated cases** are compared across all three at the level of the kernel.
- **Whole results** are compared between engine and checker on every fixture.
- **The oracle fixes expected results** inside its scope — canonical families,
  fixed and depth-priced costs, the horizon rule — each pinned by hand-derived
  assertions so a fixture cannot merely agree with itself. Its scope stops at T1.
  Later tiers' expected results come from the engine, are verified by the
  checker, and are pinned the same way.
- **The checker is not a second engine.** It takes proposal, snapshots, registry
  and result, and answers accept or refuse, with a reason from the closed list in
  `refusal.schema.json`. It re-lowers and compares `ir_digest`; re-evaluates and
  compares every claim; evaluates each witness on the *unreduced* payoff. Its
  acceptance test is refusing corrupted certificates (PLAN §5).
- **`oracle/refuse.py` is not that checker.** It exists so each of the fourteen
  bundles is known to be refused for its stated reason before a second
  implementation is asked to agree. T3's checker shares the schemas with it and
  nothing else. Where the two disagree on a bundle, the refusal classes make it a
  real disagreement rather than a wording difference — which is why the list is
  closed.

**The server computes and the client verifies.** The result screen runs the
checker in the browser on every view; a consumer runs it before it signs.

**What that does and does not protect against.** The page fetches the result, the
proposal, the lowered proposal, every snapshot by hash and every registry entry by
version, hashes each one itself, and re-derives the answer with
`checker/dist/checker.js`. This catches **a mistake in the engine that computed the
result** — a wrong walk, a dropped piece, a verdict that does not follow. That is a
real and common failure, and it is the one the check is for.

**It does not protect against a dishonest server.** A server that serves a dishonest
result can serve a dishonest checker beside it, and the page has no way to tell.
Verification in the browser is a convenience for a reader who trusts the operator to
be honest but not to be correct. **The trust boundary is the consumer**, which runs
its own copy of the checker against bundles it fetched itself. The page says exactly
this to the reader rather than implying more.

---

## 7. Boundaries, and what holds them

| Rule | Held by |
|---|---|
| Pure packages do no I/O: no network, filesystem, clock or randomness | `engine/arch_test.go` — import scan; only `adapter`, `store`, `service`, `cmd` are exempt |
| No floating point in an evaluation path | same test — `float32`, `float64`, float literals, package `math`; `checker/test/arch.test.ts` — `Number(`, `parseFloat`, `Math.` |
| No third-party code in an evaluation path | same tests — `go.mod` has no `require`; `package.json` has no dependency field; sources import only each other |
| The checker is runtime-neutral and its syntax erasable | `arch.test.ts` — no `node:`, `process`, `Deno`, `Bun`, `require`, `JSON.parse`; no `enum`, `namespace`, parameter properties. Node runs the sources unmodified; Deno type-checks them; Bun runs them too |
| A function carries its breakpoints | `oracle/verify.py` — no evaluation function has a `breakpoints` parameter |
| A schema constraint is never silently ignored | `tools/validate.py` — an unknown keyword or an unanchored pattern is an error; 36 mutations must be refused |
| Documents agree with each other | `tools/validate.py` — a proposal pins the digest of the registry entry it uses; its coin encodes its outcome and side; every snapshot it cites is retained |
| A draft registry entry gets no credit | `canon.reviewed` — state and `review.digest` together; reduced by lowering as `unreviewed_family`, loose. Tests drive both states from in-memory copies rather than reading whichever state the tree holds, so reviewing an entry changes the verdict without breaking a test |
| An unreviewed family is named as the cause, not as a symptom | `checker/src/verify.ts` — `compareReductions` runs **before** `compareProfile`, because a reduced leg contributes nothing to the lower profile and so makes the profile disagree. Refused as `REDUCTION_UNDECLARED` at `$result.reductions`, naming the family, the version, and that the version is absent from this checker's allowlist. Reporting the profile first sent an operator hunting a broken payoff for a benign cause two steps upstream |
| The gate acts on the value the checker established | `verify` returns the parsed result on acceptance; `gate` reads the verdict and envelope from it and never parses those bytes again. `consumer/test/banned.ts` bans `JSON.parse` and `TextDecoder` in `gate.ts` by name. A second parse, by a laxer parser than the checker's, would be the gate acting on a value nothing verified |
| The production gate cannot be handed a checker | `gate()` is bound to the real `verify` and takes no verifier. The injectable `gateWith` lives in `consumer/src/testing.ts`, and a guard fails if `run.ts` imports it or names it |
| A deployer-settled leg is reduced, never valued as written | `engine/lower`, `oracle/lower.py`, `checker/src/verify.ts` — `settleOutcome` carries a `settleFraction` the deployer CHOOSES (EVIDENCE §1, `[V]`), so the template says what they said they would do, not what they must. Reduced under `deployer_settled`, **loose**, so it can make a proposal need review and can never make one fail. `fixtures/bundles/good-deployer` is that bundle; `TestADeployerLegIsReduced` guards Go's own rule, which the Python-generated fixtures did not |
| Only a `computed` family is evaluated | all three — `bounded` means the payoff is not a function of the terminal price (`priceTouch` is path-dependent), and `refused` means the registry has no established reading (PLAN §6, "Everything else — Refused"). Both are **refusals**, not reductions: a reduction still yields a verdict, and neither of these has a verdict to yield. Before this, a family the registry REFUSES produced a clean `passes`. `UNSUPPORTED_FAMILY` is reused — the registry is saying what that code already means |
| The adverse wording is one string across two implementations | `TestAdverseWordingMatchesTheOracle` compares the maps directly. It used to hold only by accident: the string reaches a result through a WITNESS, and a witness attaches only to a FAILING interval, so any **loose** rule's wording could drift silently. Proven — changing Go's `deployer_settled` string left `make check` green, while the same edit to `horizon_mismatch` was caught |
| A band reduction acts on a GROUP, never leg by leg | `schema/ir.schema.json` — `reductions[].with` names the other legs, because PLAN §2 states the rule as the infimum of the group's SUMMED payoff and **the infimum of a sum is not the sum of infima**. Measured with the oracle's kernel, band 500, a long and a short digital at one strike: the sum is identically 0, grouping gives 0, per-leg gives **−1000** — a loss invented on a perfectly hedged position. The existing invariant cannot catch it: per-leg is LOWER, so it satisfies "a reduction never turns a failing proposal into a passing one" while making a sound hedge fail |
| A loose bound never fails a proposal | `oracle/verify.py` replay — the tight horizon fixture, re-run with its rule made loose, must move from `fails` to `needs_review` with no failing interval |
| Reviewing an entry does not move what proposals pin | `tools/validate.py` — `semantics_version` excludes `review`; a review with a stale digest does not count as reviewed |
| A lowered leg matches the instance it names | `oracle/verify.py` replay — terms against the catalogue, coin against outcome and side, baseline against the contexts snapshot, size against displayed depth |
| Retained evidence in a fixture is the retained response | `oracle/verify.py` replay — each file's SHA-256 against its own request record and against the hash in the evidence commit |
| Documented examples cannot drift | `oracle/verify.py` parses PLAN.md and compares its example with the generated fixture |
| Documented counts cannot drift | `tools/validate.py` — the schema count in README and ARCHITECTURE, and a layout row per top-level directory, are compared with the filesystem |
| Every contract document is schema-checked | `tools/validate.py` — including both good certificate bundles; corrupted bundles are the refuser's business |
| A stored result replays byte for byte | `engine/cmd/hedgecheck/replay_test.go` — two retained runs are recomputed from their stored bytes, offline: the 19 September capture the Python spike took, and the 20 September one this engine took itself. Reproducing the spike's run is what let the spike be deleted |
| A replay checks the result, not just the files | `replay_test.go` — a book edited in place is caught by the store's hash; a genuinely different book, honestly filed under its own digest, must still fail the result comparison |
| The capture assertion keeps its sign | `run` — `TestMeasureReproducesTheRetainedSkew` re-measures the retained bytes and gets what the run recorded. The bound is about distance from zero; the record keeps the sign, because it says which clock was ahead, and it feeds the input digest |
| Exactly one package reaches the venue | `engine/arch_test.go` — an AST scan for `http.Get`, `http.NewRequest`, `client.Do` and the rest outside `adapter/`. Keeping `net` out of the pure packages says nothing about the impure ones, and a direct call from `store` or `cmd` would slip the pace, the budget and the closed set of request types |
| The capture order is catalogue, contexts, books | `engine/cmd/hedgecheck/capture_test.go` — a fake venue records the call order. A baseline fetched after the books would describe a moment the prices had not reached, and no live run could ever detect it |
| A retained record matches the frozen schema | `tools/validate.py` — the 50 records at `085ccfb` **and** every record in the working tree. History alone missed the Go adapter writing `Z` where the schema requires `+00:00` |
| The screen answers, and never advises | `engine/screen/forbidden_test.go` — the rendered page is matched against a list of words this tool has no standing to say: *recommend*, *optimal*, *guaranteed*, *risk-free*, *executable*, *proven*. Each entry carries its reason. "advice" is permitted only in the sentence disclaiming it |
| `needs_review` is not a softer `fails` | same test — the wording is checked directly, because it is the sentence a reader acts on and the one most likely to be softened later |
| The chart cannot mislead about the bound | `engine/screen/chart_test.go` — the vertical extent always includes the cap, and a piece crossing it is **split at the crossing**, solved exactly, so colour marks where the bound is breached and nowhere else. Coordinates are computed as rationals and rounded once, at the moment they become SVG text |
| Only `cmd` and `service` may reach the network | `engine/arch_test.go` — an import scan for `engine/adapter`, so "pure" cannot come to depend on what the adapter happens to do |
| Only the adapter's own package can redirect it | `adapter/hyperliquid` — the endpoint field is unexported and empty by default, so a zero client calls the real venue; a request type outside the closed set never opens a connection |
| A loopback bind is not a security boundary against a web page | `service` — binding 127.0.0.1 keeps other MACHINES out, not other PAGES. Two checks close the two doors: `Host` must name this machine (421 otherwise, so a DNS-rebound name gets nothing), and a write must be `application/json` (415 otherwise, the one content type a cross-origin `fetch` cannot send unpreflighted — and the preflight fails, since no CORS header is ever sent). Before them, a `text/plain` POST from a foreign Origin returned 200 and the check ran. The content type is checked after the method, so a POST to a read-only path is still 405 |
| A served result does not contradict the digest it is served under | `service` — a snapshot is content-addressed and re-hashed by the store; a result is filed under `input_digest`, a CLAIM about its inputs, so nothing in the store catches a swapped file. A document naming a different input is refused 500. It is "does not contradict" rather than "states", because `input_digest` is written during bundle assembly and `evaluate` does not emit it |
| Purity is not transitive through an import | `engine/arch_test.go` — a pure package may not import `store`, `service`, `adapter` or `cmd` either. Banning `os` and `net` missed the likelier drift: the kernel importing a sibling for one helper. Proved by making `pwa` import `store` and watching the guard pass before the check existed |
| A reader constrains what its schema constrains | `engine/doc` — `execution_readiness`, `evaluation_scope` and the payoff selector's `index` are read with `enum` and a pattern, not a bare string. The reader accepted `execution_readiness: "banana"` while the schema allowed three values, and that field is what says whether an order envelope may exist |
| A name is refused as a name, before it reaches a path | `service` — every path parameter is matched against its pattern and answered **400**, not 404. A 404 is what a handler with no validation also returns, so the status is what proves the check happened. Percent-encoded traversal is used in the test, because a plain `../..` is cleaned away by the client and the mux and never reaches a handler |
| A refusal never names a path on this machine | `service` — the shape of the message is asserted across every error route, so a new route that forwards a raw `os` error is caught too |
| A refusal is not a verdict | `service` — a proposal that cannot be lowered is 422 with its refusal **class**, and is never readable as a result. Missing evidence and a lowering refusal are separate routes and separately tested |
| Concurrent writes agree and are served whole | `service` — twelve simultaneous posts of one proposal under `-race` must file one location and identical bytes; the store renames into place, so a reader never sees a partial result |
| The validator's one deviation from JSON Schema 2020-12 stays deliberate | `tools/validate.py` — 1.0 is not an integer here, and `integer` is asserted to appear only in `snapshot-record` |

Each guard was run against a deliberate violation before it was trusted.

### Lints and proofs

A guard that reads SOURCE TEXT is a lint. It catches an accident and not an adversary:
the text can always be spelled another way. The rows above that scan for `fetch`,
`Date`, `node:`, `place(` or an import path are lints, and are labelled as such here so
nobody mistakes one for a proof later.

What they are worth was measured rather than assumed. Inserting
`globalThis["fet"+"ch"](…)` into `gate.ts` matches none of the patterns. Wrapped in
`try {} catch {}` so it changes no behaviour, it also passes every behavioural test —
the call throws, but silently, and the gate's answer is unchanged. **Greps and
behavioural tests both stay green.**

`consumer/test/tripwire.test.ts` is the proof. It instruments `fetch`,
`XMLHttpRequest`, `WebSocket`, `Date.now`, `performance.now` and `setTimeout`, drives
every row of the gate table, and counts what was actually called:

- every refusing row: zero network calls, zero clock reads
- the approving row: exactly one `place` call, and still no clock of its own

The count is on the function that runs, so the spelling does not matter and neither
does whether the call happens to break anything. The lints stay, because a lint that
fires at review time is cheaper than a test that fires at run time — but the property
rests on the harness.

---

## 8. Components

```text
ARCHITECTURE.md  PLAN.md  EVIDENCE.md  Makefile
schema/     nine draft schemas. The only thing implementations share
fixtures/   golden/   lowered proposal and its generated expected result
            vectors/  numbers and canonical JSON, generated from hand-written cases
            replay/   retained responses, their request records, and the real
                      proposals lowered from them (2026-09-18), including the
                      horizon fixture valued a day after its leg is observed
registry/   semantics entries as data: recurring.priceBinary, recurring.priceBucket
oracle/     exact.py  canon.py  oracle.py (kernel, evaluate)  lower.py  verify.py
engine/     exact/  canon/  arch_test.go          ── built
            pwa/  doc/  lower/  evaluate/  discover/  run/  screen/  ── pure
            adapter/hyperliquid/  store/  service/  cmd/hedgecheck/
                                                            ── the only impure packages
checker/    src/exact.ts  src/canon.ts            ── built
            src/pwa.ts  src/lower.ts  src/verify.ts ── T3
tools/      make_vectors.py  validate.py
```

**Engine (T2).** The evaluator is a library and a CLI — proposal, snapshots and
registry in; result out; no I/O. Around it: the Hyperliquid adapter discovers
instances and retains responses with their records; the store is
content-addressed files, `snapshots/<sha256>`,
`results/<input_digest>/<engine_version>.json` and `runs/<input_digest>.json`, and
gains an index only when a query needs one. The engine version is part of the
result path rather than something that overwrites: two engines may answer the same
question, and a store keeping only the newest would silently lose the comparison.
Every name is matched against its pattern **before** it becomes a path, so a
traversal is refused as a name rather than sanitised as a path. The service is
three reads and one write, all idempotent:
`POST /v1/checks`, `GET /v1/checks/{input_digest}`, `GET /v1/snapshots/{sha256}`,
`GET /v1/registry/{semantics_version}` — everything the browser needs to verify
without trusting the server.

**Consumer (T3).** An approval gate is one function: run the checker; unless it
accepts a `passes` whose `input_digest` matches the order envelope — coin, side,
size, limit price, `Ioc`, maximum cost — make zero downstream calls. Keys live
only here: testnet, an agent wallet, never a main-wallet key on disk.

**The one third-party dependency**, pinned exactly with a lockfile, in `consumer/`
only and never in `checker/`:

| Package | Version | Why |
|---|---|---|
| `@noble/curves` | 1.7.0 | secp256k1 signing. Audited, dependency-light, and the narrowest thing that signs |
| `@noble/hashes` | 1.6.1 | keccak-256 for EIP-712. A transitive 1.6.0 also arrives under `@noble/curves` |

Chosen over a wallet library such as `viem`: 4.7 MB and three packages against 50 MB
and ten, for code that touches a key. The cost is that the EIP-712 hashing and the
action encoding are ours, and so is the burden of getting them right;
`consumer/test/` drives both against a fake exchange.

`consumer/src/gate.ts` is that function, and it ships with a recording fake and no
key of any kind. Four things about it are structural rather than conventional:

- **The envelope is issued by a step outside the evaluator.** `evaluate.Evaluate`
  is pure, the lowered form carries no instance id (§6 — instance ids are never in
  the registry or the IR), and `input_digest` is computed after evaluation. So
  `engine/envelope` takes the proposal, the IR, the finished result and the digest,
  and issues or blocks. A result nobody asked to execute stays `not_evaluated`.
- **The limit is the price of the highest level the walk touched.** Anything lower
  leaves part of the size unfilled at a price the walk counted; anything higher lets
  the order pay more than the walk measured, so `max_cost` would stop being a
  maximum. `envelope-limit-raised` is the fixture, and it is the only thing that
  catches it: no other check in the checker overlaps that one.
- **The clock is injected.** `policy.now` is a value, so the staleness boundary is
  testable at the millisecond. `gate.ts` names no clock at all and a test enforces
  that by reading the source.
- **"Approved" is unrepresentable without the check.** `Approved.brand` is typed by
  a `unique symbol` declared in `gate.ts` and exported from nowhere, so no other
  module can write the type. `consumer/test/unrepresentable.ts` holds four attempts
  and `typegate.test.ts` fails if any of them compiles.

The gate re-states the verdict, envelope and digest conditions the checker already
establishes. That is deliberate, and §7's fourth lesson is why: mutation testing
found that three of the gate's own conditions were fully shadowed by the checker
and could be deleted without a test noticing. The table now drives each of them
with an accepting stub in place of the checker, so the gate is held to its own
conditions rather than to the checker's.

**On-chain (T7).** The same checker logic over fixed-point integers, gating a
CoreWriter order. Cost is bounded by `limit price × size`, so no book is read.

**Trust.** Venue JSON, proposals and results are untrusted at every boundary and
parsed under §5 before anything else. Registry entries are trusted only by
digest: the checker ships with the digests it accepts. A language model may draft
an entry; it never runs inside lowering, evaluation or checking.

---

## 9. Changing things

- **A contract family:** a registry entry citing retained text by hash, reviewed
  by the owner; a terms schema in `proposal.schema.json`; fixtures. No kernel change.
- **A reduction:** a row in §4 with its tightness and adverse state; the lowering
  rule twice; fixtures including one where the naive version is wrong.
- **A kernel operation:** three implementations, generated differential cases, and
  a reason the existing operations cannot express it.
- **A vector:** a hand-written case in `tools/make_vectors.py`; regenerate; all
  three implementations must pass before it is committed.
- **A document field:** the schema, a mutation that must be refused, and
  `--write` for any generated fixture — never a hand edit.

---

## 10. Open

**The checker's allowlist.** `checker/dist/allowlist.json` is DERIVED, never written
by hand: `tools/build_checker.py` reads `registry/` and emits the
`semantics_version` of every entry whose state is `reviewed` **and** whose
`review.digest` still matches that version. Both entries are model drafts today, so
the list is **empty** — which is the correct answer rather than a missing one. To
rotate it the owner reviews an entry and rebuilds; to revoke, the review is removed
and the next build drops the digest. Editing an entry moves its `semantics_version`,
so a stale review stops counting without anyone having to notice. `make check`
fails if the committed list differs from what the registry produces.

| Question | Blocks |
|---|---|
| Module and package names (`hedgecheck/engine`, `@hedgecheck/checker`) are local; they change to the public path when the repository has one | Publishing |
| Whether the oracle moves from `Fn` to explicit piece lists when T1 extends it. Recommended: yes | T1 |
| ~~How the checker's accepted registry digests are distributed and rotated~~ **Answered in T3, below** | — |
| CI. No workflow is committed because none has been run; `make check` is the contract until a remote exists | Publishing |
| TypeScript tests are executed but not type-checked: that needs `@types/node`, a dependency. Only `src/` is type-checked | — |
