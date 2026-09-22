"""Generate synthesis answers and one corruption per refusal class.

    python3 tools/make_synthesis.py          # regenerate, then check
    python3 tools/make_synthesis.py --check  # fail if the generator is not reproducible

The good answers are the oracle's own, on questions with hand-derived expectations in
oracle/verify.py. The corruptions are one change each, so a checker that refuses one says
which thing it caught: a certificate that does not cancel the sizes is a different fault
from sizes that miss the floor, and a test that cannot tell them apart is not testing
either.

DERIVED. Not in git; `make generated` writes it. The gate is reproducibility, because
"does the checkout match?" has no answer on a fresh clone.
"""

import copy
from pathlib import Path
import shutil
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "oracle"))
sys.path.insert(0, str(PROJECT / "tools"))

import canon  # noqa: E402
import oracle as O  # noqa: E402

OUT = PROJECT / "fixtures" / "synthesis"

UNITS = {"money": "USDC", "price": "USDC per BTC", "exposure": "BTC", "size": "contracts"}
SPOT = {"id": "spot", "kind": "linear", "quantity": "0.1", "baseline": "100000"}
PUT90 = {"id": "put-90k", "pays_on": {"upper": "90000", "upper_inclusive": False}, "price": "0.2"}
PUT80 = {"id": "put-80k", "pays_on": {"upper": "80000", "upper_inclusive": False}, "price": "0.1"}


def request(min_pnl, candidates=None, base=None, lot="1"):
    return {
        "schema_version": "1",
        "objective": {"id": "loss_cap", "min_pnl": min_pnl},
        "domain": {"lower": "60000", "upper": "110000"},
        "units": dict(UNITS),
        "base": [dict(SPOT)] if base is None else base,
        "candidates": [dict(PUT90)] if candidates is None else candidates,
        "lot": lot,
    }


def at(document, path, value):
    """One change, deep-copied. `value` of None deletes."""
    out = copy.deepcopy(document)
    target = out
    for key in path[:-1]:
        target = target[key]
    if value is None:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return out


def cases():
    # ---- the good answers: the three statuses, and a two-candidate mixture
    infeasible = O.synthesis_document(request("-1000"))
    feasible = O.synthesis_document(request("-3333"))
    rounded = O.synthesis_document(request("-3333", lot="15000"))
    mixed = O.synthesis_document(request("-2000", candidates=[dict(PUT90), dict(PUT80)]))
    # A base that JUMPS: a position already held. Its value just below the strike differs
    # from its value at it, so the `below` row's alpha is a LIMIT rather than a point value.
    # Without such a case a checker reading the point value for every side passes -- the
    # base is continuous in every other fixture here, and a linear base always is.
    held = O.synthesis_document(request("-3333", base=[
        dict(SPOT),
        {"id": "owned", "kind": "indicator", "size": "500",
         "pays_on": {"upper": "85000", "upper_inclusive": False}},
    ]))
    assert infeasible["status"] == "infeasible", infeasible["status"]
    assert feasible["status"] == "feasible", feasible["status"]
    assert rounded["status"] == "rounding_failed", rounded["status"]
    assert mixed["status"] == "feasible", mixed["status"]

    good = [
        ("good-infeasible", "accept", infeasible,
         "the PLAN section 3 example: no size meets a -1,000 cap, with the certificate", None),
        ("good-feasible", "accept", feasible,
         "834 contracts meets a -3,333 cap, the smallest whole number that does", None),
        ("good-rounding-failed", "accept", rounded,
         "a lot of 15,000 overshoots so far that the premium breaks the cap", None),
        ("good-mixed", "accept", mixed,
         "two candidates, and the answer is a mixture no single instrument can match", None),
        ("good-held-position", "accept", held,
         "a base that jumps at 85,000, so a limit row's alpha differs from the point value", None),
    ]

    # A `detail` is a substring the refusal's own message must contain. It is there for the
    # faults the CLASS cannot distinguish: an unknown certificate site and a certificate that
    # proves nothing are both CERTIFICATE_WEIGHTS, and a checker that silently ignored an
    # unknown site would still refuse the first -- by the later b.y test, for the wrong
    # reason. Asserting the class alone cannot tell those apart.
    corrupted = [
        # ---- sizes that do not meet the objective
        ("size-one-fewer", "SIZE_WINDOW",
         at(feasible, ["sizes", 0, "size"], "833"),
         "one contract fewer, which is worth -3,333.6 against a -3,333 cap",
         "misses the floor"),
        ("size-zero", "SIZE_WINDOW",
         at(feasible, ["sizes", 0, "size"], "0"),
         "no protection at all, reported as meeting the cap",
         "misses the floor"),
        ("size-not-a-whole-lot", "SIZE_WINDOW",
         at(at(feasible, ["request", "lot"], "100"), ["sizes", 0, "size"], "834"),
         "a size that is not a multiple of the lot it claims to be rounded to",
         "not a whole multiple"),
        ("size-names-wrong-candidate", "SIZE_WINDOW",
         at(mixed, ["sizes", 0, "candidate"], "put-80k"),
         "a size naming the other candidate, so it is checked against the wrong payoff",
         "names put-80k"),
        # ---- the cost must be what the sizes cost
        ("cost-understated", "COST_MISMATCH",
         at(feasible, ["cost"], "100"),
         "a cost lower than the sizes cost at the request's own prices",
         "states 100"),
        ("cost-missing", "COST_MISMATCH",
         at(feasible, ["cost"], None),
         "a feasible answer that does not say what it costs",
         "does not say what it costs"),
        # ---- the certificate
        ("certificate-weight-negated", "CERTIFICATE_WEIGHTS",
         at(infeasible, ["certificate", "weights", 0, "weight"], "-1"),
         "a negative weight, which proves nothing about a non-negative program",
         "not strictly positive"),
        ("certificate-site-invented", "CERTIFICATE_WEIGHTS",
         at(infeasible, ["certificate", "weights", 0, "price"], "70000"),
         "a weight on a site that is not a row of this program",
         "not a row of this program"),
        ("certificate-does-not-cancel", "CERTIFICATE_WEIGHTS",
         at(infeasible, ["certificate", "weights"],
            [dict(infeasible["certificate"]["weights"][0])]),
         "one row alone, which is satisfiable, so the weights do not cancel the sizes",
         "do not cancel"),
        ("certificate-side-swapped", "CERTIFICATE_WEIGHTS",
         at(infeasible, ["certificate", "weights", 0, "side"], "below"),
         "a weight moved to the other constraint at the same price",
         None),
        # THE ONE THAT NEEDS THE b.y TEST. These two rows have net coefficient -0.2 each, so
        # A^T y = -0.4 <= 0 and the cancellation test passes -- but their right-hand sides are
        # 0 and -2,000, so b.y = -2,000 and the weights prove nothing. Without this case the
        # b.y test can be deleted and every other certificate fixture still refuses, because
        # they all fail the cancellation test first.
        ("certificate-cancels-but-proves-nothing", "CERTIFICATE_WEIGHTS",
         at(infeasible, ["certificate", "weights"],
            [{"price": "90000", "side": "at", "weight": "1"},
             {"price": "110000", "side": "at", "weight": "1"}]),
         "weights that cancel the sizes but sum to nothing positive",
         "b . y is -2000"),
        # A ZERO WEIGHT says nothing about its row, so carrying one is a claim with no
        # content -- and a certificate padded with zeros could name every site while proving
        # nothing. Refused rather than ignored: silently dropping it would accept a document
        # the schema's own `minItems` was meant to make meaningful.
        ("certificate-zero-weight", "CERTIFICATE_WEIGHTS",
         at(infeasible, ["certificate", "weights", 0, "weight"], "0"),
         "a zero weight, which is a claim about a row with no content",
         "not strictly positive"),
        # ONE SITE, TWICE. Weighting a row twice is either a mistake or an attempt to make a
        # certificate look larger than it is; either way the second entry is not a row of the
        # program, which has one constraint per site.
        ("certificate-site-twice", "CERTIFICATE_WEIGHTS",
         at(infeasible, ["certificate", "weights"],
            [dict(infeasible["certificate"]["weights"][0]),
             dict(infeasible["certificate"]["weights"][0])]),
         "the same site weighted twice",
         "twice"),
        # A NEGATIVE SIZE is not a position anyone can take. It would also let the program
        # write protection it never bought, which is not what was asked.
        ("size-negative", "SIZE_WINDOW",
         at(feasible, ["sizes", 0, "size"], "-834"),
         "a negative size, which is not a position that can be taken",
         "negative size"),

        # ---- a refused rounding claims nothing
        ("rounding-failed-with-sizes", "VERDICT_MISMATCH",
         at(rounded, ["sizes"], [{"candidate": "put-90k", "size": "15000"}]),
         "a refused rounding reporting sizes it did not establish",
         None),
    ]
    return good + corrupted


def generated_questions(count=120):
    """Questions nobody chose: the same explicit LCG the kernel cases use.

    The five hand-written cases above are good questions, but they are questions I thought
    to ask. These are not: random baselines, strikes, prices, floors and lots, so the three
    implementations are held to agreeing on programs none of their authors saw. The
    generator is a function of this source alone, so the corpus moves only when this does.
    """
    from make_kernel_cases import Rand
    rng = Rand(20260922)
    out = []
    written = 0
    index = 0
    while written < count:
        index += 1
        baseline = rng.pick([70000, 77631, 85000, 100000])
        quantity = rng.pick(["0.1", "-0.1", "0.05", "0.2"])
        strikes = sorted({rng.pick([65000, 70000, 75908, 80000, 85000, 90000, 100000])
                          for _ in range(1 + rng.below(2))})
        candidates = []
        for position, strike in enumerate(strikes):
            side = rng.below(2)
            pays_on = ({"upper": str(strike), "upper_inclusive": False} if side == 0
                       else {"lower": str(strike), "lower_inclusive": True})
            candidates.append({"id": f"c{position}", "pays_on": pays_on,
                               "price": rng.pick(["0.1", "0.2", "0.5", "0.05"])})
        base = [{"id": "spot", "kind": "linear", "quantity": quantity, "baseline": str(baseline)}]
        if rng.below(3) == 0:
            base.append({"id": "paid", "kind": "cash", "amount": rng.pick(["-500", "-100", "250"])})
        if rng.below(3) == 0:
            base.append({"id": "owned", "kind": "indicator", "size": rng.pick(["200", "500"]),
                         "pays_on": {"upper": str(rng.pick([75000, 85000])), "upper_inclusive": False}})
        question = {
            "schema_version": "1",
            "objective": {"id": "loss_cap",
                          "min_pnl": str(-rng.pick([500, 1000, 2000, 3333, 5000]))},
            "domain": {"lower": "60000", "upper": "110000"},
            "units": dict(UNITS),
            "base": base,
            "candidates": candidates,
            "lot": rng.pick(["1", "1", "1", "100"]),
        }
        try:
            answer = O.synthesis_document(question)
        except Exception:
            # A shape the oracle refuses is not a question; the generator does not get to
            # invent supported inputs.
            continue
        if answer["status"] == "unbounded":
            continue
        out.append((f"case-{written:04d}", "accept", answer,
                    f"a generated question the oracle answered {answer['status']}", None))
        written += 1
    return out


def generate():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    written = 0
    for name, expects, document, why, detail in cases() + generated_questions():
        (OUT / f"{name}.json").write_bytes(canon.canonical(document) + b"\n")
        lines = [expects, why]
        if detail is not None:
            lines.append(detail)
        (OUT / f"{name}.expects").write_text("\n".join(lines) + "\n")
        written += 1
    return written


def main():
    checking = "--check" in sys.argv
    written = generate()
    if checking:
        # REPRODUCIBLE, not merely present. The assertion that carries the weight is in
        # checker/test/synthesis.test.ts and oracle/verify.py: each document is accepted, or
        # refused with exactly the class it names.
        def snapshot():
            return {path.name: path.read_bytes() for path in sorted(OUT.iterdir())}
        first = snapshot()
        generate()
        if first != snapshot():
            print("synthesis fixtures are not reproducible", file=sys.stderr)
            return 1
    every = cases() + generated_questions()
    accepted = sum(1 for _, expects, _, _, _ in every if expects == "accept")
    written = len(every)
    print(f"{written} synthesis answers: {accepted} accepted, {written - accepted} corrupted, "
          f"each one a documented change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
