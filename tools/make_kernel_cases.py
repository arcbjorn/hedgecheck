"""Generate kernel agreement cases: the oracle's exact answers, for Go to reproduce.

    python3 tools/make_kernel_cases.py          # regenerate, then check
    python3 tools/make_kernel_cases.py --check  # fail if the file on disk is stale

Each case describes a function in the lowered-proposal vocabulary, so Go builds it
through its own constructors rather than reading pieces the oracle computed. That is
the point: two implementations are asked the same question, not handed the same answer.

Randomness is an explicit 64-bit LCG written here, not `random`. Python's Mersenne
stream is stable across versions but its float and shuffle helpers are not contractual,
and a fixture that changed with the interpreter would be worse than no fixture.
"""

from fractions import Fraction as F
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "oracle"))

import exact  # noqa: E402
import oracle as O  # noqa: E402

OUT = PROJECT / "fixtures" / "kernel" / "cases.json"


class Rand:
    """A 64-bit linear congruential generator, spelled out so the file never moves.

    Knuth's MMIX constants. Every draw below is derived from `next()` by integer
    arithmetic alone, so the sequence is fixed by this source and nothing else.
    """

    def __init__(self, seed):
        self.state = seed & ((1 << 64) - 1)

    def next(self):
        self.state = (self.state * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        return self.state >> 11

    def below(self, bound):
        return self.next() % bound

    def pick(self, options):
        return options[self.below(len(options))]

    def rational(self, lo, hi, denominators=(1, 2, 4, 5, 8, 100, 3, 7, 11)):
        """A rational in [lo, hi], sometimes non-terminating as a decimal."""
        den = self.pick(denominators)
        span = (hi - lo) * den
        return F(lo * den + self.below(int(span) + 1), den)


# --------------------------------------------------------------------------- functions
#
# A function is described as legs the Go side builds with its own constructors.


def leg_linear(rng, prices):
    return {"kind": "linear", "quantity": str(rng.rational(0, 2)), "baseline": str(rng.pick(prices))}


def leg_cash(rng):
    return {"kind": "cash", "amount": str(rng.rational(-2000, 2000))}


def leg_indicator(rng, prices):
    lo_kind = rng.below(3)
    out = {"kind": "indicator", "size": str(rng.rational(0, 2000))}
    if lo_kind != 0:
        out["lower"] = str(rng.pick(prices))
        out["lower_inclusive"] = rng.below(2) == 0
    if lo_kind != 1:
        upper = rng.pick(prices)
        if "lower" in out and F(upper) < F(out["lower"]):
            out["lower"], upper = str(upper), out["lower"]
        out["upper"] = str(upper)
        out["upper_inclusive"] = rng.below(2) == 0
    if "lower" not in out and "upper" not in out:
        out["upper"] = str(rng.pick(prices))
        out["upper_inclusive"] = False
    # An interval that contains no price is not a leg. Equal bounds are only a leg when
    # both ends own the point, which is the singleton case the kernel does support.
    if "lower" in out and "upper" in out and F(out["lower"]) == F(out["upper"]):
        out["lower_inclusive"] = True
        out["upper_inclusive"] = True
    return out


def leg_ramp(rng, prices):
    low = rng.pick(prices)
    high = low + rng.pick([1000, 5000, 10000])
    return {"kind": rng.pick(["ramp_long", "ramp_short"]), "size": str(rng.rational(0, 1000)),
            "low": str(low), "high": str(high)}


def build(legs):
    """The oracle's function for a described leg list."""
    parts = []
    for leg in legs:
        kind = leg["kind"]
        if kind == "linear":
            parts.append(O.linear(exact.parse(leg["quantity"]), exact.parse(leg["baseline"])))
        elif kind == "cash":
            parts.append(O.cash(exact.parse(leg["amount"])))
        elif kind == "indicator":
            parts.append(O.indicator(
                exact.parse(leg["size"]),
                lower=exact.parse(leg["lower"]) if "lower" in leg else None,
                lower_inclusive=leg.get("lower_inclusive", True),
                upper=exact.parse(leg["upper"]) if "upper" in leg else None,
                upper_inclusive=leg.get("upper_inclusive", False)))
        elif kind == "ramp_long":
            parts.append(O.ramp_long(exact.parse(leg["size"]), exact.parse(leg["low"]), exact.parse(leg["high"])))
        elif kind == "ramp_short":
            parts.append(O.ramp_short(exact.parse(leg["size"]), exact.parse(leg["low"]), exact.parse(leg["high"])))
        else:
            raise AssertionError(f"unknown leg kind {kind}")
    return O.total(parts)


# --------------------------------------------------------------------------- queries


def answer_profile(fn, lower, upper):
    return [{"lower": O.fmt(p["lower"]), "lower_inclusive": p["lower_inclusive"],
             "upper": O.fmt(p["upper"]), "upper_inclusive": p["upper_inclusive"],
             "slope": O.fmt(p["slope"]), "intercept": O.fmt(p["intercept"])}
            for p in O.profile(fn, lower, upper)]


def answer_infimum(fn, lower, upper):
    value, attained, at = O.infimum(fn, lower, upper)
    return {"value": O.fmt(value), "attained": attained, "at": O.fmt(at)}


def answer_below(fn, threshold, lower, upper, cuts):
    return [{"lower": O.fmt(i["lower"]), "lower_inclusive": i["lower_inclusive"],
             "upper": O.fmt(i["upper"]), "upper_inclusive": i["upper_inclusive"]}
            for i in O.below(fn, threshold, lower, upper, cuts)]


def answer_witness(fn, threshold, lower, upper):
    out = []
    for interval in O.below(fn, threshold, lower, upper):
        point = O.witness(fn, interval)
        out.append({"price": O.fmt(point["price"]), "pnl": O.fmt(point["pnl"])})
    return out


def answer_band(fn, band, probes):
    reduced = O.band_infimum(fn, band)
    return [{"at": O.fmt(p), "value": O.fmt(reduced(p))} for p in probes]


def answer_ask_cost(levels, size):
    cost = O.ask_cost([(exact.parse(p), exact.parse(s)) for p, s in levels], exact.parse(size))
    return {"covered": cost is not None, "total": O.fmt(cost) if cost is not None else None}


def answer_size_window(base, unit, levels, floor_pnl, lower, upper):
    window = O.size_window(base, unit, [(exact.parse(p), exact.parse(s)) for p, s in levels],
                           floor_pnl, lower, upper)
    out = {"status": window["status"],
           "binding": [{"price": O.fmt(site[0]), "side": site[1]} for site in window["binding"] if site]}
    if window["lower_bound"] is not None:
        out["lower_bound"] = O.fmt(window["lower_bound"])
        out["upper_bound"] = O.fmt(window["upper_bound"])
    if window.get("smallest") is not None:
        out["smallest"] = O.fmt(window["smallest"])
        out["largest"] = O.fmt(window["largest"])
    return out


# --------------------------------------------------------------------------- shapes
#
# The forced shapes come first, each named, so a reader can see the hard cases are
# present rather than hoping the generator happened to produce them.


def forced_cases():
    out = []

    def case(name, legs, query, **extra):
        out.append(dict({"name": name, "legs": legs, "query": query}, **extra))

    K, L, U = "90000", "60000", "110000"
    # Several legs sharing one breakpoint: the sum must not lose it.
    shared = [{"kind": "linear", "quantity": "0.1", "baseline": "100000"},
              {"kind": "indicator", "size": "500", "upper": K, "upper_inclusive": False},
              {"kind": "indicator", "size": "300", "upper": K, "upper_inclusive": False},
              {"kind": "cash", "amount": "-200"}]
    case("shared-breakpoint", shared, "profile", lower=L, upper=U)
    case("shared-breakpoint-infimum", shared, "infimum", lower=L, upper=U)

    # A breakpoint exactly on each domain end.
    case("breakpoint-at-lower", [{"kind": "indicator", "size": "700", "upper": L, "upper_inclusive": True}],
         "profile", lower=L, upper=U)
    case("breakpoint-at-upper", [{"kind": "indicator", "size": "700", "lower": U, "lower_inclusive": True}],
         "profile", lower=L, upper=U)

    # A strike owned by neither side: the deployer reading.
    unowned = [{"kind": "indicator", "size": "700", "upper": K, "upper_inclusive": False},
               {"kind": "indicator", "size": "700", "lower": K, "lower_inclusive": False}]
    case("unowned-strike", unowned, "profile", lower=L, upper=U)
    case("unowned-strike-below", unowned, "below", threshold="350", lower=L, upper=U, cuts=[])

    # Flat pieces, including the shape that broke the oracle's infimum.
    flat = [{"kind": "indicator", "size": "700", "upper": K, "upper_inclusive": True},
            {"kind": "cash", "amount": "-100"}]
    case("flat-open-piece-infimum", flat, "infimum", lower=L, upper=U)
    case("flat-open-piece-witness", flat, "witness", threshold="0", lower=L, upper=U)

    # A threshold exactly equal to a piece's value: strictness decides the answer.
    case("threshold-equals-value", [{"kind": "cash", "amount": "-1000"}],
         "below", threshold="-1000", lower=L, upper=U, cuts=[])
    case("threshold-just-below", [{"kind": "cash", "amount": "-1000"}],
         "below", threshold="-999.99999", lower=L, upper=U, cuts=[])

    # Band zero is the identity; a wide band makes a bucket vanish.
    bucket = [{"kind": "indicator", "size": "924", "lower": "75908", "lower_inclusive": True,
               "upper": "79007", "upper_inclusive": False}]
    case("band-zero", bucket, "band", band="0", probes=["75907", "75908", "77000", "79007"])
    case("band-shrinks-bucket", bucket, "band", band="50",
         probes=["75907", "75908", "75957", "75958", "78956", "78957", "79006"])
    case("band-vanishes-bucket", bucket, "band", band="2000",
         probes=["75908", "77000", "77457", "79006"])

    # Non-terminating rationals and long numbers.
    case("non-terminating", [{"kind": "linear", "quantity": "1/3", "baseline": "100000"},
                             {"kind": "cash", "amount": "1/7"}], "profile", lower=L, upper=U)
    big = "1" + "0" * 39
    case("forty-digit", [{"kind": "cash", "amount": big}], "infimum", lower=L, upper=U)
    case("forty-digit-linear", [{"kind": "linear", "quantity": "1/" + big, "baseline": "100000"}],
         "profile", lower=L, upper=U)

    # Ladders: equal prices, a zero size, and depth that cannot fill.
    case("levels-equal-prices", [], "ask_cost",
         levels=[["0.5", "100"], ["0.5", "100"], ["0.5", "100"]], size="250")
    case("levels-zero-size", [], "ask_cost",
         levels=[["0.4", "0"], ["0.5", "100"]], size="50")
    case("levels-insufficient", [], "ask_cost",
         levels=[["0.4", "10"]], size="50")

    # Size windows: empty, single size, and the retained bucket ladder.
    flat_ladder = [["0.2", "1000000000"]]
    case("window-empty", [], "size_window", base_legs=[{"kind": "linear", "quantity": "0.1", "baseline": "100000"}],
         unit_legs=[{"kind": "indicator", "size": "1", "upper": K, "upper_inclusive": False}],
         levels=flat_ladder, floor_pnl="-1000", lower=L, upper=U)
    case("window-bucket-ladder", [], "size_window",
         base_legs=[{"kind": "linear", "quantity": "0.1", "baseline": "77631.4"}],
         unit_legs=[{"kind": "indicator", "size": "1", "upper": "75908", "upper_inclusive": False}],
         levels=[["0.17399", "1200"], ["0.174", "1200"], ["0.99999", "100000"]],
         floor_pnl="-1000", lower=L, upper=U)
    case("window-single-size", [], "size_window",
         base_legs=[{"kind": "linear", "quantity": "0.1", "baseline": "100000"}],
         unit_legs=[{"kind": "indicator", "size": "1", "upper": K, "upper_inclusive": False}],
         levels=[["0.5", "3400"], ["0.99", "100000"]], floor_pnl="-3300", lower=L, upper=U)
    return out


def random_ladder(rng):
    """An ask ladder: non-decreasing prices in (0, 1), with sizes that may be zero.

    Prices are bounded by one because an outcome token pays at most one. A ladder
    that is not sorted is not a book, so the prices are sorted here rather than left
    to chance: the question is whether the two implementations walk the same book the
    same way, not whether they both reject nonsense.
    """
    prices = sorted(rng.rational(0, 1) for _ in range(1 + rng.below(5)))
    return [[str(price), str(rng.rational(0, 3000))] for price in prices]


def random_cases(rng, count):
    prices = [60000, 65000, 70000, 75908, 77457, 80000, 90000, 100000, 105000, 110000]
    out = []
    while len(out) < count:
        index = len(out)
        legs = []
        for _ in range(1 + rng.below(4)):
            pick = rng.below(10)
            if pick < 2:
                legs.append(leg_linear(rng, prices))
            elif pick < 4:
                legs.append(leg_cash(rng))
            elif pick < 9:
                legs.append(leg_indicator(rng, prices))
            else:
                legs.append(leg_ramp(rng, prices))
        # Sizing is in this pool because it is where the money is: an earlier
        # session found legs being sized against their FULL value rather than their
        # reduced one, and only one of seven hand-written cases caught it. A query
        # exercised by three fixtures is a query nobody is really checking.
        query = rng.pick(["profile", "infimum", "below", "witness", "band",
                          "size_window", "ask_cost"])
        case = {"name": f"random-{index:04d}", "legs": legs, "query": query,
                "lower": "60000", "upper": "110000"}
        if query in ("size_window", "ask_cost"):
            case["levels"] = random_ladder(rng)
        if query == "ask_cost":
            # No legs: a ladder walk is about the book alone.
            case["legs"] = []
            case["size"] = str(rng.rational(0, 5000))
        if query == "size_window":
            # A base the holder already has, and one contract of the thing bought.
            case["legs"] = []
            case["base_legs"] = [leg_linear(rng, prices)]
            unit = {"kind": "indicator", "size": "1"}
            if rng.below(2) == 0:
                unit["upper"] = str(rng.pick(prices))
                unit["upper_inclusive"] = rng.below(2) == 0
            else:
                unit["lower"] = str(rng.pick(prices))
                unit["lower_inclusive"] = rng.below(2) == 0
            case["unit_legs"] = [unit]
            case["floor_pnl"] = str(rng.rational(-6000, 0))
        if query in ("below", "witness"):
            case["threshold"] = str(rng.rational(-4000, 1000))
            if query == "below":
                case["cuts"] = [str(rng.pick(prices))] if rng.below(3) == 0 else []
        if query == "band":
            case["band"] = str(rng.pick([0, 1, 50, 250, 2000]))
            case["probes"] = [str(rng.pick(prices) + rng.below(3) - 1) for _ in range(4)]
        out.append(case)
    return out


def answer(case):
    query = case["query"]
    if query in ("ask_cost",):
        return answer_ask_cost(case["levels"], case["size"])
    if query == "size_window":
        base, unit = build(case["base_legs"]), build(case["unit_legs"])
        return answer_size_window(base, unit, case["levels"], exact.parse(case["floor_pnl"]),
                                  exact.parse(case["lower"]), exact.parse(case["upper"]))
    fn = build(case["legs"])
    lower, upper = exact.parse(case["lower"]), exact.parse(case["upper"])
    if query == "profile":
        return answer_profile(fn, lower, upper)
    if query == "infimum":
        return answer_infimum(fn, lower, upper)
    if query == "below":
        return answer_below(fn, exact.parse(case["threshold"]), lower, upper,
                            [exact.parse(c) for c in case.get("cuts", [])])
    if query == "witness":
        return answer_witness(fn, exact.parse(case["threshold"]), lower, upper)
    if query == "band":
        return answer_band(fn, exact.parse(case["band"]), [exact.parse(p) for p in case["probes"]])
    raise AssertionError(f"unknown query {query}")


def generate():
    cases = forced_cases()
    for case in cases:
        case.setdefault("lower", "60000")
        case.setdefault("upper", "110000")
    cases += random_cases(Rand(20260920), 400 - len(cases))
    for case in cases:
        case["answer"] = answer(case)
    return {"note": "Generated by tools/make_kernel_cases.py. The oracle's exact answers; Go must agree.",
            "cases": cases}


def main():
    document = generate()
    text = json.dumps(document, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("fixtures/kernel/cases.json is stale; run python3 tools/make_kernel_cases.py", file=sys.stderr)
            return 1
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text)
    kinds = {}
    for case in document["cases"]:
        kinds[case["query"]] = kinds.get(case["query"], 0) + 1
    print(f"{len(document['cases'])} kernel cases: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
