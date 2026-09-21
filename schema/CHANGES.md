# Schema changes

Every change to these schemas since `062a245`, the commit that first added them,
with the real case that forced it. A change with no forcing case does not belong
here and does not belong in the schemas; there are none.

The schemas are **frozen at v1** as of T1's gate. `schema_version` stays `"1"`.
A change after the freeze needs a new `schema_version`, a row here, and a
mutation in `tools/validate.py` that the old shape would have failed.

`make check` fails if any file in `schema/` differs from `HEAD` while this file
does not, so a change cannot land without a row.

---

## Forced by the 18 September replay

The first time the contract met real catalogues, books and marks.

| Change | Forcing case |
|---|---|
| `defs.cost`: a leg's premium may be `walked` — an exact `total` with `path` and `snapshot` — not only a `fixed` per-unit price | A book walk over several levels has no single per-unit price. 1,409 contracts at 645.76904 averages `8072113/17612500`, a repeating decimal. Both forms are exact under the number grammar; the total is the one that was observed. Exercised by `fixtures/bundles/premium-altered`. |
| `defs.cost`: a `walked` cost carries the `levels` it walked | The size window asks "what size would have met the cap on this book". Re-reading the snapshot inside `evaluate` would make the kernel touch evidence, so the levels travel with the total. Exercised by `fixtures/bundles/size-window-too-small`. |
| `registry-entry.review` gains `digest`; `semantics_version` excludes the `review` key | Reproduced before it was fixed: marking `recurring.priceBinary` reviewed changed its digest from `630b8c2f` to `7b1aa160`, which would have broken every proposal pinning it. An entry now counts as reviewed only when `review.digest` still matches its `semantics_version`, so editing the semantics silently un-reviews it. Exercised by `fixtures/bundles/wrong-semantics-version`. |
| `ir.baseline` keeps its `source` through lowering | Caught by the IR schema when lowering first dropped it. A checker must be able to re-read the baseline price from the same retained response rather than trust the number the lowering wrote down. |

## Forced by the complete result

A verdict alone does not answer what a person asks before approving a hedge.

| Change | Forcing case |
|---|---|
| `result.size_windows` | On 18 September the two canonical hedges both pass the same cap at 645.77 and 160.77. "Can size fix it" is unanswerable without the window, its exact bounds, and which site binds each end. Exercised by `fixtures/bundles/size-window-too-small` and `certificate-negative-weight`. |
| `result.comparisons.smallest_reduction` | The no-premium alternative is the benchmark a paid hedge has to beat: keep `5000/88157` BTC, sell the rest, worst case exactly −1000. A result that omits it invites approving a hedge that is worse than selling. |
| `result.reductions` and `result.upper_profile` | The `needs_review` verdict needs both profiles. The lower one carries the verdict; the upper one decides whether a violation rests on a loose bound. Without the upper profile a loose bound could produce `fails`, which PLAN §4 forbids. Exercised by `fixtures/bundles/reduction-without-reason` and `good-horizon`. |
| `comparison.schema.json`, a separate document | The 18 September binary and bucket lower to different IRs with different digests. Folding a cross-instrument ranking into either result would make that result depend on a proposal it is not about. The comparison cites results by `ir_digest` and restates none of their numbers. |

## Forced by the certificate fixtures

| Change | Forcing case |
|---|---|
| `refusal.schema.json`, a closed list of classes | The TypeScript checker in T3 must refuse the same bundle for the same stated reason as the reference refuser. An open list would make every disagreement a wording question. |
| `bundle-manifest.schema.json` | A bundle must be self-contained, so refusing it never depends on the state of the tree it was built from — it carries its own registry entries and snapshots. The manifest names the class the bundle must be refused with, so a fixture that stops being refused fails loudly. |
| `bundle-manifest.files.registry` and `.snapshots` are lists, not maps | The canonical JSON profile forbids a dot in a key, and `recurring.priceBinary` has one. Found by `canon.CanonError` on the first generation. |

## Forced by the audit

| Change | Forcing case |
|---|---|
| `result.capture`, `ir.capture`, `proposal.capture`, `defs.capture`, `defs.integer_text` | T1's gate says snapshots must be "retrieved within a stated skew, **recorded in it**". Nothing recorded it. `result.snapshots` already existed and nothing populated it, so the provenance slot was there and empty. `capture` is an **assertion, not a derivation**: the contexts response carries no venue timestamp, so the spread between a book's venue clock and the baseline's retrieval cannot be re-derived from the bytes by anyone, including a checker. |
| `result.upper_profile` re-typed from `interval` to the profile piece shape | Found the moment the validator began checking bundle documents: `$.upper_profile[0]: unexpected 'intercept'`. It had been typed as a bare interval while carrying `slope` and `intercept`. A schema too loose in one direction and too tight in the other, invisible until the fixtures were validated. |

## Forced by the approval gate (T3)

The first change **after** the freeze. Additive, so `schema_version` stays `"1"`
by the rule below; the row and the refused mutations in `tools/validate.py` are
what the freeze demands of it.

| Change | Forcing case |
|---|---|
| `refusal.class` gains `ENVELOPE_MISMATCH` | An envelope is a new thing to be wrong about, and the list is closed so two checkers refuse alike. Every existing class names a fault in the verdict or its evidence; "the result issued an order the book does not bound" is neither. Folding it into `COST_MISMATCH` would make a re-walk disagreement and a carried-over envelope indistinguishable, which is the exact wording question the closed list exists to prevent. |
| `result.order_envelope`, and `defs.order_envelope` | A depth-priced cost bounds **one order and no other**. The 18 September bucket cost 160.76676 for 924 contracts because the walk stopped inside the 0.17399 level; the binary cost 645.76904 for 1,409 because the walk ended in the 0.48404 level. Neither number bounds anything about 925 contracts, about a limit of 0.17400, or about an order left resting on the book. Until this row the result stated the bound and not the order it bounds, so a gate had to invent the coin, the limit and the time in force — and an invented limit is not the one the walk measured. `execution_readiness: envelope_issued` was in the enum from v1 with nothing that could ever set it. Refused by `tools/validate.py`: an envelope on a `fails`, an envelope whose `execution_readiness` disagrees, `time_in_force` other than `Ioc`, `side` other than `buy`, and `execution_readiness: envelope_issued` with no envelope. |

**What it does not change.** The envelope is not emitted by the evaluator.
`evaluate.Evaluate` is pure and the IR carries no instance id by design
(PLAN section 6: "Instance ids are never in it"), and it has no `input_digest`,
which is computed after it. So the envelope is issued by a separate step over the
proposal, the IR and the finished result — `engine/envelope` — and a result that
nobody asked to execute keeps `not_evaluated`, exactly as before.

---

## Forced by testnet discovery (T3)

**The forcing case.** T3's order path is exercised against testnet, so the adapter
gained a second endpoint constant and an explicit `--network` flag. The first
retained testnet record then failed `snapshot-record.schema.json` on two counts:

    $.endpoint: expected 'https://api.hyperliquid.xyz/info'
    $: unexpected 'network'

The schema pinned `endpoint` to the mainnet URL with a `const`, which was right while
mainnet was the only network and is wrong now. Retained evidence that cannot be
validated is not evidence.

- **`snapshot-record.endpoint` becomes an `enum` of the two info endpoints.** An enum
  rather than a base plus a path: an arbitrary URL must stay impossible, and a record
  naming a third one would be evidence of a request nothing here can make. The two
  values match `hyperliquid.Mainnet` and `hyperliquid.Testnet`, and
  `TestNetworkContract` fails if that set grows.
- **`snapshot-record.network` is added, optional, `mainnet | testnet`.** A record must
  say which network it came from, or a testnet capture and a mainnet one are
  indistinguishable once retained -- and EVIDENCE section 9 already lists "testnet
  observation establishes mainnet fees" as a known-wrong claim. Optional because the
  50 records at `085ccfb` predate the field and are all mainnet; making it required
  would invalidate the evidence commit.

## Forced by the first deployer-settled bundle (T4)

**The forcing case.** T4 added a reduction for `settlement: deployer`, and with it the
first BUNDLE whose verdict is `needs_review` — so the first result document carrying an
undecided interval that anything validated. It failed:

    $.undecided_intervals[0]: unexpected 'clause'
    $.undecided_intervals[0]: unexpected 'responsible_legs'
    $.undecided_intervals[0]: unexpected 'witness'

**The schema was wrong, and had been since the field existed.** `undecided_intervals`
pointed at `$defs/interval` — four endpoint fields, `additionalProperties: false` —
while all three implementations have always emitted seven fields there. Verified across
the generated corpus: **40 of 40** undecided intervals carry the rich shape, and
`fixtures/generated/ir/case-0090.result.json`, which predates this change, fails the
old schema exactly as the new bundle did. Nothing caught it because no validated
document had ever contained one: every bundle fixture was `passes` or `fails`.

- **`undecided_intervals` gets its own shape** rather than sharing `$defs/interval`:
  `lower`, `lower_inclusive`, `upper`, `upper_inclusive`, `clause`, `witness`,
  `responsible_legs`, all required, `additionalProperties: false`. `clause` and
  `witness` match `failing_intervals` field for field.
- **`responsible_legs` is required here and absent from a failing interval.** That
  asymmetry is the point: an undecided interval exists BECAUSE some leg's bound is
  loose, and a reader has to know whose. A failing interval has a proven violation and
  no leg is to blame for uncertainty.
- **`$defs/interval` is untouched**, so every other user of it is unaffected.

`schema_version` stays `"1"`: the change only widens what `undecided_intervals` accepts,
and every document valid before is valid now.

## Forced by the band reduction acting on a group (T4)

**The forcing case.** PLAN section 2 states the band reduction as "the infimum of the
**group's summed payoff** over the band". Every reduction the IR could express attaches to
ONE leg -- `leg` is required, singular, `additionalProperties: false` -- so a group
reduction was unexpressible.

That is not a presentation detail. **The infimum of a sum is not the sum of infima**, and
the difference is the case a hedge exists for. Two legs whose payoffs cancel have a flat
sum that no basis move can hurt; each alone is stepped. Measured with the oracle's own
kernel, band 500, a long and a short digital at the same strike:

        price     f+g   grouped   per-leg
        79000     0.0       0.0       0.0
        79600     0.0       0.0   -1000.0
        80000     0.0       0.0   -1000.0
        80400     0.0       0.0   -1000.0
        81000     0.0       0.0       0.0

Grouping gives the correct 0. Reducing leg by leg invents a **loss of 1000 on a perfectly
hedged position**.

**And the existing guard cannot catch it.** Per-leg is LOWER, so it satisfies "a reduction
never turns a failing proposal into a passing one" while making a sound hedge fail. The
error is invisible in the direction the invariants check.

- **`reductions[].with` is added, optional, an array of leg ids, `minItems: 1`.** The
  other legs reduced together with `leg`. Optional and additive: `leg` stays required, so
  every document valid before is valid now, and a per-leg rule omits it.
- **Added to `result.schema.json` as well as `ir.schema.json`.** A checker compares the
  result's declared reductions with the ones it re-derives, field for field, so a grouped
  reduction that could not round-trip into the result would be refused by the checker as a
  disagreement.
- **`leg` is not widened to a list.** The subject of the reduction stays one leg, with
  companions named -- so the existing comparison, which matches reductions in order by
  `leg`, keeps working unchanged.

`schema_version` stays `"1"`: the change only adds an optional field.

## Not changed, and why

- **`schema_version` stays `"1"`.** Every change above is additive: no field was removed, no field became required, no existing value became invalid. A document valid at `062a245` is valid now.
- **`defs.number` is untouched.** The grammar is the one thing three implementations share, pinned by 48 canonical-JSON and 55 number vectors and re-checked by a differential fuzz across Python, Go and TypeScript.
- **The validator is stricter than JSON Schema 2020-12 in exactly one place.** `1.0` is not accepted as an integer. `integer` appears only at `snapshot-record.http_status`, where a float means the record was round-tripped through something lossy — the corruption a record exists to expose. Pinned by a check in `tools/validate.py`.
