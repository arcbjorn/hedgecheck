# Settlement evidence, 15 September 2026

Public Hyperliquid mainnet info API responses retrieved on 15 September 2026
at about 22:14 UTC, sixteen hours after the recurring instances featured in
[../2026-09-15](../2026-09-15/README.md) expired. Each response has a
companion `.request.json` with endpoint, POST body, request and retrieval
times, HTTP status, server date, and the SHA-256 of the exact response bytes.
`capture.py` is the script that produced them. No account data, orders,
signatures, payments, or trades were involved.

| Response | Content |
|---|---|
| `settled-3061.json` to `settled-3064.json` | Settlement of the BTC, ETH, SOL, HYPE recurring instances that expired 2026-09-15 06:00 UTC |
| `settled-2820.json`, `settled-2822.json`, `settled-2824.json`, `settled-2825.json` | Settlement of the four instances that expired 2026-09-14 06:00 UTC |
| `outcome-meta.json` | Live catalogue at capture, including the replacement instances 3253 to 3256 expiring 2026-09-16 06:00 UTC |
| `meta-and-asset-ctxs.json` | Perp contexts at capture (BTC mark 75,362.0) |
| `book-3253-yes.json`, `book-3253-no.json` | Books of the replacement BTC instance, coins `#32530` and `#32531` |

What the package establishes:

- Canonical settlements record a numerical price in `details` (`price:77609` for 3061). Deployer settlements in the earlier package record `template`.
- The reported `settleFraction` for all eight instances agrees with the official inclusive rule (YES if and only if price is at or above target).
- Instance 3061 settled 26 USD above its 77,583 target. The NO side, asked at 0.942 nineteen minutes before expiry in the earlier package, paid zero.
- Each replacement instance's target is within 0.02 percent of the previous instance's settlement price, on both rollovers observed (14 to 15 September and 15 to 16 September).
- Settled instances are pruned from `outcomeMeta` but remain retrievable through `settledOutcome`; instances from the previous day were retrieved successfully. Retention duration is not established.

Run the verifier from the project directory:

```sh
python3 research/2026-09-15-settlement/verify.py
```

Recorded result: **222 checks passed; 12 response hashes verified in this
package, plus one prior-package book.** Hashes detect modification relative to
the request records; they are not venue signatures. The venue-reported
settlement price is what the API reported, not an independent observation of
the mark price.
