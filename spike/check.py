"""Build, size, lower and evaluate the candidate proposals. Pure.

Snapshot bytes in, results out. Nothing here fetches anything: the same function
serves a live run and a replay, which is what makes the two byte-identical.
"""

from fractions import Fraction as F
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "oracle"))

import canon  # noqa: E402
import exact  # noqa: E402
import lower as lowering  # noqa: E402
import oracle as O  # noqa: E402

import discover  # noqa: E402

SCHEMA_VERSION = "1"
UNITS = {"money": "USDC", "price": "USDC per BTC", "exposure": "BTC", "size": "contracts"}


class Unusable(Exception):
    """The captured set cannot answer the question that was asked."""


def read_mark(contexts, coin):
    """The mark price for one perp, from the contexts response."""
    universe, states = contexts[0]["universe"], contexts[1]
    for index, asset in enumerate(universe):
        if asset["name"] == coin:
            return exact.parse(states[index]["markPx"])
    raise Unusable(f"{coin} is not in the contexts snapshot")


def asks(book):
    """Displayed asks, exact, in book order. levels[0] is bids, levels[1] is asks."""
    return [(exact.parse(level["px"]), exact.parse(level["sz"])) for level in book["levels"][1]]


def smallest_passing_size(leg, book, quantity, baseline, cap, floor, ceiling, strike):
    """The smallest whole-contract size of this leg that meets the cap on this book.

    None when no size on the displayed book does. The window is computed from the
    same levels the walk would pay, so a size that appears here is a size the
    displayed book covers.
    """
    base = O.linear(quantity, baseline)
    unit = O.digital_below(F(1), strike)
    window = O.size_window(base, unit, asks(book), -cap, floor, ceiling)
    if window["status"] != "nonempty":
        return None, window
    return window["smallest"], window


def build_proposal(leg, size, digests, quantity, baseline, baseline_kind, cap,
                   floor, ceiling, valuation_time, observation_time, semantics_version,
                   capture=None):
    """One proposal, in terms of families and instances, citing snapshots by hash."""
    terms = dict(leg["terms"], expiry=observation_time)
    baseline_block = {"kind": baseline_kind, "price": exact.format(baseline)}
    if baseline_kind == "analysis_time":
        baseline_block["source"] = {"snapshot": digests["contexts"], "coin": leg["terms"]["underlying"]}
    else:
        baseline_block["label"] = "operator-supplied"
    out = {
        "schema_version": SCHEMA_VERSION,
        "units": UNITS,
        "domain": {"lower": exact.format(floor), "upper": exact.format(ceiling)},
        "baseline": baseline_block,
        "exposure": {"kind": "linear_spot", "underlying": leg["terms"]["underlying"],
                     "quantity": exact.format(quantity), "reference": "hl:perp:BTC:mark-interp"},
        "legs": [{
            "id": leg["id"],
            "family": leg["family"],
            "semantics_version": semantics_version,
            "side": leg["side"],
            "terms": terms,
            "instance": {"outcome": leg["outcome"], "coin": leg["coin"], "catalogue": digests["catalogue"]},
            "size": exact.format(size),
            "acquisition": {"kind": "book_walk", "path": "direct_book", "snapshot": digests[leg["id"]]},
        }],
        "objective": [{"id": "loss_cap", "min_pnl": exact.format(-cap)}],
        "objective_valuation_time": valuation_time,
        "objective_reference": "hl:perp:BTC:mark-interp",
        "other_costs": "0",
        "assumptions": ["common_reference", "zero_base_fee"],
    }
    if capture:
        out["capture"] = capture
    return out


def strike_of(leg, terms):
    """The price below which this leg pays, from its own terms."""
    if leg["strike_term"] == "target_price":
        return exact.parse(terms["target_price"])
    return exact.parse(terms["thresholds"][0])


def registry(entries_dir=None):
    entries = {}
    for path in sorted((entries_dir or PROJECT / "registry").glob("*.json")):
        entry = canon.loads(path.read_bytes())
        entries[entry["family"]] = entry
    return entries


def evaluate_candidates(capture, options, entries=None, provenance=None):
    """Size, build, lower and evaluate every candidate in one captured set.

    `capture` carries the parsed snapshots and their digests. Returns one row per
    candidate: the proposal, the lowered proposal, the result, and the size window.
    """
    entries = entries if entries is not None else registry()
    catalogue = capture["catalogue"]
    underlying = options["underlying"]
    expiry, legs = discover.candidates(catalogue, underlying, capture.get("expiry"))
    observation_time = discover.expiry_to_iso(expiry)
    valuation_time = options["valuation_time"] or observation_time

    quantity, cap = options["quantity"], options["cap"]
    floor, ceiling = options["floor"], options["ceiling"]
    baseline = options["baseline"]

    rows = []
    for leg in legs:
        book = capture["books"][leg["id"]]
        terms = dict(leg["terms"], expiry=observation_time)
        strike = strike_of(leg, terms)
        size, window = smallest_passing_size(leg, book, quantity, baseline, cap, floor, ceiling, strike)
        row = {"leg": leg, "window": window, "size": size}
        if size is None:
            rows.append(row)
            continue
        entry = entries.get(leg["family"])
        if entry is None:
            raise Unusable(f"the registry has no entry for {leg['family']}")
        proposal = build_proposal(leg, size, capture["digests"], quantity, baseline,
                                  options["baseline_kind"], cap, floor, ceiling,
                                  valuation_time, observation_time, canon.semantics_version(entry),
                                  provenance)
        lowered, versions = lowering.lower(proposal, entries, capture["snapshots"])
        row["proposal"] = proposal
        row["lowered"] = lowered
        row["result"] = O.evaluate(lowered)
        row["input_digest"] = lowering.input_digest(proposal, lowered, versions)
        rows.append(row)
    return {"expiry": expiry, "observation_time": observation_time,
            "valuation_time": valuation_time, "rows": rows}


def reduction_row(options):
    """The no-premium alternative, as its own row: sell down to what meets the cap."""
    quantity, cap = options["quantity"], options["cap"]
    floor, baseline = options["floor"], options["baseline"]
    keep = O.smallest_reduction(quantity, baseline, -cap, floor)
    kept = O.linear(keep, baseline)
    worst, _, where = O.infimum(kept, floor, options["ceiling"])
    return {"keep": keep, "sell": quantity - keep, "worst": worst, "worst_at": where,
            "pnl_at_baseline": kept(baseline), "fn": kept}


def run_document(capture, evaluated, options, skew, provenance=None):
    """Everything a replay needs, and nothing a replay would have to fetch."""
    return {
        "schema_version": SCHEMA_VERSION,
        "options": {key: (exact.format(value) if isinstance(value, F) else value)
                    for key, value in options.items()},
        "expiry": evaluated["expiry"],
        "observation_time": evaluated["observation_time"],
        "valuation_time": evaluated["valuation_time"],
        "digests": capture["digests"],
        "skew": skew,
        "capture": provenance,
        "results": {row["leg"]["id"]: row["result"] for row in evaluated["rows"] if row.get("result")},
        "input_digests": {row["leg"]["id"]: row["input_digest"] for row in evaluated["rows"] if row.get("input_digest")},
    }


def parse_capture(snapshots, digests, expiry=None):
    """Parsed views of stored bytes, with the bytes kept for lowering."""
    return {
        "snapshots": {digest: json.loads(raw) for digest, raw in snapshots.items()},
        "digests": digests,
        "catalogue": json.loads(snapshots[digests["catalogue"]]),
        "contexts": json.loads(snapshots[digests["contexts"]]),
        "books": {name: json.loads(snapshots[digest])
                  for name, digest in digests.items() if name not in ("catalogue", "contexts")},
        "expiry": expiry,
    }
