"""Verify the reference oracle, the conformance vectors, the golden table and the example in PLAN.md.

    python3 oracle/verify.py            # check
    python3 oracle/verify.py --write    # regenerate the expected result, then check

The expected result is generated, never hand-edited. Independent hand-derived assertions
below pin its key values, so the fixture cannot merely agree with itself.
"""

from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

import canon
import exact
import oracle as O

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
FIXTURES = PROJECT / "fixtures"
CHECKS = 0


def check(condition, description):
    global CHECKS
    if not condition:
        raise AssertionError(description)
    CHECKS += 1


def span(interval):
    return (O.fmt(interval["lower"]), interval["lower_inclusive"], O.fmt(interval["upper"]), interval["upper_inclusive"])


def inside(price, intervals):
    return any((i["lower"] < price < i["upper"]) or (price == i["lower"] and i["lower_inclusive"])
               or (price == i["upper"] and i["upper_inclusive"]) for i in intervals)


def main():
    # ---- conformance vectors: the same files the Go engine and the TypeScript checker read
    for row in json.loads((FIXTURES / "vectors" / "numbers.json").read_text())["vectors"]:
        try:
            out = exact.format(exact.parse(row["input"]))
        except exact.NumberError:
            out = None
        check((out is not None) == row["accepted"], f"number {row['input']!r}: accepted")
        check(out is None or out == row["canonical"], f"number {row['input']!r}: canonical form")
    for row in json.loads((FIXTURES / "vectors" / "canonical-json.json").read_text())["vectors"]:
        try:
            out = canon.canonical(canon.loads(bytes.fromhex(row["input_hex"])))
        except canon.CanonError:
            out = None
        check((out is not None) == row["accepted"], f"canonical JSON, {row['name']}: accepted")
        if out is not None:
            check(out.decode() == row["canonical"] and sha256(out).hexdigest() == row["sha256"], f"canonical JSON, {row['name']}: bytes and digest")
    # One digest pinned outside every implementation: printf '%s' '{"label":"cap <1000 & é"}' | shasum -a 256
    check(canon.digest({"label": "cap <1000 & é"}) == "7371d496019dedfecf8091a16e919f5fc1261f315e5e09994c71acbbde641876", "digest agrees with shasum")

    L, U, cap = F(60000), F(110000), F(-1000)
    exposure = O.linear(F("0.1"), F(100000))

    def hedged(n, p=F("0.2"), strike=F(90000)):
        return O.total([exposure, O.digital_below(F(n), strike), O.cash(-p * n)])

    # ---- PLAN.md section 3, golden table
    check([span(i) for i in O.below(exposure, cap, L, U)] == [("60000", True, "90000", False)], "no hedge: failure [60000, 90000)")
    check(O.infimum(exposure, L, U) == (F(-4000), True, F(60000)), "no hedge: worst -4,000 at 60,000")
    check([span(i) for i in O.below(hedged(1000), cap, L, U)] == [("60000", True, "82000", False), ("90000", True, "92000", False)],
          "1,000 contracts: failures [60000, 82000) and [90000, 92000)")
    check(O.infimum(hedged(1000), L, U) == (F(-3200), True, F(60000)), "1,000 contracts: worst -3,200")
    check(hedged(1000)(F(82000)) == cap and hedged(1000)(F(92000)) == cap, "82,000 and 92,000 meet the inclusive cap")
    check(hedged(1000)(F(90000)) == F(-1200), "exactly 90,000: -1,200, fails")
    check(hedged(1000)(F("89999.99")) == F("-200.001"), "one cent below the strike: -200.001")

    flat = [(F("0.2"), F(10 ** 9))]
    window = O.size_window(exposure, O.digital_below(F(1), F(90000)), flat, cap, L, U)
    check(window["status"] == "empty", "0.20 premium: no size meets the cap throughout")
    check((window["lower_bound"], window["upper_bound"]) == (F(3750), F(0)), "0.20 premium: needs n >= 3,750 and n <= 0")
    check(window["binding"] == [(F(60000), "at"), (F(90000), "at")], "0.20 premium: floor binds below, strike binds above")

    D, A, p = F(1000), F(3000), F("0.2")
    worst = {n: O.infimum(hedged(n), L, U)[0] for n in (2999, 3000, 3001)}
    check(worst[3000] == F(-1600) and worst[2999] < worst[3000] and worst[3001] < worst[3000], "best size 3,000; worst loss 1,600")
    check(A == 3000 and D + p * A == 1600, "minimax size equals A and minimax loss equals D + p*A")
    check((1 - p) * (-D) + p * (-D - A) == -(D + p * A) < cap, "Farkas weights (1-p, p) prove infeasibility")

    check(O.infimum(O.linear(F("0.07"), F(100000)), L, U)[0] == F(-2800), "sell 0.03 BTC: worst 2,800, fails")
    kept = O.linear(F("0.025"), F(100000))
    check(O.infimum(kept, L, U)[0] == F(-1000) and not O.below(kept, cap, L, U), "sell 0.075 BTC: worst 1,000, passes")
    check([span(i) for i in O.below(kept - hedged(1000), F(0), L, U)] == [("268000/3", False, "90000", False), ("308000/3", False, "110000", True)],
          "1,000 contracts beat selling 0.075 BTC only on (89,333.33.., 90,000) and (102,666.66.., 110,000]")

    # ---- endpoint ownership is data: the strike belongs to exactly one side, or to neither
    n, K = F(700), F(90000)
    parity = O.digital_below(n, K) + O.digital_at_or_above(n, K)
    check(O.profile(parity, L, U) == [{"lower": L, "lower_inclusive": True, "upper": U, "upper_inclusive": True, "slope": F(0), "intercept": n}],
          "canonical YES + NO pays n everywhere, strike included")
    neither = O.indicator(n, upper=K, upper_inclusive=False) + O.indicator(n, lower=K, lower_inclusive=False)
    check(neither(K) == 0 and neither(K - 1) == n and neither(K + 1) == n, "deployer reading: at the strike neither side is paid")
    check([(O.fmt(p["lower"]), O.fmt(p["upper"]), O.fmt(p["intercept"])) for p in O.profile(neither, L, U)] == [("60000", "90000", "700"), ("90000", "90000", "0"), ("90000", "110000", "700")],
          "an unowned strike is a piece of its own")
    P1, P2 = F(76063), F(79168)
    buckets = O.digital_below(n, P1) + O.digital_range(n, P1, P2) + O.digital_at_or_above(n, P2)
    check(len(O.profile(buckets, L, U)) == 1 and buckets(P1) == buckets(P2) == n, "three buckets partition the domain")
    check(O.profile(O.ramp_short(n, F(70000), F(80000)) + O.ramp_long(n, F(70000), F(80000)), L, U)[0]["intercept"] == n, "scalar Long + Short pays n everywhere")
    flat_between = O.linear(F("0.07"), F(80000)) + O.ramp_short(F(700), F(70000), F(80000))
    check(O.profile(flat_between, F(70000), F(80000))[0]["slope"] == 0, "q*(high-low) scalar Shorts flatten a long exposure between low and high")

    # ---- a function cannot be separated from its breakpoints
    low_strike = hedged(1000, strike=F(65000))
    check([span(i) for i in O.below(low_strike, F(-3500), L, U)] == [("65000", True, "67000", False)] and O.infimum(low_strike, L, U) == (F(-3700), True, F(65000)),
          "a strike in the outer third of the domain is evaluated correctly; nothing can omit it")
    check("breakpoints" not in O.below.__code__.co_varnames and "breakpoints" not in O.infimum.__code__.co_varnames and "breakpoints" not in O.profile.__code__.co_varnames,
          "no evaluation function accepts breakpoints")
    # The probe is a tripwire for a constructor that hides a kink. It fires only between its probe points.
    hidden_mid = O.Fn([], lambda s: F(1) if s < 90000 else F(0))
    hidden_edge = O.Fn([], lambda s: F(1) if s < 65000 else F(0))
    try:
        O.below(hidden_mid, cap, L, U)
    except ValueError:
        check(True, "tripwire fires on a kink between the probes")
    else:
        check(False, "tripwire fires on a kink between the probes")
    # Truth: hidden_edge is below 1/2 exactly on [65000, 110000]. With its kink outside the probes the
    # tripwire stays silent and the answer wrongly includes (60000, 65000). This is asserted on purpose:
    # the representation carries the guarantee, not the probe.
    missed = [span(i) for i in O.below(hidden_edge, F(1, 2), L, U)]
    check(missed == [("60000", False, "110000", True)] and hidden_edge(F(62000)) == 1, "the tripwire does NOT see a kink outside its probes")
    check([span(i) for i in O.below(O.digital_below(F(1), F(65000)), F(1, 2), L, U)] == [("65000", True, "110000", True)], "the same function built by its constructor is evaluated correctly")

    # ---- band infimum: the reduction for a declared basis bound
    band = F(50)
    target = F(77457)
    for name, fn, closed in (
        ("digital below K -> below K - b", O.digital_below(n, target), O.digital_below(n, target - band)),
        ("digital at or above K -> at or above K + b", O.digital_at_or_above(n, target), O.digital_at_or_above(n, target + band)),
        ("ramp short -> the same ramp, b lower", O.ramp_short(n, F(70000), F(80000)), O.ramp_short(n, F(70000) - band, F(80000) - band)),
        ("middle bucket [P1, P2) -> [P1 + b, P2 - b): it shrinks, it does not shift", O.digital_range(n, P1, P2), O.digital_range(n, P1 + band, P2 - band)),
    ):
        eroded = O.band_infimum(fn, band)
        check(O.profile(eroded - closed, F(60000), F(90000)) == [{"lower": F(60000), "lower_inclusive": True, "upper": F(90000), "upper_inclusive": True, "slope": F(0), "intercept": F(0)}], name)
    middle = O.band_infimum(O.digital_range(n, P1, P2), band)
    for label, shifted in (("down", O.digital_range(n, P1 - band, P2 - band)), ("up", O.digital_range(n, P1 + band, P2 + band))):
        check(O.below(middle - shifted, F(0), F(60000), F(90000)) != [], f"shifting the middle bucket {label} credits prices where it may pay nothing")
    check(O.band_infimum(exposure, band)(F(80000)) == exposure(F(80000)) - F("0.1") * band, "a linear exposure loses q*b")
    # An asymmetric tent: 3(s - 100) up to its peak at 100, then 100 - s. Within a band of 4 the worst case is
    # min(f(s - 4), f(s + 4)), and the two lines cross at 102: a breakpoint that is neither an original one nor a
    # shifted one. Derived by hand: 3(s - 104) up to 102, then 96 - s.
    tent = O.Fn([F(100)], lambda s: (s - 100) * 3 if s <= 100 else 100 - s)
    eroded_tent = O.band_infimum(tent, F(4))
    by_hand = O.Fn([F(102)], lambda s: (s - 104) * 3 if s <= 102 else 96 - s)
    check(F(102) in eroded_tent.breakpoints, "the crossing at 102 is found")
    check(O.profile(eroded_tent - by_hand, F(80), F(120)) == [{"lower": F(80), "lower_inclusive": True, "upper": F(120), "upper_inclusive": True, "slope": F(0), "intercept": F(0)}],
          "band infimum of the tent equals the hand-derived form everywhere")
    # A brute-force scan of the band can only find values at or above the infimum.
    mixed = O.digital_range(n, P1, P2) + O.linear(F("0.1"), target)
    for fn, width, lo, hi in ((tent, F(4), F(80), F(120)), (mixed, band, P1 - 200, P2 + 200)):
        eroded = O.band_infimum(fn, width)
        O.profile(eroded, lo, hi)  # affine between its own breakpoints, or the tripwire fires
        for k in range(0, 401):
            s = lo + (hi - lo) * F(k, 400)
            check(eroded(s) <= min(fn(s - width + 2 * width * F(j, 200)) for j in range(201)), f"band infimum is never above a scan of the band at {s}")

    # ---- the interval solver agrees with pointwise evaluation on a dense exact grid
    for fn in (hedged(1000), hedged(3000), low_strike, flat_between, exposure + O.digital_range(F(900), F(85000), F(95000)) + O.cash(F(-150)), neither + exposure):
        failing = O.below(fn, cap, L, U)
        eps = F(1, 1000)
        grid = {L + (U - L) * F(i, 997) for i in range(998)} | {c + d for c in list(fn.breakpoints) + [L, U] for d in (-eps, 0, eps)}
        grid |= {i[k] + d for i in failing for k in ("lower", "upper") for d in (-eps, 0, eps)}
        for s in (g for g in grid if L <= g <= U):
            check(inside(s, failing) == (fn(s) < cap), f"interval membership at {s}")

    # ---- the golden fixture, and the example result printed in PLAN.md
    lowered = canon.loads((FIXTURES / "golden" / "1000-contracts.ir.json").read_bytes())
    result = O.evaluate(lowered)
    expected_path = FIXTURES / "golden" / "1000-contracts.result.json"
    if "--write" in sys.argv:
        expected_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    expected = canon.loads(expected_path.read_bytes())
    check(result == expected, "oracle reproduces the retained expected result")
    check(expected["model_result"] == "fails" and expected["worst_case"] == {"pnl": "-3200", "attained": True, "price": "60000"}, "fixture: verdict and worst case")
    check([w["witness"] for w in expected["failing_intervals"]] == [{"price": "60000", "pnl": "-3200"}, {"price": "90000", "pnl": "-1200"}], "fixture: one admissible witness per failing interval")
    check(expected["cost"] == {"premium": "200", "other_costs": "0", "pnl_at_baseline": "-200", "breakevens": ["102000"]}, "fixture: cost of the hedge")
    check([(p["lower"], p["upper"], p["slope"], p["intercept"]) for p in expected["profile"]] == [("60000", "90000", "0.1", "-9200"), ("90000", "110000", "0.1", "-10200")], "fixture: two affine pieces")
    check(expected["profile"][0]["upper_inclusive"] is False and expected["profile"][1]["lower_inclusive"] is True, "fixture: the strike belongs to the upper piece")
    check(expected["ir_digest"] == canon.digest(lowered) and re.fullmatch(r"[0-9a-f]{64}", expected["ir_digest"]), "fixture: digest of the lowered proposal")

    plan = (PROJECT / "PLAN.md").read_text()
    block = re.search(r"```json\n(.*?)\n```", plan, re.S)
    check(block is not None, "PLAN.md contains an example result")
    shown = json.loads(block.group(1))
    check(set(shown) <= set(expected), "PLAN.md example uses only fields the result has")
    for key, value in shown.items():
        check(value == expected[key], f"PLAN.md example field '{key}' equals the verified fixture")

    print(f"{CHECKS} checks passed; vectors, golden table and the PLAN.md example all agree.")


if __name__ == "__main__":
    main()
