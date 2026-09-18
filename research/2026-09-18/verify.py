"""Verify the 18 September evidence package offline, and the arithmetic it supports.

Reads this package, re-reads the two earlier packages where a chain of observations spans
them, and uses the reference oracle in ../oracle for exact interval and sizing results.
Standard library only; no network.
"""

from datetime import datetime
from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
FIRST = ROOT.parent / "2026-09-15"
SECOND = ROOT.parent / "2026-09-15-settlement"
sys.path.insert(0, str(ROOT.parent / "oracle"))
import oracle as O  # noqa: E402

CHECKS = 0
HASHES = set()


def check(condition, description):
    global CHECKS
    if not condition:
        raise AssertionError(description)
    CHECKS += 1


def read_capture(root, stem, expected_request, date=None):
    record = json.loads((root / f"{stem}.request.json").read_text())
    raw = (root / f"{stem}.json").read_bytes()
    check(sha256(raw).hexdigest() == record["response_sha256"], f"{stem}: SHA-256")
    check(record["request_body"] == expected_request, f"{stem}: request identity")
    check(record["http_status"] == 200 and record["method"] == "POST", f"{stem}: HTTP status and method")
    check(record["endpoint"] == "https://api.hyperliquid.xyz/info", f"{stem}: endpoint")
    retrieved = datetime.fromisoformat(record["retrieved_at"])
    check(retrieved.tzinfo is not None, f"{stem}: timezone")
    if date:
        check(retrieved.date().isoformat() == date, f"{stem}: capture date")
    HASHES.add((root.name, stem))
    return json.loads(raw), record


def fields(text):
    return dict(part.split(":", 1) for part in text.split("|"))


def asks(book):
    return [(F(level["px"]), F(level["sz"])) for level in book["levels"][1]]


def spans(intervals):
    return [(O.fmt(i["lower"]), i["lower_inclusive"], O.fmt(i["upper"]), i["upper_inclusive"]) for i in intervals]


def main():
    today = "2026-09-18"

    # ------------------------------------------------------------ catalogue and rotation
    meta, _ = read_capture(ROOT, "outcome-meta", {"type": "outcomeMeta"}, today)
    check((len(meta["outcomes"]), len(meta["questions"]), len(meta["deployers"])) == (243, 25, 3), "catalogue counts")
    live = {fields(o["description"])["underlying"]: o for o in meta["outcomes"] if o["name"] == "Recurring"}
    expected_live = {"BTC": (3965, "77457"), "ETH": (3966, "2479.9"), "SOL": (3967, "105.36"), "HYPE": (3968, "87.734")}
    check(set(live) == set(expected_live), "four recurring priceBinary instances live")
    for symbol, (ident, target) in expected_live.items():
        spec = fields(live[symbol]["description"])
        check(live[symbol]["outcome"] == ident and spec["targetPrice"] == target, f"{symbol}: live instance and target")
        check(spec["class"] == "priceBinary" and spec["expiry"] == "20260919-0600" and spec["period"] == "1d", f"{symbol}: class, expiry, period")
    present = {o["outcome"] for o in meta["outcomes"]}
    check(not present & {3061, 3253, 3467, 3719}, "earlier BTC instances are pruned: ids rotate")
    venues = {}
    for o in meta["outcomes"]:
        venues[o.get("venue")] = venues.get(o.get("venue"), 0) + 1
    check(venues == {"out": 99, "txyz": 88, "skew": 48, None: 8}, "outcomes by venue; the 8 without a venue are canonical")
    check(meta["feeScale"] == "1.0", "catalogue feeScale field")

    # The canonical priceBucket family: one question, three named outcomes, one fallback.
    bucket = [q for q in meta["questions"] if q["name"] == "Recurring"]
    check(len(bucket) == 1, "one recurring question live")
    bucket = bucket[0]
    check(bucket["description"] == "class:priceBucket|underlying:BTC|expiry:20260919-0600|priceThresholds:75908,79007|period:1d", "live bucket terms")
    check((bucket["question"], bucket["namedOutcomes"], bucket["fallbackOutcome"]) == (310, [3971, 3972, 3973], 3970), "live bucket structure")
    by_id = {o["outcome"]: o for o in meta["outcomes"]}
    check([by_id[i]["description"] for i in bucket["namedOutcomes"]] == ["index:0", "index:1", "index:2"], "named outcomes are indexed in order")

    # No scalarPrice instance exists in any retained catalogue, although the template exists.
    for root in (FIRST, SECOND, ROOT):
        catalogue, _ = read_capture(root, "outcome-meta", {"type": "outcomeMeta"})
        check(not [o for o in catalogue["outcomes"] if "scalar" in o["name"].lower()], f"{root.name}: no scalarPrice instance live")

    # Deployer BTC binaries name their reference in free text; four distinct strings coexist.
    references = {}
    for o in meta["outcomes"]:
        if o["name"] == "template:binaryPrice" and o["description"].startswith("perp:BTC|"):
            spec = fields(o["description"])
            key = (spec["priceDescription"], spec["seconds"], o["venue"])
            references[key] = references.get(key, 0) + 1
    check(references == {("BTC-USDC mark", "1", "out"): 1, ("BTC-USDC perp mark", "60", "out"): 1,
                         ("the Hyperliquid BTC perp trade", "90", "skew"): 6, ("the Pyth BTC/USD price", "90", "skew"): 15},
          "BTC binaryPrice instances by reference text, TWAP seconds and venue")

    # ------------------------------------------------------------ template texts
    templates, _ = read_capture(ROOT, "outcome-templates", {"type": "outcomeTemplates"}, today)
    earlier = json.loads((FIRST / "outcome-templates.request.json").read_text())["response_sha256"]
    check(sha256((ROOT / "outcome-templates.json").read_bytes()).hexdigest() == earlier, "template registry bytes unchanged since 15 September")
    text = {t["id"]: t["description"] for t in templates}
    check(len(templates) == 18 and not any("Recurring" in json.dumps(t) or "priceBinary" in json.dumps(t) for t in templates),
          "no template describes the recurring families")
    check("resolves to Yes if the {perp} price is above {threshold} at {time}" in text["binaryPrice"], "binaryPrice: wording is 'above', not 'at or above'")
    check("{seconds}-second TWAP of {priceDescription} price ending at {time}" in text["binaryPrice"], "binaryPrice: TWAP of a free-text reference")
    check("at or above {high}" in text["scalarPrice"] and "at or below {low}" in text["scalarPrice"]
          and "$1 times (price - {low}) / ({high} - {low})" in text["scalarPrice"], "scalarPrice: capped linear payoff")
    check("equals or crosses {target} at any time after this market is deployed" in text["priceTouch"], "priceTouch: path-dependent")
    for ident in ("binaryPrice", "scalarPrice", "priceTouch"):
        check("semanticRestriction:This market must refer to the price of a Hyperliquid perp." in text[ident], f"{ident}: semantic restriction")

    # ------------------------------------------------------------ settlements: 20 binaries, 5 rollovers
    blocks = [  # (package, [BTC, ETH, SOL, HYPE] ids)
        (SECOND, [2820, 2822, 2824, 2825]), (SECOND, [3061, 3062, 3063, 3064]),
        (ROOT, [3253, 3254, 3255, 3256]), (ROOT, [3467, 3468, 3469, 3470]), (ROOT, [3719, 3720, 3721, 3722]),
    ]
    expected = {
        3253: ("BTC", "20260916-0600", "77616", "0.0", "75941.6"), 3254: ("ETH", "20260916-0600", "2496.1", "0.0", "2406"),
        3255: ("SOL", "20260916-0600", "101.32", "0.0", "97.19"), 3256: ("HYPE", "20260916-0600", "79.72", "0.0", "77.2439"),
        3467: ("BTC", "20260917-0600", "75941", "1.0", "76297.9"), 3468: ("ETH", "20260917-0600", "2406", "1.0", "2436.5"),
        3469: ("SOL", "20260917-0600", "97.19", "1.0", "99.506"), 3470: ("HYPE", "20260917-0600", "77.244", "1.0", "78.711"),
        3719: ("BTC", "20260918-0600", "76298", "1.0", "77457.8"), 3720: ("ETH", "20260918-0600", "2436.5", "1.0", "2479.9"),
        3721: ("SOL", "20260918-0600", "99.506", "1.0", "105.3626"), 3722: ("HYPE", "20260918-0600", "78.711", "1.0", "87.7225"),
    }
    chain, margins = [], {}
    for root, idents in blocks:
        row = []
        for ident in idents:
            data, _ = read_capture(root, f"settled-{ident}", {"type": "settledOutcome", "outcome": ident})
            spec = fields(data["spec"]["description"])
            check(data["spec"]["name"] == "Recurring" and spec["class"] == "priceBinary", f"{ident}: canonical priceBinary")
            target, price = F(spec["targetPrice"]), F(data["details"].split(":", 1)[1])
            if ident in expected:
                symbol, expiry, want_target, fraction, want_price = expected[ident]
                check((spec["underlying"], spec["expiry"], spec["targetPrice"]) == (symbol, expiry, want_target), f"{ident}: terms")
                check((data["settleFraction"], data["details"]) == (fraction, f"price:{want_price}"), f"{ident}: reported fraction and price")
            check(data["settleFraction"] == ("1.0" if price >= target else "0.0"), f"{ident}: fraction consistent with the inclusive rule")
            check(data["settleFraction"] == ("1.0" if price > target else "0.0"), f"{ident}: and equally with a strict rule")
            margins[ident] = abs(price - target) / target
            row.append((target, price))
        chain.append(row)
    check(len(margins) == 20 and min(margins, key=lambda ident: margins[ident]) == 3061 and margins[3061] == F(26, 77583),
          "no observation at its target; the closest is 3061 at 26 USD, so inclusivity is untested")
    live_targets = [F(expected_live[s][1]) for s in ("BTC", "ETH", "SOL", "HYPE")]
    rollovers = 0
    for previous, following in zip(chain, chain[1:] + [[(t, None) for t in live_targets]]):
        for (_, price), (target, _) in zip(previous, following):
            check(abs(target - price) / price < F("0.0002"), "next target within 0.02 percent of the previous reported settlement price")
            rollovers += 1
    check(rollovers == 20, "five rollovers across four underlyings")
    # The target is not a fixed rounding of the reported price: 75,941.6 became 75,941 (not the
    # rounded 75,942) while 77.2439 became 77.244 (not the truncated 77.243).
    check(chain[3][0][0] == 75941 and chain[2][0][1] == F("75941.6"), "BTC 17 Sep target is below the rounded previous price")
    check(chain[3][3][0] == F("77.244") and chain[2][3][1] == F("77.2439"), "HYPE 17 Sep target is above the truncated previous price")

    # ------------------------------------------------------------ bucket settlements
    for idents, want_thresholds, want_index in (([3259, 3260, 3261, 3262], "76063,79168", 0),
                                                ([3471, 3472, 3473, 3474], "74422,77460", 1),
                                                ([3723, 3724, 3725, 3726], "74772,77824", 1)):
        rows = [read_capture(ROOT, f"settled-{i}", {"type": "settledOutcome", "outcome": i}, today)[0] for i in idents]
        question = fields(rows[1]["question"]["description"])
        check(question["class"] == "priceBucket" and question["priceThresholds"] == want_thresholds, f"{idents[0]}: bucket terms")
        p1, p2 = (F(x) for x in question["priceThresholds"].split(","))
        price = F(rows[1]["details"].split(":", 1)[1])
        documented = 0 if price < p1 else (1 if price < p2 else 2)  # < P1, [P1, P2), >= P2
        check(documented == want_index, f"{idents[0]}: bucket containing the reported price")
        check([r["settleFraction"] for r in rows[1:]] == ["1.0" if k == documented else "0.0" for k in range(3)],
              f"{idents[0]}: exactly the documented bucket paid, by index order")
        check(rows[0]["spec"]["name"] == "Recurring Fallback" and rows[0]["settleFraction"] == "0.0", f"{idents[0]}: fallback paid nothing")
        binary_target = next(t for row in chain for (t, pr) in row[:1] if pr == price)
        check(abs(p1 - binary_target * F("0.98")) < 1 and abs(p2 - binary_target * F("1.02")) < 1,
              f"{idents[0]}: thresholds within 1 USD of the binary target -2 and +2 percent")
    check(abs(F(75908) - 77457 * F("0.98")) < 1 and abs(F(79007) - 77457 * F("1.02")) < 1, "live bucket thresholds follow the same pattern")

    # ------------------------------------------------------------ instance 3253: the mirror image of 3061
    late_book, _ = read_capture(SECOND, "book-3253-no", {"type": "l2Book", "coin": "#32531"})
    contexts, _ = read_capture(SECOND, "meta-and-asset-ctxs", {"type": "metaAndAssetCtxs"})
    index = next(i for i, u in enumerate(contexts[0]["universe"]) if u["name"] == "BTC")
    q, L, U, cap = F("0.1"), F(60000), F(110000), F(-1000)
    K, p, n, X0 = F(77616), asks(late_book)[0][0], F(1000), F(contexts[1][index]["markPx"])
    check((p, X0) == (F("0.975"), F(75362)), "3253: NO ask 0.975 and BTC mark 75,362 at capture")
    D, A = q * (X0 - K), q * (K - L)
    check((D, A) == (F("-225.4"), F("1761.6")), "3253 analysis_time baseline: D is negative when the mark is below the strike")
    check(D + p * A == F("1492.16") and D + p * A > -cap, "3253: best achievable worst loss 1,492.16 exceeds the cap")
    pnl = O.total([O.linear(q, X0), O.digital_below(n, K), O.cash(-p * n)])
    check(pnl(K) == F("-749.6") and pnl(L) == F("-1511.2"), "3253: -749.60 at the strike, -1,511.20 at the floor")
    check(spans(O.below(pnl, cap, L, U, [K])) == [("60000", True, "65112", False)], "3253: fails on [60000, 65112)")
    settled_price = chain[2][0][1]
    check(settled_price < K and pnl(settled_price) == F("82.96"), "3253: NO paid in full and the realized result was +82.96")
    # 3061 expired worthless inside the cap; 3253 paid in full with a gain. Both proposals fail
    # the same check for the same reason: another admissible price breaches the cap.

    # ------------------------------------------------------------ books
    no_book, no_record = read_capture(ROOT, "book-3965-no", {"type": "l2Book", "coin": "#39651"}, today)
    yes_book, _ = read_capture(ROOT, "book-3965-yes", {"type": "l2Book", "coin": "#39650"}, today)
    put_book, _ = read_capture(ROOT, "book-bucket0-3971-yes", {"type": "l2Book", "coin": "#39710"}, today)
    for stem, coin in (("book-bucket1-3972-yes", "#39720"), ("book-bucket2-3973-yes", "#39730")):
        read_capture(ROOT, stem, {"type": "l2Book", "coin": coin}, today)
    def ask_side(book):
        return [(F(level["px"]), F(level["sz"]), level["n"]) for level in book["levels"][1]]

    def mirrored_bids(book):
        return [(1 - F(level["px"]), F(level["sz"]), level["n"]) for level in book["levels"][0]]

    check(ask_side(no_book)[:7] == mirrored_bids(yes_book)[:7] and yes_book["time"] - no_book["time"] == 2236,
          "18 Sep: first seven NO asks mirror YES bids at 1 - price, equal sizes and order counts, snapshots 2.2 s apart")
    late_yes, _ = read_capture(SECOND, "book-3253-yes", {"type": "l2Book", "coin": "#32530"})
    check(ask_side(late_book) == mirrored_bids(late_yes) and len(ask_side(late_book)) == 8,
          "15 Sep: every NO ask mirrors a YES bid: one book shown twice, never additive")
    books = [p for root in (FIRST, SECOND, ROOT) for p in sorted(root.glob("book-*.json")) if not p.name.endswith(".request.json")]
    check(len(books) == 9, "nine retained books")
    for path in books:
        levels = json.loads(path.read_text())["levels"]
        check(all(F(level["sz"]).denominator == 1 for side in levels for level in side), f"{path.name}: sizes are whole contracts")
        prices = [F(level["px"]) for side in levels for level in side]
        check(F("0.00001") <= min(prices) and max(prices) <= F("0.99999"), f"{path.name}: prices within 0.00001 and 0.99999")
    fee_fields = {}
    for o in meta["outcomes"]:
        fee_fields.setdefault(o.get("venue"), set()).add(o.get("deployerFeeScale"))
    check(fee_fields == {"out": {"1.0"}, "skew": {"1.0"}, "txyz": {None}, None: {None}},
          "deployerFeeScale is 1.0 on out and skew outcomes and absent on txyz and canonical ones")
    best_bid, best_ask = F(put_book["levels"][0][0]["px"]), asks(put_book)[0][0]
    check((best_bid, best_ask) == (F("0.00002"), F("0.17399")) and best_ask / best_bid > 8699,
          "bucket-0 YES: bid 0.00002 against ask 0.17399, so no default valuation of a held token is defensible")
    contexts, ctx_record = read_capture(ROOT, "meta-and-asset-ctxs", {"type": "metaAndAssetCtxs"}, today)
    index = next(i for i, u in enumerate(contexts[0]["universe"]) if u["name"] == "BTC")
    X0 = F(contexts[1][index]["markPx"])
    check(X0 == F("77631.4"), "BTC mark at capture")
    gap = datetime.fromisoformat(no_record["retrieved_at"]) - datetime.fromisoformat(ctx_record["retrieved_at"])
    check(0 <= gap.total_seconds() < 3, "mark and NO book retrieved within three seconds")

    # ------------------------------------------------------------ the same objective through two canonical instruments
    exposure = O.linear(q, X0)
    keep = -cap / (X0 - L)
    check(keep == F(5000, 88157), "benchmark: keep 5000/88157 BTC (about 0.0567), sell the rest at the mark, hold the cash")
    benchmark = O.linear(keep, X0).value
    check(O.infimum(benchmark, L, U, [])[0] == cap, "benchmark meets the cap exactly, with no premium")

    cases = {
        "binary NO 3965": (F(77457), asks(no_book), "17.44", "1745.7", "804.7507", "18172417/12899", "25470083/12101",
                           1409, 2104, "645.76904", "-663.20904", "-999.90904", ["69999.0904", "84089.0904"], "630619989713/6813750"),
        "bucket-0 YES 3971": (F(75908), asks(put_book), "172.34", "1590.8", "449.123292", "76314000/82601", "281004800/99999",
                              924, 2810, "160.76676", "-333.10676", "-999.90676", ["69999.0676", "79239.0676"], "369512914573/4542500"),
    }
    costs = {}
    for tag, (K, levels, d, a, best, low, high, first, last, cost, at_strike, at_floor, breakevens, beats_above) in cases.items():
        D, A = q * (X0 - K), q * (K - L)
        check((O.fmt(D), O.fmt(A)) == (d, a), f"{tag}: D and A")
        check(O.fmt(D + levels[0][0] * A) == best, f"{tag}: best achievable worst loss at the best ask")
        window = O.size_window(exposure.value, O.digital_below(F(1), K).value, levels, cap, L, U, [K])
        check(window["status"] == "nonempty" and (O.fmt(window["lower_bound"]), O.fmt(window["upper_bound"])) == (low, high), f"{tag}: exact size bounds at displayed depth")
        check((window["smallest"], window["largest"]) == (first, last), f"{tag}: whole-contract window")
        check(window["binding"] == [(L, "at"), (K, "at")], f"{tag}: floor binds the minimum size, strike binds the maximum")
        n = F(first)
        spent = O.ask_cost(levels, n)
        costs[tag] = spent
        check(O.fmt(spent) == cost, f"{tag}: cost of the smallest passing size")
        pnl = O.total([exposure, O.digital_below(n, K), O.cash(-spent)])
        check(not O.below(pnl, cap, L, U, [K]), f"{tag}: passes")
        check(O.below(O.total([exposure, O.digital_below(n - 1, K), O.cash(-O.ask_cost(levels, n - 1))]), cap, L, U, [K]), f"{tag}: one contract fewer fails")
        check((O.fmt(pnl(X0)), O.fmt(pnl(K)), O.fmt(pnl(L))) == ("-" + cost, at_strike, at_floor), f"{tag}: P&L at baseline, strike, floor")
        roots = [O.fmt(-piece["intercept"] / piece["slope"]) for piece in O.profile(pnl, L, U, [K])]
        check(roots == breakevens, f"{tag}: break-even prices")
        check(spans(O.below(lambda s: benchmark(s) - pnl(s), F(0), L, U, [K])) == [("60000", True, O.fmt(K), False), (beats_above, False, "110000", True)],
              f"{tag}: beats the benchmark only below the strike and above {beats_above}")
        check(spans(O.below(lambda s: exposure.value(s) - pnl(s), F(0), L, U, [K])) == [("60000", True, O.fmt(K), False)], f"{tag}: beats no hedge only below the strike")
    binary, put = costs["binary NO 3965"], costs["bucket-0 YES 3971"]
    check(binary / (q * X0) > F("0.083") and put / (q * X0) < F("0.021"), "premium is 8.3 percent of the position through the binary, 2.1 percent through the bucket")
    check(binary / put > 4, "the same cap costs four times as much through the at-the-money binary")
    check(F("84089.0904") / X0 - 1 > F("0.083"), "binary hedge loses money at every price from the strike up to an 8.3 percent rally")

    # ------------------------------------------------------------ infeasibility survives depth
    old_book, _ = read_capture(FIRST, "book-3061-no", {"type": "l2Book", "coin": "#30611"})
    K, levels = F(77583), asks(old_book)
    unit = O.digital_below(F(1), K).value
    flat = O.size_window(O.linear(q, K).value, unit, [(levels[0][0], F(10 ** 9))], cap, L, U, [K])
    walked = O.size_window(O.linear(q, K).value, unit, levels, cap, L, U, [K])
    check(flat["status"] == "empty" and walked["status"] == "empty", "3061 at 0.942: empty at the best ask, therefore empty at depth")
    check(all(price >= levels[0][0] for price, _ in levels), "every displayed ask is at or above the best ask, so depth only tightens both constraints")

    print(f"{CHECKS} checks passed; {len([h for h in HASHES if h[0] == ROOT.name])} response hashes verified in this package, "
          f"{len([h for h in HASHES if h[0] != ROOT.name])} re-verified from earlier packages.")


if __name__ == "__main__":
    main()
