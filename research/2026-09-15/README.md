# Public market evidence

These responses were retrieved from Hyperliquid's public mainnet info API on September 15, 2026, at approximately 05:41:11 UTC. The featured recurring markets expire at 06:00 UTC that day. This folder is a historical evidence package.

Each response has a companion `.request.json` file recording the endpoint, POST body, request and retrieval times, HTTP status, server date, response filename, and SHA-256 digest of the exact response bytes.

| Response | Content |
|---|---|
| [outcome-meta.json](./outcome-meta.json) | Live catalogue at capture: 226 outcome entries, 32 questions, three deployer entries |
| [outcome-templates.json](./outcome-templates.json) | Registry of 18 templates |
| [book-3061-no.json](./book-3061-no.json) | BTC recurring NO book, coin `#30611` |
| [book-3063-no.json](./book-3063-no.json) | SOL recurring NO book, coin `#30631` |
| [settled-3176.json](./settled-3176.json) | Historical template outcome specification and reported resolution |
| [settled-3057.json](./settled-3057.json) | Another historical template outcome specification and reported resolution |

Run the verifier from the project directory:

```sh
python3 research/2026-09-15/verify.py
```

It uses Python's standard library, reads local evidence, and performs no network requests. The recorded result is **128 evidence and arithmetic checks passed, with six response hashes verified**. File hashes detect modification relative to the retained request records; they are not signatures by the venue. Numerical checks verify this package's known fixtures, not an implemented trading application.

The books are not reserved fills. Ask-walk costs exclude fees and assume captured orders remain available. A settled response establishes what the API reported, not independent verification of the underlying price observations. No account data, orders, signatures, payments, or trades were used to collect these six responses.

The original September 14 reports remain unchanged. Their quote values describe their own earlier timestamps and should not be substituted into these records.
