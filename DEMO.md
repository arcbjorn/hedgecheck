# The demo

Offline, reproducible, and needs nothing from the market. Every command below was run to
produce the output shown; the numbers are not illustrative.

**Nothing here signs or sends.** The whole page is `check`, `lower` and `compare` over the
retained 18 September capture. No key, no network, no clock.

## Why a replay and not a live run

A live run needs the market to cooperate, and today it does not: BTC spot sits **below** every
recurring binary's target, so the NO leg that pays on a fall asks 0.99999 — you would pay
essentially the full payoff for protection you will probably collect anyway. See
`tools/hedgeable_today.py`, which names the failing precondition and exits 1.

The refusal is the tool working. But a refusal is a thin demo, so the primary exhibit is a
capture in which the hedge genuinely worked.

## The one capture, three questions, three different answers

`fixtures/replay/2026-09-18/` holds one capture: the BTC perp mark, and the books for a
binary and a bucket expiring `2026-09-19T06:00:00Z`. Baseline **77,631.4**.

The objective is the same in all three: hold 0.1 BTC, lose at most **1,000** anywhere in
60,000–110,000.

```
cd engine
for p in bucket0 binary bucket0-horizon; do
  go run ./cmd/hedgecheck check \
    --proposal ../fixtures/replay/2026-09-18/$p.proposal.json \
    --registry ../registry \
    --snapshots ../fixtures/replay/2026-09-18 > /dev/null 2>&1
  echo "$p -> exit=$?"
done
```

```
bucket0         -> exit=0     passes
binary          -> exit=0     passes
bucket0-horizon -> exit=1     fails
```

(`go run` echoes `exit status 1` to stderr when the program exits non-zero; the `2>&1`
above keeps that out of the way. A built binary does not.)

Exit status *is* the verdict: 0 passes, 1 fails, 2 needs_review, 3 refused, 4 error. A
refusal is not a verdict — a proposal that cannot be lowered has no result.

### Why the third one fails, and why that is the point

`bucket0-horizon` is the same bucket leg against a valuation time **one day later** than the
leg's own expiry. The leg is observed on 19 Sep; the objective asks about 20 Sep. The engine
does not guess what happens in between. It applies the `horizon_mismatch` reduction, worst-cases
the leg to zero, and reports:

```json
"reductions": [{"leg": "bucket0-yes", "reason_code": "LEG_WORST_CASED_HORIZON",
                "rule": "horizon_mismatch", "tight": true}],
"worst_case": {"attained": true, "pnl": "-1923.90676", "price": "60000"}
```

`tight: true` means the bound is attained, not merely an upper estimate, and the witness names
the adverse state: *the leg's own observation pays zero*. The unhedged worst case was −1,763, so
this "hedge" is **worse than no hedge** — it spends premium for protection that has expired. A
tool that passed this would be worse than useless.

### Which of the two passing hedges is better

```
cd engine
T=$(mktemp -d)
for p in bucket0 binary; do
  mkdir -p $T/$p
  go run ./cmd/hedgecheck lower --proposal ../fixtures/replay/2026-09-18/$p.proposal.json \
    --registry ../registry --snapshots ../fixtures/replay/2026-09-18 > $T/$p/lowered.json
  go run ./cmd/hedgecheck check --proposal ../fixtures/replay/2026-09-18/$p.proposal.json \
    --registry ../registry --snapshots ../fixtures/replay/2026-09-18 > $T/$p/result.json
done
go run ./cmd/hedgecheck compare --result $T/binary/result.json --result $T/bucket0/result.json
```

```
ranked_by: cost_of_smallest_passing_size
ranking : ['bucket0', 'binary']
  binary     passes   cost=645.76904
  bucket0    passes   cost=160.76676
```

Both meet the cap. The bucket does it for **a quarter of the premium** — 160.77 against 645.77.
That is the answer a trader wants and cannot get from a screen: not "is this hedge sound" but
"which of these sound hedges is cheapest".

`compare` reads each result beside its lowered proposal so the shared terms are re-derived from
the documents, not asserted. The label is the containing directory's name, which is why each
result goes in its own.

Both premiums can be checked by hand against the retained books: walk the ask levels for the
smallest passing size in `size_windows` (924 bucket contracts, 1,409 binary) and the totals come
out to the last digit. Nothing rounds, because nothing is a float — Python `fractions`, Go
`math/big`, TypeScript `BigInt`.

## The same result from three independent implementations

```
make check
```

The Python oracle, the Go engine and the TypeScript checker are separate implementations of the
same specification, and `make check` requires them to agree — plus 12 Solidity tests for the
gate, and a cross-acceptance pass where the Python refuser accepts the Go bundles and rejects
five deliberate corruptions by class.

```
all checks passed
```

## If the market does turn

```
python3 tools/hedgeable_today.py
```

Exit 0 prints the live command with the correct flags. `--cap` is a **positive magnitude**
while a proposal's own `min_pnl` is negative; a negative `--cap` is refused, because it used to
double-negate into a sell-down larger than the holding.

The live path is **read-only** — `POST /info` only — and runs against mainnet today with no code
change. It is capture, skew check, discovery, lowering, evaluation and screen. It stops before
anything that signs.

**Ordering is a different matter from capture.** Every retained bundle is built from mainnet
books and carries mainnet asset ids, so a bundle must never be aimed at a network it was not
captured from; `run.ts` refuses `--send` without an explicit
`--bundle-is-for-this-network`. Any digest-approval demonstration belongs on testnet with a
testnet capture, run by the owner with their own key.
