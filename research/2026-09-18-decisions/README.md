# Evidence behind the 18 September decisions

Two kinds of retained bytes, captured 18 September 2026 by `capture.py`.

**Official documentation, as Markdown.** GitBook serves every page as Markdown
when `.md` is appended to its URL, so these files are the official text itself,
not a rendering and not a summary. Each has a `.request.json` with URL, times,
HTTP status, server date and SHA-256.

| File | Page |
|---|---|
| `contract-specifications.md` | Recurring `priceBinary` and `priceBucket` rules |
| `hip-4-outcome-markets.md` | Structure, the merged book, questions, fees, builder codes |
| `hip-4-deployer-actions.md` | Templates, deployer settlement, fee scale, builder codes. Marked "Testnet-only" |
| `interacting-with-hypercore.md` | Read precompiles, CoreWriter actions and their delay |
| `builder-codes.md` | Limits, approval, which side pays |
| `asset-ids.md` | Outcome encoding |

**A namespace sweep**, `name-availability.json`: GitHub user and repository
search, npm, crates.io, PyPI, RDAP for `.com` `.xyz` `.ai` `.dev` `.app`, and
`whois.nic.io` for `.io`, for twelve names. HTTP 404 is recorded as free and 200
as taken. The sweep includes names known to be taken, so that "free" means
something, and it reproduces the 15 September table.

What the package establishes:

- The inclusive `≥` rule, the three bucket definitions, and "the same
  interpolation" are the page's own words, retained.
- Deployer markets are settled by a fraction the deployer submits; "`details`
  must be empty"; nothing on the page derives the fraction from a price. Markets
  contradicting their template's semantic restriction are "slashable".
- Users pay "the base outcome trading fee rate times `scale + max(scale, 1)`";
  the base rate is "currently zero".
- Yes and No books "are merged to share liquidity".
- Three official pages describe builder fees on outcomes three different ways.
- `payoffbounds` was free in all eleven namespaces on 18 September.

```sh
python3 research/2026-09-18-decisions/verify.py
```

Recorded result: **82 checks passed; 6 official pages and one namespace sweep
verified.** A retained page establishes what the documentation said on the day,
not how the venue behaves. A namespace answer is point-in-time: it records what
the registries said, not what they say now. No trademark register was searched,
and the X handle was checked by hand in a browser, not retained.
