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
| `schema/` | Nine draft JSON Schemas: proposal, lowered proposal, result, comparison, registry entry, snapshot record, certificate bundle manifest, refusal classes, shared definitions |
| `fixtures/` | `golden/` a lowered proposal and its generated result · `vectors/` numbers and canonical JSON · `replay/` retained responses and the real proposals lowered from them · `bundles/` certificate bundles, two good and twelve corrupted |
| `registry/` | Contract semantics as data. Both entries are model drafts awaiting review |
| `oracle/` | Python. Exact numbers, canonical JSON, the kernel, lowering, the reference refuser, the verifier. **Not the product engine** |
| `engine/` | Go. So far the conformance spine and the architecture test |
| `checker/` | TypeScript, no dependencies. So far the conformance spine and the architecture test |
| `tools/` | The vector generator, the corruption generator and the schema validator |
| `spike/` | The T1 live spike: discovery, capture, replay. Throwaway; T2 deletes it |
| `research/` | Evidence packages and verifiers. **Restore from `085ccfb`** (above) |

Market snapshots are historical observations, not prices to trade on.
Capabilities and tiers in `PLAN.md` are proposed work, not completed features.
