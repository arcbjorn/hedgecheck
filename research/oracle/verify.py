"""Verify the reference oracle, the golden table in PLAN.md, and the example result in PLAN.md.

    python3 research/oracle/verify.py            # check
    python3 research/oracle/verify.py --write    # regenerate the expected result, then check

The expected result is generated, never hand-edited. Independent hand-derived assertions
below pin its key values, so the fixture cannot merely agree with itself.
"""

from fractions import Fraction as F
import json
from pathlib import Path
import re
import sys

import oracle as O

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
CHECKS = 0


def check(condition, description):
    global CHECKS
    if not condition:
        raise AssertionError(description)
    CHECKS += 1


def span(interval):
    return (O.fmt(interval["lower"]), interval["lower_inclusive"], O.fmt(interval["upper"]), interval["upper_inclusive"])


def main():
    L, U, cap = F(60000), F(110000), F(-1000)
    exposure = O.linear(F("0.1"), F(100000))

    def hedged(n, p=F("0.2")):
        return O.total([exposure, O.digital_below(F(n), F(90000)), O.cash(-p * n)])

    # ---- formatting is exact
    check(O.fmt(F(-3200)) == "-3200" and O.fmt(F("-939.4")) == "-939.4", "fmt: terminating decimals")
    check(O.fmt(F("0.00001")) == "0.00001" and O.fmt(F(0)) == "0", "fmt: small and zero")
    check(O.fmt(F(268000, 3)) == "268000/3", "fmt: non-terminating values stay rational")

    # ---- PLAN.md section 3, golden table
    bare = O.below(exposure.value, cap, L, U, [])
    check([span(i) for i in bare] == [("60000", True, "90000", False)], "no hedge: failure [60000, 90000)")
    check(O.infimum(exposure.value, L, U, []) == (F(-4000), True, F(60000)), "no hedge: worst -4,000 at 60,000")
    fails = O.below(hedged(1000), cap, L, U, [F(90000)])
    check([span(i) for i in fails] == [("60000", True, "82000", False), ("90000", True, "92000", False)],
          "1,000 contracts: failures [60000, 82000) and [90000, 92000)")
    check(O.infimum(hedged(1000), L, U, [F(90000)]) == (F(-3200), True, F(60000)), "1,000 contracts: worst -3,200")
    check(hedged(1000)(F(82000)) == cap and hedged(1000)(F(92000)) == cap, "82,000 and 92,000 meet the inclusive cap")
    check(hedged(1000)(F(90000)) == F(-1200), "exactly 90,000: -1,200, fails")
    check(hedged(1000)(F("89999.99")) == F("-200.001"), "one cent below the strike: -200.001")

    flat = [(F("0.2"), F(10 ** 9))]
    window = O.size_window(exposure.value, O.digital_below(F(1), F(90000)).value, flat, cap, L, U, [F(90000)])
    check(window["status"] == "empty", "0.20 premium: no size meets the cap throughout")
    check((window["lower_bound"], window["upper_bound"]) == (F(3750), F(0)), "0.20 premium: needs n >= 3,750 and n <= 0")
    check(window["binding"] == [(F(60000), "at"), (F(90000), "at")], "0.20 premium: floor binds below, strike binds above")

    # Minimax size and loss. D is the loss from baseline to strike, A from strike to floor.
    D, A, p = F(1000), F(3000), F("0.2")
    worst = {n: O.infimum(hedged(n), L, U, [F(90000)])[0] for n in (2999, 3000, 3001)}
    check(worst[3000] == F(-1600) and worst[2999] < worst[3000] > worst[3001], "best size 3,000; worst loss 1,600")
    check(A == 3000 and D + p * A == 1600, "minimax size equals A and minimax loss equals D + p*A")
    # The same number is the infeasibility certificate: weights (1-p, p) on the strike and floor
    # constraints cancel the size and leave -(D + p*A) >= cap, which is false.
    check((1 - p) * (-D) + p * (-D - A) == -(D + p * A) < cap, "Farkas weights (1-p, p) prove infeasibility")

    sold = O.total([O.linear(F("0.07"), F(100000))])
    check(O.infimum(sold, L, U, [])[0] == F(-2800), "sell 0.03 BTC: worst 2,800, fails")
    kept = O.total([O.linear(F("0.025"), F(100000))])
    check(O.infimum(kept, L, U, [])[0] == F(-1000) and not O.below(kept, cap, L, U, []), "sell 0.075 BTC: worst 1,000, passes")

    # ---- comparison with the exposure-reduction benchmark, exact and non-terminating
    better = O.below(lambda s: kept(s) - hedged(1000)(s), F(0), L, U, [F(90000)])
    check([span(i) for i in better] == [("268000/3", False, "90000", False), ("308000/3", False, "110000", True)],
          "1,000 contracts beat selling 0.075 BTC only on (89,333.33.., 90,000) and (102,666.66.., 110,000]")

    # ---- structural identities the engine must also satisfy
    n, K = F(700), F(90000)
    parity = O.total([O.digital_below(n, K), O.digital_at_or_above(n, K)])
    check(O.profile(parity, L, U, [K]) == [{"lower": L, "lower_inclusive": True, "upper": U, "upper_inclusive": True,
                                            "slope": F(0), "intercept": n}], "YES + NO pays n everywhere, strike included")
    P1, P2 = F(76063), F(79168)
    buckets = O.total([O.digital_below(n, P1), O.digital_range(n, P1, P2), O.digital_at_or_above(n, P2)])
    check(len(O.profile(buckets, L, U, [P1, P2])) == 1 and buckets(P1) == buckets(P2) == n, "three buckets partition the domain")
    short = O.scalar_short(n, F(70000), F(80000))
    check(short.value(F(70000)) == n and short.value(F(80000)) == 0 and short.value(F(75000)) == n / 2, "scalar Short endpoints and midpoint")
    put_spread = O.total([O.linear(F("0.07"), F(80000)), O.scalar_short(F(700), F(70000), F(80000))])
    check(O.profile(put_spread, F(70000), F(80000), [])[0]["slope"] == 0, "q*(high-low) scalar Shorts flatten a long exposure between low and high")

    # ---- the interval solver agrees with pointwise evaluation on a dense exact grid
    cases = [(hedged(1000), [F(90000)]), (hedged(3000), [F(90000)]), (put_spread, [F(70000), F(80000)]),
             (O.total([exposure, O.digital_range(F(900), F(85000), F(95000)), O.cash(F(-150))]), [F(85000), F(95000)])]
    for fn, cuts in cases:
        failing = O.below(fn, cap, L, U, cuts)
        eps = F(1, 1000)
        grid = {L + (U - L) * F(i, 997) for i in range(998)} | {c + d for c in cuts + [L, U] for d in (-eps, 0, eps)}
        grid |= {i[k] + d for i in failing for k in ("lower", "upper") for d in (-eps, 0, eps)}
        for s in (g for g in grid if L <= g <= U):
            inside = any((i["lower"] < s < i["upper"]) or (s == i["lower"] and i["lower_inclusive"])
                         or (s == i["upper"] and i["upper_inclusive"]) for i in failing)
            check(inside == (fn(s) < cap), f"interval membership at {s}")

    # ---- an undeclared breakpoint is an error, not a wrong answer
    try:
        O.below(hedged(1000), cap, L, U, [])
    except ValueError:
        check(True, "omitted strike is rejected")
    else:
        check(False, "omitted strike is rejected")

    # ---- the fixture, and the example result printed in PLAN.md
    proposal = json.loads((ROOT / "fixtures" / "golden-1000-contracts.proposal.json").read_text())
    result = O.evaluate(proposal)
    expected_path = ROOT / "fixtures" / "golden-1000-contracts.result.json"
    if "--write" in sys.argv:
        expected_path.write_text(json.dumps(result, indent=2) + "\n")
    expected = json.loads(expected_path.read_text())
    check(result == expected, "oracle reproduces the retained expected result")
    check(expected["model_result"] == "fails" and expected["worst_case"] == {"pnl": "-3200", "attained": True, "price": "60000"}, "fixture: verdict and worst case")
    check([w["witness"] for w in expected["failing_intervals"]] == [{"price": "60000", "pnl": "-3200"}, {"price": "90000", "pnl": "-1200"}], "fixture: one admissible witness per failing interval")
    check(expected["cost"] == {"premium": "200", "other_costs": "0", "pnl_at_baseline": "-200", "breakevens": ["102000"]}, "fixture: cost of the hedge")
    check([(p["lower"], p["upper"], p["slope"], p["intercept"]) for p in expected["profile"]] == [("60000", "90000", "0.1", "-9200"), ("90000", "110000", "0.1", "-10200")], "fixture: two affine pieces")
    check(expected["profile"][0]["upper_inclusive"] is False and expected["profile"][1]["lower_inclusive"] is True, "fixture: the strike belongs to the upper piece")

    plan = (PROJECT / "PLAN.md").read_text()
    block = re.search(r"```json\n(.*?)\n```", plan, re.S)
    check(block is not None, "PLAN.md contains an example result")
    shown = json.loads(block.group(1))
    check(set(shown) <= set(expected), "PLAN.md example uses only fields the result has")
    for key, value in shown.items():
        check(value == expected[key], f"PLAN.md example field '{key}' equals the verified fixture")

    print(f"{CHECKS} checks passed; PLAN.md example result matches the generated fixture.")


if __name__ == "__main__":
    main()
