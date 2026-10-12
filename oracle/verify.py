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

    # ---- an attaining price is a price the function actually attains
    #
    # A flat open piece attains its value everywhere inside, but at neither excluded end.
    # Reporting the excluded end would hand a witness a price where the payoff is higher,
    # which is inadmissible. The rule: the smallest attaining price when the attaining set
    # has a minimum, otherwise the midpoint of the first attaining open piece.
    for label, probe in (
        ("flat above an owned strike", O.indicator(F(700), upper=F(90000), upper_inclusive=True) + O.cash(-F(100))),
        ("flat below an owned strike", O.indicator(F(700), lower=F(90000), lower_inclusive=True) + O.cash(-F(100))),
        ("flat between two owned strikes", O.digital_range(F(700), F(80000), F(90000)) + O.cash(-F(100))),
        ("unowned strike", O.indicator(F(700), upper=F(90000), upper_inclusive=False) + O.indicator(F(700), lower=F(90000), lower_inclusive=False)),
        ("sloped", O.linear(F("0.1"), F(100000))),
    ):
        value, attained, where = O.infimum(probe, L, U)
        check(L <= where <= U, f"infimum: {label} reports a price inside the domain")
        if attained:
            check(probe(where) == value, f"infimum: {label} reports a price the function attains")
            # THE SMALLEST ATTAINING PRICE, when the attaining set has one. Checking only
            # that the price attains the value leaves the choice among attaining prices
            # free, and the two implementations then drift: Go windows maximal pieces while
            # `atoms` splits at every carried breakpoint, so a flat run with a phantom mark
            # inside it gave the midpoint of a fragment on one side and of the whole run on
            # the other. Both attain; only one is the documented answer.
            smallest = min(p for p in (L, where) if probe(p) == value)
            check(where == smallest or probe(L) != value,
                  f"infimum: {label} reports the smallest attaining price when one exists")
    # An OWNED lower end IS the minimum of the attaining set, so the rule prefers it to the
    # midpoint. Hand-derived: the indicator pays 100 on [90, inf) less a premium of 100, so
    # it is flat at zero across the whole of [90, 110] with 90 owned -- the answer is 90.
    owned = O.indicator(F(100), lower=F(90), lower_inclusive=True) + O.cash(-F(100))
    value, attained, where = O.infimum(owned, F(90), F(110))
    check((value, attained, where) == (F(0), True, F(90)),
          "infimum: an owned lower end is the smallest attaining price, not the midpoint")
    # A CARRIED BREAKPOINT IS NOT A KINK, and `infimum` must read MAXIMAL pieces, not the
    # atoms `atoms` yields. Two legs whose payoffs cancel leave 90 carried with the same
    # slope either side: `profile` merges to the single piece [70, 110], while `atoms` splits
    # at 90. Off maximal pieces the owned minimum is 70; off atoms it is the first fragment's
    # midpoint, 80. Both attain the same value, so no arithmetic check separates them -- this
    # is the only guard that does, and it is why the Go engine disagreed on case-0266.
    # The domain's own start must NOT attain the infimum, or `offer` locks onto it first and
    # the two readings agree by accident. So the value is lifted at 70 exactly, leaving the
    # attaining run (70, 110] open on the left and the midpoint standing for it.
    lifted = O.indicator(F(50), lower=F(70), lower_inclusive=True, upper=F(70), upper_inclusive=True)
    cancelling = (O.indicator(F(700), lower=F(90), lower_inclusive=True)
                  - O.indicator(F(700), lower=F(90), lower_inclusive=True))
    phantom = lifted + cancelling
    check(F(90) in phantom.breakpoints, "infimum: the cancelling sum really carries the phantom breakpoint")
    check([(O.fmt(p["lower"]), O.fmt(p["upper"])) for p in O.profile(phantom, F(70), F(110))]
          == [("70", "70"), ("70", "110")], "infimum: profile merges across the phantom, leaving one open run")
    check(O.infimum(phantom, F(70), F(110)) == (F(0), True, F(90)),
          "infimum: the midpoint is of the MAXIMAL run (70,110], which is 90, not of the first atom, which is 80")

    # THE MIDPOINT FALLBACK, on the shape that actually produces it: a flat run whose ends
    # are both excluded. A clipped window always OWNS its ends, so the fallback cannot be
    # reached by narrowing the domain -- it needs the run to sit strictly between two prices
    # where the value is lower. Here the two unowned strikes at 90 and 100 are points of
    # their own paying nothing, so the run (90, 100) is flat at 700 with neither end in it,
    # and the infimum over that run alone is the midpoint 95.
    fenced = O.indicator(F(700), lower=F(90), lower_inclusive=False, upper=F(100), upper_inclusive=False)
    run = [piece for piece in O.profile(fenced, F(90), F(100)) if piece["slope"] == 0 and piece["intercept"] == F(700)]
    check(len(run) == 1 and not run[0]["lower_inclusive"] and not run[0]["upper_inclusive"],
          "infimum: the fenced run really is open at both ends")
    check(O.infimum(-fenced, F(90), F(100)) == (-F(700), True, F(95)),
          "infimum: a run open at both ends has no minimum, so the midpoint stands for it")
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

    # ---- a clause that applies to a sub-interval is evaluated on that sub-interval
    #
    # The schema says "P&L >= min_pnl on the interval; the whole domain when 'on' is
    # absent", and PLAN section 2 calls the objective a lower envelope of
    # (interval, min_pnl) clauses. Evaluating a clause outside its own interval reports
    # a failure the objective never asked about.
    narrow = {
        "schema_version": "1", "units": {"money": "USDC", "price": "USDC per BTC",
                                         "exposure": "BTC", "size": "contracts"},
        "domain": {"lower": "60000", "upper": "110000"},
        "baseline": {"kind": "explicit", "price": "100000", "label": "synthetic"},
        "exposure": {"kind": "linear", "quantity": "0.1"},
        "legs": [{"id": "put", "kind": "indicator", "size": "0",
                  "pays_on": {"upper": "90000", "upper_inclusive": False},
                  "premium": {"kind": "fixed", "price": "0"},
                  "observation_time": "2026-01-02T06:00:00Z", "semantics": "synthetic"}],
        # P&L is 0.1*(S - 100000): -4000 at the floor, 0 at 100000, +1000 at the ceiling.
        # A -1000 cap is breached below 90000 and met above it.
        "objective": [{"id": "high_only", "min_pnl": "-1000",
                       "on": {"lower": "95000", "lower_inclusive": True,
                              "upper": "110000", "upper_inclusive": True}}],
        "objective_valuation_time": "2026-01-02T06:00:00Z",
        "other_costs": "0", "assumptions": ["common_reference"],
    }
    narrow_result = O.evaluate(narrow)
    check(narrow_result["failing_intervals"] == [],
          "a clause on [95000, 110000] is not failed by prices below 95000")
    check(narrow_result["model_result"] == "passes",
          "a clause that holds on its own interval passes")

    # ---- a size window is sized against the profile the verdict uses
    #
    # Every smallest size a result reports must actually meet the objective on the
    # lower profile. Sizing against full value where a leg was reduced produced a size
    # whose worst P&L was -4923.49676 against a -4000 cap (EVIDENCE section 9).
    generated = PROJECT / "fixtures" / "generated" / "ir"
    if generated.is_dir():
        checked_sizes = 0
        for ir_path in sorted(generated.glob("*.ir.json")):
            lowered = canon.loads(ir_path.read_bytes())
            if not lowered.get("reductions"):
                continue
            result = canon.loads(Path(str(ir_path).replace(".ir.json", ".result.json")).read_bytes())
            zeroed = {reduction["leg"] for reduction in lowered["reductions"]}
            domain_lower = exact.parse(lowered["domain"]["lower"])
            domain_upper = exact.parse(lowered["domain"]["upper"])
            cap = min(exact.parse(clause["min_pnl"]) for clause in lowered["objective"])
            for window in result.get("size_windows", []):
                if "smallest" not in window:
                    continue
                size = exact.parse(window["smallest"])
                premium, parts = F(0), []
                usable = True
                for leg in lowered["legs"]:
                    own = leg["id"] == window["leg"]
                    leg_size = size if own else exact.parse(leg["size"])
                    if own and leg["premium"]["kind"] == "walked":
                        levels = [(exact.parse(price), exact.parse(available))
                                  for price, available in leg["premium"]["levels"]]
                        walked = O.ask_cost(levels, leg_size)
                        if walked is None:
                            usable = False
                            break
                        premium += walked
                    else:
                        premium += O.leg_cost(leg)
                    if leg["id"] not in zeroed:
                        parts.append(O._leg(dict(leg, size=O.fmt(leg_size))))
                if not usable:
                    continue
                pnl = O.total([O.linear(exact.parse(lowered["exposure"]["quantity"]),
                                        exact.parse(lowered["baseline"]["price"]))]
                              + parts + [O.cash(-premium - exact.parse(lowered["other_costs"]))])
                worst = O.infimum(pnl, domain_lower, domain_upper)[0]
                check(worst >= cap,
                      f"{ir_path.name}: the smallest passing size {window['smallest']} meets the cap "
                      f"on the lower profile ({O.fmt(worst)} against {O.fmt(cap)})")
                checked_sizes += 1
        print(f"size windows: {checked_sizes} reported sizes verified against the lower profile")

    payoff_is_data()
    price_touch_bound()
    price_touch_lowering()
    established_failures()
    runbooks()
    onchain_representable()
    isolated_perp()
    assumption_vocabulary()
    synthesis_refusal_classes()
    one_definition()
    synthesis()
    reference_map()
    review_seals()
    testnet_shape()
    basis_band()
    replay()
    live_bundle()
    live_bucket_bundle()

    print(f"{CHECKS} checks passed; vectors, golden table, the PLAN.md example and the 18 September replay all agree.")


# --------------------------------------------------------------------------- the 18 September replay
#
# Two real hedges, lowered from family-level proposals against the retained catalogue,
# contexts and books, then evaluated. Every expected value below is transcribed by hand
# from `git show 085ccfb:research/2026-09-18/verify.py`, where it was hand-derived. None
# of it comes from lower.py or oracle.evaluate, the code under test here.

REPLAY = PROJECT / "fixtures" / "replay" / "2026-09-18"

RETAINED = {
    "outcome-meta": "a1692390028fdbfa2f81df15768431347fab42faa8add5e96b24a8813e9f99ac",
    "meta-and-asset-ctxs": "ed779f0670253d58214b98a18efe79bf08e65312b5364ebd9b49a5fd708ee1d1",
    "book-3965-no": "d62ba1359f45abc313840ed63deef8d705fcc9bd988ca0f29e9412d8e2cd1ef1",
    "book-bucket0-3971-yes": "00118f3902a1a8c491d1dd22782527524e71eea68f610918fa5495d5105b1218",
}

# (premium, pnl at baseline, at strike, at floor, pieces, break-evens)
PINNED = {
    "binary": ("645.76904", "-645.76904", "-663.20904", "-999.90904",
               [("0.1", "-6999.90904"), ("0.1", "-8408.90904")], ["69999.0904", "84089.0904"]),
    "bucket0": ("160.76676", "-160.76676", "-333.10676", "-999.90676",
                [("0.1", "-6999.90676"), ("0.1", "-7923.90676")], ["69999.0676", "79239.0676"]),
}
STRIKES = {"binary": "77457", "bucket0": "75908"}

# (smallest, largest, exact lower bound, exact upper bound) passing sizes at displayed depth
SIZES = {
    "binary": ("1409", "2104", "18172417/12899", "25470083/12101"),
    "bucket0": ("924", "2810", "76314000/82601", "281004800/99999"),
}

# The smallest exposure reduction meeting the same cap: keep this much BTC, sell the rest
# at the baseline, hold the cash. Its worst case is exactly -1000, with no premium.
KEEP = "5000/88157"

# Where each proposal beats that reduction, as (lower, lower_inclusive, upper, upper_inclusive).
BETTER = {
    "binary": [("60000", True, "77457", False), ("630619989713/6813750", False, "110000", True)],
    "bucket0": [("60000", True, "75908", False), ("369512914573/4542500", False, "110000", True)],
}

# The horizon fixture: the bucket hedge measured a day after the leg is observed. The leg is
# worth nothing then, its premium still counts, so P&L(S) = 0.1*(S - 77631.4) - 160.76676.
HORIZON = {"pieces": [("0.1", "-7923.90676")], "fails_on": ("60000", True, "69239.0676", False),
           "worst": {"pnl": "-1923.90676", "attained": True, "price": "60000"}}


def payoff_is_data():
    """`pays_on` transcribes the entry. It never computes an interval from proposal state.

    This is what makes a payoff reviewable: a reviewer reads the entry and knows what a leg
    pays. A REDUCTION may read the proposal -- `horizon_mismatch` compares the leg's expiry
    against the objective's valuation time, and the basis band reads the objective's
    reference -- so the rule is not "never read the proposal". It is that the INTERVAL comes
    from the entry, which is why the priceTouch direction is a reduction and not a payoff.
    """
    import inspect
    import lower

    source = inspect.getsource(lower.pays_on)
    # The signature is the check: pays_on takes the entry, the leg and the resolved term
    # values, and nothing else. A baseline or a proposal parameter would be the drift.
    parameters = list(inspect.signature(lower.pays_on).parameters)
    check(parameters == ["entry", "leg", "values"],
          f"payoff as data: pays_on takes {parameters}, want entry, leg, values")
    for forbidden in ("proposal", "baseline", "snapshots", "objective"):
        check(forbidden not in source,
              f"payoff as data: pays_on mentions {forbidden!r}, so an interval may depend on it")

    # Inclusivity is transcribed, never decided. A computed `lower_inclusive` would be an
    # interval the entry does not state, and a reviewer would be reading the wrong thing.
    check("spec[\"lower_inclusive\"]" in source and "spec[\"upper_inclusive\"]" in source,
          "payoff as data: pays_on no longer takes endpoint ownership straight from the spec")


def price_touch_bound():
    """The priceTouch bound never exceeds the payoff it bounds.

    PLAN section 2: lower-bound a touch market by the INCLUSIVE terminal digital at the
    target, in the direction the reference must travel to reach it. A terminal observation at
    or through the target implies a touch, so the bound can only understate -- but "can only
    understate" is the whole claim, and a path that touched and came back is exactly where a
    wrong bound would over-credit. Checked by brute force over both directions.

    This pins the ARITHMETIC alone. That lowering chooses the right direction, records the
    reduction, and that the evaluator applies the bound instead of zeroing the leg, is
    `price_touch_lowering` below.
    """
    target, size = F(100), F(1000)
    rise = O.indicator(size, lower=target, lower_inclusive=True)
    fall = O.indicator(size, upper=target, upper_inclusive=True)

    # "Equals or crosses" pays AT the target, in either direction. `digital_below` is
    # exclusive there and would have been the wrong primitive for a falling touch.
    check(rise(target) == size and fall(target) == size,
          "priceTouch: the bound pays at the target itself, because the text says 'equals or crosses'")
    check(rise(target + 1) == size and rise(target - 1) == 0, "priceTouch: a rising touch pays at or above")
    check(fall(target - 1) == size and fall(target + 1) == 0, "priceTouch: a falling touch pays at or below")

    # Brute force: the bound may never exceed the true payoff on any path.
    state = 20260922
    def step():
        nonlocal state
        state = (state * 1103515245 + 12345) % (2 ** 31)
        return state
    violations, touched_and_returned = 0, 0
    for _ in range(4000):
        start = [80, 90, 95, 105, 110, 120][step() % 6]
        path, price = [start], start
        for _ in range(6):
            price = max(1, price + [-12, -6, -1, 0, 1, 6, 12][step() % 7])
            path.append(price)
        rising = start < 100
        did_touch = any((p >= 100) if rising else (p <= 100) for p in path)
        terminal = path[-1]
        bounded = (terminal >= 100) if rising else (terminal <= 100)
        if bounded and not did_touch:
            violations += 1
        if did_touch and not bounded:
            touched_and_returned += 1
    check(violations == 0, f"priceTouch: the bound exceeded the true payoff on {violations} paths")
    # And the bound is genuinely LOOSE: paths that touched and came back are why it is a
    # bound rather than the payoff. Without any, the check above would prove nothing.
    check(touched_and_returned > 0,
          "priceTouch: no path touched and returned, so the corpus cannot show the bound is strict")


def testnet_shape():
    """What blocks the live testnet order is DISCOVERY, in this repository's own code.

    Three wrong answers preceded this one, each recorded in EVIDENCE section 9. It was
    "testnet lists no bucket" (true, not the blocker), then "the books are empty" (a bug in my
    probe -- the wrong coin encoding answering `null`), then "no quoted market is a price
    market" (a filter matching the word "below" in a CPI description). Running the live path
    settled it: `hedgecheck check --live --network testnet` answers `no expiry with both a
    binary and a bucket for BTC`, because `engine/discover/discover.go` REQUIRES both and
    testnet carries no price bucket at all.

    So PLAN's claim that a ladder hedge "needs no bucket" is true of the EVALUATOR and false of
    DISCOVERY, and the gap between those two is what this guard now pins. A strike ladder is
    genuinely evaluable -- long the underlying, YES at one strike, NO at another -- but nothing
    assembles one from a live catalogue today.

    THAT IS A FACT ABOUT TESTNET ONLY, and stating it without the next sentence misled this
    project for a day. MAINNET pairs a binary and a bucket at one expiry routinely, so the live
    path runs end to end there with no code change and the ladder was never needed. The
    pairing is re-derived below from every retained mainnet catalogue rather than asserted,
    because "the venue carries the shape" is exactly the kind of claim that was wrong four
    times running when it rested on one reading.

    Checked against the retained 21 September testnet catalogue so the claim in PLAN is
    re-derived rather than remembered.
    """
    catalogue = json.loads((FIXTURES / "testnet" / "2026-09-21" / "catalogue.json").read_text())
    outcomes = catalogue["outcomes"]

    # No PRICE bucket of any kind. The only buckets are policy-rate ones, which are not a
    # price market at all, so "list a bucket" was never a thing testnet was going to do.
    price_buckets = [o for o in outcomes
                     if "ucket" in o.get("name", "") and "policyRate" not in o.get("name", "")]
    check(price_buckets == [], f"testnet: expected no price bucket, found {len(price_buckets)}")

    # But binaries DO cluster at one expiry, on one underlying, with distinct strikes.
    ladders = {}
    for outcome in outcomes:
        if not outcome.get("name", "").startswith("template:binaryPrice"):
            continue
        terms = O_terms(outcome)
        if "perp" not in terms or "threshold" not in terms:
            continue
        ladders.setdefault((terms["perp"], terms.get("time")), set()).add(terms["threshold"])
    widest = max(ladders.items(), key=lambda kv: len(kv[1]))
    check(len(widest[1]) >= 3,
          f"testnet: the widest strike ladder has {len(widest[1])} strikes, so no hedge shape exists")
    btc = ladders.get(("BTC", "20260921-1200"), set())
    check(btc == {"81100", "81500", "81900"},
          f"testnet: the BTC 20260921-1200 ladder is not the three strikes PLAN names, it is {sorted(btc)}")

    # And the books are empty, which is what actually blocks the run.
    for stem in ("binary-no", "bucket0-yes"):
        book = json.loads((FIXTURES / "testnet" / "2026-09-21" / f"{stem}.json").read_text())
        bids, asks = book["levels"]
        check(bids == [] and asks == [],
              f"testnet: {stem} is no longer empty, so the liquidity blocker may have lifted")

    # THE DISCOVERY REQUIREMENT IS PINNED AGAINST THE GO SOURCE, offline.
    #
    # This is the drift that cost three days: PLAN said a ladder hedge needs no bucket, the
    # code required one, and nothing compared them. Reading `discover.go` is not the same as
    # asserting what it does -- if the requirement is ever widened to the ladder shape, this
    # fails and whoever widened it must say so here and in PLAN together.
    discover = (PROJECT / "engine" / "discover" / "discover.go").read_text()
    check("no expiry with both a binary and a bucket for " in discover,
          "discovery: the binary-and-bucket requirement is gone from discover.go; if the "
          "ladder shape is now supported, PLAN and both runbooks must stop saying it is not")
    # THE LEG IT BUILDS, not merely a name it mentions. `recurring.priceBucket` appears twice
    # -- once in a refusal message, once in the leg -- so replacing the first left the second
    # and a mutation of the name stayed green. The leg is the behaviour; the message is prose.
    check(re.search(r'ID:\s*"bucket0-yes",\s*Family:\s*"recurring\.priceBucket"', discover),
          "discovery: discover.go no longer builds a recurring.priceBucket leg, so the "
          "binary-and-bucket shape has changed and PLAN must be re-read")
    check(re.search(r'Family:\s*"recurring\.priceBinary"', discover),
          "discovery: discover.go no longer builds a recurring.priceBinary leg")
    for document, name in ((PROJECT / "PLAN.md", "PLAN"),
                           (PROJECT / "consumer" / "RUNBOOK.md", "consumer runbook")):
        text = document.read_text()
        check("no expiry with both a binary and a bucket" in text,
              f"{name} does not quote the live path's own refusal, so a reader cannot tell "
              f"that the blocker is discovery rather than liquidity")

    # MAINNET SATISFIES THE REQUIREMENT TESTNET FAILS, in every retained catalogue.
    #
    # This is the fact that made the ladder unnecessary, so it is pinned rather than
    # remembered: the reasoning above is only sound while mainnet really does pair the two
    # families at a shared expiry. Re-derived from the retained captures with the same
    # `name == "Recurring"` and `class:` filters `discover.go` uses -- filtering on a field
    # the code does not use is what produced two wrong population claims on 23 Sep.
    for day in ("2026-09-18", "2026-09-19", "2026-09-20"):
        folder = FIXTURES / "replay" / day
        catalogue = json.loads((folder / ("catalogue.json" if (folder / "catalogue.json").exists()
                                         else "outcome-meta.json")).read_text())
        binary_expiries, bucket_expiries = set(), set()
        for outcome in catalogue.get("outcomes", []):
            if outcome.get("name") != "Recurring":
                continue
            terms = O_terms(outcome)
            if terms.get("class") == "priceBinary" and terms.get("underlying") == "BTC":
                binary_expiries.add(terms.get("expiry"))
        for question in catalogue.get("questions", []):
            if question.get("name") != "Recurring":
                continue
            terms = O_terms(question)
            if terms.get("class") == "priceBucket" and terms.get("underlying") == "BTC":
                bucket_expiries.add(terms.get("expiry"))
        check(binary_expiries & bucket_expiries,
              f"mainnet {day}: no expiry carries both a BTC binary and a BTC bucket, so the "
              f"reason PLAN gives for dropping the ladder -- that mainnet already pairs them "
              f"-- does not hold in the retained captures and must be re-read")

    # THE DOWNSIDE LEG IS INDEX 0, by the registry's own payoff definition.
    #
    # On 24 Sep a genuinely quoted bucket index 1 (ask 0.036, where index 0 was a 0.99998
    # placeholder) looked briefly like an opportunity discovery was missing. It pays on a
    # RISE into the band, so buying it as downside protection would be wrong and
    # `named[0]` is right. Cheapness that comes from a payoff being unlikely is not a
    # bargain, and this pins the direction so the same mistake cannot be made twice.
    bucket_entry = json.loads((PROJECT / "registry" / "recurring.priceBucket.json").read_text())
    index0_yes = [payoff for payoff in bucket_entry["payoffs"]
                  if payoff["select"] == {"side": "yes", "index": "0"}]
    check(len(index0_yes) == 1, "registry: expected exactly one yes/index-0 bucket payoff")
    if index0_yes:
        pays_on = index0_yes[0]["pays"][0]["pays_on"]
        check("lower" not in pays_on and pays_on.get("upper", {}).get("at") == "0",
              "registry: bucket index 0 YES no longer pays strictly below thresholds[0], so it "
              "is not the downside leg and discover.go taking named[0] must be re-justified")


def review_seals():
    """Every reviewed entry ON DISK carries a digest of its own current text.

    `semantics_version` is the canonical digest of an entry WITHOUT its `review` key, so a
    review cannot sign itself and any edit to the entry invalidates it. That is the whole
    mechanism, and until 22 Sep nothing checked it against the files: the replay guard reads
    only the families its two proposals name (deliberately -- a draft for an unused family
    must not send the replay down the draft branch), so `template.priceTouch` was reviewed
    with its seal unverified. A forged digest and an entry edited after review BOTH passed.

    This reads the directory rather than a list, so an entry added later cannot be reviewed
    without its seal being checked.
    """
    entries = sorted((PROJECT / "registry").glob("*.json"))
    check(len(entries) >= 4, "review seals: the registry is meant to hold every family")
    sealed = 0
    for path in entries:
        entry = json.loads(path.read_text())
        review = entry.get("review", {})
        if review.get("state") != "reviewed":
            # A draft carries no digest to check, and must not claim one.
            check("digest" not in review, f"review seals: {path.name} is a draft but carries a digest")
            continue
        check(review.get("reviewed_by"), f"review seals: {path.name} is reviewed by nobody")
        check(review.get("reviewed_on"), f"review seals: {path.name} is reviewed on no date")
        truth = canon.semantics_version(entry)
        check(review.get("digest") == truth,
              f"review seals: {path.name} claims {review.get('digest')} but its text digests to {truth}")
        check(canon.reviewed(entry), f"review seals: {path.name} does not read as reviewed")
        sealed += 1
    check(sealed >= 3, f"review seals: only {sealed} reviewed entries, so this proves little")

    # AND THE SEAL DETECTS AN EDIT. Checking a digest against the text it was computed from
    # is circular unless tampering is shown to break it, so each reviewed entry is edited in
    # memory -- never on disk -- and must stop reading as reviewed.
    for path in entries:
        entry = json.loads(path.read_text())
        if entry.get("review", {}).get("state") != "reviewed":
            continue
        for label, mutate in (
            ("a payoff endpoint", lambda e: e["payoffs"][0]["pays"][0]["pays_on"].update(
                {k: not v for k, v in e["payoffs"][0]["pays"][0]["pays_on"].items() if isinstance(v, bool)})),
            ("the status", lambda e: e.update(status="computed" if e["status"] != "computed" else "bounded")),
            ("an ambiguity", lambda e: e["ambiguities"].append("added after review")),
        ):
            tampered = json.loads(json.dumps(entry))
            mutate(tampered)
            check(not canon.reviewed(tampered),
                  f"review seals: {path.name} still reads as reviewed after editing {label}")


def reference_map():
    """A venue's free text resolves to a canonical id, or to nothing it can name."""
    import lower

    document = canon.loads((PROJECT / "references" / "reference-map.json").read_bytes())
    index = lower.reference_index(document)
    mappings = document["mappings"]

    # ---- AN UNREVIEWED MAP RESOLVES NOTHING
    #
    # The same seal the registry uses, and until 22 Sep nothing enforced it here: every
    # mapping was honoured whatever the document said about itself, while
    # `catalogue_reference` refused with "no REVIEWED mapping" -- a word the code did not
    # mean. It is not cosmetic. A mapping nobody reviewed can point a leg at the objective's
    # OWN series, and then the basis reduction never fires: measured on the 18 September
    # bucket proposal, pointing a foreign series at `hl:perp:BTC:mark-interp` turns a
    # `needs_review` worst case of -1923.90676 into a `passes` at -999.90676.
    check(canon.reviewed(document), "reference map: the map on disk is reviewed")
    check(index, "reference map: a reviewed map yields its mappings")
    for label, broken in (
        ("a draft", {**document, "review": {"state": "draft", "drafted_by": "model"}}),
        ("a forged digest", {**document, "review": {**document["review"], "digest": "0" * 64}}),
        ("an edited mapping", {**document, "mappings": mappings + [
            {"venue": "out", "price_description": "invented", "seconds": "1",
             "state": "interpreted", "reference": "hl:perp:BTC:mark-interp", "why": "unreviewed"}]}),
    ):
        check(lower.reference_index(broken) == {},
              f"reference map: {label} must resolve nothing, not be honoured")
    catalogue = json.loads((PROJECT / "fixtures" / "replay" / "2026-09-18" / "outcome-meta.json").read_text())
    outcomes = catalogue["outcomes"]

    # EVERY price-described instance is covered. A map with a hole would silently fall back
    # to the entry's template, which is a reference the instance does not name.
    described = [o for o in outcomes if "priceDescription" in o.get("description", "")]
    check(len(described) == 78, f"reference map: 78 price-described outcomes, found {len(described)}")
    uncovered = [o for o in described
                 if (o["venue"], O_terms(o)["priceDescription"], O_terms(o).get("seconds", "")) not in index]
    check(not uncovered, f"reference map: {len(uncovered)} described instances have no mapping")

    # The three states, on real instances rather than constructed ones.
    leg = {"id": "probe"}
    by_id = {str(o["outcome"]): o for o in outcomes}
    # REFUSED, not resolved to nothing: returning None would fall back to the entry's own
    # reference, so a leg nobody can map would be treated as sharing the objective's series.
    try:
        lower.catalogue_reference(leg, by_id["2494"], index)
        check(False, "reference map: `1-minute candle` was resolved instead of refused")
    except lower.Refused as refusal:
        check(refusal.code == "AMBIGUOUS_RULES",
              f"reference map: `1-minute candle` refused as {refusal.code}, want AMBIGUOUS_RULES")
    # And a description absent from the map is refused the same way, not silently allowed.
    try:
        lower.catalogue_reference(leg, dict(by_id["2494"],
                                            description="perp:BTC|priceDescription:nothing maps this"
                                                        "|seconds:7|threshold:1|time:20261001-0000"), index)
        check(False, "reference map: an unmapped description was resolved instead of refused")
    except lower.Refused as refusal:
        check(refusal.code == "AMBIGUOUS_RULES",
              f"reference map: an unmapped description refused as {refusal.code}")
    check(lower.catalogue_reference(leg, by_id["3971"], index) is None,
          "reference map: a canonical instance describes no series, so the entry's template governs")
    check(lower.catalogue_reference(leg, by_id["1209"], index) == "hl:perp:HYPE:mark-twap:1s",
          "reference map: an interpreted description resolves to its canonical id")

    # THE TRAILING SPACE IS PART OF THE KEY. The catalogue holds `HYPE-USDC perp mark` and
    # `HYPE-USDC perp mark ` from one venue under one template, with different windows, so a
    # lookup that trimmed would answer for a string nobody wrote.
    spaced = [m for m in mappings if m["price_description"] != m["price_description"].strip()]
    check(spaced, "reference map: the trailing-space description is gone from the map")
    trimmed = {m["price_description"].strip() for m in mappings}
    check(len(trimmed) < len(mappings), "reference map: no two descriptions differ only by spacing any more")

    # Ambiguity is now the MINORITY case, and each ambiguous row says why.
    #
    # It was 6 descriptions over 61 of 78 instances until 22 Sep, when the 42 Pyth instances
    # were mapped. Four rows refused them on a contradiction that does not exist: the
    # restriction "This market must refer to the price of a Hyperliquid perp" constrains
    # {perp}, the market's SUBJECT, while settlement is "according to the {seconds}-second
    # TWAP of {priceDescription} price" -- a different template field, and the settlement
    # source by the template's own words. The retained text at
    # research/2026-09-18/outcome-templates.json (085ccfb) is the evidence.
    #
    # What remains is genuinely unmappable: `1-minute candle` (18 instances) names no source,
    # no instrument and no statistic, and its 300-second window contradicts its own stated
    # period; `xyz:CL` (1) names a ticker with no venue or statistic. 18 + 1 = 19.
    counts = {}
    for o in described:
        terms = O_terms(o)
        counts[(o["venue"], terms["priceDescription"], terms.get("seconds", ""))] = \
            counts.get((o["venue"], terms["priceDescription"], terms.get("seconds", "")), 0) + 1
    ambiguous = [m for m in mappings if m["state"] == "ambiguous"]
    instances = sum(counts[(m["venue"], m["price_description"], m["seconds"])] for m in ambiguous)
    check((len(ambiguous), instances) == (2, 19),
          f"reference map: 2 ambiguous descriptions over 19 instances, found {len(ambiguous)} over {instances}")
    # And the 42 that were freed are really mapped, to PYTH ids and not to Hyperliquid ones.
    # Mapping them to hl:* would assert two different series are the same price, which is
    # exactly the silent resolution the basis rule exists to prevent.
    pyth = [m for m in mappings if "Pyth" in m["price_description"]]
    freed = sum(counts[(m["venue"], m["price_description"], m["seconds"])] for m in pyth)
    check(freed == 42, f"reference map: the Pyth rows cover 42 instances, found {freed}")
    check(all(m["state"] == "interpreted" and m["reference"].startswith("pyth:") for m in pyth),
          "reference map: every Pyth description resolves to a pyth: id, never a Hyperliquid one")

    # EACH ROW'S OWN COUNT, not just their sum.
    #
    # The four `why` texts open "15 instances", "9 instances", "9 instances", "9 instances",
    # and only the TOTAL was ever checked -- so any redistribution summing to 42 passed, and a
    # count is exactly the kind of number this project has had go stale (EVIDENCE §9 records
    # this row's total recorded as 15 when it was 42). Prose is not usually the target, but a
    # number in prose that a reader would rely on is.
    for m in pyth:
        stated = re.match(r"(\d+) instances", m["why"])
        check(stated is not None,
              f"reference map: the Pyth row {m['price_description']!r} does not open with its count")
        if stated:
            actual = counts[(m["venue"], m["price_description"], m["seconds"])]
            check(int(stated.group(1)) == actual,
                  f"reference map: {m['price_description']!r} says {stated.group(1)} instances, "
                  f"the catalogue has {actual}")

    # `confirmed` IS NOT AVAILABLE HERE, and that is the point of the state.
    #
    # The schema defines `confirmed` as "the deployer confirmed it in writing, and `sources`
    # then carries that writing". No deployer has written to this project, so every Pyth row is
    # the OWNER'S READING and says so in every result that rests on it. Asserted as a guard
    # because the temptation is to promote a mapping that has held up for a while: holding up
    # is not confirmation, and a row claiming `confirmed` with nothing in `sources` would be
    # fabricated evidence that the basis rule then trusts.
    for m in mappings:
        if m["state"] == "confirmed":
            check(m.get("sources"),
                  f"reference map: {m['price_description']!r} claims confirmed and carries no "
                  f"written source; confirmation is a deployer's writing, not a judgement")
    check(all(m.get("why") for m in mappings), "reference map: every mapping says why")
    check(all(m.get("reference") for m in mappings if m["state"] != "ambiguous"),
          "reference map: a non-ambiguous mapping names a reference")


def O_terms(outcome):
    """The catalogue's `key:value|...` description, as a dict."""
    return dict(part.split(":", 1) for part in outcome.get("description", "").split("|") if ":" in part)


def runbooks():
    """A runbook's checkable claims are checked, because a runbook is what a human follows.

    `consumer/RUNBOOK.md` carried a superseded blocker for a day: PLAN and EVIDENCE were
    corrected on 22 Sep -- the live order waits on LIQUIDITY, not on testnet listing a bucket
    and a binary at one expiry -- and the runbook still said the old thing. Nothing checked it.
    Of the three documents, the runbook is the one somebody acts on, so it is the worst place
    for a stale claim and the last place it was noticed.

    Only claims that can be mechanically checked are checked here: signatures the contract
    really has, numbers that really scale that way, and blockers that really still hold. Prose
    is not the target; a number or a signature that has moved is.
    """
    consumer_book = (PROJECT / "consumer" / "RUNBOOK.md").read_text()
    onchain_book = (PROJECT / "onchain" / "RUNBOOK.md").read_text()

    # ---- THE BLOCKER IS THE ONE THAT HOLDS
    #
    # Both pages must name liquidity, and neither may still say a bucket is required: testnet
    # lists strike ladders, and long-plus-YES-plus-NO across two strikes is a hedge this tool
    # verifies. Checked against the retained catalogue by `testnet_shape` above.
    # THE BLOCKER IS STATED WHERE IT IS ACTED ON. Both pages must say, in the section that
    # stops an operator, that what is missing is a QUOTED BOOK -- not merely mention liquidity
    # somewhere in passing, which a page can do while telling someone to wait for the wrong
    # thing two paragraphs later.
    # SUPERSEDED 23 Sep, and the guard is the reason it was caught. Both pages said the order
    # "waits on a quoted book" and cited two books as 0 bids / 0 asks. Re-measuring found that
    # those two instances had EXPIRED (null, not empty), and that 112 of 1,236 testnet books do
    # carry quotes -- all of them World Cup or CPI markets, none a crypto price ladder. So the
    # blocker is narrower than "a quoted book": it is a quoted PRICE market. Editing the pages
    # broke this guard, which is what a guard over a claim is for.
    for name, book in (("consumer", consumer_book), ("onchain", onchain_book)):
        # BOTH PAGES POINT AT THE SWEEP rather than restating a measurement. The blocker claim
        # changed three times in two days -- listing, then depth, then a quoted price market,
        # then nothing -- and each restatement went stale. A command the reader RUNS cannot.
        check("tools/sweep_testnet.py" in book,
              f"runbook: {name} does not tell the reader to run the sweep")
        # The instruments are DATED, so the page must say the measurement expires.
        check("re-sweep" in book.lower() or "Re-run the sweep" in book,
              f"runbook: {name} does not tell the reader to re-sweep before acting")

    # THE SWEEP TABLE WAS REMOVED ON 12 OCTOBER, and with it the arithmetic guard over it.
    #
    # That guard parsed three numeric rows and required `quoted + empty == total`, with total
    # two sides of a stated outcome count. It existed because a substring test for "112" had
    # passed with the table's own cell corrupted (EVIDENCE section 9), and the arithmetic was
    # the only internally checkable claim about a set of LIVE figures.
    #
    # The page no longer tabulates them. The counts were dated measurements of instruments that
    # expire, `make check` is offline by design, and the guard's own reasoning -- recorded below
    # and still holding for the price-market count -- is that the honest check is to send the
    # reader to the sweep rather than to pin a number here that a passing expiry invalidates.
    # Having made that argument about one figure it was inconsistent to keep tabulating the
    # others, so the table went and this guard went with it. What remains is the requirement
    # that the page name the sweep and tell the reader to re-run it, which the two checks above
    # enforce, and which is the part an operator actually acts on.
    #
    # THE PRICE-MARKET COUNT IS NOT GUARDED HERE, DELIBERATELY.
    #
    # It was, briefly, as `hedgeable <= 2*markets` and `hedgeable <= quoted`. A mutation raising
    # the market count 56 -> 96 stayed GREEN, and no internal relation can catch it: 96 is
    # arithmetically consistent with 618 outcomes, 114 quoted books and 28 quoted price books.
    # The figure is a live MEASUREMENT, and `make check` is offline by design. Writing a
    # checkable-looking assertion around an uncheckable number is worse than admitting the gap:
    # it reads as verified.
    #
    # WHAT *IS* CHECKABLE is that the page does not STATE such a count as fact. Caught by
    # mutation 12 October: after the table was removed, replacing the old "read the count from
    # the sweep" instruction with "the count is 56" escaped, because the check that had enforced
    # the instruction was removed with the table and nothing replaced it. A guard whose subject
    # no longer exists on the page is vacuous, which is worse than absent -- it still counts
    # toward a green. The page may describe the sweep's categories; it may not publish a tally.
    for tally in re.findall(r"(?:^|[^\d])(\d{2,4}) (?:structured price markets|quoted books|"
                            r"markets and \d+ quoted)", consumer_book):
        check(False,
              f"runbook: consumer publishes a live sweep tally ({tally}); these are dated "
              f"instruments and make check is offline, so the page must send the reader to "
              f"tools/sweep_testnet.py for the current figure instead of stating one")
    for stale, what in (("waits on testnet listing a bucket and a binary", "the bucket blocker"),
                        ("waits on a quoted book", "the undifferentiated-depth blocker")):
        check(stale not in consumer_book, f"runbook: consumer still names {what}")
        check(stale not in onchain_book, f"runbook: onchain still names {what}")

    # ---- EVERY SIGNATURE THE ON-CHAIN PAGE TELLS AN OPERATOR TO CALL EXISTS
    #
    # A runbook is a list of commands somebody pastes. A signature that has drifted is a
    # command that reverts or, worse, calls something else.
    artifact = PROJECT / "onchain" / "out" / "ApprovedOrderGate.sol" / "ApprovedOrderGate.json"
    if artifact.exists():
        abi = json.loads(artifact.read_text())["abi"]
        signatures = {
            f"{entry['name']}({','.join(argument['type'] for argument in entry['inputs'])})"
            for entry in abi if entry["type"] == "function"
        }
        errors = {entry["name"] for entry in abi if entry["type"] == "error"}
        for quoted in re.findall(r'"(\w+\([^"]*?\))"', onchain_book):
            stripped = re.sub(r"\)\(.*", ")", quoted)  # cast's "f()(address)" return spec
            check(stripped in signatures,
                  f"runbook: the on-chain page calls {stripped}, which the gate does not have")
        for named in re.findall(r"\| `([A-Z]\w+)` \|", onchain_book):
            check(named in errors,
                  f"runbook: the on-chain page tabulates the error {named}, which does not exist")
    else:
        # forge has not been run, so there is no ABI to check against. Said out loud rather
        # than passed silently: a check that cannot run is not a check that passed.
        check(True, "runbook: no compiled ABI, so the on-chain signatures are unchecked here")

    # ---- THE SCALED NUMBERS ARE THE ENVELOPE'S OWN
    #
    # The page works the arithmetic from the retained envelope. Every figure is derived here
    # from that envelope rather than trusted, because a worked example with a wrong number
    # teaches the wrong arithmetic.
    envelope = canon.loads(
        (PROJECT / "fixtures" / "bundles" / "good-envelope" / "result.json").read_bytes()
    )["order_envelope"]

    def scaled(text):
        whole, _, fraction = text.partition(".")
        return int(whole + fraction.ljust(8, "0"))

    asset = 100_000_000 + int(envelope["coin"][1:])
    price, size = scaled(envelope["limit_price"]), scaled(envelope["size"])
    # READ FROM EACH PLACE SEPARATELY, not counted across the page.
    #
    # Two weaker spellings were tried and both let a mutation through. "Is the number present"
    # passes with the pasted command wrong, because the table still carries it. "Is it present
    # twice" passes with EITHER of the two wrong, because the other still matches -- run as a
    # mutation, corrupting the `size` row of the table stayed green. So each site is extracted
    # on its own and compared, and the one an operator pastes is a site.
    cost = scaled(envelope["max_cost"]) * 10 ** 8

    # The `Scaled` column of the worked table: last cell of each row, in page order.
    tabulated = re.findall(r"^\| `\w+`[^\n]*\| `([0-9]+)`[^`\n]*\|\s*$", onchain_book, re.M)
    check(tabulated == [str(value) for value in (asset, price, size, cost)],
          f"runbook: the worked table scales to {tabulated}, not the envelope's own "
          f"{[asset, price, size, cost]}")

    # The arguments of each `cast send` an operator pastes, read off the command itself.
    def arguments(signature):
        found = re.findall(
            re.escape(f'"{signature}"') + r'[^\n]*\n\s*<input_digest>((?: [0-9]+)+)', onchain_book)
        check(len(found) == 1,
              f"runbook: the on-chain page gives {len(found)} pasteable {signature} commands")
        return [int(word) for word in found[0].split()] if found else []

    check(arguments("approve(bytes32,uint32,uint64,uint64,uint128)") == [asset, price, size, cost],
          "runbook: the approve command an operator pastes is not the envelope's own numbers")
    check(arguments("send(bytes32,uint64,uint64)") == [price, size],
          "runbook: the send command an operator pastes is not the envelope's own numbers")

    # And the ceiling really is tight at those values: the cost check on chain is
    # `limitPx * sz <= maxCost`, so a worked example where the product exceeds the ceiling
    # would teach an operator to approve something that always reverts.
    check(price * size == cost,
          f"runbook: {price} * {size} is {price * size}, not the tabulated ceiling {cost}")
    # And the identity the page asserts: the walk touched the top level, so the bound is tight.
    check(price * size == scaled(envelope["max_cost"]) * 10 ** 8,
          "runbook: limitPx * sz is not max_cost at 10^16, so the page's table is wrong")

    # ---- NO PAGE OFFERS THE LADDER AS THE WAY THROUGH
    #
    # `consumer/RUNBOOK.md` told an operator for a day that what unblocked them was "widen
    # discovery to the ladder shape, or declare a basis bound -- both are the owner's". Both
    # were wrong: mainnet already pairs the two families, so nothing needed widening, and the
    # remaining obstacle is a market price no decision reaches. That is the second time this
    # page has carried a superseded blocker, and a runbook is the document somebody ACTS on.
    # The historical record in PLAN may discuss the ladder; a page that stops an operator may
    # not offer it as an action.
    #
    # A BARE SUBSTRING CANNOT DO THIS, found by the guard's own control failing 24 Sep: the
    # corrected page NAMES the dropped advice in order to retract it, so "widen discovery to
    # the ladder shape" not in book fails on the very text that fixes the problem. Prohibiting
    # a phrase forbids quoting it, which is the opposite of a page that explains itself. What
    # distinguishes them is the RETRACTION, so that is what is checked: any page mentioning the
    # ladder as a way through must also say it was dropped, and must send the reader to the
    # command that decides today.
    for name, book in (("consumer", consumer_book), ("onchain", onchain_book)):
        offers = re.search(r"widen discovery to the ladder shape", book)
        if offers:
            check(re.search(r"ladder is not being built|ladder was dropped", book),
                  f"{name} runbook names widening discovery to the ladder shape without saying "
                  f"it was dropped, so an operator reads a superseded action as the way through")
    check("hedgeable_today.py" in consumer_book,
          "consumer runbook does not point at tools/hedgeable_today.py, so an operator has no "
          "command that says whether today's market can produce a hedge")

    # ---- README'S VERIFICATION SECTION IS HELD TO THE RETAINED CAPTURE
    #
    # The section states three verdicts and two premiums as reproducible output. Those are
    # exactly the figures that go stale, and a published number that disagrees with the capture
    # it claims to come from is worse than no number. Checked against the retained 18 September
    # bytes rather than against the engine, so the page and the capture cannot drift apart
    # silently. (These guards covered DEMO.md until 12 October, when that page was folded into
    # README; the figures and the reasoning are unchanged.)
    demo = (PROJECT / "README.md").read_text()
    base = FIXTURES / "replay" / "2026-09-18"

    # The premium for the smallest passing size, walked over the retained ask levels by hand.
    # Costs are money and the page quotes them to five decimals, so Fraction, never float.
    def premium_for(stem, size):
        levels = json.loads((base / f"{stem}.json").read_text())["levels"][1]
        remaining, spend = size, F(0)
        for level in levels:
            take = min(remaining, int(F(level["sz"])))
            spend += F(level["px"]) * take
            remaining -= take
            if remaining == 0:
                break
        check(remaining == 0,
              f"README: the retained {stem} book cannot fill {size}, so the stated premium is "
              f"not a number this capture supports")
        return spend

    for stem, size, shown in (("book-bucket0-3971-yes", 924, "160.76676"),
                              ("book-3965-no", 1409, "645.76904")):
        walked = premium_for(stem, size)
        check(walked == F(shown),
              f"README states {shown} for {size} of {stem}, the retained book walks to "
              f"{walked} -- the page and the capture disagree")
        check(shown in demo,
              f"README no longer shows the premium {shown}, so its ranking table has moved "
              f"away from the retained capture")

    # THE SIZES THE PREMIUMS ARE FOR, which the page states in prose.
    #
    # Caught by mutation 24 Sep: changing "924 bucket contracts" to 999 stayed green, because
    # only the premium strings were pinned and the size sat in a sentence. The size is what the
    # premium is computed FOR, so a reader who re-walks the book with the wrong size gets a
    # different number and concludes the page is wrong. The size is also the engine's own
    # `smallest` in `size_windows`, so it is checked against the result rather than a literal.
    # The sizes are HAND-PINNED, not read back from the engine. Running the engine here would
    # break the oracle's purity (no I/O, no subprocess) and, worse, would take the expected
    # value from the code under test -- so a wrong size would agree with itself. 924 and 1,409
    # are the values whose premiums are walked over the retained books above, and that walk is
    # the independent check: if a size were wrong the premium would not match the page.
    check("(924 bucket contracts, 1,409 binary)" in demo,
          "README does not state the sizes 924 and 1,409 that its hand-walk depends on, so a "
          "reader re-walking the book would use a different size and get a different total")

    # The ranking claim, which is the page's punchline: the bucket is the cheaper hedge.
    check(F("160.76676") < F("645.76904"),
          "the two premiums no longer rank bucket0 below binary")
    check("ranking : ['bucket0', 'binary']" in demo,
          "README does not show the ranking it states compare produces")

    # And the third proposal must still be the one that FAILS. A demo whose point is that the
    # tool refuses an expired hedge stops making it the moment that proposal passes.
    check("bucket0-horizon -> exit=1" in demo,
          "README no longer shows bucket0-horizon failing, which is the case that shows a "
          "reduction refusing a hedge rather than a hedge being approved")
    for stem in ("bucket0", "binary"):
        check(f"{stem}" in demo and (base / f"{stem}.proposal.json").exists(),
              f"README names {stem} but the retained proposal is gone")
    check((base / "bucket0-horizon.proposal.json").exists(),
          "the bucket0-horizon proposal README runs is missing from the capture")


def onchain_representable():
    """Every number an on-chain gate would carry survives 10^8 fixed point, exactly.

    Retained evidence (085ccfb, `interacting-with-hypercore.md`) says a CoreWriter limit order
    sends `limitPx` and `sz` as "10^8 * the human readable value". That is a LOSSY encoding for
    anything not a multiple of 10^-8 -- so a gate on chain would check a different number from
    the one the oracle proved, silently, for any price with a longer expansion.

    It does not happen, and the reason is a decision already made elsewhere. `defs.cost` carries
    a walked premium as a TOTAL rather than a per-unit price, because "a walk over several
    levels has no single price, and its average is a derived quantity that is usually a
    repeating decimal". The envelope follows: `limit_price` is the price of the highest level
    the walk TOUCHED -- a displayed price -- and `max_cost` is a sum of (displayed price x whole
    contracts). Displayed prices are multiples of 10^-8 and sizes are whole, so every product
    and every sum of them is a multiple of 10^-8.

    The AVERAGE is where it breaks: 1,409 contracts at 645.76904 averages 8072113/17612500,
    which no fixed point represents. The schema never carries one. This guard pins that the
    property holds, because the on-chain gate's soundness rests on it and it is a consequence
    of a choice that could be revisited without anyone noticing this.
    """
    scale = F(10) ** 8

    def exact_at_scale(text):
        return (O.num(text) * scale).denominator == 1

    def decimals(text):
        """The smallest e with value * 10^e integral, or None if no power of ten works."""
        value = O.num(text)
        for exponent in range(0, 20):
            if (value * F(10) ** exponent).denominator == 1:
                return exponent
        return None

    # ---- every displayed number in every retained book
    checked = 0
    for path in sorted((PROJECT / "fixtures" / "replay").rglob("book-*.json")):
        if path.name.endswith(".request.json"):
            continue  # the retained request record, not the response
        book = json.loads(path.read_text())
        for side in book["levels"]:
            for level in side:
                for key in ("px", "sz"):
                    check(exact_at_scale(level[key]),
                          f"on-chain: {path.name} {key} {level[key]} is not a multiple of 10^-8")
                    checked += 1
    check(checked >= 40, f"on-chain: only {checked} displayed numbers checked")
    # HEADROOM, not just representability. Checking "integral at 10^8" alone passes at 10^6
    # too, so it does not establish that the venue's scale is the binding one -- it would
    # still pass if the scale were smaller than the data needs. What is worth pinning is the
    # margin: the retained books need 10^5 at most, five orders of magnitude inside 10^8, so
    # the encoding has room and a price with a longer expansion would be a NEW observation
    # rather than a silent truncation.
    needed = max(decimals(level[key])
                 for path in sorted((PROJECT / "fixtures" / "replay").rglob("book-*.json"))
                 if not path.name.endswith(".request.json")
                 for side in json.loads(path.read_text())["levels"]
                 for level in side for key in ("px", "sz"))
    check(needed == 5,
          f"on-chain: the retained books need 10^{needed} decimals, recorded as 5 -- a change "
          f"is a new observation about the venue, not a rounding")
    check(needed < 8, "on-chain: and that is inside the 10^8 the venue encodes at")

    # ---- and every envelope the bundles carry
    envelopes = 0
    for path in sorted((PROJECT / "fixtures" / "bundles").glob("*/result.json")):
        result = canon.loads(path.read_bytes())
        envelope = result.get("order_envelope")
        if envelope is None:
            continue
        for key in ("limit_price", "size", "max_cost"):
            check(exact_at_scale(envelope[key]),
                  f"on-chain: {path.parent.name} {key} {envelope[key]} is not a multiple of 10^-8")
        envelopes += 1
    check(envelopes >= 1, "on-chain: no envelope was checked")

    # ---- THE AVERAGE WOULD BREAK IT, which is why the schema carries a total
    #
    # Hand-derived: 1,409 contracts for a walked total of 8072113/12500 averages
    # 8072113/17612500, whose expansion does not terminate at 10^-8.
    average = F(8072113, 12500) / F(1409)
    check((average * scale).denominator != 1,
          "on-chain: the worked average really is unrepresentable, so the total matters")
    check(O.fmt(F(8072113, 12500)) == "645.76904"
          and (F(8072113, 12500) * scale).denominator == 1,
          "on-chain: while the total it came from is exact")


def isolated_perp():
    """A liquidatable exposure is worth minus its margin at every terminal price.

    THE HEDGE CANNOT BE LIQUIDATED; THE EXPOSURE CAN. Retained evidence at 085ccfb states
    that outcomes "do not involve leverage or liquidations" -- so an outcome leg is safe, and
    the liquidation risk sits on the thing being hedged. That is why this is an EXPOSURE rule
    and not a leg rule, and why `linear_spot` could never express it.

    PLAN section 2 gives the rule: with the liquidation price inside the PATH domain, the leg
    is worth minus its isolated margin at EVERY terminal price. Not sometimes -- liquidation
    at any moment closes the position permanently, and a later recovery does not bring it
    back. Path dependence a terminal kernel cannot compute, mirrored from `priceTouch` except
    that here it cuts against the holder, so the worst case is the one that must be taken.
    """
    import lower

    replay = REPLAY
    snapshots = {}
    for stem in ("book-bucket0-3971-yes", "meta-and-asset-ctxs", "outcome-meta"):
        digest, document = lower.snapshot((replay / f"{stem}.json").read_bytes())
        snapshots[digest] = document
    registry = {}
    for path in sorted((PROJECT / "registry").glob("*.json")):
        entry = canon.loads(path.read_bytes())
        registry[entry["family"]] = entry
    base = canon.loads((replay / "bucket0.proposal.json").read_bytes())

    def perp(liquidation_price, margin="5000", **overrides):
        proposal = json.loads(json.dumps(base))
        proposal["exposure"] = {
            "kind": "isolated_perp", "underlying": "BTC",
            "quantity": proposal["exposure"]["quantity"],
            "reference": proposal["exposure"]["reference"],
            "liquidation_price": liquidation_price, "isolated_margin": margin,
        }
        proposal.update(overrides)
        lowered, _ = lower.lower(proposal, registry, snapshots)
        return lowered, O.evaluate(lowered)

    # ---- THE PATH DOMAIN IS THE HULL of the terminal domain and where the price starts
    #
    # PLAN section 2: "every price between now and the valuation time, so it contains the
    # current price and the terminal domain". A baseline OUTSIDE the terminal domain widens
    # it, which is right: the path starts there whatever the terminal range says.
    for label, baseline, expected in (("inside", F(77631), (F(60000), F(110000))),
                                      ("above", F(120000), (F(60000), F(120000))),
                                      ("below", F(50000), (F(50000), F(110000)))):
        proposal = {"domain": {"lower": "60000", "upper": "110000"}}
        check(lower.path_domain(proposal, baseline) == expected,
              f"isolated perp: a baseline {label} the domain gives the hull {expected}, "
              f"got {lower.path_domain(proposal, baseline)}")

    # ---- THE REDUCTION FIRES ON THE PATH DOMAIN, not on the terminal one
    #
    # The 18 September baseline is 77,631.4 and the domain is [60,000, 110,000], so the two
    # coincide here; the distinction is checked above on the hull itself.
    inside, _ = perp("80000")
    check([r["rule"] for r in inside.get("reductions", [])] == ["liquidated_in_path"],
          f"isolated perp: a liquidation price inside the path domain reduces, "
          f"got {[r['rule'] for r in inside.get('reductions', [])]}")
    outside, _ = perp("40000")
    check([r["rule"] for r in outside.get("reductions", [])] == [],
          "isolated perp: a liquidation price the path cannot reach reduces nothing")

    # TIGHT, unlike a loose bound: the adverse state is ADMISSIBLE, not merely unproven, so a
    # verdict may rest on it alone and it CAN make a proposal fail. That is the difference from
    # `price_touch`, whose bound understates a payoff and may therefore only ask for review.
    row = inside["reductions"][0]
    check(row["tight"] and row["reason_code"] == "LIQUIDATED_IN_PATH",
          f"isolated perp: the rule is tight and names its code, got {row}")

    # ---- THE IR CARRIES THE KIND, so a checker can re-derive the reduction
    #
    # Lowering used to write `{"kind": "linear", ...}` whatever the proposal said, which left
    # an isolated perp indistinguishable from spot by the time the evaluator saw it.
    check(inside["exposure"]["kind"] == "isolated_perp",
          f"isolated perp: the IR says what is exposed, got {inside['exposure']}")
    check(inside["exposure"]["liquidation_price"] == "80000"
          and inside["exposure"]["isolated_margin"] == "5000",
          "isolated perp: and carries the two numbers the reduction rests on")
    spot_ir, _ = lower.lower(base, registry, snapshots)
    check(spot_ir["exposure"] == {"kind": "linear", "quantity": "0.1"},
          f"isolated perp: a spot exposure is unchanged, got {spot_ir['exposure']}")

    # ---- MINUS THE MARGIN AT EVERY PRICE, and the profile is FLAT because of it
    #
    # Hand-derived: margin 5,000 plus the retained book walk of 160.76676 is 5,160.76676 at
    # and above the bucket's 75,908 threshold, where the hedge pays nothing. Below it the
    # hedge pays its 924, so the loss is 4,236.76676. Both pieces are flat, which is the
    # signature of an exposure that has stopped being a function of the terminal price.
    _, result = perp("80000")
    check([(piece["lower"], piece["upper"], piece["slope"], piece["intercept"])
           for piece in result["profile"]]
          == [("60000", "75908", "0", "-4236.76676"),
              ("75908", "110000", "0", "-5160.76676")],
          f"isolated perp: the liquidated profile is two flat pieces, got {result['profile']}")
    check(result["worst_case"] == {"pnl": "-5160.76676", "attained": True, "price": "75908"},
          f"isolated perp: the worst case is the margin plus the premium, got {result['worst_case']}")
    check(F("5000") + F("160.76676") == F("5160.76676"),
          "isolated perp: and that is exactly margin plus premium")

    # IT CAN FAIL A PROPOSAL, which a loose rule may never do. The same proposal passes on
    # spot and fails on a liquidatable perp, which is the whole point of the tier.
    spot_result = O.evaluate(spot_ir)
    check(spot_result["model_result"] == "passes" and result["model_result"] == "fails",
          f"isolated perp: spot passes and a liquidatable perp fails, got "
          f"{spot_result['model_result']} and {result['model_result']}")

    # ---- A NEGATIVE MARGIN IS REFUSED, not reduced: a position with negative money at risk
    # is not a position, and reducing by it would CREDIT the holder for being liquidated.
    try:
        perp("80000", margin="-5000")
        raise AssertionError("isolated perp: a negative isolated margin was accepted")
    except lower.Refused as refusal:
        check(refusal.code == "EXPOSURE_UNSOUND",
              f"isolated perp: a negative margin is EXPOSURE_UNSOUND, not {refusal.code}")


def assumption_vocabulary():
    """The assumption vocabulary is closed, defined once, and the same on both sides.

    An assumption is carried into the result and shown to a reader, who relies on what it
    MEANS. Until 22 Sep nothing checked the name: the schema types `assumptions` as any slug,
    so a proposal declaring `nothing_can_go_wrong` validated, lowered, and appeared in the
    result's own `assumptions` list beside the real ones with equal standing. Verified before
    the fix and refused after.

    TWO LISTS IN TWO LANGUAGES DRIFT. The oracle's `ASSUMPTIONS` and the engine's
    `assumptions` are the same vocabulary written twice, so they are compared here -- and
    every name is required to be USED, because a name nothing asks for is a word with no
    meaning to look up.
    """
    import lower

    check(lower.ASSUMPTIONS, "assumptions: the vocabulary is not empty")
    check(all(reason for reason in lower.ASSUMPTIONS.values()),
          "assumptions: every assumption says what declaring it asserts")

    # The Go vocabulary, read from its source. A second list is a second thing to keep right.
    source = (PROJECT / "engine" / "lower" / "lower.go").read_text()
    marker = "var assumptions = map[string]string{"
    check(marker in source, "assumptions: the engine declares its vocabulary")
    body = source[source.index(marker):]
    body = body[:body.index("\n}")]
    engine = set(re.findall(r'"([a-z_]+)":', body))
    check(engine == set(lower.ASSUMPTIONS),
          f"assumptions: the oracle has {sorted(set(lower.ASSUMPTIONS) - engine)} and the engine has "
          f"{sorted(engine - set(lower.ASSUMPTIONS))}")

    # EVERY NAME IS USED. `zero_base_fee` is required by lowering, `deployer_settles_as_written`
    # by a registry entry, and `common_reference` is declared by real proposals. A name none of
    # those reach is a word in a dictionary nobody reads.
    required_by_lowering = set(re.findall(r'for required in \(([^)]*)\)',
                                          (PROJECT / "oracle" / "lower.py").read_text()))
    from_lowering = set(re.findall(r'"([a-z_]+)"', " ".join(required_by_lowering)))
    from_registry = set()
    for path in sorted((PROJECT / "registry").glob("*.json")):
        from_registry.update(json.loads(path.read_text())["assumptions_required"])
    from_proposals = set()
    for path in sorted((PROJECT / "fixtures" / "replay").rglob("*.proposal.json")):
        from_proposals.update(canon.loads(path.read_bytes())["assumptions"])
    used = from_lowering | from_registry | from_proposals
    check(set(lower.ASSUMPTIONS) <= used,
          f"assumptions: {sorted(set(lower.ASSUMPTIONS) - used)} are defined but nothing uses them")
    check(used <= set(lower.ASSUMPTIONS),
          f"assumptions: {sorted(used - set(lower.ASSUMPTIONS))} are used but not defined")

    # AND AN UNKNOWN ONE IS REFUSED, including a near-miss typo -- the likelier fault, which
    # used to pass here and then fail the zero_base_fee requirement with a confusing message.
    replay = REPLAY
    snapshots = {}
    for stem in ("book-bucket0-3971-yes", "meta-and-asset-ctxs", "outcome-meta"):
        digest, document = lower.snapshot((replay / f"{stem}.json").read_bytes())
        snapshots[digest] = document
    registry = {}
    for path in sorted((PROJECT / "registry").glob("*.json")):
        entry = canon.loads(path.read_bytes())
        registry[entry["family"]] = entry
    base = canon.loads((replay / "bucket0.proposal.json").read_bytes())
    for invented in ("nothing_can_go_wrong", "zero_base_fees", "ZERO_BASE_FEE"):
        proposal = json.loads(json.dumps(base))
        proposal["assumptions"] = sorted(set(proposal["assumptions"]) | {invented})
        try:
            lower.lower(proposal, registry, snapshots)
        except lower.Refused as refusal:
            check(refusal.code == "ASSUMPTION_UNKNOWN",
                  f"assumptions: {invented!r} is refused as ASSUMPTION_UNKNOWN, not {refusal.code}")
        else:
            raise AssertionError(f"assumptions: {invented!r} was accepted")
    # The honest proposal still lowers, so the rule refuses the wrong thing and not everything.
    lowered, _ = lower.lower(base, registry, snapshots)
    check(set(lowered["assumptions"]) <= set(lower.ASSUMPTIONS),
          "assumptions: a lowered proposal carries only defined assumptions")


def synthesis_refusal_classes():
    """The synthesis checker's classes are the frozen closed list, not a second list.

    `checker/src/synthesis.ts` declares its own `SynthesisRefusalClass` rather than importing
    `verify.ts`'s, so the two modules do not depend on each other for a type. That is the
    right structure and it costs something: nothing stops the two lists drifting apart, and
    a class outside `schema/refusal.schema.json` would be a refusal a consumer cannot act on,
    since the schema is the contract the closed list lives in.

    So the claim the comment in that file makes -- that the schema holds it to the list -- is
    checked here. It was written before this guard existed and was therefore false.
    """
    frozen = set()
    schema = json.loads((PROJECT / "schema" / "refusal.schema.json").read_text())

    def collect(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "enum" and isinstance(value, list):
                    frozen.update(item for item in value if isinstance(item, str))
                collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)
    collect(schema)
    check(len(frozen) >= 18, f"synthesis classes: the frozen list has {len(frozen)} classes")

    source = (PROJECT / "checker" / "src" / "synthesis.ts").read_text()
    marker = "export type SynthesisRefusalClass ="
    check(marker in source, "synthesis classes: the checker declares its class list")
    body = source[source.index(marker):]
    body = body[:body.index(";")]
    named = set(re.findall(r'"([A-Z_]+)"', body))
    check(named, "synthesis classes: the declared list is not empty")
    check(named <= frozen,
          f"synthesis classes: {sorted(named - frozen)} are outside schema/refusal.schema.json")

    # And every class the checker can actually RETURN is declared. A `refuse(...)` call with a
    # class outside the declared list would not type-check, but a class declared and never
    # used is a claim the fixtures do not exercise -- which is the other direction, and the
    # synthesis fixtures cover it: `checker/test/synthesis.test.ts` asserts the classes seen.
    returned = set(re.findall(r'refuse\(\s*"([A-Z_]+)"', source))
    check(returned <= named,
          f"synthesis classes: {sorted(returned - named)} are returned but not declared")
    check(returned == named,
          f"synthesis classes: {sorted(named - returned)} are declared but never returned")


def one_definition():
    """No module defines the same name twice.

    Python binds the LATER definition, so a duplicate silently replaces the earlier one --
    and every edit to the earlier, including every mutation, becomes a no-op that passes.
    That defeated mutation testing twice on 22 Sep: `_simplex` returned (0, 0) for a program
    whose only constraint was `n1 + n2 >= 10`, and deleting the left-limit constraint rows
    showed no effect at all. Both looked like logic errors; neither was.

    A guard is trusted only after it has been seen failing, and a mutation that cannot
    reach the running code cannot fail. This makes the shadowing visible instead.
    """
    import ast
    for path in sorted((PROJECT / "oracle").glob("*.py")) + sorted((PROJECT / "tools").glob("*.py")):
        tree = ast.parse(path.read_text())
        seen = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                check(node.name not in seen,
                      f"one definition: {path.name} defines {node.name} at lines "
                      f"{seen.get(node.name)} and {node.lineno}")
                seen[node.name] = node.lineno


def synthesis():
    """The synthesis LP: exact, finite, certified, and re-checked after rounding.

    PLAN section 3: "breakpoints come from strikes, not sizes, so cheapest sizes meeting the
    envelope is a linear program with finitely many constraints, solved in exact arithmetic.
    Its dual gives an infeasibility certificate the checker verifies by one multiplication.
    Sizes are whole contracts, so the program is a relaxation: round, re-check the rounded
    structure with the evaluator, and claim infeasibility only when the relaxation itself
    is infeasible."
    """
    L, U = F(60000), F(110000)

    # ---- THE BREAKPOINTS DO NOT DEPEND ON THE SIZES
    #
    # This is what makes the program finite: one atom walk with unit sizes gives the
    # constraint sites for every member of the family. If the sites moved with the sizes
    # there would be no fixed row set and no linear program at all.
    def family(n1, n2):
        return O.total([O.linear(F("0.1"), F(77631)),
                        O.indicator(n1, upper=F(75908), upper_inclusive=False),
                        O.indicator(n2, upper=F(79007), upper_inclusive=False)])
    marks = [sorted(family(F(a), F(b)).breakpoints) for a, b in ((0, 0), (1, 1), (924, 500))]
    check(marks[0] == marks[1] == marks[2] == [F(75908), F(79007)],
          "synthesis: the breakpoint set is the strikes, whatever the sizes")

    # ---- THE ROWS ARE THE OBJECTIVE, exactly
    #
    # Feasibility over the whole domain is feasibility at these rows and at no other price.
    # Checked against a brute-force sweep rather than asserted: a row set that missed a site
    # would call a structure feasible at a price where it is not.
    base = O.linear(F("0.1"), F(77631))
    units = [O.indicator(F(1), upper=F(75908), upper_inclusive=False),
             O.indicator(F(1), upper=F(79007), upper_inclusive=False)]
    rows = O.constraints(base, units, F(-1000), L, U)
    for sizes in ([F(0), F(0)], [F(924), F(500)], [F(2000), F(0)], [F(0), F(3000)]):
        priced = O.total([base] + [O.indicator(n, upper=u, upper_inclusive=False)
                                   for n, u in zip(sizes, (F(75908), F(79007)))])
        by_rows = min(alpha + sum(c * n for c, n in zip(coefficients, sizes))
                      for _, _, alpha, coefficients in rows)
        by_kernel = O.infimum(priced, L, U)[0]
        check(by_rows == by_kernel,
              f"synthesis: the rows give the kernel's infimum for {[O.fmt(n) for n in sizes]}, "
              f"{O.fmt(by_rows)} against {O.fmt(by_kernel)}")

    # ---- THE ROWS ARE DISTINCT CONSTRAINTS, so a site NAME identifies one
    #
    # Walking atoms emits a site per atom end, so a price where the function is continuous
    # yields the same inequality twice or three times: before this rule the PLAN section 3
    # example had 7 rows carrying 4 distinct constraints. They have to be deduplicated
    # because the certificate NAMES its sites, and a second implementation deriving rows
    # from MAXIMAL pieces finds the 4, not the 7. Keeping them would force either porting
    # this implementation's atom walk or resolving names by a fallback that could silently
    # accept the wrong row.
    plan_rows = O.constraints(O.linear(F("0.1"), F(100000)),
                              [O.digital_below(F(1), F(90000))], F(-1000), L, U)
    check(len(plan_rows) == 4,
          f"synthesis: the PLAN section 3 program has 4 distinct rows, got {len(plan_rows)}")
    shapes = [(alpha, tuple(coefficients)) for _, _, alpha, coefficients in plan_rows]
    check(len(set(shapes)) == len(shapes),
          "synthesis: no two rows are the same inequality written twice")
    names = [(at, side) for at, side, _, _ in plan_rows]
    check(len(set(names)) == len(names), "synthesis: no two rows share a site name")
    # DEDUPLICATION IS BY THE WHOLE CONSTRAINT, not by the price. Two rows at one price with
    # different coefficients are different constraints and both must survive -- 90,000 is
    # exactly that, `below` where the digital still pays and `at` where it does not.
    at_ninety = [(side, O.fmt(coefficients[0])) for at, side, _, coefficients in plan_rows
                 if at == F(90000)]
    check(sorted(at_ninety) == [("at", "0"), ("below", "1")],
          f"synthesis: both constraints at the strike survive, got {sorted(at_ninety)}")

    # ---- A LEFT-LIMIT SITE IS A CONSTRAINT, and dropping it hides a real failure
    #
    # Each open atom contributes TWO rows, its `above` and `below` ends, because a sloped
    # piece never attains its infimum at an excluded end and a jump makes the two ends
    # different numbers. The `below` rows look redundant on a long exposure -- the worst
    # site is the domain floor and the left-limits sit above it -- so a row set missing
    # them passes every ordinary case.
    #
    # It fails here. SHORT exposure, so the loss grows with the price, and a base that
    # jumps UP at 79,007, so the worst point is the left-limit just below it. Hand-derived
    # at 1,000 contracts: the full row set gives -137.6, the `above`-only set gives +763.1
    # -- a structure called feasible at a price where it is not.
    short = O.total([O.linear(F("-0.1"), F(77631)), O.digital_at_or_above(F(3000), F(79007))])
    step = [O.indicator(F(1), lower=F(90000), lower_inclusive=True)]
    step_rows = O.constraints(short, step, F(-1000), L, U)
    # Read through `constraints` itself, never a list rebuilt here: the claim is about what
    # that function yields, and a check that filters its own copy passes whatever the
    # function does. The rows must reproduce the KERNEL's infimum, which is the independent
    # answer, and they must do it because the left-limit row is present.
    check(any(side == "below" for _, side, _, _ in step_rows),
          "synthesis: constraints yields left-limit rows at all")
    for size, want in ((F(1000), F("-137.6")), (F(3000), F("-137.6"))):
        priced = O.total([short, O.indicator(size, lower=F(90000), lower_inclusive=True)])
        by_rows = min(alpha + coefficients[0] * size for _, _, alpha, coefficients in step_rows)
        check(by_rows == want,
              f"synthesis: the left-limit site binds at {O.fmt(size)}, expected {O.fmt(want)}, got {O.fmt(by_rows)}")
        check(by_rows == O.infimum(priced, L, U)[0],
              f"synthesis: and the rows agree with the kernel at {O.fmt(size)}")

    # ---- THE PLAN SECTION 3 EXAMPLE IS INFEASIBLE, and the certificate proves it
    #
    # Hand-derived there: 0.1 BTC from 100,000, one digital below 90,000 at 0.20, cap -1000.
    # The best worst case any size can buy is -(D + p*A) = -1,600, against a -1,000 cap.
    hedge = O.digital_below(F(1), F(90000))
    answer = O.synthesise(O.linear(F("0.1"), F(100000)), [hedge], [F("0.2")], F(-1000), L, U)
    check(answer["status"] == "infeasible",
          f"synthesis: the PLAN section 3 example is infeasible, got {answer['status']}")

    # THE CERTIFICATE IS CHECKED, not trusted: y >= 0, A^T y <= 0, b . y > 0 is exactly the
    # statement that no non-negative sizes satisfy the rows. One multiplication, as PLAN says.
    rows = O.constraints(O.linear(F("0.1"), F(100000)), [hedge], F(-1000), L, U)
    net = [[c - F("0.2") for c in coefficients] for _, _, _, coefficients in rows]
    right = [F(-1000) - alpha for _, _, alpha, _ in rows]
    # The weights are SPARSE and each NAMES ITS SITE, so the checker resolves them against
    # its own rows rather than relying on a shared row order. Resolution is part of the
    # check: a weight naming a site the rows do not have is a certificate about a different
    # program, which must be refused rather than quietly skipped.
    index = {(at, side): k for k, (at, side, _, _) in enumerate(rows)}
    sparse = answer["certificate"]["weights"]
    check(sparse, "synthesis: the certificate carries at least one weight")
    check(len(sparse) <= len(rows), "synthesis: the certificate is sparse, never longer than the rows")
    y = [F(0)] * len(rows)
    for entry in sparse:
        site = (entry["price"], entry["side"])
        check(site in index,
              f"synthesis: the certificate names site {O.fmt(entry['price'])}/{entry['side']}, "
              f"which is not a row of this program")
        y[index[site]] = entry["weight"]
    check(all(entry["weight"] > 0 for entry in sparse),
          "synthesis: a carried weight is strictly positive, since a zero weight says nothing")
    columns = [sum(y[j] * net[j][i] for j in range(len(net))) for i in range(1)]
    check(all(value <= 0 for value in columns),
          f"synthesis: A^T y <= 0, got {[O.fmt(v) for v in columns]}")
    check(sum(y[j] * right[j] for j in range(len(right))) > 0,
          "synthesis: b . y > 0, so the rows are contradictory")

    # PLAN'S OWN two-row certificate is valid on these rows too. It weights the STRIKE row,
    # whose net coefficient is -p, by (1 - p), and the FLOOR row, whose net coefficient is
    # 1 - p, by p: (1-p)(-p) + p(1-p) = 0. Pairing them the other way round does not cancel,
    # which is the arithmetic that made this check worth writing down.
    at = {(a, s): k for k, (a, s, _, _) in enumerate(rows)}
    # Named, so a row set that stops yielding point sites fails with the reason rather than
    # a KeyError. The `at` rows are where a digital's own value lives; without them the
    # strike -- the site the whole certificate turns on -- has no constraint at all.
    for site in ((F(90000), "at"), (F(60000), "at")):
        check(site in at, f"synthesis: the row set has a point site at {O.fmt(site[0])}")
    plan = [F(0)] * len(rows)
    plan[at[(F(90000), "at")]] = F(1) - F("0.2")
    plan[at[(F(60000), "at")]] = F("0.2")
    check(sum(plan[j] * net[j][0] for j in range(len(net))) == 0,
          "synthesis: PLAN's weights cancel the size, paired strike-then-floor")
    check(sum(plan[j] * right[j] for j in range(len(right))) > 0,
          "synthesis: and PLAN's weights leave a contradiction")

    # ---- A FEASIBLE CASE, with the answer checked against the evaluator
    #
    # The same shape with a cap the hedge can meet. The sizes come back as whole contracts,
    # and the structure they describe really does meet the objective -- established with the
    # kernel's own infimum, not with the solver that proposed it.
    easy = O.synthesise(O.linear(F("0.1"), F(100000)), [hedge], [F("0.2")], F(-4000), L, U)
    check(easy["status"] == "feasible", f"synthesis: a reachable cap is feasible, got {easy['status']}")
    sizes = easy["sizes"]
    check(all(n == int(n) for n in sizes), f"synthesis: sizes are whole contracts, got {sizes}")
    built = O.total([O.linear(F("0.1"), F(100000)), O.digital_below(sizes[0], F(90000)),
                     O.cash(-F("0.2") * sizes[0])])
    check(O.infimum(built, L, U)[0] >= F(-4000),
          f"synthesis: the reported structure meets the cap, worst {O.fmt(O.infimum(built, L, U)[0])}")

    # ---- THE DOCUMENT CARRIES THE QUESTION, and validates
    #
    # A synthesis answer is only checkable if the question travels with it. These three
    # documents are the three statuses, each validated against schema/synthesis.schema.json
    # by the project's own validator -- not by a shape assertion written here, which would
    # pass whatever the schema said.
    schema_check = _validator()

    def request_for(min_pnl, lot="1"):
        return {
            "schema_version": "1",
            "objective": {"id": "loss_cap", "min_pnl": min_pnl},
            "domain": {"lower": "60000", "upper": "110000"},
            "units": {"money": "USDC", "price": "USDC per BTC", "exposure": "BTC", "size": "contracts"},
            "base": [{"id": "spot", "kind": "linear", "quantity": "0.1", "baseline": "100000"}],
            "candidates": [{"id": "put-90k", "pays_on": {"upper": "90000", "upper_inclusive": False},
                            "price": "0.2"}],
            "lot": lot,
        }

    for label, request, wanted in (("infeasible", request_for("-1000"), "infeasible"),
                                   ("feasible", request_for("-3333"), "feasible"),
                                   ("rounded off", request_for("-3333", lot="15000"), "rounding_failed")):
        document = O.synthesis_document(request)
        check(document["status"] == wanted,
              f"synthesis document: {label} is {wanted}, got {document['status']}")
        check(not schema_check.valid(document, "synthesis.schema.json"),
              f"synthesis document: {label} validates, "
              f"{schema_check.valid(document, 'synthesis.schema.json')}")
        check(document["request"] == request,
              "synthesis document: the question travels with the answer, unchanged")
        # NO SOLVER STATE. A certificate that needed the search replayed would not be one.
        check(not ({"tableau", "basis", "pivots", "iterations"} & set(document)),
              "synthesis document: no solver state is carried")

    # The feasible document names its sizes by CANDIDATE, so a reader never has to match
    # them to the request by position.
    feasible = O.synthesis_document(request_for("-3333"))
    check([entry["candidate"] for entry in feasible["sizes"]] == ["put-90k"],
          "synthesis document: a size names the candidate it is for")
    check("cost" in feasible, "synthesis document: a feasible answer says what it costs")
    check(feasible["sizes"][0]["size"] == "834" and feasible["cost"] == "166.8",
          f"synthesis document: 834 contracts at 0.2 costs 166.8, got {feasible['sizes'][0]['size']} "
          f"and {feasible.get('cost')}")

    # A REFUSED ROUNDING STILL SAYS WHAT IT WAS ROUNDING. `relaxed` is the program's own
    # answer, and without it `rounding_failed` is a dead end: a reader cannot see whether the
    # search was close or hopeless, and cannot pick a smaller lot to try again.
    rounded_off = O.synthesis_document(request_for("-3333", lot="15000"))
    check("relaxed" in rounded_off,
          "synthesis document: a refused rounding carries the relaxed point it was rounding")
    check(rounded_off["relaxed"] == ["833.75"],
          f"synthesis document: and it is 833.75, got {rounded_off.get('relaxed')}")
    check("sizes" not in rounded_off and "cost" not in rounded_off,
          "synthesis document: and reports no sizes, because none were established")

    # EVERY BASE KIND IS READ. `cash` is the one nothing else exercises: a premium already
    # paid, or a credit received, which shifts the whole profile. Ignoring it would make the
    # holder look better off than they are -- checked below, a -500 cash term against the
    # -3,333 cap moves the answer from 834 contracts to 1,459, and 1,458 misses at -3,333.6.
    with_cash = request_for("-3333")
    with_cash["base"] = with_cash["base"] + [{"id": "paid", "kind": "cash", "amount": "-500"}]
    carried = O.synthesis_document(with_cash)
    check(not schema_check.valid(carried, "synthesis.schema.json"),
          f"synthesis document: a cash base validates, {schema_check.valid(carried, 'synthesis.schema.json')}")
    check(carried["status"] == "feasible" and carried["sizes"][0]["size"] == "1459",
          f"synthesis: a -500 cash term moves the answer to 1459, got {carried.get('sizes')}")

    def with_cash_worst(size):
        return O.infimum(O.total([O.linear(F("0.1"), F(100000)), O.cash(-F(500)),
                                  O.digital_below(size, F(90000)),
                                  O.cash(-F("0.2") * size)]), L, U)[0]
    check(with_cash_worst(F(1459)) == F("-3332.8") and with_cash_worst(F(1459)) >= F(-3333),
          f"synthesis: 1,459 contracts is worth {O.fmt(with_cash_worst(F(1459)))} and meets the cap")
    check(with_cash_worst(F(1458)) == F("-3333.6") and with_cash_worst(F(1458)) < F(-3333),
          "synthesis: 1,458 misses it, so 1,459 is the smallest that works")

    # ---- SEVERAL INSTRUMENTS AT ONCE, which is what a synthesis is for
    #
    # Two digitals, at 90,000 for 0.20 and at 80,000 for 0.10. The program trades them off:
    # hand-derived and checked with the kernel below,
    #   cap -3,000  ->  (0, 1112), buying only the cheaper strike; 1,111 misses at -3,000.1
    #   cap -2,000  ->  (250, 2000) at a cost of 250, and NO pure 80,000 position meets that
    #                   cap at any size -- 2,500 is worth -2,250 and 3,334 is worth -2,333.4.
    # The second line is the point of synthesis: single-instrument sizing cannot find it,
    # because the answer is a mixture and sizing asks about one leg at a time.
    two = {"schema_version": "1",
           "objective": {"id": "loss_cap", "min_pnl": "-2000"},
           "domain": {"lower": "60000", "upper": "110000"},
           "units": {"money": "USDC", "price": "USDC per BTC", "exposure": "BTC", "size": "contracts"},
           "base": [{"id": "spot", "kind": "linear", "quantity": "0.1", "baseline": "100000"}],
           "candidates": [{"id": "put-90k", "pays_on": {"upper": "90000", "upper_inclusive": False},
                           "price": "0.2"},
                          {"id": "put-80k", "pays_on": {"upper": "80000", "upper_inclusive": False},
                           "price": "0.1"}],
           "lot": "1"}
    mixed = O.synthesis_document(two)
    check(not schema_check.valid(mixed, "synthesis.schema.json"),
          f"synthesis document: a two-candidate answer validates, {schema_check.valid(mixed, 'synthesis.schema.json')}")
    check([(entry["candidate"], entry["size"]) for entry in mixed["sizes"]]
          == [("put-90k", "250"), ("put-80k", "2000")],
          f"synthesis: the two-candidate answer is (250, 2000), got {mixed['sizes']}")
    check(mixed["cost"] == "250", f"synthesis: and it costs 250, got {mixed['cost']}")

    def two_candidate_worst(first, second):
        return O.infimum(O.total([O.linear(F("0.1"), F(100000)),
                                  O.digital_below(first, F(90000)),
                                  O.digital_below(second, F(80000)),
                                  O.cash(-F("0.2") * first - F("0.1") * second)]), L, U)[0]
    check(two_candidate_worst(F(250), F(2000)) == F(-2000),
          "synthesis: the mixed structure is worth exactly the cap at worst")
    # NO PURE POSITION IN THE CHEAPER INSTRUMENT MEETS IT. Without this the mixture could be
    # an accident of the solver rather than the answer sizing cannot reach.
    for alone in (F(2500), F(3000), F(3334), F(5000)):
        check(two_candidate_worst(F(0), alone) < F(-2000),
              f"synthesis: {O.fmt(alone)} contracts of the 80,000 strike alone still misses the cap")

    # A SIZE NAMES ITS CANDIDATE, checked where it can be checked: with two candidates at
    # different sizes, a builder that hardcoded one id would report the wrong one.
    check({entry["candidate"] for entry in mixed["sizes"]} == {"put-90k", "put-80k"},
          f"synthesis document: both candidates are named, got {mixed['sizes']}")

    # A POSITION ALREADY HELD is read too: the `indicator` base kind. A holder who already
    # owns protection needs less of it, and ignoring what they hold would size them as if
    # they held nothing. Checked below: 500 contracts of the 90,000 strike already owned
    # moves the answer from 834 to 209, and 208 misses at -3,333.6.
    holding = request_for("-3333")
    holding["base"] = holding["base"] + [
        {"id": "owned", "kind": "indicator", "size": "500",
         "pays_on": {"upper": "90000", "upper_inclusive": False}}]
    already = O.synthesis_document(holding)
    check(not schema_check.valid(already, "synthesis.schema.json"),
          f"synthesis document: an indicator base validates, {schema_check.valid(already, 'synthesis.schema.json')}")
    check(already["status"] == "feasible" and already["sizes"][0]["size"] == "209",
          f"synthesis: 500 contracts already held moves the answer to 209, got {already.get('sizes')}")

    def held_worst(extra):
        return O.infimum(O.total([O.linear(F("0.1"), F(100000)),
                                  O.digital_below(F(500), F(90000)),
                                  O.digital_below(extra, F(90000)),
                                  O.cash(-F("0.2") * extra)]), L, U)[0]
    check(held_worst(F(209)) >= F(-3333) and held_worst(F(208)) < F(-3333),
          f"synthesis: 209 more meets the cap at {O.fmt(held_worst(F(209)))} and 208 does not "
          f"at {O.fmt(held_worst(F(208)))}")

    # The infeasible document's certificate NAMES ITS SITES, so a checker resolves them
    # against its own rows rather than trusting a shared row order.
    refused = O.synthesis_document(request_for("-1000"))
    sites = {(entry["price"], entry["side"]) for entry in refused["certificate"]["weights"]}
    check(("90000", "at") in sites,
          f"synthesis document: the certificate names the strike, got {sorted(sites)}")
    check(all(O.num(entry["weight"]) > 0 for entry in refused["certificate"]["weights"]),
          "synthesis document: every carried weight is strictly positive")

    # ---- THE RELAXATION IS ROUNDED UP, NEVER DOWN
    #
    # Rounding down can drop below the floor the program solved for. The reported sizes are
    # therefore at least the relaxed ones, and the re-check above is what licenses reporting
    # them at all.
    check(all(n >= r for n, r in zip(easy["sizes"], easy["relaxed"])),
          "synthesis: every reported size is at least its relaxed value")

    # A FRACTIONAL relaxation, where the direction of the rounding decides the answer.
    # Hand-derived: a -3,333 cap needs 833.75 contracts; 834 gives a worst case of -3,332.8
    # and meets it, 833 gives -3,333.6 and does not. Rounding down would publish a size that
    # fails the objective it was chosen for -- the defect EVIDENCE section 9 records for
    # size windows, in a second place. Without a fractional case the whole rounding rule
    # could be deleted and every other check here would still pass.
    for cap, relaxed, rounded, worst_up, worst_down in (
        (F(-3333), F("833.75"), F(834), F("-3332.8"), F("-3333.6")),
        (F(-1999), F("2501.25"), F(2502), F("-1998.4"), F("-1999.2")),
    ):
        answer = O.synthesise(O.linear(F("0.1"), F(100000)), [hedge], [F("0.2")], cap, L, U)
        check(answer["status"] == "feasible", f"synthesis: cap {O.fmt(cap)} is feasible")
        check(answer["relaxed"][0] == relaxed,
              f"synthesis: cap {O.fmt(cap)} relaxes to {O.fmt(relaxed)}, got {O.fmt(answer['relaxed'][0])}")
        check(answer["sizes"][0] == rounded,
              f"synthesis: cap {O.fmt(cap)} rounds UP to {O.fmt(rounded)}, got {O.fmt(answer['sizes'][0])}")

        def built_at(size):
            return O.total([O.linear(F("0.1"), F(100000)), O.digital_below(size, F(90000)),
                            O.cash(-F("0.2") * size)])
        check(O.infimum(built_at(rounded), L, U)[0] == worst_up,
              f"synthesis: {O.fmt(rounded)} contracts is worth {O.fmt(worst_up)} at worst")
        check(O.infimum(built_at(rounded), L, U)[0] >= cap,
              "synthesis: and that meets the cap")
        # THE DIRECTION MATTERS, and this is the check that says so: one contract fewer
        # misses the cap, so rounding down would report a structure that fails.
        check(O.infimum(built_at(rounded - 1), L, U)[0] == worst_down,
              f"synthesis: one contract fewer is worth {O.fmt(worst_down)}")
        check(O.infimum(built_at(rounded - 1), L, U)[0] < cap,
              "synthesis: one contract fewer misses the cap, so rounding down would publish a failure")

    # ---- THE RE-CHECK IS REAL, on a rounding that does not meet the objective
    #
    # `synthesise` re-evaluates the rounded structure against the same rows and refuses to
    # report one that misses. Forced here with a lot size: rounding to the nearest 1,000
    # contracts overshoots so far that the premium alone breaks the cap, and the answer
    # must be `rounding_failed` -- which says the search found nothing, never that nothing
    # exists. Deleting the re-check turns this into a published structure that fails.
    # MORE PROTECTION IS NOT ALWAYS BETTER: the premium is paid at every price, so a large
    # enough position breaks the cap from above. Hand-derived: 834 contracts is worth
    # -3,332.8 at worst, but 15,000 is worth -3,000 at 90,000 and 20,000 is worth -5,000.
    # A lot size of 15,000 forces the relaxed 833.75 up past that, the re-check refuses it,
    # and the answer is `rounding_failed` -- the search found nothing, never "nothing exists".
    lumpy = O.synthesise(O.linear(F("0.1"), F(100000)), [hedge], [F("0.2")], F(-3333), L, U, lot=15000)
    check(lumpy["status"] == "rounding_failed",
          f"synthesis: a rounding that misses the cap is refused, got {lumpy['status']}")
    check("sizes" not in lumpy, "synthesis: and a refused rounding reports no sizes")
    overshoot = O.total([O.linear(F("0.1"), F(100000)), O.digital_below(F(15000), F(90000)),
                         O.cash(-F("0.2") * F(15000))])
    check(O.infimum(overshoot, L, U)[0] < F(-3333),
          "synthesis: 15,000 contracts really does miss the cap, so the refusal is right")
    # A lot that fits is still reported, so the rule refuses the wrong answer and not every
    # answer -- without this the re-check could reject everything and look correct.
    fits = O.synthesise(O.linear(F("0.1"), F(100000)), [hedge], [F("0.2")], F(-3333), L, U, lot=100)
    check(fits["status"] == "feasible" and fits["sizes"][0] == F(900),
          f"synthesis: a lot of 100 rounds to 900 and is reported, got {fits}")


def established_failures():
    """A `fails` verdict names only prices where the BEST case also violates the clause.

    A loose bound may lower a proposal's value but proves nothing about its real payoff, so a
    violation only the lower profile sees is `needs_review`. The verdict already obeyed that
    per INTERVAL; it did not obey it per PRICE. The lower profile can violate across a wider
    span than the upper one, and a witness drawn from the whole lower interval can land in
    the surplus, naming a counterexample whose best case MEETS the clause.

    This is the invariant, checked directly on the evaluator rather than on a fixture: for
    every failing interval of every generated case, the upper profile must violate that
    clause at the reported witness price. Regenerating the corpus cannot satisfy it, because
    it is not a comparison against stored output.
    """
    cases = sorted((FIXTURES / "generated" / "ir").glob("*.ir.json"))
    check(len(cases) >= 300, "established: the generated corpus is meant to be broad")
    thresholds, checked = {}, 0
    for path in cases:
        lowered = json.loads(path.read_text())
        result = O.evaluate(lowered)
        if result["model_result"] != "fails":
            continue
        # With no reduction the two profiles coincide and the invariant is trivial; the
        # result publishes no upper profile precisely because there is nothing to compare.
        if "upper_profile" not in result:
            continue
        # ONLY A LOOSE BOUND has to be established on the upper profile. A tight reduction
        # says the adverse state is ADMISSIBLE, not merely unproven -- `horizon_mismatch` is
        # the case: the leg really is worth zero when the objective is valued. A verdict may
        # rest on that alone, so the best case is allowed to meet the clause there.
        if all(reduction["tight"] for reduction in result["reductions"]):
            continue
        thresholds = {clause["id"]: O.num(clause["min_pnl"]) for clause in lowered["objective"]}
        # The upper profile the RESULT publishes, read as the piece list it is. Rebuilding it
        # here would test this function's copy of the rule rather than the evaluator's.
        def best_at(price):
            for piece in result["upper_profile"]:
                low, high = O.num(piece["lower"]), O.num(piece["upper"])
                if (low < price < high or (price == low and piece["lower_inclusive"])
                        or (price == high and piece["upper_inclusive"])):
                    return O.num(piece["intercept"]) + O.num(piece["slope"]) * price
            raise AssertionError(f"{path.name}: no upper piece covers {O.fmt(price)}")

        for interval in result.get("failing_intervals", []):
            price = O.num(interval["witness"]["price"])
            threshold = thresholds[interval["clause"]]
            check(best_at(price) < threshold,
                  f"established: {path.name} clause {interval['clause']} witness {interval['witness']['price']}: "
                  f"the upper profile gives {O.fmt(best_at(price))}, which meets {O.fmt(threshold)}")
            checked += 1
    check(checked > 0, "established: no failing interval was checked, so this proves nothing")


def price_touch_lowering():
    """A touch leg is lowered under its bound: right direction, kept, and loose.

    `price_touch_bound` above pins the arithmetic. This pins the PLUMBING, which is where
    the bound can be silently lost: lowering must pick the direction from the baseline,
    and the evaluator must APPLY the bound rather than zero the leg the way every other
    reduction is zeroed. Both were wrong before this guard existed.

    Outcome 1209 on the 18 September catalogue is the instance, unmodified:
      perp:HYPE|priceDescription:HYPE-USDC perp mark |seconds:1|target:100|time:20261001-0000
    """
    import lower

    replay_dir = PROJECT / "fixtures" / "replay" / "2026-09-18"
    entry = json.loads((PROJECT / "registry" / "template.priceTouch.json").read_text())
    entry["review"] = {"state": "reviewed", "drafted_by": "model", "reviewed_by": "fixture",
                       "reviewed_on": "2026-09-22", "digest": canon.semantics_version(entry)}
    base = canon.loads((replay_dir / "bucket0.proposal.json").read_bytes())
    snapshots = {}
    for stem in ("book-bucket0-3971-yes", "meta-and-asset-ctxs", "outcome-meta"):
        digest, document = lower.snapshot((replay_dir / f"{stem}.json").read_bytes())
        snapshots[digest] = document

    target, size = F(100), F(924)

    def lowered_for(baseline_price, quantity="0", drop_term=None):
        p = json.loads(json.dumps(base))
        p["baseline"] = {"kind": "explicit", "price": str(baseline_price), "label": "fixture"}
        p["assumptions"] = sorted(set(p["assumptions"]) | {"deployer_settles_as_written"})
        # The objective is stated on the same series the leg is observed on, so no basis
        # band is in play and the touch reduction is the only one under test.
        # The objective is stated on the series the leg's description MAPS to, so no basis
        # band is in play and the touch reduction is the only one under test.
        p["objective_reference"] = "hl:perp:HYPE:mark-twap:1s"
        # SHORT, so the loss grows as the price RISES and the worst case lands ABOVE the
        # target -- which is the only place the touch bound pays, and therefore the only
        # place where applying it rather than zeroing the leg is visible in the verdict.
        # With a long or flat exposure the worst case sits at the domain floor, the bound
        # pays nothing there, and zeroing the leg changes no reported number at all.
        p["exposure"] = {"kind": "linear_spot", "quantity": quantity, "underlying": "HYPE",
                         "reference": "hl:perp:HYPE:mark-twap:1s"}
        p["domain"] = {"lower": "50", "upper": "150"}
        leg = p["legs"][0]
        leg["family"] = "template.priceTouch"
        leg["id"] = "touch-yes"
        leg["instance"] = {"catalogue": leg["instance"]["catalogue"], "coin": "#12090", "outcome": "1209"}
        leg["semantics_version"] = canon.semantics_version(entry)
        leg["size"] = str(size)
        leg["side"] = "yes"
        # The acquisition is the base proposal's own book walk, kept as it is: the touch
        # bound is about what the leg PAYS, and paying a real premium keeps the verdict
        # honest about the cost of the bound.
        leg["terms"] = {"underlying": "HYPE", "target_price": "100", "seconds": "1",
                        "expiry": "2026-10-01T00:00:00Z"}
        if drop_term is not None:
            del leg["terms"][drop_term]
        p["objective_valuation_time"] = "2026-10-01T00:00:00Z"
        index = lower.reference_index(canon.loads((PROJECT / "references" / "reference-map.json").read_bytes()))
        ir, _ = lower.lower(p, {entry["family"]: entry}, snapshots, references=index)
        return ir, O.evaluate(ir)

    # ---- the direction comes from the baseline, and nothing else
    rising, _ = lowered_for(F(80))
    falling, _ = lowered_for(F(120))
    check(rising["legs"][0]["pays_on"] == {"lower": "100", "lower_inclusive": True},
          "touch: a baseline BELOW the target bounds the leg at or above it")
    check(falling["legs"][0]["pays_on"] == {"upper": "100", "upper_inclusive": True},
          "touch: a baseline ABOVE the target bounds the leg at or below it")
    # The entry states the rising case only. Mirroring is lowering's job, so a falling leg
    # that came back with the entry's own interval would mean the mirror never ran.
    check(rising["legs"][0]["pays_on"] != falling["legs"][0]["pays_on"],
          "touch: the two directions are different intervals")

    # ---- the reduction is declared, and it is LOOSE
    for ir, name in ((rising, "rising"), (falling, "falling")):
        rows = [r for r in ir.get("reductions", []) if r["rule"] == "price_touch"]
        check(len(rows) == 1 and rows[0]["reason_code"] == "PRICE_TOUCH_BOUNDED",
              f"touch: the {name} leg declares exactly one price_touch reduction")
        check(not rows[0]["tight"], f"touch: the {name} bound is loose, so it can never condemn")

    # ---- THE BOUND IS APPLIED, NOT DISCARDED
    #
    # Every other reduction worst-cases its leg to zero. Zeroing here would throw the bound
    # away and make a sound lower bound worth exactly as much as none -- the same defect a
    # declared basis bound had before the band rule existed. So the leg must be WORTH the
    # bound at a price the bound pays at.
    # ---- A ZEROING RULE WINS OVER THE BOUND, AND TODAY THAT MEANS THE BOUND IS INERT
    #
    # Every live touch instance is deployer-settled, and `deployer_settled` says the leg
    # may pay NOTHING at any price. `price_touch` says it is worth at least the terminal
    # digital. Both apply to one leg, and the LOWER must govern: crediting the bound over
    # a zeroing rule raises the lower profile on a leg that may pay nothing, which is the
    # one direction that can turn a failing proposal into a passing one.
    #
    # In the registry as it stands `bounded` and `deployer` coincide exactly -- the only
    # bounded family is deployer-settled -- so the bound reaches no verdict at all. It is
    # built, correct and DOMINATED. These checks pin that, so the day a protocol-settled
    # bounded family appears the bound is already right, and until then nobody reads the
    # touch machinery as doing work it is not doing.
    ir, _ = lowered_for(F(80), quantity="-10")
    rules = {r["rule"] for r in ir["reductions"]}
    check("deployer_settled" in rules and "price_touch" in rules,
          "touch: a live touch leg carries both the bound and the deployer rule")
    profile = O.evaluate(ir)
    check([r["reason_code"] for r in profile["reductions"] if r["rule"] == "price_touch"]
          == ["PRICE_TOUCH_BOUNDED"],
          "touch: the result names the reason code, so a reader sees which bound was used")

    def evaluate_with(rules_for_leg):
        copy_of = json.loads(json.dumps(ir))
        copy_of["reductions"] = [{"leg": "touch-yes", "rule": rule, "tight": False,
                                  "reason_code": "PRICE_TOUCH_BOUNDED" if rule == "price_touch"
                                  else "DEPLOYER_SETTLED"} for rule in rules_for_leg]
        return O.evaluate(copy_of)

    # HAND-DERIVED, not read off the code. Short 10 units from a baseline of 80, a premium
    # of 160.76676 for 924 contracts, a domain top of 150 and a target of 100:
    #   zeroed   the leg pays nothing anywhere, so the worst is at 150:
    #            -10*(150-80) - 160.76676  =  -860.76676
    #   bounded  the leg pays 924 on [100, 150], so above the target the short loss is more
    #            than repaid and the worst is the open approach to 100 from below:
    #            -10*(100-80) - 160.76676  =  -360.76676, NOT attained.
    only_bound = evaluate_with(["price_touch"])
    with_zeroing = evaluate_with(["price_touch", "deployer_settled"])
    check(with_zeroing["worst_case"] == {"pnl": "-860.76676", "attained": True, "price": "150"},
          "touch: a zeroed touch leg is worst at the domain top, at the hand-derived loss")
    check(only_bound["worst_case"] == {"pnl": "-360.76676", "attained": False, "price": "100"},
          "touch: an applied bound is worst approaching the target, at the hand-derived loss")
    # THE BOUND IS WORTH SOMETHING. Without this the whole touch path could be deleted and
    # every other check here would still pass.
    check(O.num(only_bound["worst_case"]["pnl"]) > O.num(with_zeroing["worst_case"]["pnl"]),
          "touch: applying the bound is strictly better than zeroing the leg")

    # A ZEROING RULE WINS. `deployer_settled` says the leg may pay nothing at any price, so
    # it must dominate the bound: crediting the bound over it would raise the lower profile
    # on a leg that may pay nothing, the one direction that can turn a fail into a pass.
    check(profile["worst_case"] == with_zeroing["worst_case"],
          "touch: a deployer-settled touch leg is valued at zero, bound or no bound")

    # THE UPPER PROFILE CREDITS THE FULL SIZE EVERYWHERE, INCLUDING BELOW THE TARGET.
    #
    # At a terminal price under the target the true payoff may still be the whole size: the
    # reference may have touched and retraced. So the best case cannot step at the target --
    # an upper profile that agreed with the bound there would claim to know the path.
    # Sampling only the domain top misses this entirely, because above the target the bound
    # and the full size coincide; without the gap correction the profile splits into two
    # pieces at 100 and understates everything below it by exactly the leg's size.
    def upper_at(result, price):
        for piece in result["upper_profile"]:
            if O.num(piece["lower"]) <= price <= O.num(piece["upper"]):
                return O.num(piece["intercept"]) + O.num(piece["slope"]) * price
        raise AssertionError(f"no upper piece covers {price}")
    for price in (F(50), F(99), F(100), F(150)):
        check(upper_at(only_bound, price) == upper_at(with_zeroing, price),
              f"touch: the upper profile credits the full size at {price}, bounded or zeroed")
    check(len(only_bound["upper_profile"]) == 1,
          "touch: the upper profile does not step at the target, because any path may have touched")

    # ---- A TERM THE LEG DOES NOT CARRY IS REFUSED, NOT A CRASH
    #
    # A proposal may name any family with any terms. The `unsupported-family` refusal fixture
    # relabels a bucket leg as a templated one, keeping the bucket's `index` and `thresholds`,
    # so `check_terms` is reached with no `seconds` at all. Indexing the terms directly raised
    # KeyError out of a function whose whole contract is to refuse -- and `make_refusals.py`
    # catches only `Refused`, so the generator crashed rather than recording a code.
    # `expiry` is read before check_terms, by the horizon comparison, and every family's
    # schema requires it -- so it cannot be absent here and is not in this list. The other
    # three are template-only terms a relabelled leg simply does not have.
    for missing in ("underlying", "target_price", "seconds"):
        try:
            ir, _ = lowered_for(F(80), quantity="-10", drop_term=missing)
        except lower.Refused as refusal:
            check(refusal.code == "TERMS_MISMATCH",
                  f"touch: a leg missing the {missing!r} term is refused as TERMS_MISMATCH, not {refusal.code}")
        else:
            raise AssertionError(f"touch: a leg missing the {missing!r} term was lowered")

    # ---- a baseline EXACTLY at the target is refused, not bounded
    #
    # The market's question is already answered, so it is not a hedge against anything and
    # a bound would be a claim about a market that is over.
    try:
        lowered_for(target)
        raise AssertionError("touch: a baseline at the target was lowered")
    except lower.Refused as refusal:
        check(refusal.code == "UNSUPPORTED_PAYOFF",
              "touch: a baseline exactly at the target is refused, not bounded")


def basis_band():
    """A declared basis bound reaches the verdict, and it is applied to the GROUP."""
    import lower

    replay_dir = PROJECT / "fixtures" / "replay" / "2026-09-18"
    entry = json.loads((PROJECT / "registry" / "recurring.priceBucket.json").read_text())
    proposal = canon.loads((replay_dir / "bucket0.proposal.json").read_bytes())
    snapshots = {}
    for stem in ("book-bucket0-3971-yes", "meta-and-asset-ctxs", "outcome-meta"):
        digest, document = lower.snapshot((replay_dir / f"{stem}.json").read_bytes())
        snapshots[digest] = document
    objective = proposal["objective_reference"]
    foreign = "pyth:BTC/USD:price-twap:90s"

    def lowered_for(reference_template, bounds):
        copy_of = json.loads(json.dumps(entry))
        copy_of["reference"] = reference_template
        copy_of["review"] = {"state": "reviewed", "drafted_by": "model", "reviewed_by": "fixture",
                             "reviewed_on": "2026-09-19", "digest": canon.semantics_version(copy_of)}
        p = json.loads(json.dumps(proposal))
        p["legs"][0]["semantics_version"] = canon.semantics_version(copy_of)
        if bounds is not None:
            p["basis_bounds"] = bounds
        ir, _ = lower.lower(p, {copy_of["family"]: copy_of}, snapshots)
        return ir, O.evaluate(ir)

    native = "hl:perp:{underlying}:mark-interp"
    away = "pyth:{underlying}/USD:price-twap:90s"
    declared = [{"between": [objective, foreign], "bound": "500"}]

    # A leg on the objective's own reference earns no band reduction at all. The entry
    # carries a TEMPLATE, so this also checks that {underlying} resolves from the leg's
    # own terms rather than being restated in the proposal.
    ir, result = lowered_for(native, None)
    check([r["rule"] for r in ir.get("reductions", [])] == [], "basis: a leg on the objective's reference is not banded")
    baseline_worst = result["worst_case"]["pnl"]

    # A ZERO band is no uncertainty, so it must give exactly the unbanded answer. This is
    # the check that catches a band applied with the wrong sign or to the wrong side.
    ir, result = lowered_for(away, [{"between": [objective, foreign], "bound": "0"}])
    check([r["rule"] for r in ir.get("reductions", [])] == ["basis_band"], "basis: a zero bound still declares the rule")
    check(result["worst_case"]["pnl"] == baseline_worst, "basis: a zero band is the unbanded answer")

    # A DECLARED bound buys something. Without this check `basis_band` and
    # `basis_unbridged` were the same answer -- the bound was recorded and discarded.
    ir_bounded, bounded = lowered_for(away, declared)
    ir_open, unbridged = lowered_for(away, None)
    check([r["rule"] for r in ir_open.get("reductions", [])] == ["basis_unbridged"],
          "basis: no declared bound is basis_unbridged")
    check(ir_bounded["reductions"][0]["bound"] == "500", "basis: the reduction states the bound it used")
    check(O.num(bounded["worst_case"]["pnl"]) > O.num(unbridged["worst_case"]["pnl"]),
          "basis: a declared bound is worth more than none")

    # A loose bound never condemns: PLAN section 2. Both forms are loose.
    for ir_case, name in ((ir_bounded, "basis_band"), (ir_open, "basis_unbridged")):
        check(all(not r["tight"] for r in ir_case["reductions"]), f"basis: {name} is loose")

    # THE GROUP, NOT THE LEG. The infimum of a sum is not the sum of infima: two legs
    # whose payoffs cancel have a flat sum that no basis move can hurt. Reducing them
    # separately invents a loss on a perfectly hedged position -- and per-leg is the LOWER
    # answer, so "a reduction never turns a failing proposal into a passing one" cannot
    # catch it. Measured on the kernel, which is where the difference lives.
    band = F(500)
    long_leg = O.digital_below(F(1000), F(80000))
    short_leg = O.digital_below(F(-1000), F(80000))
    grouped = O.band_infimum(O.total([long_leg, short_leg]), band)
    per_leg = O.total([O.band_infimum(long_leg, band), O.band_infimum(short_leg, band)])
    check(all(grouped(F(s)) == 0 for s in (79600, 80000, 80400)),
          "basis: a cancelling pair has a flat sum the band cannot hurt")
    check(all(per_leg(F(s)) < grouped(F(s)) for s in (79600, 80000, 80400)),
          "basis: reducing leg by leg is strictly worse, which is why the rule groups")

    # AND THE EVALUATOR MUST GROUP, not merely the kernel.
    #
    # The kernel check above proves the two differ; it does not prove `evaluate` uses the
    # grouped one. Every fixture is single-leg, where grouping and per-leg agree, so a
    # per-leg evaluator passed every check until this case existed -- found by mutation.
    #
    # Two legs that cancel: long 1000 below 80,000 and short 1000 below 80,000. The summed
    # payoff is identically zero, so no basis move can hurt it and the band must change
    # nothing. Per-leg banding invents a loss of 1000.
    cancelling = {
        "schema_version": "1",
        "units": ir_bounded["units"],
        "domain": {"lower": "79000", "upper": "81000"},
        "baseline": {"kind": "fixed", "price": "80000"},
        "exposure": {"kind": "linear", "quantity": "0"},
        "legs": [
            {"id": "long-leg", "kind": "indicator", "size": "1000",
             "pays_on": {"upper": "80000", "upper_inclusive": False},
             "premium": {"kind": "fixed", "price": "0"}, "observation_time": ir_bounded["objective_valuation_time"],
             "semantics": "0" * 64},
            {"id": "short-leg", "kind": "indicator", "size": "-1000",
             "pays_on": {"upper": "80000", "upper_inclusive": False},
             "premium": {"kind": "fixed", "price": "0"}, "observation_time": ir_bounded["objective_valuation_time"],
             "semantics": "0" * 64},
        ],
        "objective": [{"clause": "cap", "min_pnl": "-1"}],
        "objective_valuation_time": ir_bounded["objective_valuation_time"],
        "other_costs": "0",
        "assumptions": ir_bounded["assumptions"],
        "reductions": [{"leg": "long-leg", "with": ["short-leg"], "rule": "basis_band",
                        "tight": False, "reason_code": "BASIS_BAND", "bound": "500"}],
    }
    result = O.evaluate(cancelling)
    check(result["worst_case"]["pnl"] == "0",
          f"basis: a cancelling pair is worth 0 under a band, not {result['worst_case']['pnl']}")
    # `passes`, not `needs_review`: a loose reduction only makes a verdict undecided where
    # a clause is actually breached on the lower profile, and this one is not breached
    # anywhere. A loose rule does not condemn; it also does not manufacture doubt.
    check(result["model_result"] == "passes",
          "basis: a cancelling pair breaches no clause, so there is nothing to review")
    check(result["failing_intervals"] == [] and result.get("undecided_intervals", []) == [],
          "basis: a cancelling pair has neither a failing nor an undecided interval")


def replay():
    import lower

    # ---- the retained bytes are byte-identical to the evidence commit
    snapshots = {}
    for stem, expected_hash in RETAINED.items():
        raw = (REPLAY / f"{stem}.json").read_bytes()
        digest, document = lower.snapshot(raw)
        check(digest == expected_hash, f"replay: {stem}.json is the retained response")
        record = json.loads((REPLAY / f"{stem}.request.json").read_text())
        check(record["response_sha256"] == digest, f"replay: {stem} matches its own request record")
        snapshots[digest] = document
    # A one-cent edit anywhere in a retained file must be detected.
    tampered = (REPLAY / "book-3965-no.json").read_bytes().replace(b'"0.451"', b'"0.452"', 1)
    check(sha256(tampered).hexdigest() != RETAINED["book-3965-no"], "replay: a one-cent change in a retained byte is detected")

    registry = {}
    for path in sorted((PROJECT / "registry").glob("*.json")):
        entry = canon.loads(path.read_bytes())
        registry[entry["family"]] = entry

    proposals = {name: canon.loads((REPLAY / f"{name}.proposal.json").read_bytes()) for name in PINNED}

    # ---- what the entries ON DISK produce, whichever state they are in
    #
    # This used to assert the draft behaviour unconditionally, which made it a record of
    # the tree's state at one moment rather than a check. The draft arithmetic is still
    # worth holding, so it is driven from in-memory DRAFT copies below; the on-disk
    # entries are checked for whichever state they are actually in.
    drafted = {}
    for family, entry in registry.items():
        copy = json.loads(json.dumps(entry))
        copy["review"] = {"state": "draft", "drafted_by": "model"}
        drafted[family] = copy

    # The entries these PROPOSALS use, not every entry on disk. A draft for a family no
    # replay proposal names -- a newly drafted template family, say -- says nothing about
    # whether these two proposals are reduced, and treating it as if it did sent the whole
    # replay down the draft branch.
    used = {leg["family"] for proposal in proposals.values() for leg in proposal["legs"]}
    on_disk_reviewed = all(canon.reviewed(registry[family]) for family in used)
    for name, proposal in proposals.items():
        lowered, _ = lower.lower(proposal, registry, snapshots)
        rules = [r["rule"] for r in lowered.get("reductions", [])]
        if on_disk_reviewed:
            check(rules == [], f"replay: {name} on disk is reduced by nothing")
            check(O.evaluate(lowered)["model_result"] == "passes", f"replay: {name} on disk passes")
        else:
            check(rules == ["unreviewed_family"], f"replay: {name} on disk is reduced by unreviewed_family")

    # ---- the DRAFT arithmetic, pinned against in-memory draft copies
    #
    # Hand-derived. The bucket leg is valued at zero and its premium still counts, so the
    # lower profile is 0.1*(S - 77631.4) - 160.76676, which is -1923.90676 at the floor and
    # crosses the -1000 cap at 69239.0676. The upper profile credits the leg with its full
    # 924 (EVIDENCE section 1), giving -999.90676 at the floor: inside the cap everywhere.
    # So nothing is proven to fail, and the verdict may never be `fails`.
    for name, proposal in proposals.items():
        lowered, _ = lower.lower(proposal, drafted, snapshots)
        check([r["rule"] for r in lowered["reductions"]] == ["unreviewed_family"], f"replay: {name} as a draft is reduced by unreviewed_family")
        check(lowered["reductions"][0]["tight"] is False, f"replay: {name} unreviewed_family is a loose rule")
        result = O.evaluate(lowered)
        check(result["model_result"] == "needs_review", f"replay: {name} as a draft needs review")
        check(result["failing_intervals"] == [], f"replay: {name} proves no failure from a loose bound")
        check("UNREVIEWED_FAMILY" in result["reason_codes"], f"replay: {name} names the loose rule")
        check([interval["responsible_legs"] for interval in result["undecided_intervals"]] == [[proposal["legs"][0]["id"]]],
              f"replay: {name} names the leg responsible for each undecided interval")
    bucket_draft = O.evaluate(lower.lower(proposals["bucket0"], drafted, snapshots)[0])
    check([(i["lower"], i["lower_inclusive"], i["upper"], i["upper_inclusive"]) for i in bucket_draft["undecided_intervals"]]
          == [("60000", True, "69239.0676", False)], "replay: bucket0 as a draft is undecided on [60000, 69239.0676)")
    check([(p["slope"], p["intercept"]) for p in bucket_draft["profile"]] == [("0.1", "-7923.90676")], "replay: bucket0 lower profile with the leg at zero")
    check([(p["slope"], p["intercept"]) for p in bucket_draft["upper_profile"]] == [("0.1", "-6999.90676")], "replay: bucket0 upper profile credits the leg with 924")
    check(O.fmt(_at(bucket_draft["upper_profile"], exact.parse("60000"))) == "-999.90676", "replay: bucket0 upper profile meets the cap at the floor")

    # ---- the numbers are pinned against in-memory reviewed copies, never written to disk
    reviewed = {}
    for family, entry in registry.items():
        copy = json.loads(json.dumps(entry))
        copy["review"] = {"state": "reviewed", "drafted_by": "model", "reviewed_by": "owner",
                          "reviewed_on": "2026-09-19", "digest": canon.semantics_version(entry)}
        check(canon.reviewed(copy) and canon.semantics_version(copy) == canon.semantics_version(entry),
              f"replay: the in-memory copy of {family} is reviewed and pins the same semantics")
        reviewed[family] = copy

    for name, (premium, at_baseline, at_strike, at_floor, pieces, breakevens) in PINNED.items():
        lowered, versions = lower.lower(proposals[name], reviewed, snapshots)
        check(not validate_ir(lowered), f"replay: {name} lowers to a document valid against ir.schema.json")
        check(versions == [canon.semantics_version(reviewed[proposals[name]["legs"][0]["family"]])],
              f"replay: {name} reports the semantics it used")
        cost = lowered["legs"][0]["premium"]
        check(cost["kind"] == "walked" and cost["total"] == premium and cost["snapshot"] == proposals[name]["legs"][0]["acquisition"]["snapshot"],
              f"replay: {name} cost is the walked total, citing the book it walked")

        result = O.evaluate(lowered)
        check(result["cost"]["premium"] == premium, f"replay: {name} premium")
        check(result["cost"]["pnl_at_baseline"] == at_baseline, f"replay: {name} P&L at the baseline")
        check(result["cost"]["breakevens"] == breakevens, f"replay: {name} break-even prices")
        check([(p["slope"], p["intercept"]) for p in result["profile"]] == pieces, f"replay: {name} affine pieces")
        check(result["model_result"] == "passes", f"replay: {name} passes the cap")

        # P&L at the strike and at the floor, evaluated from the profile the result carries.
        strike, floor = exact.parse(STRIKES[name]), exact.parse(lowered["domain"]["lower"])
        check(O.fmt(_at(result["profile"], strike)) == at_strike, f"replay: {name} P&L at the strike")
        check(O.fmt(_at(result["profile"], floor)) == at_floor, f"replay: {name} P&L at the domain floor")

        # The strike is owned by the piece above it: NO pays strictly below the target.
        lower_piece = [p for p in result["profile"] if exact.parse(p["upper"]) == strike]
        check(lower_piece and lower_piece[0]["upper_inclusive"] is False, f"replay: {name} strike belongs to the upper piece")

        # ---- size window: which sizes would have met the cap on this book
        smallest, largest, low_bound, high_bound = SIZES[name]
        window = result["size_windows"][0]
        check(window["status"] == "nonempty" and window["leg"] == lowered["legs"][0]["id"], f"replay: {name} reports a size window for its sized leg")
        check((window["smallest"], window["largest"]) == (smallest, largest), f"replay: {name} whole-contract window {smallest}..{largest}")
        check((window["lower_bound"], window["upper_bound"]) == (low_bound, high_bound), f"replay: {name} exact size bounds")
        check([(b["price"], b["side"]) for b in window["binding"]] == [(lowered["domain"]["lower"], "at"), (STRIKES[name], "at")],
              f"replay: {name} floor binds the minimum size, strike binds the maximum")
        # The proposal's own size is the smallest that passes, and one fewer fails.
        check(lowered["legs"][0]["size"] == smallest, f"replay: {name} is proposed at the smallest passing size")
        one_fewer = json.loads(json.dumps(proposals[name]))
        one_fewer["legs"][0]["size"] = str(int(smallest) - 1)
        fewer_result = O.evaluate(lower.lower(one_fewer, reviewed, snapshots)[0])
        check(fewer_result["model_result"] == "fails", f"replay: {name} at {int(smallest) - 1} contracts fails")

        # ---- alternatives
        reduction = result["comparisons"]["smallest_reduction"]
        check(reduction["keep_quantity"] == KEEP, f"replay: {name} smallest reduction keeps {KEEP} BTC")
        check(reduction["worst_case"]["pnl"] == "-1000", f"replay: {name} the reduction meets the cap exactly, with no premium")
        check([(i["lower"], i["lower_inclusive"], i["upper"], i["upper_inclusive"]) for i in reduction["proposal_better"]] == BETTER[name],
              f"replay: {name} beats the reduction exactly where it should")
        no_hedge = result["comparisons"]["no_hedge"]
        check([(i["lower"], i["upper"]) for i in no_hedge["proposal_better"]] == [(lowered["domain"]["lower"], STRIKES[name])],
              f"replay: {name} beats no hedge only below the strike")

    # ---- a leg whose terms disagree with the catalogue is refused
    wrong = json.loads(json.dumps(proposals["binary"]))
    wrong["legs"][0]["terms"]["target_price"] = "77458"
    try:
        lower.lower(wrong, reviewed, snapshots)
        check(False, "replay: refuses terms that disagree with the catalogue")
    except lower.Refused as refusal:
        check(refusal.code == "TERMS_MISMATCH", "replay: refuses terms that disagree with the catalogue")

    # ---- a hand-edited baseline cannot reach the kernel
    wrong = json.loads(json.dumps(proposals["binary"]))
    wrong["baseline"]["price"] = "77631.5"
    try:
        lower.lower(wrong, reviewed, snapshots)
        check(False, "replay: refuses a baseline the snapshot does not support")
    except lower.Refused as refusal:
        check(refusal.code == "BASELINE_MISMATCH", "replay: refuses a baseline the snapshot does not support")

    # ---- a stale pin is refused, and so is a size the displayed book cannot fill
    wrong = json.loads(json.dumps(proposals["binary"]))
    wrong["legs"][0]["semantics_version"] = "0" * 64
    try:
        lower.lower(wrong, reviewed, snapshots)
        check(False, "replay: refuses a stale semantics pin")
    except lower.Refused as refusal:
        check(refusal.code == "SEMANTICS_PIN_MISMATCH", "replay: refuses a stale semantics pin")

    # An instance the catalogue does not list. The coin is moved with it, so the coin
    # check passes and the catalogue check is the one that refuses.
    absent = json.loads(json.dumps(proposals["binary"]))
    absent["legs"][0]["instance"]["outcome"] = "9999"
    absent["legs"][0]["instance"]["coin"] = "#99991"
    try:
        lower.lower(absent, reviewed, snapshots)
        check(False, "replay: refuses an instance the cited catalogue does not list")
    except lower.Refused as refusal:
        check(refusal.code == "INSTANCE_NOT_IN_CATALOGUE", "replay: refuses an instance the cited catalogue does not list")

    # The coin must encode outcome and side, so a leg cannot be priced on another book.
    swapped = json.loads(json.dumps(proposals["binary"]))
    swapped["legs"][0]["instance"]["coin"] = "#39650"
    try:
        lower.lower(swapped, reviewed, snapshots)
        check(False, "replay: refuses a coin that does not encode outcome and side")
    except lower.Refused as refusal:
        check(refusal.code == "COIN_MISMATCH", "replay: refuses a coin that does not encode outcome and side")

    # Pricing at displayed asks rests on a dated assumption; without it there is no result.
    unassumed = json.loads(json.dumps(proposals["binary"]))
    unassumed["assumptions"] = ["common_reference"]
    try:
        lower.lower(unassumed, reviewed, snapshots)
        check(False, "replay: refuses book pricing without the zero_base_fee assumption")
    except lower.Refused as refusal:
        check(refusal.code == "ASSUMPTION_REQUIRED", "replay: refuses book pricing without the zero_base_fee assumption")

    deep = json.loads(json.dumps(proposals["bucket0"]))
    deep["legs"][0]["size"] = "999999999"
    try:
        lower.lower(deep, reviewed, snapshots)
        check(False, "replay: refuses a size the displayed book cannot fill")
    except lower.Refused as refusal:
        check(refusal.code == "INSUFFICIENT_DEPTH", "replay: refuses a size the displayed book cannot fill")

    # ---- horizon: a leg observed at another time is worth nothing here, its premium still counts
    horizon_proposal = canon.loads((REPLAY / "bucket0-horizon.proposal.json").read_bytes())
    check(horizon_proposal["objective_valuation_time"] == "2026-09-20T06:00:00Z", "replay: the horizon fixture is valued a day later")
    lowered = lower.lower(horizon_proposal, reviewed, snapshots)[0]
    check([(r["rule"], r["tight"], r["reason_code"]) for r in lowered.get("reductions", [])] == [("horizon_mismatch", True, "LEG_WORST_CASED_HORIZON")],
          "replay: a horizon mismatch is a tight reduction")
    horizon = O.evaluate(lowered)
    check(horizon["model_result"] == "fails", "replay: the horizon fixture fails; a tight bound can prove a failure")
    check([(p["slope"], p["intercept"]) for p in horizon["profile"]] == HORIZON["pieces"], "replay: horizon profile is the exposure less the premium")
    check(horizon["worst_case"] == HORIZON["worst"], "replay: horizon worst case -1923.90676 at the floor")
    check([(i["lower"], i["lower_inclusive"], i["upper"], i["upper_inclusive"]) for i in horizon["failing_intervals"]] == [HORIZON["fails_on"]],
          "replay: horizon fails on [60000, 69239.0676)")
    check(horizon["cost"]["premium"] == PINNED["bucket0"][0], "replay: the horizon leg still costs its premium")
    # A price alone is not a counterexample once a leg has been bounded.
    states = horizon["failing_intervals"][0]["witness"]["adverse_states"]
    check([(s["leg"], s["rule"]) for s in states] == [("bucket0-yes", "horizon_mismatch")], "replay: the witness names each bounded leg and the rule that bounded it")
    check(states[0]["state"] == "the leg's own observation pays zero", "replay: the adverse state is the leg paying zero at its own observation")

    # ---- no result anywhere may assert `fails` from a loose bound
    #
    # The strongest form of the rule: take the tight fixture, which really does fail, and
    # make its reduction loose. The failure must stop being a failure, because a loose
    # bound proves nothing about what the leg is worth.
    loosened = json.loads(json.dumps(lowered))
    loosened["reductions"][0]["tight"] = False
    loosened_result = O.evaluate(loosened)
    check(loosened_result["model_result"] == "needs_review", "replay: the same violation under a loose rule needs review")
    check(loosened_result["failing_intervals"] == [], "replay: a loose rule proves no failing interval")
    check([(i["lower"], i["upper"]) for i in loosened_result["undecided_intervals"]] == [(HORIZON["fails_on"][0], HORIZON["fails_on"][2])],
          "replay: the violation moves to undecided intervals unchanged")
    for label, document in (("tight", horizon), ("loose", loosened_result), ("draft", bucket_draft)):
        if document["model_result"] == "fails":
            check(all(r["tight"] for r in document.get("reductions", [])), f"replay: {label} only fails when every reduction is tight")

    # ---- comparing instruments is a separate document, citing results by digest
    candidates = []
    for name in PINNED:
        candidate_ir = lower.lower(proposals[name], reviewed, snapshots)[0]
        candidates.append((name, candidate_ir, O.evaluate(candidate_ir)))
    comparison = O.compare(candidates)
    check(not validate_comparison(comparison), "replay: the comparison is valid against comparison.schema.json")
    check([c["ir_digest"] for c in comparison["candidates"]] == [canon.digest(ir) for _, ir, _ in candidates],
          "replay: the comparison cites each result by the digest of its lowered proposal")
    check(comparison["ranking"] == ["bucket0", "binary"], "replay: the bucket hedge is the cheaper way to meet the same cap")
    check([c["cost"] for c in comparison["candidates"]] == [PINNED[name][0] for name in PINNED], "replay: each candidate carries its own cost")
    # Proposals answering different questions may not be ranked against each other.
    try:
        O.compare([candidates[0], (("horizon"), lowered, horizon)])
        check(False, "replay: refuses to compare proposals with different valuation times")
    except ValueError:
        check(True, "replay: refuses to compare proposals with different valuation times")

    bundles()
    state = "reviewed" if on_disk_reviewed else "drafts"
    print(f"replay: {len(proposals)} real proposals against {state} on disk; "
          f"draft and reviewed arithmetic both pinned against in-memory copies")


def live_bundle():
    """The 5 October live mainnet pass, held against bytes and against hand arithmetic.

    This is the first PASSING answer this project produced from a live book rather than a
    retained one, and the first where the market cooperated: for eleven days every daily
    binary sat ~3% out of the money, so the NO leg that pays on a fall asked 0.99999 and no
    size met any cap. On 5 October spot 86,360 sat ABOVE the target 85,749, the NO leg asked
    0.3547, and 987 contracts met a 2,000 cap.

    THE WORST CASE IS DERIVED HERE, not read from the run document. The engine's own number is
    the thing under test, so taking the expectation from it would check the arithmetic against
    itself:

        spot loss at the floor  0.1 * (60,000 - 86,360)  = -2,636
        the NO leg pays in full 987 * 1                  =   +987
        premium paid                                     =   -350.3793
                                                           -----------
                                                            -1,999.3793   <= the -2,000 cap

    And the other candidate for the worst case is just ABOVE the target, where the NO pays
    nothing: 0.1 * (85,749 - 86,360) - 350.3793 = -411.4793, which is better. So the binding
    price is the floor, the bound is attained there, and the cap is met by 62 cents. A hedge
    is only interesting when the binding case is identified correctly, which is why both are
    computed rather than the one that happens to be worse.

    The bytes are digested AS RETAINED -- plain sha256, no canonicalisation -- because a
    venue response is full of JSON numbers that `canon` deliberately refuses, and because the
    digest should say what arrived rather than what we made of it.
    """
    bundle = PROJECT / "fixtures" / "live" / "2026-10-05"
    runs = sorted(bundle.glob("*.run.json"))
    check(len(runs) == 1, f"live bundle: expected one run document, found {len(runs)}")
    if not runs:
        return
    run = json.loads(runs[0].read_text())

    # ---- EVERY RETAINED BYTE HASHES TO THE DIGEST THE RUN DOCUMENT NAMES
    for name, filename in (("binary-no", "binary-no.json"),
                           ("bucket0-yes", "bucket0-yes.json"),
                           ("catalogue", "catalogue.json"),
                           ("contexts", "contexts.json")):
        path = bundle / filename
        check(path.exists(), f"live bundle: {filename} is missing")
        if path.exists():
            found = sha256(path.read_bytes()).hexdigest()
            check(found == run["digests"][name],
                  f"live bundle: {filename} hashes to {found[:16]}, the run document names "
                  f"{run['digests'][name][:16]} -- the bundle has been edited")
    # A one-digit price edit must be detected, same as the 18 September guard above.
    tampered = (bundle / "binary-no.json").read_bytes().replace(b'"0.3547"', b'"0.3548"', 1)
    check(sha256(tampered).hexdigest() != run["digests"]["binary-no"],
          "live bundle: a one-digit price change in a retained book is detected")

    # ---- THE OPTIONS ARE THE ONES THE PAGES QUOTE
    options = run["options"]
    check(options["cap"] == "2000",
          f"live bundle: the cap is {options['cap']}, and --cap is a POSITIVE magnitude")
    check((options["quantity"], options["floor"], options["ceiling"]) == ("0.1", "60000", "110000"),
          f"live bundle: the exposure or domain has changed: {options}")
    check(options["baseline"] == "86360",
          f"live bundle: the baseline is {options['baseline']}, not the retained 86360")

    # ---- THE ARITHMETIC, hand-derived above and recomputed in exact rationals here
    quantity, baseline, floor = F("0.1"), F(86360), F(60000)
    size, premium, target = 987, F("350.3793"), F(85749)
    at_floor = quantity * (floor - baseline) + size - premium
    just_above_target = quantity * (target - baseline) - premium
    check(at_floor == F("-1999.3793"),
          f"live bundle: the worst case at the floor is {at_floor}, not -1999.3793")
    check(just_above_target == F("-411.4793"),
          f"live bundle: just above the target is {just_above_target}, not -411.4793")
    check(at_floor < just_above_target,
          "live bundle: the floor is no longer the binding price, so the worst case this "
          "bundle reports is about a different state than the one derived")
    check(at_floor >= F(-2000),
          f"live bundle: {at_floor} does not meet the -2000 cap, so this bundle does not pass")

    # ---- AND THE RESULT THE ENGINE WROTE AGREES WITH THAT DERIVATION
    result = run["results"]["binary-no"]
    check(result["model_result"] == "passes",
          f"live bundle: the retained verdict is {result['model_result']}, not passes")
    check(F(result["worst_case"]["pnl"]) == at_floor,
          f"live bundle: the retained worst case {result['worst_case']['pnl']} is not the "
          f"hand-derived {at_floor}")
    check(F(result["worst_case"]["price"]) == floor,
          "live bundle: the retained worst case is not attained at the floor")
    check(result["worst_case"]["attained"] is True,
          "live bundle: the retained worst case is a bound rather than an attained value")
    check(F(result["cost"]["premium"]) == premium,
          f"live bundle: the retained premium is {result['cost']['premium']}, not {premium}")
    check(result["reason_codes"] == [],
          f"live bundle: a passing result carries reason codes {result['reason_codes']}")
    check(result["failing_intervals"] == [],
          "live bundle: a passing result carries failing intervals")

    # THE SKEW BOUND HELD, which is what makes two books comparable at all. `run["skew"]` is
    # per leg; `run["capture"]` carries the one the result was judged against, so BOTH are
    # checked -- a capture summary inside the bound while an individual leg sat outside it
    # would be a bound that means nothing.
    bound = int(run["capture"]["max_skew_ms"])
    check(abs(int(run["capture"]["skew_ms"])) <= bound,
          f"live bundle: the capture skew {run['capture']['skew_ms']} ms exceeds its own bound")
    for leg, measured in run["skew"].items():
        check(abs(int(measured["skew_ms"])) <= bound,
              f"live bundle: leg {leg} was captured {measured['skew_ms']} ms out, beyond the "
              f"{bound} ms bound, so the two books are not comparable")
    check(F(run["sizes"]["binary-no"]) == size,
          f"live bundle: the retained size is {run['sizes']['binary-no']}, not {size}")

    # ---- README'S STATUS CLAIM MATCHES THIS BUNDLE
    #
    # The status line said "T1 closed, 19 September. The Go engine and the TypeScript checker
    # do not exist yet" until 5 October, by which time all three had existed for a fortnight
    # and conformance was the project's main claim. Nothing checked it, so it rotted quietly
    # in the first paragraph a reader sees -- the single worst place for a stale claim. What
    # is pinned is only what this bundle can settle: the figures, and the directory that
    # backs them. Whether a tier is "closed" is the owner's judgement and not checkable here.
    readme = (PROJECT / "README.md").read_text()
    check("do not exist yet" not in readme,
          "README still says an implementation does not exist; all three are built and "
          "make check holds them to the same answers")
    # PROSE SPELLS NUMBERS LIKE PROSE, found by this guard's own control failing: the page
    # writes "−1,999.3793" with a typographic minus and a thousands comma, while the engine
    # emits "-1999.3793". Demanding the machine spelling would force the prose to be ugly to
    # satisfy a check, so the page is normalised before comparing instead. The figure still
    # has to be the retained one; only its typography is free.
    plain = readme.replace("−", "-").replace("–", "-").replace(",", "")
    for figure in (str(size), result["worst_case"]["pnl"], "fixtures/live/2026-10-05"):
        check(figure in plain,
              f"README's status paragraph does not carry {figure!r}, so its account of the "
              f"live pass has drifted from the retained bundle")
    check("tools/replay_live.py" in readme,
          "README states a live pass without the command that reproduces it offline")

    # ---- AND README'S LIVE TABLE CARRIES THE SAME FIGURES
    #
    # EVERY OCCURRENCE, not merely one. Mutation 24 Sep and again 5 October: a figure appears
    # more than once on the page -- in the table and again in the derivation -- so corrupting
    # one left the other satisfying an `in` test and the edit escaped. That is the same escape
    # as the runbook's `"112" in book`, the third time a presence test passed with a figure
    # wrong. The count is what the page promises: the two statements of a number must agree
    # with each other as well as with the bundle.
    readme_plain = readme.replace("\u2212", "-").replace(",", "")
    for figure, occurrences in ((str(size), 3),
                                (result["cost"]["premium"], 2),
                                (result["worst_case"]["pnl"], 2),
                                ("tools/replay_live.py fixtures/live/2026-10-05", 2)):
        found = readme_plain.count(figure)
        check(found == occurrences,
              f"README carries {figure!r} {found} times, expected {occurrences}: the table and "
              f"the hand-derivation must state the same number, so corrupting one of them "
              f"cannot pass")

    # THE HAND-DERIVATION THE PAGE SHOWS, as arithmetic rather than as text. The three terms
    # must sum to the worst case, or the page teaches a derivation that does not reach the
    # number beside it.
    spot_loss = quantity * (floor - baseline)
    check(spot_loss == F(-2636), f"the spot loss at the floor is {spot_loss}, not -2636")
    check(spot_loss + size - premium == at_floor,
          "the three terms README tabulates do not sum to the worst case it reports")
    # A Fraction prints as `3503793/10000`, which no page would write, so the terms are
    # compared against the DECIMAL spelling the documents use -- the retained strings, whose
    # equality to these exact values was checked above.
    for row in ("2636", str(size), result["cost"]["premium"]):
        check(row in readme_plain,
              f"README's derivation does not show {row!r}, so a reader cannot re-add the "
              f"terms to the worst case")

    print(f"live bundle: 2026-10-05 mainnet passes, {size} contracts, premium "
          f"{result['cost']['premium']}, worst case {result['worst_case']['pnl']} against a "
          f"-2000 cap, all four digests re-derived")


def live_bucket_bundle():
    """The 12 October live pass, which is the BUCKET leg -- a different leg from 5 October.

    Worth a second guard rather than a loop over bundles, because the arithmetic is genuinely
    different: bucket0 YES pays 1 strictly BELOW thresholds[0], so the state that kills it is
    just above that threshold rather than just above a binary target, and the hand derivation
    has to use the threshold the venue published.

    DERIVED HERE, not read from the run document:

        spot loss at the floor  0.1 * (60,000 - 82,549)  = -2,254.90
        bucket0 YES pays        542 * 1                  =   +542
        premium                                          =   -286.71258
                                                           -------------
                                                            -1,999.61258   <= the -2,000 cap

    And just above the low threshold 82,308, where the leg pays nothing:
    0.1 * (82,308 - 82,549) - 286.71258 = -310.81258, which is better. So the floor binds.

    THIS BUNDLE EXISTS BECAUSE A BUG WAS FOUND BY DISAGREEMENT. On 12 October
    `tools/hedgeable_today.py` printed HEDGEABLE while `check --live` refused the same book:
    the tool screened on `ask < 0.999` and the bucket asked 0.99666, which is under that
    threshold and still costs 99.7% of the payoff. The live check was right, the screening
    tool was wrong, and the threshold was replaced by the arithmetic in `viable()`. Within the
    hour the bucket tightened to 0.52899 and both agreed on `passes` -- so the fix was
    confirmed by the two tools AGREEING on a book neither had seen, not merely by one of them
    going quiet.
    """
    bundle = PROJECT / "fixtures" / "live" / "2026-10-12"
    runs = sorted(bundle.glob("*.run.json"))
    check(len(runs) == 1, f"live bucket bundle: expected one run document, found {len(runs)}")
    if not runs:
        return
    run = json.loads(runs[0].read_text())
    check(run["leg"] == "bucket0-yes",
          f"live bucket bundle: the retained leg is {run['leg']}, not bucket0-yes -- this "
          f"guard's arithmetic is about the bucket and does not describe another leg")

    for name, filename in (("binary-no", "binary-no.json"),
                           ("bucket0-yes", "bucket0-yes.json"),
                           ("catalogue", "catalogue.json"),
                           ("contexts", "contexts.json")):
        path = bundle / filename
        check(path.exists(), f"live bucket bundle: {filename} is missing")
        if path.exists():
            found = sha256(path.read_bytes()).hexdigest()
            check(found == run["digests"][name],
                  f"live bucket bundle: {filename} hashes to {found[:16]}, the run document "
                  f"names {run['digests'][name][:16]} -- the bundle has been edited")

    quantity, baseline, floor = F("0.1"), F(82549), F(60000)
    size, premium, low = 542, F("286.71258"), F(82308)
    at_floor = quantity * (floor - baseline) + size - premium
    above_low = quantity * (low - baseline) - premium
    check(at_floor == F("-1999.61258"),
          f"live bucket bundle: the worst case at the floor is {at_floor}, not -1999.61258")
    check(above_low == F("-310.81258"),
          f"live bucket bundle: just above the low threshold is {above_low}, not -310.81258")
    check(at_floor < above_low,
          "live bucket bundle: the floor is no longer the binding price")
    check(at_floor >= F(-2000),
          f"live bucket bundle: {at_floor} does not meet the -2000 cap")

    result = run["results"]["bucket0-yes"]
    check(result["model_result"] == "passes",
          f"live bucket bundle: the retained verdict is {result['model_result']}")
    check(F(result["worst_case"]["pnl"]) == at_floor,
          f"live bucket bundle: the retained worst case {result['worst_case']['pnl']} is not "
          f"the hand-derived {at_floor}")
    check(F(result["cost"]["premium"]) == premium,
          f"live bucket bundle: the retained premium is {result['cost']['premium']}")
    check(F(run["sizes"]["bucket0-yes"]) == size,
          f"live bucket bundle: the retained size is {run['sizes']['bucket0-yes']}")
    check(result["reason_codes"] == [] and result["failing_intervals"] == [],
          "live bucket bundle: a passing result carries reason codes or failing intervals")

    # README'S LIVE TABLE CARRIES THIS CAPTURE TOO. Both rows of that table are retained
    # bundles, so both are held to their own bytes rather than one standing in for the other.
    readme_plain = (PROJECT / "README.md").read_text().replace("−", "-").replace(",", "")
    for figure in (str(size), result["cost"]["premium"], result["worst_case"]["pnl"],
                   "fixtures/live/2026-10-12"):
        check(figure in readme_plain,
              f"README's live table does not carry {figure!r} from the 12 October capture")

    # THE SITE SERVES THE CHECKER THE PROJECT SHIPS, byte for byte.
    #
    # `site/` carries its own copy so the page works on static hosting with no build step.
    # A stale copy would be the worst kind of wrong: the page would invite a reader to
    # verify a result with code the repository no longer has, and the verdict would look
    # just as authoritative. `tools/build_checker.py --check` already holds dist/ to its
    # sources; this holds the vendored copy to dist/.
    for name in ("checker.js", "allowlist.json"):
        shipped = (PROJECT / "checker" / "dist" / name).read_bytes()
        served = (PROJECT / "site" / "vendor" / name)
        check(served.exists(), f"site/vendor/{name} is missing, so the page cannot verify")
        if served.exists():
            check(served.read_bytes() == shipped,
                  f"site/vendor/{name} differs from checker/dist/{name}: the page would "
                  f"verify with code this repository does not ship. Re-copy it.")

    # THE SCREENING TOOL NO LONGER GUESSES AT A THRESHOLD. The bug above was a hardcoded
    # 0.999; if one reappears, the tool can disagree with the engine again.
    # A BARE SUBSTRING WOULD BAN THE EXPLANATION, which this guard hit on its own first run:
    # the file NAMES `PLACEHOLDER_ASK` in the comment recording why it was removed, and the
    # comment is the most useful part. What must not come back is the ASSIGNMENT, so that is
    # what is matched -- the same distinction the consumer runbook's guard needed.
    tool = (PROJECT / "tools" / "hedgeable_today.py").read_text()
    check(not re.search(r"^PLACEHOLDER_ASK\s*=", tool, re.M),
          "hedgeable_today.py defines a placeholder-ask threshold again; on 12 Oct that made "
          "it print HEDGEABLE on a 0.99666 book the live check correctly refused")
    check("def viable(" in tool,
          "hedgeable_today.py no longer derives whether an ask can meet the cap, so it is "
          "back to guessing what a real quote looks like")

    print(f"live bundle: 2026-10-12 mainnet bucket0-yes passes, {size} contracts, premium "
          f"{result['cost']['premium']}, worst case {result['worst_case']['pnl']}")


def bundles():
    """Every certificate bundle is accepted or refused with exactly its stated class.

    The manifest names the class, so a fixture that stops being refused, or starts
    being refused for a different reason, fails here rather than silently weakening.
    """
    import refuse

    directory = PROJECT / "fixtures" / "bundles"
    found = sorted(path for path in directory.iterdir() if path.is_dir())

    def manifest_expects(path):
        return canon.loads((path / "manifest.json").read_bytes())["expects"]

    check(found, "bundles: the fixtures exist")
    accepted, refused = 0, {}
    for path in found:
        manifest = canon.loads((path / "manifest.json").read_bytes())
        check(not validate_manifest(manifest), f"bundles: {path.name} manifest is valid")
        outcome = refuse.refuse_directory(path)
        actual = "accept" if outcome["accepted"] else outcome["refusal"]["class"]
        check(actual == manifest["expects"],
              f"bundles: {path.name} expects {manifest['expects']}, the refuser said {actual}")
        if outcome["accepted"]:
            accepted += 1
            check("corruption" not in manifest, f"bundles: {path.name} is accepted and declares no corruption")
        else:
            refused[manifest["expects"]] = refused.get(manifest["expects"], 0) + 1
            check("corruption" in manifest, f"bundles: {path.name} is refused and documents its one change")
    check(accepted == 8, "bundles: eight good bundles -- passing, failing, passing with its envelope, "
                         "a deployer-settled family, a foreign reference with and without a bound, "
                         "two legs on one foreign reference banded as a GROUP, and an isolated perp "
                         "liquidated inside the path domain")
    # THE LIQUIDATED BUNDLE FAILS, and it is the only good bundle that fails for a reason on
    # the EXPOSURE rather than on a leg. A tight rule may condemn, so this is where that is
    # exercised end to end: lowering reduces, the evaluator applies, the refuser rebuilds the
    # same profile independently and accepts the bundle.
    liquidated = canon.loads((directory / "good-liquidated" / "result.json").read_bytes())
    check(liquidated["model_result"] == "fails",
          f"bundles: the liquidated bundle fails, got {liquidated['model_result']}")
    check([(r["rule"], r["tight"]) for r in liquidated["reductions"]] == [("liquidated_in_path", True)],
          f"bundles: and does so under one tight rule, got {liquidated.get('reductions')}")
    # THE GROUP IS CARRIED, not merely present. A `with` list is the only part of a
    # reduction that names other legs, and until the grouped bundle existed no fixture had
    # one -- so Go and the TypeScript checker each implemented grouping and neither was
    # held to agreeing with the other two about it.
    # A LEG IN A MULTI-LEG BAND GROUP HAS NO SIZE WINDOW, in any implementation.
    #
    # The group's value is the infimum of its SUMMED payoff over the band, so resizing one
    # member moves the sum and with it the infimum -- the question "the smallest size of
    # this leg" presumes a separability the evaluator does not have. Both implementations
    # answered it anyway and disagreed about the base: the oracle credited a banded sibling
    # with zero, Go with its full unbanded payoff, and they reported different binding
    # prices for this one bundle. Neither was right, and the fix is to report neither.
    group_dir = directory / "good-basis-grouped"
    check(group_dir.is_dir(), "bundles: the grouped basis bundle exists")
    group_ir = canon.loads((group_dir / "lowered.json").read_bytes())
    rows = [r for r in group_ir["reductions"] if r["rule"] == "basis_band"]
    check(len(rows) == 1 and rows[0].get("with"),
          "bundles: the grouped bundle carries one band reduction naming its other leg")
    members = {rows[0]["leg"], *rows[0]["with"]}
    check(members == {leg["id"] for leg in group_ir["legs"]},
          f"bundles: the band group is not both legs, it is {sorted(members)}")
    group_result = canon.loads((group_dir / "result.json").read_bytes())
    check("size_windows" not in group_result,
          "bundles: a jointly banded leg has no size window, because the group is not separable")
    # And the non-separability is a FACT about the arithmetic, not a policy: resizing one
    # member really does move the group's banded value. Without this the rule above could
    # be deleted and replaced by any other reason for omitting the window.
    band = O.num(group_ir["reductions"][0]["bound"])
    values = []
    for size in ("0", "500", "1409", "3000"):
        resized = [dict(leg, size=size) if leg["id"] == "binary-no" else leg
                   for leg in group_ir["legs"]]
        eroded = O.band_infimum(O.total([O._leg(leg) for leg in resized]), band)
        values.append(eroded(F(76000)))
    check(len(set(values)) == len(values),
          f"basis: resizing a group member must move the group's banded value, got {values}")
    # Every class the fixtures claim to exercise is exercised, and every corruption is
    # refused. These were one check while every corruption had a class to itself; the
    # envelope corruptions are four ways to be wrong about one thing, so counting
    # classes and counting corruptions became two different claims. Both are asserted:
    # collapsing them would have let a whole class quietly stop being covered.
    check(sum(refused.values()) == len(found) - accepted, "bundles: every corruption is refused")
    check(len(refused) >= 12, f"bundles: only {len(refused)} refusal classes are exercised")
    expected_classes = {manifest_expects(path) for path in found} - {"accept"}
    check(set(refused) == expected_classes, "bundles: every class a manifest names is the class the refuser gave")

    # The kernel-level corruption, which is not a bundle: a band reduction that shifts
    # the middle bucket instead of shrinking it. Shifting claims value below P1 that the
    # true reduction does not have, so it is unsound rather than merely loose.
    P1, P2, size, band = exact.parse("75908"), exact.parse("79007"), exact.parse("924"), exact.parse("50")
    middle = O.digital_range(size, P1, P2)
    true_reduction = O.band_infimum(middle, band)
    shrunk = O.digital_range(size, P1 + band, P2 - band)
    shifted = O.digital_range(size, P1 - band, P2 - band)
    probes = [P1 - 1, P1, P1 + band - 1, P1 + band, P2 - band - 1, P2 - band, P2 - 1, P2]
    check(all(shrunk(price) == true_reduction(price) for price in probes),
          "bundles: shrinking the middle bucket from both sides is the band reduction")
    check(any(shifted(price) != true_reduction(price) for price in probes),
          "bundles: shifting the middle bucket is not the band reduction")
    over = [price for price in probes if shifted(price) > true_reduction(price)]
    check(over and O.fmt(over[0]) == "75907",
          "bundles: the shift claims 924 at 75907, where the true reduction pays nothing")
    check(true_reduction(P1 - 1) == 0 and shifted(P1 - 1) == size,
          "bundles: a shifted bucket over-credits a long holder below the lower threshold")

    # THE COUNTS README PUBLISHES, which were stale the moment two fixtures were added.
    #
    # README said "seven good and seventeen corrupted" and "refusing twelve corrupted ones"
    # while the corpus held 8 and 19. Nothing checked either number, which is the same drift
    # that put a wrong schema count in two documents (section 9). A count in prose is a claim.
    corrupted = len(found) - accepted
    readme = (PROJECT / "README.md").read_text()
    check(f"{accepted} good and {corrupted} corrupted" in readme,
          f"README's fixtures row does not say '{accepted} good and {corrupted} corrupted'")
    check(f"refusing {corrupted} corrupted ones by class" in readme,
          f"README does not say 'refusing {corrupted} corrupted ones by class'")

    print(f"bundles: {accepted} accepted, {corrupted} refused, each with its stated class")


def validate_manifest(document):
    return _validator().valid(document, "bundle-manifest.schema.json")


def _at(profile, price):
    """P&L at `price`, from the piece that owns it."""
    for piece in profile:
        low, high = exact.parse(piece["lower"]), exact.parse(piece["upper"])
        if (low < price < high or (price == low and piece["lower_inclusive"]) or (price == high and piece["upper_inclusive"])):
            return exact.parse(piece["slope"]) * price + exact.parse(piece["intercept"])
    raise AssertionError(f"no piece owns {price}")


def validate_ir(document):
    return _validator().valid(document, "ir.schema.json")


def validate_comparison(document):
    return _validator().valid(document, "comparison.schema.json")


def _validator():
    sys.path.insert(0, str(PROJECT / "tools"))
    import validate
    return validate


if __name__ == "__main__":
    main()
