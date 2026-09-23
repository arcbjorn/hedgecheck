# HedgeCheck

Pre-trade verification of whether a proposed hedge satisfies an explicit
protection objective, what satisfying it costs, and what the alternatives are —
for Hyperliquid HIP-4 outcome markets.

> *Do these exact terms, costs and holdings satisfy my objective — and what does
> satisfying it cost me, against what else I could do?*

**Status: T1 closed, 19 September.** One complete check runs on real data, on the
Python oracle: it discovers the live instruments without being told their ids,
lowers a proposal from retained bytes, and returns a verdict with its cost, the
sizes that would have met the objective, the alternatives, and a witness per
failing interval. The schemas are frozen at v1. **The Go engine and the
TypeScript checker do not exist yet** — T2 and T3 build them, and the plan says
in what order.

## Read these three

- **[PLAN.md](./PLAN.md)** — authoritative for what is built, why, and in what order.
- **[EVIDENCE.md](./EVIDENCE.md)** — every fact the plan depends on, labeled verified / third-party / unverified, with source and date.
- **[ARCHITECTURE.md](./ARCHITECTURE.md)** — how it is built, and which test holds each boundary.

## Check the tree

```sh
make check
```

Offline, no install step; needs `python3`, `go`, `node` 23.6 or later, and `deno`.
It regenerates and compares the conformance vectors and the certificate bundles,
validates every contract document against the frozen schemas, runs the oracle's
verifier — which also fails if the example result printed in `PLAN.md` drifts
from the generated fixture, and which accepts two certificate bundles while
refusing twelve corrupted ones by class — replays the retained live capture byte
for byte, and runs the Go and TypeScript suites, architecture tests included.

A schema file cannot change unless [schema/CHANGES.md](./schema/CHANGES.md)
changes with it: `make check` fails on a one-character edit otherwise.

## Run the engine

```sh
cd engine && go build -o hedgecheck ./cmd/hedgecheck
```

```text
hedgecheck lower    --proposal P --registry DIR --snapshots DIR
hedgecheck evaluate --lowered L
hedgecheck check    --proposal P --registry DIR --snapshots DIR [--envelope]
hedgecheck bundle   --proposal P --registry DIR --snapshots DIR --out DIR [--envelope]
hedgecheck compare  --result R --result R [--result R ...]
hedgecheck replay   --input-digest D --store DIR --registry DIR
hedgecheck retain   --input-digest D --store DIR --out DIR
hedgecheck serve    --store DIR --registry DIR [--address 127.0.0.1:8787]
hedgecheck render   --input-digest D --store DIR [--out FILE]
```

Exit status is the answer, so a caller can branch without parsing output: `0`
passes, `1` fails, `2` needs review, `3` refused with the class on stderr, `4` a
usage or technical error.

`--envelope` adds the order the cost bound assumes: coin, side, size, the price of
the highest level the walk touched, `Ioc`, the maximum cost, and the
`input_digest` it belongs to. It is issued only for a passing, depth-priced,
single-leg answer; anything else sets `execution_readiness` to `blocked` and says
why on stderr, without changing the exit status — **"this cannot be executed" is
not "this failed the objective."** The envelope is a statement of which order, and
only which order, the cost bound is about. It is not permission to send one. **A refusal is not a verdict** — status `3` never means
the objective was evaluated and found wanting.

`render` writes the result screen for a stored run: the candidates ranked by the
cost of the smallest size that met the objective, a payoff chart per candidate
showing the stated bound and where the payoff crosses it, and a section stating
what the answer does **not** establish. It renders what was stored rather than
recomputing, so the page shows what was filed under that input digest. The page
answers a stated objective and is not advice; `screen/forbidden_test.go` holds it
to that.

`serve` binds loopback and nothing else. It offers one write and three reads, all
idempotent, which together are everything a browser needs to verify a result
without trusting the server: post a proposal, then fetch the result, every
snapshot it cites, and every registry entry it pins, and re-derive the answer
yourself.

## Check the evidence

The evidence packages are **not in the working tree**. They are committed at
`085ccfb` and restored with one command:

```sh
git checkout 085ccfb -- research/
```

```sh
python3 research/2026-09-15/verify.py             # 128 checks, 6 response hashes
python3 research/2026-09-15-settlement/verify.py  # 222 checks, 13 response hashes
python3 research/2026-09-18/verify.py             # 471 checks, 32 response hashes, 14 re-verified
python3 research/2026-09-18-decisions/verify.py   # 82 checks, 6 official pages, name sweep
```

The first three verify retained API response bytes and the arithmetic built on
them; the fourth, retained official documentation text and the namespace sweep.
`research/oracle/` at that commit is the first oracle, superseded by `oracle/`
here. Every **[V]** claim in `EVIDENCE.md` is checkable this way. The retained
bytes cannot be re-captured — instances rotate and are pruned from the live
catalogue — so `085ccfb` is the only copy.

## Layout

| Path | Contents |
|---|---|
| `schema/` | 11 draft JSON Schemas: proposal, lowered proposal, result, comparison, synthesis, registry entry, reference map, snapshot record, certificate bundle manifest, refusal classes, shared definitions |
| `fixtures/` | `golden/` a lowered proposal and its generated result · `vectors/` numbers and canonical JSON · `replay/` retained responses and the real proposals lowered from them · `bundles/` certificate bundles, seven good and seventeen corrupted · `kernel/` the oracle's exact answers to 400 kernel queries, which the Go engine must reproduce · `rejected/` documents every schema must refuse, shared by all three implementations · `generated/` 320 lowered proposals with the oracle results the Go engine must reproduce · `refusals/` one proposal per refusal code lowering can raise · `synthesis/` the oracle's synthesis answers and one corruption per refusal class, which the TypeScript checker judges · `testnet/` a read-only testnet catalogue and its two empty books, retained as the evidence for EVIDENCE section 4 |
| `registry/` | Contract semantics as data: one reviewed reading of each family's payoff |
| `references/` | What a venue's free-text price description denotes, versioned separately from a payoff reading |
| `oracle/` | Python. Exact numbers, canonical JSON, the kernel, lowering, the reference refuser, the verifier. **Not the product engine** |
| `engine/` | Go. So far the conformance spine and the architecture test |
| `checker/` | TypeScript, no dependencies. So far the conformance spine and the architecture test |
| `consumer/` | TypeScript. The approval gate: one function that runs its own copy of the checker and places an order only for an accepted `passes` carrying the order envelope its cost bound assumes. The clock is injected; `place` is a parameter and this tier ships only a recording fake. No keys, no network, no signing |
| `onchain/` | Solidity. `ApprovedOrderGate`: sends a CoreWriter limit order only when it is the order an owner-approved certificate digest authorised, at no worse a price, no larger a size, and no more than the approved cost. It does NOT verify certificates — that needs the payoff kernel, and the evidence a cost bound rests on cannot be established on chain at all, since the read precompiles expose positions and balances but no order book. No dependencies: `forge-std` is not used, so the tests are plain Solidity. Skipped with a notice when `forge` is absent |
| `tools/` | The vector generator, the corruption generator and the schema validator |
| `research/` | Evidence packages and verifiers. **Restore from `085ccfb`** (above) |

Market snapshots are historical observations, not prices to trade on.
Capabilities and tiers in `PLAN.md` are proposed work, not completed features.
