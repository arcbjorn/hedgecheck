# HedgeCheck: architecture

How the system is built. [PLAN.md](./PLAN.md) says what, why and in what order;
[EVIDENCE.md](./EVIDENCE.md) holds the facts. Where this file and the plan
disagree about *order or scope*, the plan wins; about *structure*, this file does.

19 Sep 2026, **T1 closed.** What exists is one complete check, on real data, on
the oracle: the contract as **frozen v1 schemas**, discovery that names no ids,
lowering from retained bytes, an exact result with its cost, sizing, alternatives
and witnesses, a reference refuser that refuses fourteen certificate bundles by
class, and a throwaway live spike that replays byte for byte. The conformance
spine stands in three languages; **the engine and the checker do not exist yet**
— T2 and T3 build them. Everything below marked with a tier is design.

```sh
make check    # vectors, bundles, schemas, oracle, spike, Go, TypeScript. Offline, no install
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
| A draft registry entry gets no credit | `canon.reviewed` — state and `review.digest` together; reduced by lowering as `unreviewed_family`, loose. Both entries here are **model drafts awaiting the owner's review**, so the on-disk replay returns `needs_review` |
| A loose bound never fails a proposal | `oracle/verify.py` replay — the tight horizon fixture, re-run with its rule made loose, must move from `fails` to `needs_review` with no failing interval |
| Reviewing an entry does not move what proposals pin | `tools/validate.py` — `semantics_version` excludes `review`; a review with a stale digest does not count as reviewed |
| A lowered leg matches the instance it names | `oracle/verify.py` replay — terms against the catalogue, coin against outcome and side, baseline against the contexts snapshot, size against displayed depth |
| Retained evidence in a fixture is the retained response | `oracle/verify.py` replay — each file's SHA-256 against its own request record and against the hash in the evidence commit |
| Documented examples cannot drift | `oracle/verify.py` parses PLAN.md and compares its example with the generated fixture |
| Documented counts cannot drift | `tools/validate.py` — the schema count in README and ARCHITECTURE, and a layout row per top-level directory, are compared with the filesystem |
| Every contract document is schema-checked | `tools/validate.py` — including both good certificate bundles; corrupted bundles are the refuser's business |
| A stored result replays byte for byte | `spike/verify.py` — the retained 19 September run is recomputed from its stored bytes, offline |
| The validator's one deviation from JSON Schema 2020-12 stays deliberate | `tools/validate.py` — 1.0 is not an integer here, and `integer` is asserted to appear only in `snapshot-record` |

Each guard was run against a deliberate violation before it was trusted.

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
            pwa/  ir/  lower/  evaluate/  result/  ── T2, pure
            adapter/hyperliquid/  store/  service/  cmd/hedgecheck/  ── T2, the only impure packages
checker/    src/exact.ts  src/canon.ts            ── built
            src/pwa.ts  src/lower.ts  src/verify.ts ── T3
tools/      make_vectors.py  validate.py
```

**Engine (T2).** The evaluator is a library and a CLI — proposal, snapshots and
registry in; result out; no I/O. Around it: the Hyperliquid adapter discovers
instances and retains responses with their records; the store is
content-addressed files, `snapshots/<sha256>` and
`results/<input_digest>/<engine_version>.json`, and gains an index only when a
query needs one; the service is three reads and one write, all idempotent:
`POST /v1/checks`, `GET /v1/checks/{input_digest}`, `GET /v1/snapshots/{sha256}`,
`GET /v1/registry/{semantics_version}` — everything the browser needs to verify
without trusting the server.

**Consumer (T3).** An approval gate is one function: run the checker; unless it
accepts a `passes` whose `input_digest` matches the order envelope — coin, side,
size, limit price, `Ioc`, maximum cost — make zero downstream calls. Keys live
only here: testnet, an agent wallet, never a main-wallet key on disk.

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

| Question | Blocks |
|---|---|
| Module and package names (`hedgecheck/engine`, `@hedgecheck/checker`) are local; they change to the public path when the repository has one | Publishing |
| Whether the oracle moves from `Fn` to explicit piece lists when T1 extends it. Recommended: yes | T1 |
| How the checker's accepted registry digests are distributed and rotated | T3 |
| CI. No workflow is committed because none has been run; `make check` is the contract until a remote exists | Publishing |
| TypeScript tests are executed but not type-checked: that needs `@types/node`, a dependency. Only `src/` is type-checked | — |
