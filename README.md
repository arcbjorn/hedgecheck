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

```sh
python3 research/2026-09-15/verify.py             # 128 checks, 6 response hashes
python3 research/2026-09-15-settlement/verify.py  # 222 checks, 13 response hashes
python3 research/2026-09-18/verify.py             # 471 checks, 32 response hashes, 14 re-verified
python3 research/2026-09-18-decisions/verify.py   # 82 checks, 6 official pages, name sweep
python3 research/oracle/verify.py                 # 4,077 checks: golden table, fixture, PLAN.md example
```

All five run offline with no dependencies. The first three verify retained API
response bytes and the arithmetic built on them. The fourth verifies retained
official documentation text and the namespace sweep. The fifth verifies the golden
table and the example result printed in `PLAN.md` against a generated fixture,
and fails if the document drifts from it.

## Layout

| Path | Contents |
|---|---|
| `research/2026-09-15/` | Catalogue, templates and books nineteen minutes before the 15 September expiry |
| `research/2026-09-15-settlement/` | Eight settlements across two rollovers, capture script |
| `research/2026-09-18/` | Twelve more binary settlements, three bucket settlements, the live binary and bucket books, capture and discovery scripts |
| `research/2026-09-18-decisions/` | Six official documentation pages retained as Markdown, the name-availability sweep, capture script |
| `research/oracle/` | Reference oracle for exact terminal evaluation, fixtures. **Not the product engine** — the smallest evaluator that can state an expected result |
| `research/observer.mjs` | Approximate settlement consistency observer. Optional, not independent, no characterised tolerance — see [EVIDENCE.md §5](./EVIDENCE.md) |

Market snapshots are historical observations, not prices to trade on.
Capabilities and tiers in `PLAN.md` are proposed work, not completed features.
