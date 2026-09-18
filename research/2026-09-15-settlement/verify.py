"""Verify the settlement evidence package offline and the arithmetic it supports."""

from datetime import datetime
from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIOR = ROOT.parent / "2026-09-15"
CHECKS = 0


def check(condition, description):
    global CHECKS
    if not condition:
        raise AssertionError(description)
    CHECKS += 1


def read_capture(root, stem, expected_request):
    record = json.loads((root / f"{stem}.request.json").read_text())
    raw = (root / f"{stem}.json").read_bytes()
    check(sha256(raw).hexdigest() == record["response_sha256"], f"{stem}: SHA-256")
    check(record["request_body"] == expected_request, f"{stem}: request identity")
    check(record["http_status"] == 200, f"{stem}: HTTP status")
    check(record["endpoint"] == "https://api.hyperliquid.xyz/info", f"{stem}: endpoint")
    retrieved = datetime.fromisoformat(record["retrieved_at"])
    check(retrieved.tzinfo is not None, f"{stem}: timezone")
    return json.loads(raw), record


def parse_description(text):
    return dict(part.split(":", 1) for part in text.split("|"))


def main():
    # Settlements of the four recurring instances that expired 2026-09-15 06:00 UTC,
    # and of the four that expired 2026-09-14 06:00 UTC.
    settled = {}
    for ident in (2820, 2822, 2824, 2825, 3061, 3062, 3063, 3064):
        data, record = read_capture(ROOT, f"settled-{ident}", {"type": "settledOutcome", "outcome": ident})
        check(data["spec"]["outcome"] == ident, f"{ident}: identity")
        check(data["spec"]["name"] == "Recurring", f"{ident}: canonical family")
        check(data["spec"]["quoteToken"] == "USDC", f"{ident}: quote token")
        check(data["details"].startswith("price:"), f"{ident}: canonical settlement records a price")
        check(datetime.fromisoformat(record["retrieved_at"]).date().isoformat() == "2026-09-15", f"{ident}: capture date")
        settled[ident] = data

    expected = {
        2820: ("BTC", "20260914-0600", "77284", "1.0", "77576.7"),
        2822: ("ETH", "20260914-0600", "2522.3", "0.0", "2515.6"),
        2824: ("SOL", "20260914-0600", "101.76", "0.0", "101.0579"),
        2825: ("HYPE", "20260914-0600", "79.348", "1.0", "79.546"),
        3061: ("BTC", "20260915-0600", "77583", "1.0", "77609"),
        3062: ("ETH", "20260915-0600", "2516", "0.0", "2496"),
        3063: ("SOL", "20260915-0600", "101.07", "1.0", "101.31"),
        3064: ("HYPE", "20260915-0600", "79.546", "1.0", "79.7216"),
    }
    for ident, (symbol, expiry, target, fraction, price) in expected.items():
        spec = parse_description(settled[ident]["spec"]["description"])
        check(spec["class"] == "priceBinary" and spec["period"] == "1d", f"{ident}: class and period")
        check(spec["underlying"] == symbol and spec["expiry"] == expiry, f"{ident}: underlying and expiry")
        check(spec["targetPrice"] == target, f"{ident}: target")
        check(settled[ident]["settleFraction"] == fraction, f"{ident}: reported fraction")
        check(settled[ident]["details"] == f"price:{price}", f"{ident}: reported settlement price")
        # The official rule: YES if and only if settlement price >= target (inclusive).
        implied = "1.0" if F(price) >= F(target) else "0.0"
        check(implied == fraction, f"{ident}: reported fraction agrees with the inclusive rule")

    # 3061: settled 26 USD above target. NO paid nothing.
    margin = F("77609") - F("77583")
    check(margin == 26, "3061: settlement margin above target")
    check(margin / F("77583") < F("0.0004"), "3061: margin under 0.04 percent")
    no_payout_3061 = 1 - F(settled[3061]["settleFraction"])
    check(no_payout_3061 == 0, "3061: NO side paid zero")

    # The prior package captured the 3061 NO book 19 minutes before expiry: best ask 0.942 for 1,000.
    book, record = read_capture(PRIOR, "book-3061-no", {"type": "l2Book", "coin": "#30611"})
    best_ask = F(book["levels"][1][0]["px"])
    check(best_ask == F("0.942"), "prior package: NO best ask 0.942")
    check(book["time"] == 1789450871880, "prior package: exchange timestamp")
    premium_late = best_ask * 1000
    check(premium_late == 942, "1,000 NO at the late ask cost 942 USDC")
    check(premium_late - no_payout_3061 * 1000 == 942, "late buyer lost the whole premium")
    # A 0.1 BTC holder valued at 77,583 (the target) who bought that hedge and a 1,000 USD cap:
    # any settlement at or above the target leaves the position roughly flat and the hedge worthless.
    combined_at_settle = F("0.1") * (F("77609") - F("77583")) + 0 - premium_late
    check(combined_at_settle == F("-939.4"), "combined P&L at settlement for the late hedge")
    check(combined_at_settle >= -1000, "late hedge still inside a 1,000 cap at settlement")
    # Had the price settled one dollar below the TARGET, NO would have paid 1,000. Note that
    # 77,582 is one dollar below the target, not one dollar below the reported settlement price
    # of 77,609: the two differ by the 26 USD margin, so this is a 27 dollar move, not a 1 USD one.
    combined_if_below = F("0.1") * (F("77582") - F("77583")) + 1000 - premium_late
    check(combined_if_below == F("57.9"), "one dollar below the target flips the hedge to +57.9")
    check(F("77609") - F("77582") == 27, "the reported price is 27 dollars above that case")
    # The cliff is measured across the threshold itself, both sides valued at the target:
    # at 77,583 NO pays nothing; at 77,582 it pays in full. The step is 999.9, not 997.3.
    combined_at_target = F("0.1") * (F("77583") - F("77583")) + 0 - premium_late
    check(combined_at_target == F("-942"), "at the target the hedge pays nothing")
    check(combined_if_below - combined_at_target == F("999.9"),
          "crossing the threshold by 1 USD moves the result by 999.9 USD")

    # Rollover: the next day's target tracks the previous settlement price.
    meta, meta_record = read_capture(ROOT, "outcome-meta", {"type": "outcomeMeta"})
    recurring = {parse_description(o["description"])["underlying"]: o for o in meta["outcomes"] if o["name"] == "Recurring"}
    check(set(recurring) == {"BTC", "ETH", "SOL", "HYPE"}, "four recurring instances live")
    next_expected = {
        "BTC": (3253, "77616", 3061), "ETH": (3254, "2496.1", 3062),
        "SOL": (3255, "101.32", 3063), "HYPE": (3256, "79.72", 3064),
    }
    for symbol, (ident, target, prev) in next_expected.items():
        item = recurring[symbol]
        spec = parse_description(item["description"])
        check(item["outcome"] == ident, f"{symbol}: new instance id")
        check(spec["expiry"] == "20260916-0600" and spec["targetPrice"] == target, f"{symbol}: new expiry and target")
        prev_price = F(settled[prev]["details"].split(":", 1)[1])
        drift = abs(F(target) - prev_price) / prev_price
        check(drift < F("0.0002"), f"{symbol}: new target within 0.02 percent of previous settlement price")
    for symbol, prev, prev_prev in (("BTC", 3061, 2820), ("ETH", 3062, 2822), ("SOL", 3063, 2824), ("HYPE", 3064, 2825)):
        target = F(parse_description(settled[prev]["spec"]["description"])["targetPrice"])
        prev_price = F(settled[prev_prev]["details"].split(":", 1)[1])
        check(abs(target - prev_price) / prev_price < F("0.0002"), f"{symbol}: 15 Sep target within 0.02 percent of 14 Sep settlement")
    check(3061 not in {o["outcome"] for o in meta["outcomes"]}, "3061 pruned from live catalogue after settlement")

    # BTC perp mark at capture, sixteen hours after settlement.
    ctxs, _ = read_capture(ROOT, "meta-and-asset-ctxs", {"type": "metaAndAssetCtxs"})
    universe, contexts = ctxs[0]["universe"], ctxs[1]
    index = next(i for i, u in enumerate(universe) if u["name"] == "BTC")
    mark = F(contexts[index]["markPx"])
    check(mark == F("75362.0"), "BTC mark at capture")
    check((mark - F("77609")) / F("77609") < F("-0.028"), "BTC more than 2.8 percent below the settlement price at capture")

    # Today's instance: NO is deep in the money; its maximum net benefit is small.
    no_book, _ = read_capture(ROOT, "book-3253-no", {"type": "l2Book", "coin": "#32531"})
    yes_book, _ = read_capture(ROOT, "book-3253-yes", {"type": "l2Book", "coin": "#32530"})
    no_ask = F(no_book["levels"][1][0]["px"])
    check(no_ask == F("0.975"), "3253 NO best ask 0.975")
    check(F(yes_book["levels"][1][0]["px"]) == F("0.037"), "3253 YES best ask 0.037")
    max_net_benefit = (1 - no_ask) * 1000
    check(max_net_benefit == 25, "1,000 NO at 0.975 can add at most 25 USDC net of premium")
    # For 0.1 BTC valued at the 77,616 target, a 1,000 USD cap needs the hedge to absorb a 10,000 USD
    # per-BTC move; 25 USDC covers a 250 USD per-BTC move.
    check(max_net_benefit / F("0.1") == 250, "covers at most a 250 USD per-BTC decline")
    check(max_net_benefit / F("0.1") < 10000, "cannot support the cap over the declared domain")

    # Feasibility window for a NO hedge of a long linear exposure under an inclusive terminal loss cap,
    # canonical family (NO pays 1 when the settlement price is strictly below K), domain lower bound L.
    #
    # The baseline is explicit, never implied. X0 is the analysis-time valuation price:
    #   D = q * (X0 - K)   unrealized move from the analysis-time baseline down to the strike
    #   A = q * (K - L)    further loss from the strike down to the domain floor
    # "strike_reference" is the special case X0 == K, so D == 0. It is a labeled convention,
    # not a default: the 14 September examples used it implicitly and understated the floor loss.
    #
    # Terminal P&L (zero other costs, one common valuation reference):
    #   at S = K (hedge pays nothing):  -D - p*n            >= -cap  ->  n <= (cap - D) / p
    #   at S = L (hedge pays in full):  -D - A + n*(1 - p)  >= -cap  ->  n >= (D + A - cap) / (1 - p)
    # A feasible nonnegative size exists if and only if D + p * A <= cap.
    def window(q, K, L, cap, p, X0=None):
        D = q * ((X0 if X0 is not None else K) - K)
        A = q * (K - L)
        lo = max(F(0), (D + A - cap) / (1 - p))
        return lo, (cap - D) / p

    def pnl_at(S, q, K, p, n, X0=None):
        """Terminal P&L at settlement price S. NO pays 1 strictly below K."""
        X = X0 if X0 is not None else K
        return q * (S - X) + (n if S < K else F(0)) - p * n

    q, L, cap = F("0.1"), F(60000), F(1000)
    K0, p0, n0 = F(77583), F("0.055"), F(1000)

    # Strike-reference baseline (D = 0).
    lo, hi = window(q, K0, L, cap, p0)
    check(lo == F("758.3") / F("0.945") and hi == F(1000) / p0, "0.055 strike baseline: bounds")
    check(lo < hi and lo <= n0 <= hi, "0.055 strike baseline: 1,000 contracts feasible")
    # Floor and target evaluated through pnl_at, so the assertion cannot pass without the hedge.
    # The previous revision asserted q*(K - L) + n - p*n >= -cap, which is +A rather than -A and
    # therefore held even at n = 0, where the true floor loss is 1,758.3 and breaches the cap.
    check(pnl_at(L, q, K0, p0, n0) == F("-813.300"), "0.055 strike baseline: floor P&L -813.30")
    check(pnl_at(L, q, K0, p0, n0) >= -cap, "0.055 strike baseline: passes at the domain floor")
    check(pnl_at(K0, q, K0, p0, n0) == -F(55), "0.055 strike baseline: target P&L -55")
    check(pnl_at(K0, q, K0, p0, n0) >= -cap, "0.055 strike baseline: passes at the target")
    # Regression: the unhedged exposure must fail at the floor, under both the corrected
    # assertion and the closed form. This is the check the previous revision could not make.
    check(pnl_at(L, q, K0, p0, F(0)) == F("-1758.3"), "no hedge: floor P&L -1,758.3")
    check(not (pnl_at(L, q, K0, p0, F(0)) >= -cap), "no hedge: fails at the domain floor")

    # Analysis-time baseline, X0 = 79,087 (14 Sep 19:30 UTC mark). Illustration only: this
    # observation is six minutes later than the 0.055 quote and its response bytes were not
    # retained, so it is not hash-verifiable here.
    X0 = F(79087)
    check(q * (X0 - K0) == F("150.4"), "X0 = 79,087: D = 150.40")
    check(pnl_at(L, q, K0, p0, n0, X0) == F("-963.700"), "X0 baseline: floor P&L -963.70")
    check(cap + pnl_at(L, q, K0, p0, n0, X0) == F("36.300"), "X0 baseline: 36.30 cap headroom")
    # The same proposal is feasible under both baselines, but the headroom differs by D = 150.40.
    # That margin is what fees and cost assumptions consume, so the baseline must be stated.
    lo_x, hi_x = window(q, K0, L, cap, p0, X0)
    check(lo_x < hi_x and lo_x <= n0 <= hi_x, "X0 baseline: 1,000 contracts feasible")
    check(cap + pnl_at(L, q, K0, p0, n0) - (cap + pnl_at(L, q, K0, p0, n0, X0)) == F("150.400"),
          "baselines differ by D at the floor")

    # Infeasible quotes. Under the strike baseline these are the 15 September asks.
    for K, p, tag in ((F(77583), F("0.942"), "0.942"), (F(77616), F("0.975"), "0.975")):
        lo, hi = window(q, K, L, cap, p)
        check(lo > hi, f"window at {tag}: no feasible size")

    # At 0.975 the premium alone is 975 and does NOT exceed the 1,000 cap; the proposal fails
    # at the domain floor. A PREMIUM_EXHAUSTS_BUDGET reason code would misdescribe this failure.
    K3, p3 = F(77616), F("0.975")
    check(p3 * n0 == F("975.000") and p3 * n0 <= cap, "0.975: premium 975 is within the cap")
    check(pnl_at(K3, q, K3, p3, n0) == F("-975.000"), "0.975: target P&L -975, inside the cap")
    check(pnl_at(L, q, K3, p3, n0) == F("-1736.600"), "0.975: floor P&L -1,736.60 breaches the cap")

    # Closed form agrees with the window under both baselines.
    for K, p, feasible in ((F(77583), F("0.055"), True), (F(77583), F("0.942"), False), (F(77616), F("0.975"), False)):
        lo, hi = window(q, K, L, cap, p)
        check((q * (K - L) * p <= cap) == (lo <= hi), f"closed form agrees at p={p}")
        check((lo <= hi) == feasible, f"feasibility at p={p}")
    for X in (K0, X0):
        lo, hi = window(q, K0, L, cap, p0, X)
        D, A = q * (X - K0), q * (K0 - L)
        check((D + p0 * A <= cap) == (lo <= hi), f"general closed form agrees at X0={X}")

    # The threshold cliff. Crossing K by one dollar flips the full 1,000-contract payout.
    # The 15 September settlement margin was 26 USD above target (77,609 vs 77,583); a
    # "one dollar lower" settlement is 77,582, which is 27 dollars below the reported price.
    pc = F("0.942")
    at_K = pnl_at(K0, q, K0, pc, n0)
    below = pnl_at(K0 - 1, q, K0, pc, n0)
    check(F(77609) - F(77582) == F(27), "77,609 to 77,582 is a 27 dollar move")
    check(below - at_K == F("999.900"), "crossing 77,583 to 77,582 moves P&L by 999.90")
    # Realized P&L for that late purchase was -939.40, inside the cap: NO settling worthless is
    # not itself an objective breach. The proposal fails because other admissible prices breach it.
    check(pnl_at(F(77609), q, K0, pc, n0) == F("-939.400"), "realized P&L -939.40, inside the cap")
    check(pnl_at(F(77609), q, K0, pc, n0) >= -cap, "realized outcome met the cap")
    check(not (pnl_at(L, q, K0, pc, n0) >= -cap), "same proposal breaches the cap at the floor")
    print(f"{CHECKS} checks passed; {len(expected) + 4} response hashes verified in this package, plus one prior-package book.")


if __name__ == "__main__":
    main()
