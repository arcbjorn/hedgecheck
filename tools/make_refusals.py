"""Write one proposal per refusal code, so both implementations refuse the same way.

    python3 tools/make_refusals.py          # regenerate, then check
    python3 tools/make_refusals.py --check  # fail if anything on disk is stale

Every code `oracle/lower.py` can raise gets a fixture: a good proposal with exactly
one documented change, and the code that change must produce. Ten of the seventeen
codes had no fixture before this — they were reachable in principle and untested in
fact, which is the same as untested.

A refusal is not a verdict. A proposal that cannot be lowered has no result; saying
`fails` would be claiming the objective was evaluated and found wanting, when it was
never evaluated at all.
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
import lower as lowering  # noqa: E402

REPLAY = PROJECT / "fixtures" / "replay" / "2026-09-18"
OUT = PROJECT / "fixtures" / "refusals"

DELETE = object()


def mutate(document, path, value=DELETE):
    out = copy.deepcopy(document)
    node = out
    for step in path[:-1]:
        node = node[step]
    if value is DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return out


def good():
    """The 18 September bucket replay, with the entry it pins marked reviewed."""
    proposal = canon.loads((REPLAY / "bucket0.proposal.json").read_bytes())
    entries = {}
    for path in sorted((PROJECT / "registry").glob("*.json")):
        entry = canon.loads(path.read_bytes())
        reviewed = copy.deepcopy(entry)
        reviewed["review"] = {"state": "reviewed", "drafted_by": "model", "reviewed_by": "fixture",
                              "reviewed_on": "2026-09-19", "digest": canon.semantics_version(entry)}
        entries[entry["family"]] = reviewed
    proposal["legs"][0]["semantics_version"] = canon.semantics_version(entries["recurring.priceBucket"])
    snapshots = {}
    for stem in ("outcome-meta", "meta-and-asset-ctxs", "book-bucket0-3971-yes"):
        raw = (REPLAY / f"{stem}.json").read_bytes()
        snapshots[sha256(raw).hexdigest()] = raw
    return proposal, entries, snapshots


def cases():
    proposal, entries, snapshots = good()
    book = proposal["legs"][0]["acquisition"]["snapshot"]
    catalogue = proposal["legs"][0]["instance"]["catalogue"]
    contexts = next(d for d in snapshots if d not in (book, catalogue))

    def with_leg(path, value=DELETE):
        return mutate(proposal, ["legs", 0] + path, value)

    return [
        ("unsupported-schema", "UNSUPPORTED_SCHEMA",
         mutate(proposal, ["schema_version"], "2"), entries, snapshots,
         "a schema version this lowering does not implement"),
        ("assumption-required", "ASSUMPTION_REQUIRED",
         mutate(proposal, ["assumptions"], ["common_reference"]), entries, snapshots,
         "pricing at displayed asks without the dated zero_base_fee assumption"),
        ("unknown-family", "UNKNOWN_FAMILY",
         proposal, {"recurring.priceBinary": entries["recurring.priceBinary"]}, snapshots,
         "a leg naming a family the registry does not carry"),
        ("semantics-pin-mismatch", "SEMANTICS_PIN_MISMATCH",
         with_leg(["semantics_version"], "0" * 64), entries, snapshots,
         "a pin that is not the entry's semantics version"),
        ("coin-mismatch", "COIN_MISMATCH",
         with_leg(["instance", "coin"], "#39711"), entries, snapshots,
         "a coin that does not encode its outcome and side"),
        ("instance-not-in-catalogue", "INSTANCE_NOT_IN_CATALOGUE",
         mutate(with_leg(["instance", "outcome"], "9999"), ["legs", 0, "instance", "coin"], "#99990"),
         entries, snapshots, "an instance the cited catalogue does not list"),
        ("terms-mismatch", "TERMS_MISMATCH",
         with_leg(["terms", "thresholds"], ["75908", "79008"]), entries, snapshots,
         "terms that disagree with the catalogue in one field"),
        ("baseline-mismatch", "BASELINE_MISMATCH",
         mutate(proposal, ["baseline", "price"], "77631.5"), entries, snapshots,
         "a baseline the cited contexts snapshot does not support"),
        ("insufficient-depth", "INSUFFICIENT_DEPTH",
         with_leg(["size"], "999999999"), entries, snapshots,
         "a size the displayed book cannot fill"),
        ("size-not-whole", "SIZE_NOT_WHOLE",
         with_leg(["size"], "924.5"), entries, snapshots,
         "a size that is not a whole number of contracts"),
        ("snapshot-not-supplied", "SNAPSHOT_NOT_SUPPLIED",
         with_leg(["acquisition", "snapshot"], "f" * 64), entries, snapshots,
         "a citation of a snapshot that was not supplied"),
        ("snapshot-not-a-book", "SNAPSHOT_NOT_A_BOOK",
         with_leg(["acquisition", "snapshot"], catalogue), entries, snapshots,
         "a leg citing the catalogue where a book belongs"),
        ("unsupported-acquisition", "UNSUPPORTED_ACQUISITION",
         with_leg(["acquisition", "path"], "split_and_sell"), entries, snapshots,
         "an acquisition path lowering does not price yet"),
        ("unsupported-family", "UNSUPPORTED_FAMILY", *repin(
            with_leg(["family"], "template.priceTouch"),
            dict(entries, **{"template.priceTouch": touch_entry(entries)}),
            "template.priceTouch"), snapshots,
         "a family lowering has no rule for"),
        ("no-payoff-for-side", "NO_PAYOFF_FOR_SIDE",
         with_leg(["side"], "long"), entries, snapshots,
         "a side the registry entry defines no payoff for"),
        ("unsupported-payoff", "UNSUPPORTED_PAYOFF", *repin(
            proposal, two_indicator_entries(entries), "recurring.priceBucket"), snapshots,
         "a payoff row that expands to more than one indicator"),
        ("catalogue-unreadable", "CATALOGUE_UNREADABLE",
         proposal, entries, unreadable_catalogue(snapshots, catalogue),
         "a catalogue description that is not key:value"),
    ]


def repin(proposal, entries, family):
    """Point the proposal at the edited entry, and mark that entry reviewed.

    Editing an entry moves its semantics_version, so without this the pin check fires
    before the rule under test and the fixture proves the wrong thing.
    """
    out = copy.deepcopy(entries)
    entry = out[family]
    plain = copy.deepcopy(entry)
    plain.pop("review", None)
    version = canon.semantics_version(entry)
    entry["review"] = {"state": "reviewed", "drafted_by": "model", "reviewed_by": "fixture",
                       "reviewed_on": "2026-09-19", "digest": version}
    proposal = copy.deepcopy(proposal)
    proposal["legs"][0]["semantics_version"] = version
    return proposal, out


def touch_entry(entries):
    """A priceTouch entry, so the refusal is the family rule and not a missing entry."""
    out = copy.deepcopy(entries["recurring.priceBucket"])
    out["family"] = "template.priceTouch"
    return out


def two_indicator_entries(entries):
    """A bucket entry whose index-0 YES pays on two intervals, which lowering refuses."""
    out = copy.deepcopy(entries)
    entry = copy.deepcopy(out["recurring.priceBucket"])
    for payoff in entry["payoffs"]:
        if payoff["select"].get("side") == "yes" and payoff["select"].get("index") == "0":
            payoff["pays"] = payoff["pays"] + copy.deepcopy(payoff["pays"])
    out["recurring.priceBucket"] = entry
    return out


def unreadable_catalogue(snapshots, digest):
    """The catalogue with one description that is not key:value."""
    out = dict(snapshots)
    document = json.loads(out[digest])
    for outcome in document.get("outcomes", []):
        if str(outcome.get("outcome")) == "3971":
            outcome["description"] = "nocolonhere"
            break
    raw = json.dumps(document).encode()
    out[sha256(raw).hexdigest()] = raw
    # The proposal still cites the original digest, so replace the bytes under it.
    out[digest] = raw
    return out


def generate():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    _, baseline_entries, baseline_snapshots = good()
    written, produced = 0, {}
    for name, expected, proposal, entries, snapshots, why in cases():
        parsed = {digest: json.loads(raw) for digest, raw in snapshots.items()}
        try:
            lowering.lower(proposal, entries, parsed)
            actual = "ACCEPTED"
        except lowering.Refused as refusal:
            actual = refusal.code
        produced[name] = actual
        document = {"schema_version": "1", "name": name, "expects": expected, "why": why,
                    "proposal": proposal}
        # Most cases run against the tree's own registry and the retained snapshots.
        # Only a case that needs a DIFFERENT input carries one, and it says which:
        # embedding a catalogue in every fixture would cost megabytes to say nothing.
        if entries != baseline_entries:
            document["registry"] = {family: entry for family, entry in sorted(entries.items())}
        if set(snapshots) != set(baseline_snapshots):
            document["snapshots"] = {digest: raw.decode()
                                     for digest, raw in sorted(snapshots.items())
                                     if baseline_snapshots.get(digest) != raw}
        elif any(baseline_snapshots[d] != raw for d, raw in snapshots.items()):
            document["snapshots"] = {digest: raw.decode()
                                     for digest, raw in sorted(snapshots.items())
                                     if baseline_snapshots.get(digest) != raw}
        (OUT / f"{name}.json").write_text(json.dumps(document, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        written += 1
    return written, produced


def main():
    checking = "--check" in sys.argv
    before = {}
    if checking and OUT.exists():
        before = {path.name: path.read_bytes() for path in sorted(OUT.glob("*.json"))}
    written, produced = generate()
    if checking:
        after = {path.name: path.read_bytes() for path in sorted(OUT.glob("*.json"))}
        if before != after:
            print("refusal fixtures are stale; run python3 tools/make_refusals.py", file=sys.stderr)
            return 1
    wrong = {name: got for name, got in produced.items()
             if got != next(expected for n, expected, *_ in cases() if n == name)}
    if wrong:
        for name, got in sorted(wrong.items()):
            expected = next(e for n, e, *_ in cases() if n == name)
            print(f"  {name}: expected {expected}, the oracle raised {got}", file=sys.stderr)
        return 1
    print(f"{written} refusal fixtures, one per code lowering can raise")
    return 0


if __name__ == "__main__":
    sys.exit(main())
