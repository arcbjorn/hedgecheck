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

    # ---- on disk the entries are drafts, so the replay refuses rather than answering
    unreviewed = []
    for name, proposal in proposals.items():
        try:
            lower.lower(proposal, registry, snapshots)
        except lower.Refused as refusal:
            check(refusal.code == "UNREVIEWED_FAMILY", f"replay: {name} refuses an unreviewed family")
            unreviewed.append(name)
    check(len(unreviewed) == len(proposals), "replay: every on-disk entry is still a draft")

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

    print(f"replay: {len(proposals)} real proposals refused as drafts on disk; "
          f"pinned values verified against in-memory reviewed copies")


def _at(profile, price):
    """P&L at `price`, from the piece that owns it."""
    for piece in profile:
        low, high = exact.parse(piece["lower"]), exact.parse(piece["upper"])
        if (low < price < high or (price == low and piece["lower_inclusive"]) or (price == high and piece["upper_inclusive"])):
            return exact.parse(piece["slope"]) * price + exact.parse(piece["intercept"])
    raise AssertionError(f"no piece owns {price}")


def validate_ir(document):
    sys.path.insert(0, str(PROJECT / "tools"))
    import validate
    return validate.valid(document, "ir.schema.json")


if __name__ == "__main__":
    main()
