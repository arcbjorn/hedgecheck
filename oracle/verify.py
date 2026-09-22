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

    reference_map()
    basis_band()
    replay()

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


def reference_map():
    """A venue's free text resolves to a canonical id, or to nothing it can name."""
    import lower

    document = canon.loads((PROJECT / "references" / "reference-map.json").read_bytes())
    index = lower.reference_index(document)
    mappings = document["mappings"]
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

    # Ambiguity is the COMMON case, and each ambiguous row says why.
    counts = {}
    for o in described:
        terms = O_terms(o)
        counts[(o["venue"], terms["priceDescription"], terms.get("seconds", ""))] = \
            counts.get((o["venue"], terms["priceDescription"], terms.get("seconds", "")), 0) + 1
    ambiguous = [m for m in mappings if m["state"] == "ambiguous"]
    instances = sum(counts[(m["venue"], m["price_description"], m["seconds"])] for m in ambiguous)
    check((len(ambiguous), instances) == (6, 61),
          f"reference map: 6 ambiguous descriptions over 61 instances, found {len(ambiguous)} over {instances}")
    check(all(m.get("why") for m in mappings), "reference map: every mapping says why")
    check(all(m.get("reference") for m in mappings if m["state"] != "ambiguous"),
          "reference map: a non-ambiguous mapping names a reference")


def O_terms(outcome):
    """The catalogue's `key:value|...` description, as a dict."""
    return dict(part.split(":", 1) for part in outcome.get("description", "").split("|") if ":" in part)


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
    check(accepted == 6, "bundles: six good bundles -- passing, failing, passing with its envelope, "
                         "a deployer-settled family, and a foreign reference with and without a bound")
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

    print(f"bundles: {accepted} accepted, {len(found) - accepted} refused, each with its stated class")


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
