"""Generate the certificate bundles: one good, and one per documented corruption.

    python3 tools/make_corruptions.py          # regenerate, then check
    python3 tools/make_corruptions.py --check  # fail if anything on disk is stale

Every bundle here is generated. None is hand-edited, and a corruption is exactly
one documented change to the good bundle, so a fixture can never quietly drift
into testing something other than what its manifest says.

The good bundle is the 18 September bucket replay, with an in-memory **reviewed**
copy of the registry entry written into the bundle. It is never written into
`registry/`: reviewing an entry is the owner's act, and a fixture must not perform
it. Carrying the entry inside the bundle also makes a stored bundle mean the same
thing forever, whatever the tree later says.
"""

import copy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "oracle"))

import canon  # noqa: E402
import exact  # noqa: E402
import lower as lowering  # noqa: E402
import oracle as O  # noqa: E402

REPLAY = PROJECT / "fixtures" / "replay" / "2026-09-18"
BUNDLES = PROJECT / "fixtures" / "bundles"
SOURCE = {"catalogue": "outcome-meta", "contexts": "meta-and-asset-ctxs",
          "book": "book-bucket0-3971-yes"}
# The second leg of the GROUPED basis bundle: outcome 3965 NO, its own retained book.
# Both legs are real 18 September instances sharing the expiry 2026-09-19T06:00:00Z, so
# the group is genuine and nothing about it is invented.
SECOND_BOOK = "book-3965-no"


def reviewed(entry):
    """An in-memory reviewed copy. Never written to registry/."""
    out = copy.deepcopy(entry)
    out["review"] = {"state": "reviewed", "drafted_by": "model", "reviewed_by": "fixture",
                     "reviewed_on": "2026-09-19", "digest": canon.semantics_version(entry)}
    return out


def issue_envelope(proposal, lowered, result, versions):
    """Attach the order the cost bound assumes. PLAN section 7's T3 row.

    A separate step, never part of evaluation: the lowered form carries no instance
    id (PLAN section 6) and the input digest is computed after the result, so the
    evaluator cannot know either. Only for a passing, depth-priced, single-leg answer.
    """
    if result["model_result"] != "passes":
        return result
    if len(proposal["legs"]) != 1:
        return result
    leg, priced = proposal["legs"][0], lowered["legs"][0]
    if priced["premium"]["kind"] != "walked":
        return result

    size = exact.parse(leg["size"])
    remaining, cost, limit = size, exact.parse("0"), None
    for price_text, available in priced["premium"]["levels"]:
        fill = min(remaining, exact.parse(available))
        if fill > 0:
            limit = price_text
        cost += fill * exact.parse(price_text)
        remaining -= fill
        if remaining == 0:
            break
    if remaining != 0 or limit is None:
        return result

    out = dict(result)
    out["execution_readiness"] = "envelope_issued"
    out["input_digest"] = lowering.input_digest(proposal, lowered, versions)
    out["order_envelope"] = {
        "coin": leg["instance"]["coin"], "side": "buy", "size": exact.format(size),
        "limit_price": limit, "time_in_force": "Ioc", "max_cost": exact.format(cost),
        "input_digest": out["input_digest"],
    }
    return out


FOREIGN_REFERENCE = "pyth:{underlying}/USD:price-twap:90s"
FOREIGN_RESOLVED = "pyth:BTC/USD:price-twap:90s"


def second_leg():
    """The binary NO leg of the 18 September replay, for the GROUPED basis bundle.

    Real, retained, and it shares the bucket leg's expiry (2026-09-19T06:00:00Z), so the
    two sit in one group with one valuation time. Nothing here is invented: the leg is
    lifted from binary.proposal.json and its book is the retained #39651 response.
    """
    other = canon.loads((REPLAY / "binary.proposal.json").read_bytes())
    return copy.deepcopy(other["legs"][0])


def build_good(proposal_file="bucket0.proposal.json", envelope=False, settlement=None,
               reference=None, basis_bound=None, grouped=False):
    """Lower and evaluate an 18 Sep replay proposal against a reviewed entry.

    `settlement` forces the entry's settlement, so a bundle can carry a family whose
    payout the DEPLOYER submits. That leg is reduced under `deployer_settled`, loosely,
    so the verdict becomes `needs_review` -- which is the whole point of the fixture.

    `reference` forces the entry's reference TEMPLATE, and `basis_bound` declares a bound
    between it and the objective's. Together they make a leg observed on another price
    series: the band reduction. Without such a bundle the three implementations cannot
    disagree about it, because every other fixture has one reference throughout.
    """
    proposal = canon.loads((REPLAY / proposal_file).read_bytes())
    if grouped:
        # TWO legs on the same foreign reference, so the band is applied to their SUMMED
        # payoff. The infimum of a sum is not the sum of infima, and a bucket YES over
        # [75908, 79007) plus a binary NO over (-inf, 77457) overlap -- so the group's sum
        # is a different shape from either leg, which is exactly what per-leg banding gets
        # wrong. Without this bundle, grouping is exercised only inside the Python guard
        # and the three implementations are never held to agreeing on it.
        proposal = dict(proposal, legs=[*proposal["legs"], second_leg()])
    entries, snapshots = {}, {}
    for path in sorted((PROJECT / "registry").glob("*.json")):
        entry = canon.loads(path.read_bytes())
        if settlement is not None:
            entry = dict(entry, settlement=settlement)
        if reference is not None:
            entry = dict(entry, reference=reference)
        entries[entry["family"]] = reviewed(entry)
    if basis_bound is not None:
        proposal = dict(proposal, basis_bounds=[
            {"between": [proposal["objective_reference"], FOREIGN_RESOLVED], "bound": basis_bound}])
    stems = list(SOURCE.values()) + ([SECOND_BOOK] if grouped else [])
    for stem in stems:
        raw = (REPLAY / f"{stem}.json").read_bytes()
        snapshots[sha256(raw).hexdigest()] = raw

    legs = [dict(leg, semantics_version=canon.semantics_version(entries[leg["family"]]))
            for leg in proposal["legs"]]
    proposal = dict(proposal, legs=legs)
    parsed = {digest: json.loads(raw) for digest, raw in snapshots.items()}
    lowered, versions = lowering.lower(proposal, entries, parsed)
    result = O.evaluate(lowered)
    if envelope:
        result = issue_envelope(proposal, lowered, result, versions)
    return {"proposal": proposal, "entries": entries, "snapshots": snapshots,
            "lowered": lowered, "result": result}


def write_bundle(directory, parts, name, expects, corruption=None):
    directory.mkdir(parents=True, exist_ok=True)
    files = {"proposal": "proposal.json", "lowered": "lowered.json", "result": "result.json",
             "registry": [], "snapshots": []}
    (directory / "proposal.json").write_bytes(canon.canonical(parts["proposal"]) + b"\n")
    (directory / "lowered.json").write_bytes(canon.canonical(parts["lowered"]) + b"\n")
    (directory / "result.json").write_bytes(canon.canonical(parts["result"]) + b"\n")
    # ONLY THE READINGS THIS BUNDLE USES. Copying the whole registry made every bundle
    # carry every family -- four entries for a proposal that names one -- so a bundle's
    # contents depended on the repository's registry rather than on its own proposal, and
    # grew with every family added. A corruption that edits an entry still works: it edits
    # the entry its proposal pins.
    used = {leg["family"] for leg in parts["proposal"]["legs"]}
    for family, entry in parts["entries"].items():
        if family not in used:
            continue
        path = f"registry-{family}.json"
        (directory / path).write_bytes(canon.canonical(entry) + b"\n")
        files["registry"].append({"family": family, "path": path})
    for digest, raw in parts["snapshots"].items():
        path = f"snapshot-{digest[:16]}.json"
        (directory / path).write_bytes(raw)
        files["snapshots"].append({"sha256": digest, "path": path})
    manifest = {"schema_version": "1", "name": name, "expects": expects, "files": files}
    if corruption:
        manifest["corruption"] = corruption
    (directory / "manifest.json").write_bytes(canon.canonical(manifest) + b"\n")


# --------------------------------------------------------------------------- corruptions
#
# Each takes the good parts and returns (changed parts, what changed). Exactly one
# change each: a corruption that altered two things would not show which one a
# refuser caught.


def strike_piece_removed(parts):
    """Drop the piece boundary at the strike, merging two pieces into one."""
    out = copy.deepcopy(parts)
    profile = out["result"]["profile"]
    if len(profile) < 2:
        raise AssertionError("the good result has no strike to remove")
    merged = dict(profile[0])
    merged["upper"] = profile[1]["upper"]
    merged["upper_inclusive"] = profile[1]["upper_inclusive"]
    out["result"]["profile"] = [merged] + profile[2:]
    return out, {"of": "result", "change": "the piece boundary at the strike is removed", "target": "profile"}


def premium_altered(parts):
    """Add 0.00001 to the claimed cost: below any rounding, above exact equality."""
    out = copy.deepcopy(parts)
    leg = out["lowered"]["legs"][0]
    before = exact.parse(leg["premium"]["total"])
    leg["premium"]["total"] = exact.format(before + exact.parse("0.00001"))
    return out, {"of": "lowered", "change": "the walked total is altered by 0.00001", "target": "legs[0].premium.total"}


def objective_changed(parts):
    """Loosen the cap in the lowered proposal, leaving the proposal's own intact.

    The lowered objective must be detached first: lowering copies the proposal's
    objective by reference, so editing one would otherwise edit both and the bundle
    would be self-consistent about the wrong question.
    """
    out = copy.deepcopy(parts)
    out["lowered"] = dict(out["lowered"], objective=copy.deepcopy(out["lowered"]["objective"]))
    clause = out["lowered"]["objective"][0]
    clause["min_pnl"] = exact.format(exact.parse(clause["min_pnl"]) - 500)
    return out, {"of": "lowered", "change": "the loss cap is loosened by 500, the proposal's is not",
                 "target": "objective[0].min_pnl"}


def endpoint_ownership_swapped(parts):
    """Give the strike to the lower piece instead of the upper one."""
    out = copy.deepcopy(parts)
    profile = out["result"]["profile"]
    if len(profile) < 2:
        raise AssertionError("the good result has no strike to swap")
    profile[0]["upper_inclusive"] = not profile[0]["upper_inclusive"]
    profile[1]["lower_inclusive"] = not profile[1]["lower_inclusive"]
    return out, {"of": "result", "change": "the strike is owned by the lower piece", "target": "profile"}


def book_byte_changed(parts):
    """Change one displayed price in the book, leaving its stored name alone."""
    out = copy.deepcopy(parts)
    digest = out["proposal"]["legs"][0]["acquisition"]["snapshot"]
    raw = out["snapshots"][digest]
    changed = raw.replace(b'"0.17399"', b'"0.17398"', 1)
    if changed == raw:
        raise AssertionError("the book does not contain the price this corruption edits")
    out["snapshots"][digest] = changed
    return out, {"of": "snapshot", "change": "one displayed price is changed by 0.00001", "target": digest}


def snapshot_hash_replaced(parts):
    """Cite another snapshot that really is in the bundle, and really is not the book."""
    out = copy.deepcopy(parts)
    book = out["proposal"]["legs"][0]["acquisition"]["snapshot"]
    other = next(digest for digest in out["snapshots"] if digest != book)
    out["proposal"]["legs"][0]["acquisition"]["snapshot"] = other
    return out, {"of": "proposal", "change": "the book citation is replaced with another valid hash",
                 "target": "legs[0].acquisition.snapshot"}


def wrong_semantics_version(parts):
    """Pin a digest that is a real digest, of the wrong thing."""
    out = copy.deepcopy(parts)
    entry = next(iter(out["entries"].values()))
    out["proposal"]["legs"][0]["semantics_version"] = canon.digest(entry)
    return out, {"of": "proposal", "change": "the pin is the digest of the whole entry, review included",
                 "target": "legs[0].semantics_version"}


def reduction_without_reason(parts):
    """Declare the reduction, drop the reason code that names it."""
    out = copy.deepcopy(parts)
    reductions = out["result"].get("reductions")
    if not reductions:
        raise AssertionError("the good result declares no reduction")
    del reductions[0]["reason_code"]
    return out, {"of": "result", "change": "a declared reduction loses its reason code", "target": "reductions[0]"}


def witness_inadmissible(parts):
    """Name an adverse state for a leg that was never reduced."""
    out = copy.deepcopy(parts)
    intervals = out["result"].get("failing_intervals") or out["result"].get("undecided_intervals")
    if not intervals:
        raise AssertionError("the good result has no interval to corrupt")
    intervals[0].setdefault("witness", {})["adverse_states"] = [
        {"leg": "no-such-leg", "rule": "horizon_mismatch", "state": "invented"}]
    return out, {"of": "result", "change": "the witness names an adverse state for a leg that was not reduced",
                 "target": "failing_intervals[0].witness"}


def interval_widened(parts):
    """Move one endpoint outward by a cent."""
    out = copy.deepcopy(parts)
    key = "failing_intervals" if out["result"].get("failing_intervals") else "undecided_intervals"
    intervals = out["result"].get(key)
    if not intervals:
        raise AssertionError("the good result has no interval to widen")
    intervals[0]["upper"] = exact.format(exact.parse(intervals[0]["upper"]) + exact.parse("0.01"))
    return out, {"of": "result", "change": "a failing interval is widened by one endpoint", "target": f"{key}[0].upper"}


def size_window_too_small(parts):
    """Claim a smallest passing size one contract below the real one."""
    out = copy.deepcopy(parts)
    windows = out["result"].get("size_windows")
    if not windows or "smallest" not in windows[0]:
        raise AssertionError("the good result has no size window to corrupt")
    windows[0]["smallest"] = exact.format(exact.parse(windows[0]["smallest"]) - 1)
    return out, {"of": "result", "change": "the smallest passing size is one contract too small",
                 "target": "size_windows[0].smallest"}


def certificate_negative_weight(parts):
    """A Farkas certificate whose weights are not a convex combination."""
    out = copy.deepcopy(parts)
    windows = out["result"].get("size_windows")
    if not windows:
        raise AssertionError("the good result has no size window to corrupt")
    windows[0]["certificate"] = {"kind": "farkas", "weights": ["-0.2", "1.2"]}
    return out, {"of": "result", "change": "an infeasibility certificate carries a negative weight",
                 "target": "size_windows[0].certificate"}


def envelope_limit_raised(parts):
    """Raise the limit one tick above the level the walk ended in.

    The tempting corruption, because it looks harmless and even prudent: a higher
    limit fills more readily. It is the one that breaks the bound. The walk measured
    what 924 contracts cost at prices up to 0.17399; at 0.174 the same order may cost
    more, and `max_cost` would no longer be a maximum.
    """
    out = copy.deepcopy(parts)
    out["result"]["order_envelope"]["limit_price"] = "0.174"
    return out, {"of": "result", "change": "the limit is raised above the level the walk ended in",
                 "target": "order_envelope.limit_price"}


def envelope_size_raised(parts):
    """Buy one more contract than the walk priced."""
    out = copy.deepcopy(parts)
    envelope = out["result"]["order_envelope"]
    envelope["size"] = exact.format(exact.parse(envelope["size"]) + 1)
    return out, {"of": "result", "change": "the envelope buys one more contract than was priced",
                 "target": "order_envelope.size"}


def envelope_digest_swapped(parts):
    """Point the envelope at some other answer: a stale bound on a live order."""
    out = copy.deepcopy(parts)
    out["result"]["order_envelope"]["input_digest"] = "f" * 64
    return out, {"of": "result", "change": "the envelope names a different input digest",
                 "target": "order_envelope.input_digest"}


def envelope_readiness_dropped(parts):
    """Keep the envelope, say nothing was evaluated."""
    out = copy.deepcopy(parts)
    out["result"]["execution_readiness"] = "not_evaluated"
    return out, {"of": "result", "change": "an envelope beside a readiness that denies it",
                 "target": "execution_readiness"}


def envelope_on_a_failure(parts):
    """The envelope stays, the verdict becomes a failure.

    The result is then internally inconsistent in two ways at once -- the profile no
    longer supports `fails` either -- so this fixture asserts only that it is refused,
    and the class it is refused with is the checker's to choose. It is here because a
    bundle where the envelope survives a verdict change is exactly what must never be
    accepted.
    """
    out = copy.deepcopy(parts)
    out["result"]["model_result"] = "fails"
    return out, {"of": "result", "change": "the verdict becomes a failure and the envelope stays",
                 "target": "model_result"}


# Three good bundles, because one cannot exercise everything. The passing bundle has a
# profile, a size window and no reduction; the failing one has a reduction, a failing
# interval and a witness carrying an adverse state; the third is the passing one with
# the order envelope its cost bound assumes. A corruption is attached to whichever good
# bundle actually contains the thing it corrupts.
BASES = {
    "good": "bucket0.proposal.json",
    "good-horizon": "bucket0-horizon.proposal.json",
    "good-envelope": "bucket0.proposal.json",
    # A family whose payout the deployer SUBMITS. Accepted, and `needs_review`: the leg
    # is worst-cased under a loose rule, so it can never make a proposal fail.
    "good-deployer": "bucket0.proposal.json",
    # A leg observed on ANOTHER price series. With a declared bound its payoff is the
    # infimum over the band; without one the group is worth zero. Every other fixture
    # has one reference throughout, so without these two the band reduction is code no
    # bundle exercises and the three implementations cannot be held to agreeing on it.
    "good-basis-band": "bucket0.proposal.json",
    "good-basis-unbridged": "bucket0.proposal.json",
    # TWO legs on one foreign reference, banded as a GROUP. The two above are single-leg,
    # so no bundle carried a `with` list at all and neither Go nor the TypeScript checker
    # was ever held to agreeing on one -- both implement grouping, and both were untested
    # against the other two on it.
    #
    # WHAT THIS BUNDLE DOES NOT DO: separate grouped banding from per-leg banding. Its two
    # legs are a bucket YES below 75908 and a binary NO below 77457, both MONOTONE DECREASING,
    # and for same-direction legs the infimum of the sum IS the sum of infima -- measured
    # at bands of 100, 500, 1,000, 2,000 and 5,000, the two agree at every price. Separating
    # them needs legs pointing OPPOSITE ways, whose sum is flat where each alone is stepped,
    # and no retained book supports such a pair: binary YES would need coin #39650 and
    # bucket NO #39711, neither of which was captured. That case is therefore synthetic, in
    # `basis_band`'s cancelling pair in oracle/verify.py, which is where the arithmetic is
    # pinned. This bundle pins the PLUMBING: that a group is recorded, carried and agreed.
    "good-basis-grouped": "bucket0.proposal.json",
}
ENVELOPE_BASES = {"good-envelope"}
DEPLOYER_BASES = {"good-deployer"}
BASIS_BASES = {"good-basis-band": "500", "good-basis-unbridged": None,
               "good-basis-grouped": "500"}
GROUPED_BASES = {"good-basis-grouped"}

CORRUPTIONS = [
    ("strike-piece-removed", "good", "PROFILE_COVERAGE", strike_piece_removed),
    ("premium-altered", "good", "COST_MISMATCH", premium_altered),
    ("objective-changed", "good", "OBJECTIVE_MISMATCH", objective_changed),
    ("endpoint-ownership-swapped", "good", "ENDPOINT_OWNERSHIP", endpoint_ownership_swapped),
    ("book-byte-changed", "good", "SNAPSHOT_BYTES", book_byte_changed),
    ("snapshot-hash-replaced", "good", "SNAPSHOT_NOT_CITED", snapshot_hash_replaced),
    ("wrong-semantics-version", "good", "SEMANTICS_PIN", wrong_semantics_version),
    ("size-window-too-small", "good", "SIZE_WINDOW", size_window_too_small),
    ("certificate-negative-weight", "good", "CERTIFICATE_WEIGHTS", certificate_negative_weight),
    ("reduction-without-reason", "good-horizon", "REDUCTION_UNDECLARED", reduction_without_reason),
    ("witness-inadmissible", "good-horizon", "WITNESS_INADMISSIBLE", witness_inadmissible),
    ("interval-widened", "good-horizon", "INTERVAL_MISMATCH", interval_widened),
    ("envelope-limit-raised", "good-envelope", "ENVELOPE_MISMATCH", envelope_limit_raised),
    ("envelope-size-raised", "good-envelope", "ENVELOPE_MISMATCH", envelope_size_raised),
    ("envelope-digest-swapped", "good-envelope", "ENVELOPE_MISMATCH", envelope_digest_swapped),
    ("envelope-readiness-dropped", "good-envelope", "ENVELOPE_MISMATCH", envelope_readiness_dropped),
    ("envelope-on-a-failure", "good-envelope", "VERDICT_MISMATCH", envelope_on_a_failure),
]


def generate():
    goods = {name: build_good(source, envelope=name in ENVELOPE_BASES,
                              settlement="deployer" if name in DEPLOYER_BASES else None,
                              reference=FOREIGN_REFERENCE if name in BASIS_BASES else None,
                              grouped=name in GROUPED_BASES,
                              basis_bound=BASIS_BASES.get(name))
             for name, source in BASES.items()}
    if BUNDLES.exists():
        shutil.rmtree(BUNDLES)
    for name, parts in goods.items():
        write_bundle(BUNDLES / name, parts, name, "accept")
    for name, base, expects, corrupt in CORRUPTIONS:
        parts, description = corrupt(goods[base])
        description = dict(description, of=f"{base}:{description['of']}")
        write_bundle(BUNDLES / name, parts, name, expects, description)
    return len(goods) + len(CORRUPTIONS)


def main():
    checking = "--check" in sys.argv
    count = generate()
    if checking:
        # REPRODUCIBLE, not merely present. These bundles are derived and are not in git,
        # so "does the checkout match?" has no answer on a fresh clone -- `before` would be
        # empty and every file would read as stale. What still has to hold is that the
        # generator is a function of its source alone. The assertion that carries the real
        # weight is elsewhere: `bundles()` in oracle/verify.py requires each bundle to be
        # accepted, or refused with exactly the class its manifest names.
        first = {path.relative_to(BUNDLES): path.read_bytes() for path in sorted(BUNDLES.rglob("*.json"))}
        generate()
        second = {path.relative_to(BUNDLES): path.read_bytes() for path in sorted(BUNDLES.rglob("*.json"))}
        if first != second:
            moved = sorted({name for name in set(first) | set(second) if first.get(name) != second.get(name)})
            print(f"bundles are not reproducible: {', '.join(str(name) for name in moved[:3])}", file=sys.stderr)
            return 1
    print(f"{count} bundles generated: {len(BASES)} good, {len(CORRUPTIONS)} corrupted, each one documented change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
