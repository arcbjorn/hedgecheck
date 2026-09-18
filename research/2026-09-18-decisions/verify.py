"""Verify the retained official text and namespace sweep behind the 18 September decisions. Offline."""

from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECKS = 0


def check(condition, description):
    global CHECKS
    if not condition:
        raise AssertionError(description)
    CHECKS += 1


def page(stem):
    record = json.loads((ROOT / f"{stem}.request.json").read_text())
    raw = (ROOT / f"{stem}.md").read_bytes()
    check(sha256(raw).hexdigest() == record["response_sha256"], f"{stem}: SHA-256")
    check(record["http_status"] == 200 and record["method"] == "GET", f"{stem}: HTTP status and method")
    check(record["url"].startswith("https://hyperliquid.gitbook.io/hyperliquid-docs/") and record["url"].endswith(".md"), f"{stem}: official Markdown URL")
    check(record["retrieved_at"].startswith("2026-09-18"), f"{stem}: capture date")
    return raw.decode()


def says(text, stem, *quotes):
    for quote in quotes:
        check(quote in text, f"{stem}: says \"{quote[:70]}\"")


def main():
    spec = page("contract-specifications")
    says(spec, "contract-specifications",
         "the contract settles to YES if and only if `markPrice0 + (settlementTime - t0) / (t1 - t0) * (markPrice1 - markPrice0) ≥ targetPrice`",
         "There are three price buckets depending on the target price at the time of settlement: `< P1`, `[P1, P2)` and `≥ P2.`",
         "Exactly one of the 3 outcomes settles to 1, and the others settle to 0.",
         "The target price computation uses the same interpolation as binary markets described above.",
         "at most one recurring series for each `(seriesType, underlying, period)` combination",
         "period:15m")

    hip4 = page("hip-4-outcome-markets")
    says(hip4, "hip-4-outcome-markets",
         "Outcomes are fully collateralized contracts that settle within a fixed range.",
         "does not involve leverage or liquidations",
         "composing with other primitives such as portfolio margin and the HyperEVM",
         "The order books of Yes and No tokens for the same outcome are merged to share liquidity.",
         "an order to buy Yes at price `p` is equivalent to an order to sell No at price `1-p`",
         "exactly one outcome will settle to Yes, and all others will settle to No",
         "linked by `negate` and `merge` operations",
         "Fees are currently zero for outcome markets for initial testing.",
         "builders earn builder fees on sell orders that specify their builder code")

    deployer = page("hip-4-deployer-actions")
    says(deployer, "hip-4-deployer-actions",
         "Testnet-only",
         "validators vote on outcome templates",
         "Markets that contradict their template's semantic restriction are considered malformed and slashable by validators.",
         "`settleFraction` is a decimal in `[0, 1]`. Standalone outcomes may settle to any fraction",
         "`details` must be empty.",
         "pay the base outcome trading fee rate times `scale + max(scale, 1)`",
         "Maker rebates are never paid on outcome markets.",
         "Per-outcome scales are returned in the `outcomeMeta` info request.",
         "Builder codes can also be applied to buy orders for outcome orders, and are also charged in the quote token.",
         "charged by the protocol on a best-effort basis")
    # Deployer markets are settled by a submitted fraction. Nothing on the page computes it from a
    # price, so which side owns the strike is the deployer's reading of the template text.
    check("interpolation" not in deployer and "markPrice" not in deployer, "hip-4-deployer-actions: no protocol price computation on the deployer path")

    core = page("interacting-with-hypercore")
    says(core, "interacting-with-hypercore",
         "The testnet EVM provides read precompiles",
         "perps positions, spot balances, vault equity, staking delegations, oracle prices, and the L1 block number",
         "order actions and vault transfers sent from CoreWriter are delayed onchain for a few seconds",
         "(uint32, bool, uint64, uint64, bool, uint8, uint128)",
         "Outcome operation",
         "<code>SplitOutcome</code>", "<code>MergeOutcome</code>", "<code>MergeQuestion</code>", "<code>NegateOutcome</code>")
    check(100_000_000 + 10 * 3965 + 1 == 100_039_651 < 2 ** 32, "an outcome asset id fits the limit order's uint32 asset field")

    builder = page("builder-codes")
    says(builder, "builder-codes",
         "This action must be signed by the user's main wallet, not an agent/API wallet.",
         "The builder must have at least 100 USDC in perps account value",
         "builder codes do not apply to the buying side of spot trades but apply to both sides of perp trades",
         "Builder fees charged can be at most 0.1% on perps and 1% on spot.",
         "Each user can have a maximum of 10 active builder code approvals at a time.")

    ids = page("asset-ids")
    says(ids, "asset-ids", "encoding = 10 * outcome + side", "Outcome asset ID: `100_000_000 + encoding`",
         "Outcome spot coin: `#<encoding>`", "Only side `0` and side `1` are valid.")

    # ---- namespace sweep
    sweep = json.loads((ROOT / "name-availability.json").read_text())
    check(sweep["retrieved_at"].startswith("2026-09-18"), "sweep: capture date")
    names = sweep["names"]
    spaces = ["github_user", "npm", "crates", "pypi", "com", "xyz", "ai", "dev", "app", "io"]
    for name in ("payoffbounds", "payoffbound", "payoffproof", "lossbounds", "pnlbounds", "payoffverdict", "hedgeassert"):
        check(all(names[name][space] == "free" for space in spaces) and names[name]["github_repos_named"] == 0, f"{name}: free in all eleven namespaces")
    # Controls: the method must be able to say "taken", and must reproduce the 15 September table.
    check(sum(names["countersign"][space] == "taken" for space in spaces) == 9, "control countersign: taken in nine of ten")
    check(names["payoff"]["com"] == "taken" and names["payoff"]["github_repos_named"] == 801, "control payoff: the bare root is taken")
    check(names["payoffcheck"]["com"] == "taken" and names["payoffcheck"]["xyz"] == "free", "payoffcheck: .com taken, .xyz free, as on 15 September")
    check((names["settlecheck"]["com"], names["settlecheck"]["xyz"], names["settlecheck"]["github_repos_named"]) == ("taken", "taken", 2), "settlecheck: as on 15 September")
    check(all(names[name][tld] in ("free", "taken") for name in names for tld in ("ai", "io")), ".ai and .io now answer for every name")

    print(f"{CHECKS} checks passed; 6 official pages and one namespace sweep verified.")


if __name__ == "__main__":
    main()
