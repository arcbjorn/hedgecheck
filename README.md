# PayoffBounds

Pre-trade verification of whether a proposed hedge satisfies an explicit
protection objective, what satisfying it costs, and what the alternatives are —
for Hyperliquid HIP-4 outcome markets.

> *Do these exact terms, costs and holdings satisfy my objective — and what does
> satisfying it cost me, against what else I could do?*

**Status: research, evidence and a reference oracle. No engine or application has
been implemented.** Formerly codenamed HedgeCheck, a name that collides with
HedgeCheck LLC; the directory keeps the codename. The namespaces for
`payoffbounds` were free on 18 September and are not yet registered.

## Read these two

- **[PLAN.md](./PLAN.md)** — authoritative. What to build, in what order, and the open decisions.
- **[EVIDENCE.md](./EVIDENCE.md)** — every fact the plan depends on, labeled verified / third-party / unverified, with source and date.

## Check everything yourself

The evidence packages are **not in the working tree**. They are committed at
`085ccfb` and restored with one command:

```sh
git checkout 085ccfb -- research/
```

Then all five verifiers run offline, with no dependencies:

```sh
python3 research/2026-09-15/verify.py             # 128 checks, 6 response hashes
python3 research/2026-09-15-settlement/verify.py  # 222 checks, 13 response hashes
python3 research/2026-09-18/verify.py             # 471 checks, 32 response hashes, 14 re-verified
python3 research/2026-09-18-decisions/verify.py   # 82 checks, 6 official pages, name sweep
python3 research/oracle/verify.py                 # 4,077 checks: golden table, fixture, PLAN.md example
```

The first three verify retained API response bytes and the arithmetic built on
them. The fourth verifies retained official documentation text and the namespace
sweep. The fifth verifies the golden table and the example result printed in
`PLAN.md` against a generated fixture, and fails if the document drifts from it.

Every **[V]** claim in `EVIDENCE.md` is checkable this way. The retained bytes
cannot be re-captured — instances rotate and are pruned from the live catalogue —
so `085ccfb` is the only copy.

## Layout

| Path | Contents |
|---|---|
| `PLAN.md` | Authoritative build plan |
| `EVIDENCE.md` | Verified facts, with source and date |
| `research/` | Evidence packages and verifiers. **Restore from `085ccfb`** (above) |

Market snapshots are historical observations, not prices to trade on.
Capabilities and tiers in `PLAN.md` are proposed work, not completed features.
