"""A reference refuser for certificate bundles. Standard library only.

**This is not the checker.** The checker is TypeScript, written separately in T3,
and sharing only the schemas. This exists for one narrow purpose: so that every
corrupted fixture is known to be refused, and refused for the stated reason,
before a second implementation is asked to agree.

It re-derives rather than re-reads. The bundle's `lowered` and `result` are
treated as claims: the proposal is lowered again from the bundle's own snapshots
and registry entries, evaluated again, and every claim compared. A comparison
that merely re-added the numbers the engine emitted would accept an engine that
omitted a strike, which is the whole point of PLAN section 5.

Witnesses get a stronger test than comparison. Each is evaluated on the
**unreduced** payoff at its own price and adverse states: a price alone is not a
counterexample once a leg has been bounded, so the witness has to be admissible
under the reduction it names.

Returns `accept`, or the first refusal class it finds. First, not all: a bundle
with two faults is refused by whichever the ordering reaches, and the ordering
runs cheapest and most fundamental first, so a corrupted byte is never reported
as a downstream arithmetic disagreement.
"""

from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import canon  # noqa: E402
import exact  # noqa: E402
import lower as lowering  # noqa: E402
import oracle as O  # noqa: E402


class Refusal(Exception):
    def __init__(self, klass, detail, at=None):
        super().__init__(f"{klass}: {detail}")
        self.klass = klass
        self.detail = detail
        self.at = at


def _refuse(klass, detail, at=None):
    raise Refusal(klass, detail, at)


def load(directory):
    """Read a bundle from disk. Nothing here interprets; that is `refuse`."""
    directory = Path(directory)
    manifest = canon.loads((directory / "manifest.json").read_bytes())
    files = manifest["files"]
    return {
        "directory": directory,
        "manifest": manifest,
        "proposal": canon.loads((directory / files["proposal"]).read_bytes()),
        "lowered": canon.loads((directory / files["lowered"]).read_bytes()),
        "result": canon.loads((directory / files["result"]).read_bytes()),
        "registry": {item["family"]: canon.loads((directory / item["path"]).read_bytes())
                     for item in files["registry"]},
        "snapshot_bytes": {item["sha256"]: (directory / item["path"]).read_bytes()
                           for item in files["snapshots"]},
    }


# --------------------------------------------------------------------------- evidence


def _check_snapshots(bundle):
    """Every stored snapshot hashes to the name it is stored under, and is cited."""
    for digest, raw in bundle["snapshot_bytes"].items():
        actual = sha256(raw).hexdigest()
        if actual != digest:
            _refuse("SNAPSHOT_BYTES", f"the file stored as {digest[:12]} hashes to {actual[:12]}", digest)
    cited = set(lowering._snapshots_cited(bundle["proposal"]))
    missing = cited - set(bundle["snapshot_bytes"])
    if missing:
        _refuse("SNAPSHOT_NOT_CITED", f"the proposal cites {sorted(missing)[0][:12]}, which the bundle does not carry")


def _check_pins(bundle):
    """Each leg pins the semantics of the entry the bundle carries."""
    for leg in bundle["proposal"]["legs"]:
        entry = bundle["registry"].get(leg["family"])
        if entry is None:
            _refuse("SEMANTICS_PIN", f"{leg['id']}: the bundle carries no entry for {leg['family']}", leg["id"])
        version = canon.semantics_version(entry)
        if leg["semantics_version"] != version:
            _refuse("SEMANTICS_PIN",
                    f"{leg['id']}: pins {leg['semantics_version'][:12]}, the bundle's entry is {version[:12]}", leg["id"])


# --------------------------------------------------------------------------- re-derivation


def _relower(bundle):
    """Lower the proposal again from the bundle's own evidence."""
    snapshots = {digest: json.loads(raw) for digest, raw in bundle["snapshot_bytes"].items()}
    try:
        return lowering.lower(bundle["proposal"], bundle["registry"], snapshots)
    except lowering.Refused as refused:
        mapped = {"TERMS_MISMATCH": "TERMS_MISMATCH", "BASELINE_MISMATCH": "TERMS_MISMATCH",
                  "SEMANTICS_PIN_MISMATCH": "SEMANTICS_PIN", "COIN_MISMATCH": "TERMS_MISMATCH",
                  "INSUFFICIENT_DEPTH": "COST_MISMATCH",
                  "SNAPSHOT_NOT_A_BOOK": "SNAPSHOT_NOT_CITED"}.get(refused.code, "ENGINE_DISAGREES")
        _refuse(mapped, f"the proposal does not lower: {refused.detail}")


def _check_costs(bundle, lowered):
    """Re-walk the book bytes; the claimed total must be what the walk costs."""
    claimed = {leg["id"]: leg["premium"] for leg in bundle["lowered"]["legs"]}
    for leg in lowered["legs"]:
        mine, theirs = leg["premium"], claimed.get(leg["id"])
        if theirs is None:
            _refuse("ENGINE_DISAGREES", f"the bundle's lowered proposal has no leg {leg['id']}", leg["id"])
        if mine["kind"] != theirs["kind"]:
            _refuse("COST_MISMATCH", f"{leg['id']}: cost kind {theirs['kind']!r}, re-derived {mine['kind']!r}", leg["id"])
        if mine["kind"] == "walked":
            if exact.parse(mine["total"]) != exact.parse(theirs["total"]):
                _refuse("COST_MISMATCH",
                        f"{leg['id']}: claims {theirs['total']}, the book walks to {mine['total']}", leg["id"])
            if mine["snapshot"] != theirs["snapshot"]:
                _refuse("COST_MISMATCH", f"{leg['id']}: cites a different book than the one walked", leg["id"])
        elif exact.parse(mine["price"]) != exact.parse(theirs["price"]):
            _refuse("COST_MISMATCH", f"{leg['id']}: claims {theirs['price']}, re-derived {mine['price']}", leg["id"])


def _check_objective(bundle, lowered):
    """The lowered objective, domain and baseline are the proposal's own."""
    claimed = bundle["lowered"]
    for key in ("objective", "domain", "objective_valuation_time"):
        if canon.canonical(claimed[key]) != canon.canonical(lowered[key]):
            _refuse("OBJECTIVE_MISMATCH", f"the lowered {key} is not the proposal's {key}", key)
    if exact.parse(claimed["baseline"]["price"]) != exact.parse(lowered["baseline"]["price"]):
        _refuse("OBJECTIVE_MISMATCH", "the lowered baseline is not the one the snapshot supports", "baseline")
    if canon.canonical(bundle["result"]["objective_valuation_time"]) != canon.canonical(lowered["objective_valuation_time"]):
        _refuse("OBJECTIVE_MISMATCH", "the result is stated for another valuation time", "result")


# --------------------------------------------------------------------------- the profile


def _payoff(lowered, include_reduced):
    """The combined payoff. With `include_reduced`, no leg is bounded away.

    A BAND reduction is banded, not zeroed. Every other reduction worst-cases its leg to
    zero; a declared basis bound says more -- the group is worth the infimum of its SUMMED
    payoff over the band. Zeroing it here would make this refuser reject the very bundles
    the lowering it checks produces, which is how the difference was found.
    """
    baseline = exact.parse(lowered["baseline"]["price"])
    reductions = lowered.get("reductions", [])
    premium = sum((O.leg_cost(leg) for leg in lowered["legs"]), F(0))
    # A LIQUIDATED EXPOSURE IS WORTH MINUS ITS MARGIN, at every terminal price. With the
    # liquidation price inside the path domain the path may reach it, and reaching it closes
    # the position permanently -- so the exposure stops being a function of the terminal price.
    # Rebuilding it as linear here would make this refuser reject the very bundles the
    # lowering it checks produces, which is how the band difference above was found.
    liquidated = any(reduction["rule"] == "liquidated_in_path" for reduction in reductions)
    if liquidated:
        holding = O.cash(-exact.parse(lowered["exposure"]["isolated_margin"]))
    else:
        holding = O.linear(exact.parse(lowered["exposure"]["quantity"]), baseline)
    parts = [holding, O.cash(-premium - exact.parse(lowered["other_costs"]))]

    banded = set()
    if not include_reduced:
        for reduction in reductions:
            if reduction["rule"] != "basis_band":
                continue
            members = set([reduction["leg"]] + list(reduction.get("with", [])))
            banded |= members
            group = [O._leg(leg) for leg in lowered["legs"] if leg["id"] in members]
            parts.append(O.band_infimum(O.total(group), exact.parse(reduction["bound"])))
    zeroed = {reduction["leg"] for reduction in reductions} - banded

    for leg in lowered["legs"]:
        if include_reduced or (leg["id"] not in zeroed and leg["id"] not in banded):
            parts.append(O._leg(leg))
    return O.total(parts)


def _check_profile(bundle, lowered):
    """Coverage, ownership and values, derived rather than re-added.

    Coverage is checked first because a missing piece is what an engine that
    omitted a strike would produce, and a value comparison alone would not see it.
    """
    claimed = bundle["result"]["profile"]
    mine = [O.text_interval(piece) for piece in O.profile(_payoff(lowered, False),
                                                         exact.parse(lowered["domain"]["lower"]),
                                                         exact.parse(lowered["domain"]["upper"]))]
    low = exact.parse(lowered["domain"]["lower"])
    high = exact.parse(lowered["domain"]["upper"])

    if not claimed:
        _refuse("PROFILE_COVERAGE", "the profile is empty", "profile")
    if exact.parse(claimed[0]["lower"]) != low or not claimed[0]["lower_inclusive"]:
        _refuse("PROFILE_COVERAGE", f"the profile starts at {claimed[0]['lower']}, the domain at {lowered['domain']['lower']}", "profile")
    if exact.parse(claimed[-1]["upper"]) != high or not claimed[-1]["upper_inclusive"]:
        _refuse("PROFILE_COVERAGE", f"the profile ends at {claimed[-1]['upper']}, the domain at {lowered['domain']['upper']}", "profile")
    for left, right in zip(claimed, claimed[1:]):
        if exact.parse(left["upper"]) != exact.parse(right["lower"]):
            _refuse("PROFILE_COVERAGE", f"a gap between {left['upper']} and {right['lower']}", "profile")
        if left["upper_inclusive"] == right["lower_inclusive"]:
            side = "both" if left["upper_inclusive"] else "neither"
            _refuse("ENDPOINT_OWNERSHIP", f"{side} piece owns {left['upper']}", left["upper"])

    # Every breakpoint the payoff actually has must appear in the claimed profile.
    mine_edges = {exact.parse(piece["upper"]) for piece in mine[:-1]}
    claimed_edges = {exact.parse(piece["upper"]) for piece in claimed[:-1]}
    if mine_edges - claimed_edges:
        missing = sorted(mine_edges - claimed_edges)[0]
        _refuse("PROFILE_COVERAGE", f"the profile has no piece boundary at {exact.format(missing)}", exact.format(missing))
    if claimed_edges - mine_edges:
        extra = sorted(claimed_edges - mine_edges)[0]
        _refuse("PROFILE_VALUE", f"the profile claims a boundary at {exact.format(extra)} that the payoff does not have", exact.format(extra))

    # Ownership at each strike, then the affine value on each claimed piece.
    payoff = _payoff(lowered, False)
    for piece in claimed:
        slope, intercept = exact.parse(piece["slope"]), exact.parse(piece["intercept"])
        for price, owned in ((exact.parse(piece["lower"]), piece["lower_inclusive"]),
                             (exact.parse(piece["upper"]), piece["upper_inclusive"])):
            if owned and payoff(price) != slope * price + intercept:
                _refuse("ENDPOINT_OWNERSHIP",
                        f"the piece owning {exact.format(price)} gives {exact.format(slope * price + intercept)}, "
                        f"the payoff gives {exact.format(payoff(price))}", exact.format(price))
        inside = (exact.parse(piece["lower"]) + exact.parse(piece["upper"])) / 2
        if payoff(inside) != slope * inside + intercept:
            _refuse("PROFILE_VALUE", f"the piece on [{piece['lower']}, {piece['upper']}] does not match the payoff", piece["lower"])


# --------------------------------------------------------------------------- verdict and witnesses


def _check_reductions(bundle, lowered):
    """Each reduction is declared with its reason code, and is sound as claimed."""
    claimed = bundle["result"].get("reductions", [])
    mine = lowered.get("reductions", [])
    if canon.canonical(claimed) != canon.canonical(mine):
        if len(claimed) != len(mine):
            _refuse("REDUCTION_UNDECLARED", f"the result declares {len(claimed)} reductions, lowering derives {len(mine)}", "reductions")
        for theirs, ours in zip(claimed, mine):
            if theirs.get("reason_code") != ours["reason_code"]:
                _refuse("REDUCTION_UNDECLARED",
                        f"{ours['leg']}: reduced by {ours['rule']} without its reason code {ours['reason_code']}", ours["leg"])
            if theirs.get("tight") != ours["tight"]:
                _refuse("REDUCTION_UNSOUND",
                        f"{ours['leg']}: {ours['rule']} is declared tight={theirs.get('tight')}, it is tight={ours['tight']}", ours["leg"])
        _refuse("REDUCTION_UNDECLARED", "the declared reductions are not the ones lowering derives", "reductions")
    for reduction in claimed:
        if "reason_code" not in reduction:
            _refuse("REDUCTION_UNDECLARED", f"{reduction['leg']}: a reduction without its reason code", reduction["leg"])


def _check_verdict(bundle, result):
    claimed = bundle["result"]["model_result"]
    if claimed != result["model_result"]:
        _refuse("VERDICT_MISMATCH", f"the bundle says {claimed}, re-evaluation says {result['model_result']}", "model_result")
    # A loose reduction may never produce a proven failure, whatever the bundle says.
    loose = {r["leg"] for r in bundle["result"].get("reductions", []) if not r.get("tight", True)}
    if loose and claimed == "fails" and bundle["result"]["failing_intervals"]:
        _refuse("REDUCTION_UNSOUND", f"fails on a loose bound from {sorted(loose)[0]}", "model_result")


def _check_intervals(bundle, result):
    for key in ("failing_intervals", "undecided_intervals"):
        claimed, mine = bundle["result"].get(key, []), result.get(key, [])
        if len(claimed) != len(mine):
            _refuse("INTERVAL_MISMATCH", f"{key}: the bundle has {len(claimed)}, re-evaluation {len(mine)}", key)
        for theirs, ours in zip(claimed, mine):
            for field in ("lower", "upper"):
                if exact.parse(theirs[field]) != exact.parse(ours[field]):
                    _refuse("INTERVAL_MISMATCH",
                            f"{key}: {field} is {theirs[field]}, re-evaluation gives {ours[field]}", theirs[field])
            for field in ("lower_inclusive", "upper_inclusive"):
                if theirs[field] != ours[field]:
                    _refuse("INTERVAL_MISMATCH", f"{key}: {field} at {theirs['lower']} disagrees", theirs["lower"])


def _check_witnesses(bundle, lowered):
    """Evaluate each witness on the UNREDUCED payoff at its price and adverse states.

    This is the test a comparison cannot do. A witness that names no adverse state
    must violate the clause on the payoff as written; one that names a reduction
    must be admissible under it, which for the rules here means the reduced leg
    really can pay zero at that price.
    """
    reduced = _payoff(lowered, False)
    unreduced = _payoff(lowered, True)
    declared = {reduction["leg"]: reduction for reduction in lowered.get("reductions", [])}
    cap = min(exact.parse(clause["min_pnl"]) for clause in lowered["objective"])

    for interval in bundle["result"].get("failing_intervals", []):
        witness = interval["witness"]
        price = exact.parse(witness["price"])
        if exact.parse(witness["pnl"]) != reduced(price):
            _refuse("WITNESS_INADMISSIBLE",
                    f"the witness at {witness['price']} claims {witness['pnl']}, the payoff gives {exact.format(reduced(price))}",
                    witness["price"])
        states = witness.get("adverse_states", [])
        for state in states:
            if state["leg"] not in declared:
                _refuse("WITNESS_INADMISSIBLE",
                        f"the witness names an adverse state for {state['leg']}, which was not reduced", witness["price"])
            if state["rule"] != declared.get(state["leg"], {}).get("rule"):
                _refuse("WITNESS_INADMISSIBLE",
                        f"the witness names rule {state['rule']!r} for {state['leg']}, which was reduced by "
                        f"{declared.get(state['leg'], {}).get('rule')!r}", witness["price"])
        if not states and unreduced(price) > cap:
            # No leg was bounded, so the price alone must breach the clause.
            _refuse("WITNESS_INADMISSIBLE",
                    f"the witness at {witness['price']} does not breach the objective on the payoff as written",
                    witness["price"])
        if states and len(states) != len(declared):
            _refuse("WITNESS_INADMISSIBLE",
                    f"the witness names {len(states)} adverse states, {len(declared)} legs were reduced", witness["price"])


def _check_size_windows(bundle, lowered):
    """Re-derive each window; a smallest size must be the smallest that passes."""
    claimed = {window["leg"]: window for window in bundle["result"].get("size_windows", [])}
    if not claimed:
        return
    lower = exact.parse(lowered["domain"]["lower"])
    upper = exact.parse(lowered["domain"]["upper"])
    cap = min(exact.parse(clause["min_pnl"]) for clause in lowered["objective"])
    for leg in lowered["legs"]:
        window = claimed.get(leg["id"])
        if window is None:
            continue
        for site in window.get("binding", []):
            if site["side"] not in ("at", "above", "below"):
                _refuse("SIZE_WINDOW", f"{leg['id']}: a binding site that is not at, above or below", leg["id"])
        certificate = window.get("certificate")
        if certificate:
            weights = [exact.parse(weight) for weight in certificate["weights"]]
            if any(weight < 0 for weight in weights):
                _refuse("CERTIFICATE_WEIGHTS",
                        f"{leg['id']}: an infeasibility certificate with a negative weight", leg["id"])
            if sum(weights) != 1:
                _refuse("CERTIFICATE_WEIGHTS", f"{leg['id']}: the weights do not sum to one", leg["id"])
        if "smallest" not in window:
            continue
        # The claimed smallest must pass, and one contract fewer must not.
        smallest = exact.parse(window["smallest"])
        for size, must_pass in ((smallest, True), (smallest - 1, False)):
            if size <= 0:
                continue
            probe = json.loads(json.dumps(lowered))
            for candidate in probe["legs"]:
                if candidate["id"] == leg["id"]:
                    candidate["size"] = exact.format(size)
                    if candidate["premium"]["kind"] == "walked":
                        levels = [(exact.parse(price), exact.parse(available))
                                  for price, available in candidate["premium"]["levels"]]
                        cost = O.ask_cost(levels, size)
                        if cost is None:
                            break
                        candidate["premium"]["total"] = exact.format(cost)
            else:
                passes = not O.below(_payoff(probe, False), cap, lower, upper)
                if passes != must_pass:
                    _refuse("SIZE_WINDOW",
                            f"{leg['id']}: size {exact.format(size)} "
                            f"{'does not pass' if must_pass else 'passes'}, so {window['smallest']} is not the smallest",
                            leg["id"])


# --------------------------------------------------------------------------- entry point


def _check_envelope(bundle, lowered):
    """The order envelope, against a walk of the book bytes done here.

    `lowered` is what this refuser re-derived from the proposal, so the levels and the
    size come from the evidence rather than from the result being checked. The coin
    comes from the proposal, because the lowered form does not carry an instance id.

    The envelope is what turns a bound into an order, so it is checked after the
    verdict it depends on: an envelope on a result whose verdict is already wrong
    should be reported as the wrong verdict.
    """
    result = bundle["result"]
    envelope = result.get("order_envelope")
    present = envelope is not None
    if present != (result.get("execution_readiness") == "envelope_issued"):
        _refuse("ENVELOPE_MISMATCH",
                f"execution_readiness is {result.get('execution_readiness')!r} "
                f"and an envelope is {'present' if present else 'absent'}",
                "execution_readiness")
    if not present:
        return

    if result["model_result"] != "passes":
        _refuse("ENVELOPE_MISMATCH", f"an envelope on a {result['model_result']}", "order_envelope")
    if len(lowered["legs"]) != 1:
        _refuse("ENVELOPE_MISMATCH",
                f"the proposal has {len(lowered['legs'])} legs; an envelope describes one order",
                "order_envelope")
    leg, priced = bundle["proposal"]["legs"][0], lowered["legs"][0]
    if priced["premium"]["kind"] != "walked":
        _refuse("ENVELOPE_MISMATCH", "the leg is not priced on a book", "order_envelope")

    if envelope["coin"] != leg["instance"]["coin"]:
        _refuse("ENVELOPE_MISMATCH",
                f"the envelope names {envelope['coin']}, the proposal names {leg['instance']['coin']}",
                "order_envelope.coin")
    if envelope["side"] != "buy":
        _refuse("ENVELOPE_MISMATCH", f"side is {envelope['side']!r}", "order_envelope.side")
    if envelope["time_in_force"] != "Ioc":
        _refuse("ENVELOPE_MISMATCH", f"time in force is {envelope['time_in_force']!r}",
                "order_envelope.time_in_force")

    size = exact.parse(priced["size"])
    if exact.parse(envelope["size"]) != size:
        _refuse("ENVELOPE_MISMATCH",
                f"the envelope buys {envelope['size']}, the proposal asks for {priced['size']}",
                "order_envelope.size")

    remaining, cost, limit = size, exact.parse("0"), None
    for price_text, available in priced["premium"]["levels"]:
        if remaining == 0:
            break
        fill = min(remaining, exact.parse(available))
        if fill > 0:
            limit = price_text
        cost += fill * exact.parse(price_text)
        remaining -= fill
    if remaining != 0 or limit is None:
        _refuse("ENVELOPE_MISMATCH", "the depth does not fill the size", "order_envelope")
    if exact.parse(envelope["limit_price"]) != exact.parse(limit):
        _refuse("ENVELOPE_MISMATCH",
                f"the envelope says {envelope['limit_price']}, the walk ends in {limit}",
                "order_envelope.limit_price")
    if exact.parse(envelope["max_cost"]) != cost:
        _refuse("ENVELOPE_MISMATCH",
                f"the envelope says {envelope['max_cost']}, the walk costs {exact.format(cost)}",
                "order_envelope.max_cost")

    stated = result.get("input_digest")
    if not stated:
        _refuse("ENVELOPE_MISMATCH",
                "an envelope was issued for a result that does not name its input digest", "input_digest")
    if envelope["input_digest"] != stated:
        _refuse("ENVELOPE_MISMATCH",
                f"the envelope belongs to {envelope['input_digest'][:12]}, the result is {stated[:12]}",
                "order_envelope.input_digest")


def refuse(bundle):
    """accept, or the first refusal class found. Ordered cheapest and most fundamental first."""
    try:
        _check_snapshots(bundle)
        _check_pins(bundle)
        lowered, _versions = _relower(bundle)
        # The objective is checked before anything derived from it. A loosened cap
        # changes the size window too, and reporting that as SIZE_WINDOW would name
        # a symptom rather than the fault.
        _check_objective(bundle, lowered)
        _check_costs(bundle, lowered)
        result = O.evaluate(lowered)
        _check_reductions(bundle, lowered)
        _check_profile(bundle, lowered)
        _check_verdict(bundle, result)
        _check_intervals(bundle, result)
        _check_witnesses(bundle, lowered)
        _check_size_windows(bundle, lowered)
        _check_envelope(bundle, lowered)
    except Refusal as refusal:
        out = {"accepted": False, "refusal": {"class": refusal.klass, "detail": refusal.detail}}
        if refusal.at:
            out["refusal"]["at"] = str(refusal.at)
        return out
    return {"accepted": True}


def refuse_directory(directory):
    return refuse(load(directory))
