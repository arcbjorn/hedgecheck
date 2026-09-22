"""Generate lowered proposals and the oracle's results, for Go to reproduce.

    python3 tools/make_ir_cases.py          # regenerate, then check
    python3 tools/make_ir_cases.py --check  # fail if anything on disk is stale

Where the kernel cases test one query at a time, these test a whole result: verdict,
witnesses, profile, cost, comparisons, size windows, reductions. Every field the two
implementations must agree on, on proposals neither author chose by hand.

The generator is the same explicit LCG the kernel cases use, so the corpus is fixed by
this source and moves only when this source does.
"""

from fractions import Fraction as F
import json
from pathlib import Path
import shutil
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "oracle"))
sys.path.insert(0, str(PROJECT / "tools"))

import canon  # noqa: E402
import exact  # noqa: E402
import oracle as O  # noqa: E402

from make_kernel_cases import Rand  # noqa: E402

OUT = PROJECT / "fixtures" / "generated" / "ir"
COUNT = 320

UNITS = {"money": "USDC", "price": "USDC per BTC", "exposure": "BTC", "size": "contracts"}
PRICES = [60000, 65000, 70000, 75908, 77457, 80000, 85000, 90000, 100000, 105000, 110000]


def q(value):
    """Canonical text for a number. str(Fraction) is not it: 19/50 vs 0.38."""
    return O.fmt(F(value))


def ladder(rng):
    """A displayed-depth ladder: rising prices, sometimes with an equal or empty rung."""
    # An outcome token pays at most 1, so every displayed ask lies in (0, 1).
    # Retained books hold prices from 0.00001 to 0.99999 (EVIDENCE section 4).
    rungs, price = [], F(1 + rng.below(50), 100)
    for _ in range(1 + rng.below(4)):
        size = rng.pick([0, 100, 500, 1200, 3000, 100000])
        rungs.append([q(price), q(size)])
        if rng.below(4) == 0:
            pass  # repeat the same price: equal-priced rungs are a real shape
        else:
            price = price + F(1 + rng.below(20), 100)
        if price >= 1:
            price = F(99999, 100000)
    rungs.append([q(F(99999, 100000)), "100000"])
    return rungs


def walked_cost(rng, size, rungs):
    """The exact total for `size` along the rungs, or None when depth runs out."""
    levels = [(exact.parse(p), exact.parse(s)) for p, s in rungs]
    cost = O.ask_cost(levels, exact.parse(q(size)))
    if cost is None:
        return None
    return {"kind": "walked", "total": O.fmt(cost), "path": "direct_book",
            "snapshot": "a" * 64, "levels": rungs}


def indicator_leg(rng, index, observation):
    """One indicator leg with random ownership, priced fixed or walked."""
    size = rng.pick([0, 1, 100, 924, 1409, 2000])
    shape = rng.below(3)
    pays_on = {}
    if shape != 0:
        pays_on["upper"] = q(rng.pick(PRICES))
        pays_on["upper_inclusive"] = rng.below(2) == 0
    if shape != 1:
        lower = rng.pick(PRICES)
        if "upper" in pays_on and F(lower) > F(pays_on["upper"]):
            lower, pays_on["upper"] = int(pays_on["upper"]), str(lower)
        pays_on["lower"] = q(lower)
        pays_on["lower_inclusive"] = rng.below(2) == 0
    if not pays_on:
        pays_on = {"upper": q(rng.pick(PRICES)), "upper_inclusive": False}
    if "lower" in pays_on and "upper" in pays_on and pays_on["lower"] == pays_on["upper"]:
        pays_on["lower_inclusive"] = True
        pays_on["upper_inclusive"] = True

    leg = {"id": f"leg-{index}", "kind": "indicator", "size": q(size), "pays_on": pays_on,
           "observation_time": observation, "semantics": "b" * 64}
    if rng.below(2) == 0:
        leg["premium"] = {"kind": "fixed", "price": q(rng.rational(0, 1, denominators=(100, 8)))}
    else:
        rungs = ladder(rng)
        cost = walked_cost(rng, size, rungs)
        if cost is None:
            leg["premium"] = {"kind": "fixed", "price": "0.5"}
        else:
            leg["premium"] = cost
    return leg


def build_case(rng, index):
    baseline_price = rng.pick(PRICES)
    lower = 60000
    upper = 110000
    valuation = "2026-09-19T06:00:00Z"
    observation = valuation
    legs = []
    for leg_index in range(1 + rng.below(4)):
        # Some legs are observed at another time, which lowering reduces.
        leg_observation = valuation
        if rng.below(6) == 0:
            leg_observation = "2026-09-20T06:00:00Z"
        legs.append(indicator_leg(rng, leg_index, leg_observation))

    clauses = []
    for clause_index in range(1 + rng.below(3)):
        clause = {"id": f"clause_{clause_index}", "min_pnl": q(-rng.pick([500, 1000, 2000, 4000, 8000, 20000]))}
        if rng.below(4) == 0:
            low = rng.pick(PRICES[:6])
            high = rng.pick([p for p in PRICES if p > low] or [110000])
            clause["on"] = {"lower": q(low), "lower_inclusive": True,
                            "upper": q(high), "upper_inclusive": rng.below(2) == 0}
        clauses.append(clause)

    lowered = {
        "schema_version": "1",
        "units": UNITS,
        "domain": {"lower": q(lower), "upper": q(upper)},
        "baseline": {"kind": "explicit", "price": q(baseline_price), "label": "generated"},
        "exposure": {"kind": "linear", "quantity": q(rng.pick([0, F(1, 10), F(1, 4), 1]))},
        "legs": legs,
        "objective": clauses,
        "objective_valuation_time": valuation,
        "other_costs": q(rng.pick([0, 5, 25])),
        "assumptions": ["common_reference"],
    }

    # Reductions: a horizon-reduced leg, and sometimes an unreviewed one.
    reductions = []
    for leg in legs:
        if leg["observation_time"] != valuation:
            reductions.append({"leg": leg["id"], "rule": "horizon_mismatch", "tight": True,
                               "reason_code": "LEG_WORST_CASED_HORIZON"})
        elif rng.below(3) == 0:
            reductions.append({"leg": leg["id"], "rule": "unreviewed_family", "tight": False,
                               "reason_code": "UNREVIEWED_FAMILY"})
    if reductions:
        lowered["reductions"] = reductions
    return lowered


def generate():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    rng = Rand(20260920)
    written = 0
    verdicts = {}
    index = 0
    while written < COUNT:
        lowered = build_case(rng, index)
        index += 1
        try:
            result = O.evaluate(lowered)
        except Exception:
            # A generated shape the oracle refuses is not a case; the generator is not
            # the specification and does not get to invent supported inputs.
            continue
        name = f"case-{written:04d}"
        (OUT / f"{name}.ir.json").write_bytes(canon.canonical(lowered) + b"\n")
        (OUT / f"{name}.result.json").write_bytes(canon.canonical(result) + b"\n")
        verdicts[result["model_result"]] = verdicts.get(result["model_result"], 0) + 1
        written += 1
    return written, verdicts


def main():
    checking = "--check" in sys.argv
    written, verdicts = generate()
    if checking:
        # REPRODUCIBLE, not merely present. The corpus is derived and is not in git, so
        # "does the checkout match?" has no answer on a fresh clone -- `before` would be
        # empty and every file would read as stale. What still has to hold is that the
        # generator is a function of its source alone: run it twice, get the same bytes.
        # A corpus that moved between two runs of one unchanged program would mean an
        # unseeded draw or a dict iteration leaking into the output, which is the failure
        # this gate exists to catch.
        first = {path.name: path.read_bytes() for path in sorted(OUT.glob("*.json"))}
        generate()
        second = {path.name: path.read_bytes() for path in sorted(OUT.glob("*.json"))}
        if first != second:
            moved = sorted({name for name in set(first) | set(second) if first.get(name) != second.get(name)})
            print(f"generated IR cases are not reproducible: {', '.join(moved[:3])}", file=sys.stderr)
            return 1
    summary = ", ".join(f"{count} {verdict}" for verdict, count in sorted(verdicts.items()))
    print(f"{written} lowered proposals with the oracle's results: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
