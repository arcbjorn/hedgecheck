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
import re
from typing import NoReturn

import canon
import exact
import oracle

SCHEMA_VERSION = "1"

# THE ASSUMPTION VOCABULARY IS CLOSED.
#
# An assumption is carried into the result and shown to a reader, who relies on what it
# MEANS. An invented slug means nothing, so it must be refused rather than displayed beside
# the real ones with equal standing -- which is what happened until 22 Sep: the schema types
# `assumptions` as any slug, so a proposal declaring `nothing_can_go_wrong` validated,
# lowered, and appeared in the result's own `assumptions` list.
#
# Enforced here rather than in the schema. The schema is frozen and narrowing `slug` to an
# enum would make previously-valid documents invalid, which needs a new `schema_version` and
# every pinned document regenerated. And the vocabulary is a SEMANTIC rule, like the family
# whitelist: what an assumption means is a fact about this system, not about JSON shape.
#
# Each entry says what declaring it asserts, because a name a reader cannot interpret is no
# better than an invented one.
ASSUMPTIONS = {
    # Pricing at displayed asks assumes the venue takes no base fee. Required by lowering:
    # a cost bound read off a book is wrong by the fee if there is one.
    "zero_base_fee": "the venue charges no base fee on an outcome trade",
    # A deployer submits `settleFraction` rather than having it computed (EVIDENCE section 1),
    # so a templated family's payoff holds only if the deployer settles as the template reads.
    # Required by `template.*` registry entries.
    "deployer_settles_as_written": "the deployer settles as the template is written",
    # A NOTE, not a gate. It does not switch the basis rule off: a leg observed on another
    # series still earns `basis_band` or `basis_unbridged` whether or not this is declared,
    # because the reduction rests on the RESOLVED references and not on an assertion about
    # them. Kept in the vocabulary because proposals carry it and a reader should be able to
    # look it up; if it ever gates anything, that will be a change with its own reason.
    "common_reference": "the holder believes every leg is observed on the objective's series",
}

# Families whose payoff is path-dependent AND for which lowering carries a sound bound.
# A `bounded` family absent from this set is refused: the status says a terminal kernel
# cannot compute it, and without a bound there is nothing to put in its place.
BOUNDED_FAMILIES = {"template.priceTouch"}


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


def _templated_terms(leg, item, level_name):
    """The catalogue's description against the leg's terms, for a deployer-templated family.

    `level_name` is what the template calls the price level: `threshold` for binaryPrice,
    `target` for priceTouch. Everything else is the same shape.

    A term the leg does NOT CARRY is a refusal, not a crash. A proposal can name any family
    with any terms -- the `unsupported-family` refusal fixture relabels a bucket leg as a
    touch, keeping the bucket's `index` and `thresholds` -- so indexing the terms directly
    raised KeyError out of a function whose whole contract is to refuse.
    """
    terms = leg["terms"]
    described = _terms_of(item["description"])
    for name in ("underlying", "target_price", "seconds", "expiry"):
        if name not in terms:
            _refuse("TERMS_MISMATCH",
                    f"{leg['id']}: {leg['family']} needs the {name!r} term, which the leg does not carry")
    want = {"perp": terms["underlying"], "priceDescription": described.get("priceDescription", ""),
            "seconds": terms["seconds"], level_name: terms["target_price"],
            "time": _expiry_compact(terms["expiry"])}
    if described != want:
        _refuse("TERMS_MISMATCH", f"{leg['id']}: catalogue says {item['description']!r}, leg says {want}")
    return num(terms["target_price"]), item


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

    if family == "template.binaryPrice":
        # A DEPLOYER-TEMPLATED binary. Every field the catalogue carries is checked, the
        # price description included: the reference map keys on that exact text, so a leg
        # that disagreed about it would be mapped to a series its instance does not name.
        return _templated_terms(leg, item, "threshold")

    if family == "template.priceTouch":
        # A DEPLOYER-TEMPLATED touch. Same shape, except the template names the level
        # `target` rather than `threshold` -- checked against outcome 1209 on the
        # 18 September catalogue, which reads
        #   perp:HYPE|priceDescription:HYPE-USDC perp mark |seconds:1|target:100|time:...
        return _templated_terms(leg, item, "target")

    _refuse("UNSUPPORTED_FAMILY", f"{leg['id']}: lowering has no rule for {family}")


# --------------------------------------------------------------------------- registry


def leg_reference(leg, entry):
    """The price series this leg is observed on, resolved from the entry's template.

    A registry entry carries a TEMPLATE -- `hl:perp:{underlying}:mark-interp` -- because one
    reading covers every instance of a family. Each `{name}` is the leg's own term of that
    name, so the reference is a fact about the leg and never restated in the proposal.

    A template naming a term the leg does not carry is a MALFORMED ENTRY, not a leg on a
    foreign reference: there is no series to name at all. That is a refusal, not the
    reduction below.
    """
    def one(match):
        name = match.group(1)
        if name not in leg["terms"]:
            _refuse("UNSUPPORTED_FAMILY",
                    f"{leg['id']}: the entry's reference names {{{name}}}, which the leg's terms do not carry")
        value = leg["terms"][name]
        if not isinstance(value, str):
            _refuse("UNSUPPORTED_FAMILY",
                    f"{leg['id']}: the entry's reference names {{{name}}}, which is not a single value")
        return value
    return re.sub(r"\{([a-z_]+)\}", one, entry["reference"])


def reference_index(document):
    """A reference map, keyed for lookup. The caller reads the file; this module does no I/O.

    AN UNREVIEWED DOCUMENT CARRIES NO MAPPINGS. The same seal the registry uses:
    `semantics_version` digests the document WITHOUT its `review` key, so a review cannot
    sign itself and any edit to a mapping voids it. Until 22 Sep nothing checked it here --
    every mapping was honoured whatever the document said about itself, while
    `catalogue_reference` refused with "no REVIEWED mapping", a word the code did not mean.

    Returning an empty index rather than raising keeps the refusal in one place: a templated
    leg then finds no key and `catalogue_reference` refuses it as `AMBIGUOUS_RULES`, which
    is what an unestablished reference already means. Falling back to the entry's own
    template instead would treat a leg nobody mapped as sharing the objective's series --
    measured, that flips a `needs_review` at -1923.90676 into a `passes` at -999.90676.
    """
    if not canon.reviewed(document or {}):
        return {}
    return {(m["venue"], m["price_description"], m["seconds"]): m
            for m in (document or {}).get("mappings", [])}


def catalogue_reference(leg, item, references):
    """The reference a DEPLOYER-TEMPLATED instance is observed on, or None.

    A canonical family's reference is fixed by its registry entry: no `recurring` outcome on
    the 18 September catalogue carries a `priceDescription` (0 of 32), and all 78 that do are
    `template:*`. So this governs the templated families only, and returns None where the
    catalogue describes no series.

    The key is the venue's text EXACTLY as the catalogue carries it, spacing included. The
    catalogue holds both `HYPE-USDC perp mark` and `HYPE-USDC perp mark ` -- one venue, one
    template, one trailing space, different windows -- so trimming would answer for a string
    nobody wrote.

    AN UNMAPPABLE DESCRIPTION IS REFUSED, never resolved. Returning None here would fall
    back to the entry's own reference, so a leg nobody can map would be treated as sharing
    the objective's series -- the silent resolution PLAN section 6 forbids by name.
    """
    described = _terms_of(item.get("description", ""))
    if "priceDescription" not in described:
        return None
    key = (item.get("venue", ""), described["priceDescription"], described.get("seconds", ""))
    mapping = references.get(key)
    if mapping is None:
        _refuse("AMBIGUOUS_RULES",
                f"{leg['id']}: no reviewed mapping for {described['priceDescription']!r} "
                f"at {described.get('seconds', '?')}s on {item.get('venue', '?')!r}")
    if mapping["state"] == "ambiguous":
        # `1-minute candle` names neither a source nor a series; 42 instances name a Pyth
        # series under a template saying the market must refer to a Hyperliquid perp.
        # Either resolution would be a reading the evidence contradicts.
        _refuse("AMBIGUOUS_RULES", f"{leg['id']}: {mapping['why']}")
    return mapping["reference"]


def resolve(leg, registry):
    """The registry entry this leg pins, refusing a stale pin or an unreviewed reading."""
    entry = registry.get(leg["family"])
    if entry is None:
        _refuse("UNKNOWN_FAMILY", f"{leg['id']}: the registry has no entry for {leg['family']}")
    version = canon.semantics_version(entry)
    if leg["semantics_version"] != version:
        _refuse("SEMANTICS_PIN_MISMATCH",
                f"{leg['id']}: pins {leg['semantics_version'][:12]}, the registry entry is {version[:12]}")
    if entry["status"] == "bounded" and entry["family"] not in BOUNDED_FAMILIES:
        # A bounded family's payoff is NOT a function of the terminal price, so evaluating
        # it with the terminal machinery would treat a path payoff as a terminal one and
        # over-credit it at prices it may never have touched. A family with a bound in
        # BOUNDED_FAMILIES is lowered under that bound; one without is refused, because a
        # bound that does not exist cannot be applied.
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


def touch_bound(interval, baseline, target, leg_id):
    """The inclusive terminal digital at `target`, on the side the reference must travel.

    `template.priceTouch` pays if the reference EVER equals or crosses the target before
    the expiry. That is path-dependent: where the reference ended does not say where it
    has been, so a terminal kernel cannot compute it. What a terminal kernel CAN say is
    that ending at or beyond the target implies the target was reached, so the inclusive
    terminal digital is a LOWER bound -- it pays only where a touch is certain, and pays
    nothing on the paths that touched and came back. Verified by brute force over 4,000
    random paths in both directions: the bound never exceeded the true payoff.

    The DIRECTION is not in the terms, which carry the target and not the current price.
    A market whose reference already sits at the target is settled, not a hedge, so the
    reference must travel: up from a baseline below the target, down from one above. The
    entry states the rising case, `[target, inf)`; this mirrors it to `(-inf, target]`
    when the baseline is above. Both are INCLUSIVE at the target, because "equals or
    crosses" is satisfied by equalling it from either side -- `digital_below` is exclusive
    there and would be the wrong primitive for a falling touch.
    """
    if baseline == target:
        # Already touched, so the question the market asks is answered and it is not a
        # hedge against anything. Refusing beats bounding: a bound here would be a claim
        # about a market that is over.
        _refuse("UNSUPPORTED_PAYOFF",
                f"{leg_id}: the baseline is exactly the touch target, so the market is settled")
    if baseline < target:
        return {"lower": exact.format(target), "lower_inclusive": True}
    return {"upper": exact.format(target), "upper_inclusive": True}


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


def lowered_exposure(exposure):
    """The exposure, with its KIND carried rather than discarded.

    Lowering used to write `{"kind": "linear", ...}` whatever the proposal said, so an
    isolated perp arrived at the evaluator indistinguishable from spot. A checker cannot
    re-derive a reduction from an IR that does not say what is exposed.
    """
    quantity = exact.format(num(exposure["quantity"]))
    if exposure["kind"] == "isolated_perp":
        return {"kind": "isolated_perp", "quantity": quantity,
                "liquidation_price": exact.format(num(exposure["liquidation_price"])),
                "isolated_margin": exact.format(num(exposure["isolated_margin"]))}
    return {"kind": "linear", "quantity": quantity}


def path_domain(proposal, baseline):
    """Every price the path can take: the hull of the terminal domain and where it starts.

    PLAN section 2: "every price between now and the valuation time, so it contains the
    current price and the terminal domain". The price is at the baseline NOW and may end
    anywhere in the domain, so the path passes through the first and reaches the second, and
    the hull is the smallest interval containing both. A baseline outside the terminal domain
    WIDENS it, which is right: the path starts there whatever the terminal range says.
    """
    lower, upper = num(proposal["domain"]["lower"]), num(proposal["domain"]["upper"])
    return min(lower, baseline), max(upper, baseline)


def liquidation_reduction(proposal, baseline):
    """A reduction when the exposure can be liquidated inside the path domain, or None.

    THE HEDGE CANNOT BE LIQUIDATED; THE EXPOSURE CAN. Retained evidence at 085ccfb states
    that outcomes "do not involve leverage or liquidations", so an outcome leg is safe and an
    isolated perp is not.

    The rule is PLAN section 2's: with the liquidation price inside the path domain, the leg
    is worth MINUS ITS ISOLATED MARGIN at every terminal price. Not "sometimes" -- at every
    one, because liquidation at any moment closes the position permanently and a later
    recovery does not bring it back. That is the priceTouch situation mirrored: path
    dependence a terminal kernel cannot compute, except here it cuts against the holder, so
    the worst case is the one that must be taken.

    TIGHT, unlike a loose bound. The adverse state is ADMISSIBLE, not merely unproven: a path
    that reaches the liquidation price really does end the position, so a verdict may rest on
    this alone and it CAN make a proposal fail. That is the difference from `price_touch`,
    whose bound understates a payoff and therefore may only ask for review.
    """
    exposure = proposal["exposure"]
    if exposure["kind"] != "isolated_perp":
        return None
    price = num(exposure["liquidation_price"])
    low, high = path_domain(proposal, baseline)
    if not (low <= price <= high):
        # The path cannot reach it within the declared domain, so there is nothing to reduce.
        # Silence here is a statement: the result carries no rule, and a reader sees that the
        # verdict did not rest on one.
        return None
    if num(exposure["isolated_margin"]) < 0:
        _refuse("EXPOSURE_UNSOUND", "an isolated margin cannot be negative")
    return {"leg": "exposure", "rule": "liquidated_in_path", "tight": True,
            "reason_code": "LIQUIDATED_IN_PATH"}


def lower(proposal, registry, snapshots, references=None):
    """(proposal, registry entries by family, snapshot bytes by SHA-256) -> lowered proposal.

    Pure. Raises `Refused` rather than returning a verdict.
    """
    if proposal["schema_version"] != SCHEMA_VERSION:
        _refuse("UNSUPPORTED_SCHEMA", f"proposal schema_version {proposal['schema_version']!r}")
    for declared in proposal["assumptions"]:
        if declared not in ASSUMPTIONS:
            _refuse("ASSUMPTION_UNKNOWN",
                    f"{declared!r} is not an assumption this system defines, so it means nothing "
                    f"to a reader; the vocabulary is {sorted(ASSUMPTIONS)}")
    for required in ("zero_base_fee",):
        if required not in proposal["assumptions"]:
            _refuse("ASSUMPTION_REQUIRED", f"pricing at displayed asks requires the {required!r} assumption")

    baseline = read_baseline(proposal, snapshots)

    legs, versions, reductions = [], [], []
    # THE EXPOSURE'S OWN REDUCTION, before any leg's. An isolated perp liquidated inside the
    # path domain is worth minus its margin at every terminal price, and no hedge can undo
    # that -- so the reader should see it first among the rules the verdict rests on.
    liquidation = liquidation_reduction(proposal, baseline)
    if liquidation is not None:
        reductions.append(liquidation)
    # Each leg's resolved price series, for the basis-band grouping after the loop.
    leg_references = {}
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
        # A DEPLOYER-TEMPLATED instance names its own series, so the catalogue governs and
        # the entry's template is only for families whose reference is fixed.
        described = catalogue_reference(leg, _item, references or {})
        leg_references[leg["id"]] = described if described else leg_reference(leg, entry)
        # A bounded family is lowered under its bound, not its payoff rows. The rows for
        # `template.priceTouch` state the RISING case only -- one payoff row cannot carry
        # both directions -- so the direction is derived here, from the baseline, and the
        # reduction says the leg's value rests on a bound rather than on a computation.
        pays = pays_on(entry, leg, values)
        if entry["status"] == "bounded":
            pays = touch_bound(pays, baseline, _bound({"term": "target_price"}, values), leg["id"])
            # Not tight: the true payoff is at least the bound and usually more, since
            # every path that touched and retraced pays in full and the bound pays zero.
            # So this may make a proposal need review, and may never make one fail.
            reductions.append({"leg": leg["id"], "rule": "price_touch", "tight": False,
                               "reason_code": "PRICE_TOUCH_BOUNDED"})
        legs.append({
            "id": leg["id"],
            "kind": "indicator",
            "size": exact.format(num(leg["size"])),
            "pays_on": pays,
            "premium": price(leg, snapshots),
            "observation_time": leg["terms"]["expiry"],
            "semantics": version,
        })

    # ---- the basis band: legs observed on a reference the objective is not stated on
    #
    # GROUPED, never leg by leg. PLAN section 2 states the rule as the infimum of the
    # GROUP's SUMMED payoff over [S - b, S + b], and the infimum of a sum is not the sum of
    # infima: two legs whose payoffs cancel have a flat sum that no basis move can hurt,
    # while each alone is stepped. Reducing them separately invents a loss on a perfectly
    # hedged position -- and the "a reduction never turns a failing proposal into a passing
    # one" invariant cannot catch that, because per-leg is the LOWER answer.
    #
    # The reduction is recorded here; the arithmetic is the kernel's `band_infimum`, applied
    # by the evaluator to the group's summed payoff.
    objective_reference = proposal.get("objective_reference")
    if objective_reference is not None:
        bounds = {}
        for declared in proposal.get("basis_bounds", []):
            left, right = declared["between"]
            bounds[frozenset((left, right))] = declared["bound"]
        groups = {}
        for leg, reference in leg_references.items():
            if reference != objective_reference:
                groups.setdefault(reference, []).append(leg)
        for reference, members in sorted(groups.items()):
            members = sorted(members)
            bound = bounds.get(frozenset((objective_reference, reference)))
            head, rest = members[0], members[1:]
            row = {"leg": head, "rule": "basis_band", "tight": False,
                   "reason_code": "BASIS_BAND"}
            if rest:
                row["with"] = rest
            if bound is None:
                # PLAN section 2: "No bound declared: zero". The reference is KNOWN -- it
                # just cannot be related to the objective's -- so this is a reduction and
                # not a refusal. Loose: the group is probably worth more than zero.
                row["rule"], row["reason_code"] = "basis_unbridged", "BASIS_UNBRIDGED"
            else:
                row["bound"] = exact.format(num(bound))
            reductions.append(row)

    lowered = {
        "schema_version": SCHEMA_VERSION,
        "units": proposal["units"],
        "domain": proposal["domain"],
        # The baseline keeps its provenance: a checker re-reads the price from the same
        # retained response rather than trusting the number the lowering wrote down.
        "baseline": dict(proposal["baseline"], price=exact.format(baseline)),
        "exposure": lowered_exposure(proposal["exposure"]),
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
