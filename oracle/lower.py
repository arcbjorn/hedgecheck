"""Lower a family-level proposal to the exact intermediate form. Standard library only.

A proposal names contract *families* and *instances*: "the NO side of outcome 3965,
924 contracts, bought by walking this book." The kernel knows none of that. Lowering
is the one place that reads a registry entry, checks the instance against the
catalogue the proposal cites, prices the size against the book it cites, and emits
primitives the kernel can evaluate.

Pure: bytes and documents in, a lowered proposal out. No I/O, no clock, no network.
Every number enters through `exact.parse` and every contract document through
`canon.loads`; a venue response is evidence, not contract, so it is read with
`json.loads` and its bytes are pinned by SHA-256 (ARCHITECTURE section 2).

Refusals are exceptions, never verdicts. A proposal that cannot be lowered has no
result; it is not a `fails`.
"""

from hashlib import sha256
import json
from typing import NoReturn

import canon
import exact
import oracle

SCHEMA_VERSION = "1"


class Refused(Exception):
    """A proposal that cannot be lowered. `code` is the reason code."""

    def __init__(self, code, detail):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _refuse(code, detail) -> NoReturn:
    raise Refused(code, detail)


def num(text):
    return exact.parse(text)


# --------------------------------------------------------------------------- snapshots


def snapshot(raw):
    """A retained response, keyed by the SHA-256 of its exact bytes.

    The venue's JSON carries numbers, so it cannot go through the canonical profile.
    It is evidence: hashed as a file, parsed permissively, never re-serialized.
    """
    return sha256(raw).hexdigest(), json.loads(raw)


def _cited(snapshots, digest, what):
    if digest not in snapshots:
        _refuse("SNAPSHOT_NOT_SUPPLIED", f"{what} cites {digest[:12]}, which was not supplied")
    return snapshots[digest]


# --------------------------------------------------------------------------- catalogue


def _terms_of(description):
    """Parse a catalogue description, 'key:value|key:value'."""
    out = {}
    for part in description.split("|"):
        key, _, value = part.partition(":")
        if not key or not _:
            _refuse("CATALOGUE_UNREADABLE", f"description part {part!r} is not key:value")
        out[key] = value
    return out


def _find_outcome(catalogue, outcome):
    for item in catalogue.get("outcomes", []):
        if str(item.get("outcome")) == outcome:
            return item
    _refuse("INSTANCE_NOT_IN_CATALOGUE", f"outcome {outcome} is not in the cited catalogue")


def _question_of(catalogue, outcome):
    """The question that names this outcome, for families whose terms live on the parent."""
    for question in catalogue.get("questions", []):
        if int(outcome) in question.get("namedOutcomes", []):
            return question
    _refuse("INSTANCE_NOT_IN_CATALOGUE", f"no question names outcome {outcome}")


def _check_coin(leg):
    """The coin encodes outcome and side: '#' + (10*outcome + side), yes=0, no=1."""
    side = 0 if leg["side"] in ("yes", "long") else 1
    want = f"#{10 * int(leg['instance']['outcome']) + side}"
    if leg["instance"]["coin"] != want:
        _refuse("COIN_MISMATCH", f"{leg['id']}: coin {leg['instance']['coin']} does not encode outcome and side, expected {want}")


def _expiry_compact(iso):
    """'2026-09-19T06:00:00Z' -> '20260919-0600', the catalogue's form."""
    if not (len(iso) == 20 and iso.endswith("Z")):
        _refuse("TERMS_MISMATCH", f"expiry {iso!r} is not an ISO instant ending in Z")
    return f"{iso[0:4]}{iso[5:7]}{iso[8:10]}-{iso[11:13]}{iso[14:16]}"


def check_terms(leg, catalogue):
    """The leg's terms must be the instance the catalogue describes, field by field.

    This is the check that stops a proposal being evaluated against terms nobody
    verified: the numbers the kernel uses come from here, not from the leg.
    """
    item = _find_outcome(catalogue, leg["instance"]["outcome"])
    terms = leg["terms"]
    family = leg["family"]

    if family == "recurring.priceBinary":
        described = _terms_of(item["description"])
        want = {"class": "priceBinary", "underlying": terms["underlying"], "expiry": _expiry_compact(terms["expiry"]),
                "targetPrice": terms["target_price"], "period": terms["period"]}
        if described != want:
            _refuse("TERMS_MISMATCH", f"{leg['id']}: catalogue says {item['description']!r}, leg says {want}")
        return num(terms["target_price"]), item

    if family == "recurring.priceBucket":
        # The outcome carries only its index; the thresholds live on the parent question.
        index = _terms_of(item["description"]).get("index")
        if index != terms["index"]:
            _refuse("TERMS_MISMATCH", f"{leg['id']}: catalogue says index {index!r}, leg says {terms['index']!r}")
        question = _question_of(catalogue, leg["instance"]["outcome"])
        described = _terms_of(question["description"])
        want = {"class": "priceBucket", "underlying": terms["underlying"], "expiry": _expiry_compact(terms["expiry"]),
                "priceThresholds": ",".join(terms["thresholds"]), "period": terms["period"]}
        if described != want:
            _refuse("TERMS_MISMATCH", f"{leg['id']}: question says {question['description']!r}, leg says {want}")
        if question["namedOutcomes"].index(int(leg["instance"]["outcome"])) != int(terms["index"]):
            _refuse("TERMS_MISMATCH", f"{leg['id']}: outcome is not at index {terms['index']} of its question")
        return [num(t) for t in terms["thresholds"]], item

    _refuse("UNSUPPORTED_FAMILY", f"{leg['id']}: lowering has no rule for {family}")


# --------------------------------------------------------------------------- registry


def resolve(leg, registry):
    """The registry entry this leg pins, refusing a stale pin or an unreviewed reading."""
    entry = registry.get(leg["family"])
    if entry is None:
        _refuse("UNKNOWN_FAMILY", f"{leg['id']}: the registry has no entry for {leg['family']}")
    version = canon.semantics_version(entry)
    if leg["semantics_version"] != version:
        _refuse("SEMANTICS_PIN_MISMATCH",
                f"{leg['id']}: pins {leg['semantics_version'][:12]}, the registry entry is {version[:12]}")
    if entry["status"] == "bounded":
        # A bounded family's payoff is NOT a function of the terminal price. `priceTouch`
        # is the case: whether the price ever touched a level is path-dependent, and a
        # terminal-price kernel cannot compute it. PLAN section 2 gives the bound -- the
        # inclusive terminal digital at the target, and only when the touch window covers
        # the valuation time -- but no such family exists yet, so there is no rule here to
        # apply. Until one does, refusing is the safe direction: evaluating a bounded
        # family with the terminal machinery would silently treat a path payoff as a
        # terminal one, which over-credits it at prices it may never have touched.
        _refuse("UNSUPPORTED_FAMILY",
                f"{leg['id']}: {entry['family']} is bounded, not computed, and lowering has no bound for it yet")
    if entry["status"] == "refused":
        # The registry says this family is not understood (PLAN section 6: "Everything
        # else -- Refused"). A REFUSAL, not a reduction: a reduction still produces a
        # verdict, and there is no verdict to produce about a payoff nobody has read.
        # Worst-casing it to zero would answer a question this project has declared
        # unanswerable, and `needs_review` would invite someone to review a reading that
        # does not exist. UNSUPPORTED_FAMILY is exactly the existing code for "lowering
        # has no rule for this family"; here the registry says so itself.
        _refuse("UNSUPPORTED_FAMILY",
                f"{leg['id']}: the registry refuses {entry['family']}: its reading is not established")
    return entry, version


def _payoff_for(entry, leg):
    for payoff in entry["payoffs"]:
        select = payoff["select"]
        if select["side"] != leg["side"]:
            continue
        if "index" in select and select["index"] != leg["terms"].get("index"):
            continue
        return payoff
    _refuse("NO_PAYOFF_FOR_SIDE", f"{leg['id']}: the entry defines no payoff for side {leg['side']!r}")


def _bound(spec, values):
    """One endpoint from the entry's payoff, resolved against the leg's terms."""
    if "at" in spec:
        return values[int(spec["at"])]
    return values if not isinstance(values, list) else values[0]


def pays_on(entry, leg, values):
    """The interval this leg pays on, as data, with both endpoints owned explicitly."""
    payoff = _payoff_for(entry, leg)
    if len(payoff["pays"]) != 1 or payoff["pays"][0]["primitive"] != "indicator":
        _refuse("UNSUPPORTED_PAYOFF", f"{leg['id']}: only a single indicator is lowered here")
    spec = payoff["pays"][0]["pays_on"]
    out = {}
    if "lower" in spec:
        out["lower"] = exact.format(_bound(spec["lower"], values))
        out["lower_inclusive"] = spec["lower_inclusive"]
    if "upper" in spec:
        out["upper"] = exact.format(_bound(spec["upper"], values))
        out["upper_inclusive"] = spec["upper_inclusive"]
    if not out:
        _refuse("UNSUPPORTED_PAYOFF", f"{leg['id']}: an indicator that pays nowhere in particular")
    return out


# --------------------------------------------------------------------------- pricing


def _asks(book, leg_id):
    """Displayed asks, exactly, in book order. levels[0] is bids, levels[1] is asks.

    A leg may cite any retained snapshot by hash, and a hash says nothing about what
    the response was. Citing the catalogue where a book belongs is a wrong citation,
    not a crash, so the shape is checked before it is indexed.
    """
    levels = book.get("levels") if isinstance(book, dict) else None
    if not isinstance(levels, list) or len(levels) != 2 or "coin" not in book:
        _refuse("SNAPSHOT_NOT_A_BOOK", f"{leg_id}: the cited snapshot is not an l2Book response")
    return [(num(level["px"]), num(level["sz"])) for level in levels[1]]


def walk(leg, book, digest):
    """The exact total paid to acquire this leg's whole size along the direct book.

    Carried as a total, not a per-unit price: a walk over several levels has no single
    price, and its average is derived rather than observed.
    """
    size = num(leg["size"])
    if size.denominator != 1 or size <= 0:
        _refuse("SIZE_NOT_WHOLE", f"{leg['id']}: size {leg['size']} is not a positive whole number of contracts")
    levels = _asks(book, leg["id"])
    cost = oracle.ask_cost(levels, size)
    if cost is None:
        _refuse("INSUFFICIENT_DEPTH", f"{leg['id']}: displayed asks do not cover {leg['size']} contracts")
    # The levels travel with the total so the size window is derived from the same bytes
    # as the price, without a second look at the book.
    return {"kind": "walked", "total": exact.format(cost), "path": "direct_book", "snapshot": digest,
            "levels": [[exact.format(price), exact.format(available)] for price, available in levels]}


def price(leg, snapshots):
    acquisition = leg["acquisition"]
    if acquisition["kind"] != "book_walk":
        _refuse("UNSUPPORTED_ACQUISITION", f"{leg['id']}: {acquisition['kind']!r}")
    if acquisition["path"] != "direct_book":
        _refuse("UNSUPPORTED_ACQUISITION", f"{leg['id']}: path {acquisition['path']!r} is not lowered yet")
    digest = acquisition["snapshot"]
    return walk(leg, _cited(snapshots, digest, f"{leg['id']}"), digest)


# --------------------------------------------------------------------------- baseline


def read_baseline(proposal, snapshots):
    """Re-read the baseline from the contexts snapshot the proposal cites.

    The proposal states a price; this recomputes it from the retained bytes and
    refuses a mismatch, so a hand-edited baseline cannot reach the kernel.
    """
    baseline = proposal["baseline"]
    if baseline["kind"] != "analysis_time":
        return num(baseline["price"])
    source = baseline["source"]
    contexts = _cited(snapshots, source["snapshot"], "baseline")
    universe, states = contexts[0]["universe"], contexts[1]
    for index, asset in enumerate(universe):
        if asset["name"] == source["coin"]:
            mark = num(states[index]["markPx"])
            if mark != num(baseline["price"]):
                _refuse("BASELINE_MISMATCH",
                        f"baseline says {baseline['price']}, the cited snapshot says {exact.format(mark)}")
            return mark
    _refuse("BASELINE_MISMATCH", f"{source['coin']} is not in the cited contexts snapshot")


# --------------------------------------------------------------------------- digests


def proposal_digest(proposal):
    return canon.digest(proposal)


def ir_digest(lowered):
    return canon.digest(lowered)


def input_digest(proposal, lowered, versions):
    """Everything that determines a result except the engine (ARCHITECTURE section 2)."""
    return canon.digest({
        "schema_version": SCHEMA_VERSION,
        "proposal_digest": proposal_digest(proposal),
        "ir_digest": ir_digest(lowered),
        "semantics_versions": sorted(set(versions)),
        "snapshots": sorted(set(_snapshots_cited(proposal))),
    })


def _snapshots_cited(proposal):
    out = []
    baseline = proposal["baseline"]
    if "source" in baseline:
        out.append(baseline["source"]["snapshot"])
    for leg in proposal["legs"]:
        out.append(leg["instance"]["catalogue"])
        if isinstance(leg.get("acquisition"), dict) and "snapshot" in leg["acquisition"]:
            out.append(leg["acquisition"]["snapshot"])
    return out


# --------------------------------------------------------------------------- lowering


def lower(proposal, registry, snapshots):
    """(proposal, registry entries by family, snapshot bytes by SHA-256) -> lowered proposal.

    Pure. Raises `Refused` rather than returning a verdict.
    """
    if proposal["schema_version"] != SCHEMA_VERSION:
        _refuse("UNSUPPORTED_SCHEMA", f"proposal schema_version {proposal['schema_version']!r}")
    for required in ("zero_base_fee",):
        if required not in proposal["assumptions"]:
            _refuse("ASSUMPTION_REQUIRED", f"pricing at displayed asks requires the {required!r} assumption")

    baseline = read_baseline(proposal, snapshots)

    legs, versions, reductions = [], [], []
    for leg in proposal["legs"]:
        entry, version = resolve(leg, registry)
        versions.append(version)
        # Reductions lower a leg's value to something provable. Each is listed in the
        # lowered proposal so a checker can re-derive it, and each declares whether it
        # is tight: a loose bound can make a proposal need review, never make it fail.
        if leg["terms"]["expiry"] != proposal["objective_valuation_time"]:
            # The leg is not observed when the objective is valued. Its own observation
            # may pay nothing by then, or not be resolved yet, so it is worth zero here.
            # Tight: that state is admissible, not merely unproven.
            reductions.append({"leg": leg["id"], "rule": "horizon_mismatch", "tight": True,
                               "reason_code": "LEG_WORST_CASED_HORIZON"})
        if not canon.reviewed(entry):
            # Nobody has checked this reading of the contract, so nothing is known about
            # what the leg pays. Not tight: the leg is probably worth more than zero, and
            # a verdict may not rest on the bound alone.
            reductions.append({"leg": leg["id"], "rule": "unreviewed_family", "tight": False,
                               "reason_code": "UNREVIEWED_FAMILY"})
        if entry["settlement"] == "deployer":
            # A deployer leg pays what the deployer SUBMITS. EVIDENCE section 1,
            # verified: `settleOutcome` carries a `settleFraction` the deployer chooses,
            # and nothing in the protocol derives it from a price. The template says what
            # they said they would do, not what they must. Not tight, for the same reason
            # as above: the leg is probably worth more than zero, so this may make a
            # proposal need review and may never make one fail.
            reductions.append({"leg": leg["id"], "rule": "deployer_settled", "tight": False,
                               "reason_code": "DEPLOYER_SETTLED"})
        _check_coin(leg)
        catalogue = _cited(snapshots, leg["instance"]["catalogue"], f"{leg['id']} catalogue")
        values, _item = check_terms(leg, catalogue)
        for name in entry["assumptions_required"]:
            if name not in proposal["assumptions"]:
                _refuse("ASSUMPTION_REQUIRED", f"{leg['id']}: {entry['family']} requires the {name!r} assumption")
        legs.append({
            "id": leg["id"],
            "kind": "indicator",
            "size": exact.format(num(leg["size"])),
            "pays_on": pays_on(entry, leg, values),
            "premium": price(leg, snapshots),
            "observation_time": leg["terms"]["expiry"],
            "semantics": version,
        })

    lowered = {
        "schema_version": SCHEMA_VERSION,
        "units": proposal["units"],
        "domain": proposal["domain"],
        # The baseline keeps its provenance: a checker re-reads the price from the same
        # retained response rather than trusting the number the lowering wrote down.
        "baseline": dict(proposal["baseline"], price=exact.format(baseline)),
        "exposure": {"kind": "linear", "quantity": exact.format(num(proposal["exposure"]["quantity"]))},
        "legs": legs,
        "objective": proposal["objective"],
        "objective_valuation_time": proposal["objective_valuation_time"],
        "other_costs": exact.format(num(proposal["other_costs"])),
        "assumptions": proposal["assumptions"],
    }
    if reductions:
        lowered["reductions"] = reductions
    # Capture provenance travels with the proposal. Lowering cannot re-derive it --
    # the contexts response carries no venue timestamp -- so it is copied, not checked.
    if "capture" in proposal:
        lowered["capture"] = proposal["capture"]
    return lowered, versions
