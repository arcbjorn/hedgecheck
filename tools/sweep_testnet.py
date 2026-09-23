"""Sweep testnet outcome books for depth, and say whether any of it is hedgeable.

    python3 tools/sweep_testnet.py

READ-ONLY, and the only network this project's tooling touches: `POST .../info`, which the
T3 security note permits. No key, no signing, nothing that places an order.

WHY THIS EXISTS. Both runbooks say "re-sweep before trying again", and on 23 Sep the sweep was
a throwaway script that got the coin encoding wrong -- it asked for `#10218` where the venue
wants `#102180`, read the resulting `null` as an empty book, and reported no depth across 618
markets. The documentation had the encoding right; the probe did not. A check that gates the
one remaining live step should not be retyped from memory each time.

TWO FACTS, KEPT APART. "Is there depth" and "is any of it hedgeable" moved independently on
23 Sep -- depth appeared while hedgeable depth did not -- and the earlier runbooks conflated
them into "waits on a quoted book". A quoted World Cup market is depth this tool cannot use:
a sports outcome carries no priceDescription, no perp and no threshold, so nothing relates it
to a perp exposure and lowering refuses it rather than inventing a series.
"""

import json

import sys
import urllib.request

HOST = "https://api.hyperliquid-testnet.xyz/info"

# A price market names its settlement source in the template's own `priceDescription`, and its
# subject in `perp`. Those TEMPLATE FIELDS are the test, not English words in the prose.
#
# A looser first version searched the description for `below|above|strike|twap` near a digit
# and counted 50 "hedgeable" markets, every one of them a World Cup or CPI book -- "is below
# 4.3%" matched. A CPI print is a macro statistic, not a price series a perp settles on, so
# that answer contradicted the sweep's own purpose. The catalogue's structured
# `key:value|...` description is what `lower.catalogue_reference` reads, so that is what this
# reads too: the same fields, asked the same way.
PRICE_TERMS = ("pricedescription", "perp")


def info(body, timeout=25):
    request = urllib.request.Request(
        HOST, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def side_coin(outcome, side):
    """The venue's own encoding: '#' + (10 * outcome + side), yes=0, no=1.

    The rule `engine/discover/discover.go` implements. Getting this wrong is not an error --
    the venue answers `null`, which is easy to read as an empty book.
    """
    return f"#{10 * int(outcome) + (0 if side == 'yes' else 1)}"


def levels(coin):
    """(bids, asks, best_ask) for a coin, or None when the instance does not exist.

    `None` and an empty book are DIFFERENT FACTS: a dated instance that has expired answers
    `null`, and reporting that as "0 bids, 0 asks" claims something false about a market that
    is not there. This is the distinction that made the first sweep wrong.
    """
    book = info({"type": "l2Book", "coin": coin})
    if book is None:
        return None
    rows = book.get("levels", [[], []])
    return len(rows[0]), len(rows[1]), (rows[1][0] if rows[1] else None)


def is_price_market(outcome):
    """True when the catalogue's STRUCTURED description carries a price leg's template fields.

    The catalogue writes `key:value|key:value|...`; a price instance carries `priceDescription`
    (its settlement source) and `perp` (its subject). Prose is deliberately not consulted --
    see PRICE_TERMS. An outcome whose description is empty or unstructured is not a price
    market, which is also what lowering concludes when it refuses with CATALOGUE_UNREADABLE.
    """
    described = outcome.get("description", "") or ""
    terms = {part.split(":", 1)[0].lower() for part in described.split("|") if ":" in part}
    # A prose description yields no `key:value` parts, so `terms` is empty and both lookups
    # fail -- an unstructured market is not a price market, which is the intended answer.
    return all(term in terms for term in PRICE_TERMS)


def main():
    meta = info({"type": "outcomeMeta"})
    outcomes = meta["outcomes"]
    question_of = {}
    for question in meta.get("questions", []):
        for named in question.get("namedOutcomes", []):
            question_of[named] = question

    quoted, empty, absent = [], 0, 0
    for outcome in outcomes:
        for side in ("yes", "no"):
            coin = side_coin(outcome["outcome"], side)
            try:
                found = levels(coin)
            except Exception as error:                       # noqa: BLE001 - reported, not raised
                print(f"  {coin}: {type(error).__name__} {error}", file=sys.stderr)
                continue
            if found is None:
                absent += 1
            elif found[0] or found[1]:
                quoted.append((coin, side, outcome, found))
            else:
                empty += 1

    books = len(quoted) + empty
    print(f"outcomes {len(outcomes)}  probed {2 * len(outcomes)}  "
          f"absent(null) {absent}  books {books}")
    print(f"  carrying at least one quote: {len(quoted)}")
    print(f"  empty (0 bids, 0 asks):      {empty}")

    hedgeable = [q for q in quoted if is_price_market(q[2])]
    print(f"\nquoted AND a price market: {len(hedgeable)}")
    if not hedgeable:
        print("  none -- so the live order is still blocked, and NOT on depth in general.")
        print("  Every quoted book below is a market this tool refuses as a price leg.")
    for coin, side, outcome, (bids, asks, best) in quoted[:20]:
        question = question_of.get(outcome["outcome"], {})
        print(f"  {coin} {side:3} {outcome['name'][:26]:28} "
              f"{bids:3}b {asks:3}a  best_ask={best}  q={question.get('name','?')[:30]}")
    return 0 if hedgeable else 1


if __name__ == "__main__":
    sys.exit(main())
