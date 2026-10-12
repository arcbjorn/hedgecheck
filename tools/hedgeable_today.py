"""Say whether today's mainnet daily pair can produce a passing hedge, and why not if not.

    python3 tools/hedgeable_today.py

READ-ONLY (`POST .../info`), no key, no signing, nothing placed. Exits 0 when the conditions
for a useful hedge hold, 1 when they do not, so it can gate a demo attempt.

WHY THIS EXISTS. `hedgecheck check --live` is the real answer, but when it says "no size on the
displayed book meets the cap" it does not say WHICH precondition failed, and on 23 Sep I
mis-diagnosed that as a depth limit and modelled it by hand before checking. The two conditions
below are what actually decide it, and both are one request away:

  1. THE BINARY'S TARGET MUST SIT BELOW SPOT. The hedge is NO on the binary, which pays below
     the target. If spot is already below it, NO is in the money and asks near 1 -- paying ~0.97
     for a payoff of 1 you will probably get anyway transfers almost no risk, and the real worst
     case is just ABOVE the target, where it pays nothing and the premium is spent.
  2. THE BUCKET MUST BE GENUINELY QUOTED. On 23 Sep every BTC bucket book was 0.00002 bid /
     0.99998 ask -- a placeholder spanning the whole range, not price discovery -- so buying
     bucket0 YES costs essentially its full payoff at any size.

Neither is a defect in this project, and neither is something it controls.
"""

from fractions import Fraction
import json
import sys
import urllib.request

HOST = "https://api.hyperliquid.xyz/info"

# WHY THERE IS NO PLACEHOLDER THRESHOLD ANY MORE.
#
# This read `PLACEHOLDER_ASK = 0.999` until 12 October, on the theory that a book quoting the
# extremes is a placeholder and anything tighter is a market. On 12 October the BTC bucket
# asked **0.99666** -- under that threshold, so the tool reported "genuinely quoted: yes" and
# printed HEDGEABLE, while `check --live` refused the same book. The live check was right.
#
# The threshold was the wrong KIND of test. What matters is not whether an ask looks like a
# placeholder but whether a leg at that price can meet the cap at all, and that is arithmetic,
# not a guess: a contract costing `ask` and paying 1 nets `1 - ask` where it pays, so covering
# a shortfall S needs `S / (1 - ask)` contracts and costs `ask * S / (1 - ask)` -- and that
# premium is spent in EVERY state, including the ones where the leg pays nothing. At 0.99666
# a 2,000 cap on 0.1 BTC needed 79,192 contracts for 78,927, breaching the cap 39 times over
# in the state just above the threshold. The premium alone decides it long before depth does.
#
# So the test is: is the premium the cap's own shortfall would require still inside the cap?
def viable(ask, shortfall, cap):
    """Can a leg asking `ask` cover `shortfall` without the premium itself breaching `cap`?

    Exact, in Fractions: this is a screening decision about money and a float here would put
    the tool and the engine on different sides of a boundary for no reason.
    """
    ask = Fraction(str(ask))
    if ask >= 1:
        return False
    contracts = shortfall / (1 - ask)
    return contracts * ask <= cap


def info(body, timeout=25):
    request = urllib.request.Request(
        HOST, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def side_coin(outcome, side):
    """'#' + (10 * outcome + side), yes=0, no=1 -- the venue's own encoding."""
    return f"#{10 * int(outcome) + (0 if side == 'yes' else 1)}"


def terms_of(description):
    return dict(part.split(":", 1) for part in (description or "").split("|") if ":" in part)


def best_ask(coin):
    book = info({"type": "l2Book", "coin": coin})
    if book is None:
        return None
    asks = book.get("levels", [[], []])[1]
    return float(asks[0]["px"]) if asks else None


def recurring(meta, underlying):
    """The daily binary outcome and bucket question for an underlying, or (None, None)."""
    found_binary = found_bucket = None
    for outcome in meta["outcomes"]:
        if outcome.get("name") != "Recurring":
            continue
        terms = terms_of(outcome.get("description"))
        if terms.get("class") == "priceBinary" and terms.get("underlying") == underlying:
            found_binary = (outcome, terms)
    for question in meta.get("questions", []):
        if question.get("name") != "Recurring":
            continue
        terms = terms_of(question.get("description"))
        if terms.get("class") == "priceBucket" and terms.get("underlying") == underlying:
            found_bucket = (question, terms)
    return found_binary, found_bucket


def spot(underlying):
    universe, contexts = info({"type": "metaAndAssetCtxs"})[:2]
    for index, asset in enumerate(universe["universe"]):
        if asset["name"] == underlying:
            return float(contexts[index]["markPx"])
    raise LookupError(f"no {underlying} perp in the universe")


def main():
    underlying = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    meta = info({"type": "outcomeMeta"})
    found_binary, found_bucket = recurring(meta, underlying)
    if not found_binary or not found_bucket:
        print(f"{underlying}: no daily recurring pair listed right now")
        return 1

    outcome, binary_terms = found_binary
    question, bucket_terms = found_bucket
    price = spot(underlying)
    target = float(binary_terms["targetPrice"])
    thresholds = [float(x) for x in bucket_terms["priceThresholds"].split(",")]

    print(f"{underlying} spot {price:,.0f}")
    print(f"  binary  exp={binary_terms['expiry']} target={target:,.0f}")
    print(f"  bucket  exp={bucket_terms['expiry']} thresholds={thresholds}")

    # SHARED EXPIRY. Discovery pairs them at one expiry; on testnet they sit 21 hours apart
    # and can never pair, which is why this tool asks mainnet.
    shared = binary_terms["expiry"] == bucket_terms["expiry"]
    print(f"\n  shared expiry:        {'yes' if shared else 'NO -- discovery cannot pair them'}")

    out_of_money = target < price
    binary_ask = best_ask(side_coin(outcome["outcome"], "no"))
    print(f"  binary NO out of money: {'yes' if out_of_money else 'NO -- target is above spot'}"
          f"   ask={binary_ask}")

    named = question.get("namedOutcomes", [])
    bucket_ask = best_ask(side_coin(named[0], "yes")) if named else None

    # THE SHORTFALL A HEDGE HAS TO COVER, from the same 0.1 BTC and 2,000 cap the printed
    # command uses. Unhedged, the worst case at the floor is qty * (floor - spot); whatever is
    # worse than -cap is what a leg must make up.
    quantity, cap, floor = Fraction(1, 10), Fraction(2000), Fraction(60000)
    unhedged = quantity * (floor - Fraction(str(price)))
    shortfall = max(Fraction(0), -cap - unhedged)

    binary_viable = binary_ask is not None and viable(binary_ask, shortfall, cap)
    bucket_viable = bucket_ask is not None and viable(bucket_ask, shortfall, cap)
    print(f"  bucket ask usable:    {'yes' if bucket_viable else 'NO -- premium alone would '
                                     'breach the cap'}   ask={bucket_ask}")
    print(f"  binary ask usable:    {'yes' if binary_viable else 'NO -- premium alone would '
                                     'breach the cap'}   ask={binary_ask}")
    print(f"  (shortfall to cover {float(shortfall):,.2f} on an unhedged "
          f"{float(unhedged):,.2f})")

    if shared and (binary_viable or bucket_viable):
        # --cap IS A POSITIVE MAGNITUDE. A negative one used to double-negate into a sell-down
        # larger than the holding and a positive "loss" cap; it is refused now, but the command
        # is spelled out here so the right sign is what gets copied.
        print("\nHEDGEABLE. From the engine directory:\n")
        print("  go run ./cmd/hedgecheck check --live --network mainnet \\")
        print(f"    --underlying {underlying} --quantity 0.1 --cap 2000 \\")
        print("    --floor 60000 --ceiling 110000 --baseline analysis_time \\")
        print(f"    --valuation-time {bucket_terms['expiry'][:4]}-{bucket_terms['expiry'][4:6]}"
              f"-{bucket_terms['expiry'][6:8]}T{bucket_terms['expiry'][9:11]}:"
              f"{bucket_terms['expiry'][11:]}:00Z \\")
        print("    --store ~/.hedgecheck/store --registry ../registry")
        return 0
    print("\nNOT HEDGEABLE TODAY. A refusal from the live check would be correct, not a bug.")
    # WHAT IS BEING WAITED FOR, stated without overclaiming. On 24 Sep all four live binaries
    # sat ~3% out (BTC +3.15, ETH +3.16, SOL +3.33, HYPE +6.10), so the NO leg is in the money
    # on any flat or falling day and "wait for a rally in BTC" misdescribes the wait. The one
    # retained day with both numbers (18 Sep: target 77,457, baseline 77,631.4) had the target
    # just BELOW spot. One comparison is not a trend, so no claim is made about why.
    if not out_of_money and target > price:
        print(f"  The target is {(target / price - 1) * 100:.2f}% above spot. Every live binary "
              f"sits out by a similar margin,")
        print("  so this is not one underlying having a bad day -- do not switch underlying "
              "looking for a way round.")
    print("  For a demo that needs no market at all, see DEMO.md (offline replay).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
