# Evidence, 18 September 2026

Public Hyperliquid mainnet info API responses retrieved on 18 September 2026
between 07:17 and 07:25 UTC, about seventy-five minutes after the daily 06:00 UTC
rollover. Each response has a companion `.request.json` with endpoint, POST body,
request and retrieval times, HTTP status, server date, and the SHA-256 of the
exact response bytes. No account data, orders, signatures, payments, or trades
were involved.

`capture.py` produced the catalogue, contexts, books, templates and the
16 September settlements. `discover_settled.py` produced the 17 and 18 September
settlements by probing `settledOutcome` across the id gap, paced at one request
per 1.5 seconds; only recurring responses were retained.

| Response | Content |
|---|---|
| `outcome-meta.json` | Live catalogue: 243 outcome entries, 25 questions, 3 deployers |
| `outcome-templates.json` | Template registry, byte-identical to 15 September |
| `meta-and-asset-ctxs.json` | Perp contexts at capture (BTC mark 77,631.4) |
| `book-3965-no.json`, `book-3965-yes.json` | Books of the live BTC `priceBinary` instance, strike 77,457 |
| `book-bucket{0,1,2}-397{1,2,3}-yes.json` | YES books of the live BTC `priceBucket` named outcomes, thresholds 75,908 and 79,007 |
| `settled-3253.json` to `settled-3256.json`, `settled-3259.json` to `settled-3262.json` | Binary and bucket instances that expired 2026-09-16 06:00 UTC |
| `settled-3467.json` to `settled-3474.json` | The same, expired 2026-09-17 06:00 UTC |
| `settled-3719.json` to `settled-3726.json` | The same, expired 2026-09-18 06:00 UTC |

What the package establishes, together with the two earlier packages:

- Twenty canonical `priceBinary` settlements over five consecutive days. Every
  reported fraction is consistent with the inclusive rule and, because no
  instance settled at its target, equally consistent with a strict one. The
  closest remains instance 3061 at 26 USD.
- Five rollovers. Every new target is within 0.02 percent of the previous
  reported settlement price, and is not a fixed rounding of it.
- A second canonical family, `priceBucket`: one question, three named outcomes
  and a fallback. In three settlements exactly the bucket containing the reported
  price paid, in index order `< P1`, `[P1, P2)`, `>= P2`, and the fallback paid
  nothing. Thresholds sat within 1 USD of the binary target minus and plus
  2 percent.
- Instance 3253, asked at 0.975 on 15 September, paid in full on the 16th.
  The 1,000-contract proposal realized +82.96 and still fails the check.
- For 0.1 BTC, floor 60,000 and a 1,000 USD cap at the 07:17 mark, the smallest
  passing size through the at-the-money binary costs 645.77 USDC; through the
  bucket-0 YES, struck 2 percent lower, 160.77 USDC.
- NO asks mirror YES bids at one minus the price with equal sizes. It is one
  book shown twice; depth is never additive across the two coins.

Run the verifier from the project directory:

```sh
python3 research/2026-09-18/verify.py
```

Recorded result: **471 checks passed; 32 response hashes verified in this
package, 14 re-verified from earlier packages.** Hashes detect modification
relative to the request records; they are not venue signatures. A settled
response establishes what the API reported, not an independent observation of
the mark price. The books are not reserved fills; ask-walk costs exclude fees
and assume the captured orders remain available. The mark and the NO book were
retrieved 1.9 seconds apart and the contexts response carries no venue
timestamp.
