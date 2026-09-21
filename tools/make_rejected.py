"""Write the refused mutations out as documents, so every language can use them.

    python3 tools/make_rejected.py          # regenerate, then check
    python3 tools/make_rejected.py --check  # fail if anything on disk is stale

A mutation living as Python inside `tools/validate.py` can only be run by Python. The
Go decoder and the TypeScript checker must refuse exactly the same documents, and the
only way to hold them to that is to make the documents shared data.

Each file is a whole document that its schema must refuse, beside a `.why` naming the
constraint it violates in one sentence. Valid documents need no generator: every
fixture already in `fixtures/` is an accepted case.
"""

import copy
import json
from pathlib import Path
import shutil
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "oracle"))

import canon  # noqa: E402

OUT = PROJECT / "fixtures" / "rejected"

DELETE = object()


def mutate(document, path, value=DELETE):
    """A deep copy with one change: set path to value, or delete it when value is omitted."""
    out = copy.deepcopy(document)
    node = out
    for step in path[:-1]:
        node = node[step]
    if value is DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return out


def sources():
    """The documents the mutations are made from: real, valid, already in the tree."""
    lowered = canon.loads((PROJECT / "fixtures/golden/1000-contracts.ir.json").read_bytes())
    result = canon.loads((PROJECT / "fixtures/golden/1000-contracts.result.json").read_bytes())
    entry = canon.loads((PROJECT / "registry/recurring.priceBinary.json").read_bytes())
    proposal = canon.loads((PROJECT / "fixtures/replay/2026-09-18/bucket0.proposal.json").read_bytes())
    manifest = canon.loads((PROJECT / "fixtures/bundles/good/manifest.json").read_bytes())
    comparison = {
        "schema_version": "1",
        "shared": {"domain": lowered["domain"], "baseline": lowered["baseline"],
                   "objective": lowered["objective"],
                   "objective_valuation_time": lowered["objective_valuation_time"]},
        "candidates": [{"label": "binary", "ir_digest": "a" * 64, "model_result": "passes", "cost": "645.76904"},
                       {"label": "bucket0", "ir_digest": "b" * 64, "model_result": "passes", "cost": "160.76676"}],
        "ranked_by": "cost_of_smallest_passing_size",
        "ranking": ["bucket0", "binary"],
        "engine_version": "reference-oracle-3",
    }
    return lowered, result, entry, proposal, manifest, comparison


def envelope(**changes):
    """A well-formed order envelope, then exactly one thing wrong with it.

    The numbers are the 18 September binary walk, hand-derived from
    fixtures/replay/2026-09-18/book-3965-no.json and written down here rather than
    taken from any implementation: 1,409 contracts fill 36 + 115 + 1000 + 41 + 40 +
    21 + 40 + 40 + 50 = 1,383 through 0.48123, so the last 26 come from the 0.48404
    level and that level is the highest the walk touched. The total in units of
    1e-5 is 1623600 + 5203750 + 45600000 + 1875750 + 1840000 + 969150 + 1880000 +
    1920000 + 2406150 + 1258504 = 64576904.
    """
    out = {"coin": "#39651", "side": "buy", "size": "1409", "limit_price": "0.48404",
           "time_in_force": "Ioc", "max_cost": "645.76904", "input_digest": "c" * 64}
    drop = changes.pop("drop", None)
    if drop is not None:
        del out[drop]
    out.update(changes)
    return out


def cases():
    lowered, result, entry, proposal, manifest, comparison = sources()
    book = "d62ba1359f45abc313840ed63deef8d705fcc9bd988ca0f29e9412d8e2cd1ef1"
    return [
        # ---- the number grammar, which a rational library would accept and the schema must not
        ("ir", "size-exponent", mutate(lowered, ["legs", 0, "size"], "1e3"), "an exponent"),
        ("ir", "size-trailing-newline", mutate(lowered, ["legs", 0, "size"], "5\n"),
         "a trailing newline, which Python's own $ would let through"),
        ("ir", "size-hexadecimal", mutate(lowered, ["legs", 0, "size"], "0x10"), "a hexadecimal number"),
        ("ir", "domain-leading-zero", mutate(lowered, ["domain", "lower"], "05"), "a leading zero"),
        # ---- endpoint ownership is never implied
        ("ir", "bound-without-owner", mutate(lowered, ["legs", 0, "pays_on", "upper_inclusive"]),
         "a bound that does not say who owns it"),
        ("ir", "indicator-pays-nowhere", mutate(lowered, ["legs", 0, "pays_on"], {}),
         "an indicator that pays nowhere in particular"),
        # ---- a grouped reduction names its other legs, and they are leg ids
        #
        # `with` exists because the band reduction acts on a GROUP: the infimum of a sum
        # is not the sum of infima, so reducing leg by leg invents a loss on a hedge whose
        # legs cancel. The field is bounded, not free text: an empty list is not a group,
        # and a member is a leg id.
        ("ir", "grouped-reduction-empty", mutate(lowered, ["reductions"], [
            {"leg": "bucket0-yes", "rule": "basis_band", "tight": False,
             "reason_code": "BASIS_BAND", "with": []}]),
         "a grouped reduction whose group is empty"),
        ("ir", "grouped-reduction-not-a-leg", mutate(lowered, ["reductions"], [
            {"leg": "bucket0-yes", "rule": "basis_band", "tight": False,
             "reason_code": "BASIS_BAND", "with": ["Not A Leg"]}]),
         "a grouped reduction naming something that is not a leg id"),
        # ---- the baseline and the objective are required and explicit
        ("ir", "baseline-missing", mutate(lowered, ["baseline"]), "a missing baseline"),
        ("ir", "baseline-unknown-kind", mutate(lowered, ["baseline", "kind"], "strike_reference"),
         "an unknown baseline kind"),
        ("ir", "objective-empty", mutate(lowered, ["objective"], []), "an empty objective"),
        ("ir", "breakpoints-beside-the-function", mutate(lowered, ["breakpoints"], ["90000"]),
         "breakpoints passed beside the function"),
        ("ir", "time-not-utc", mutate(lowered, ["objective_valuation_time"], "2026-01-02T06:00:00+00:00"),
         "a time that is not UTC 'Z'"),
        # ---- a walked cost carries its provenance
        ("ir", "walked-without-snapshot",
         mutate(lowered, ["legs", 0, "premium"], {"kind": "walked", "total": "645.76904", "path": "direct_book"}),
         "a walked cost that does not cite the book it walked"),
        ("ir", "walked-unknown-path",
         mutate(lowered, ["legs", 0, "premium"],
                {"kind": "walked", "total": "645.76904", "path": "guessed", "snapshot": book}),
         "a walked cost on an unnamed acquisition path"),
        ("ir", "walked-per-unit-price",
         mutate(lowered, ["legs", 0, "premium"],
                {"kind": "walked", "price": "0.2", "path": "direct_book", "snapshot": book}),
         "a walked cost carrying a per-unit price instead of a total"),
        # ---- reductions declare their tightness and their reason
        ("ir", "reduction-without-tightness",
         mutate(lowered, ["reductions"],
                [{"leg": "put", "rule": "horizon_mismatch", "reason_code": "LEG_WORST_CASED_HORIZON"}]),
         "a reduction that does not say whether it is tight"),
        ("ir", "reduction-tightness-as-string",
         mutate(lowered, ["reductions"],
                [{"leg": "put", "rule": "horizon_mismatch", "tight": "yes", "reason_code": "LEG_WORST_CASED_HORIZON"}]),
         "a tightness that is a string rather than a boolean"),

        # ---- results
        ("result", "verdict-unknown", mutate(result, ["model_result"], "unproven"), "an unknown verdict"),
        ("result", "reason-code-lowercase", mutate(result, ["reason_codes"], ["loss_bound_exceeded"]),
         "a lowercase reason code"),
        ("result", "failing-interval-without-witness", mutate(result, ["failing_intervals", 0, "witness"]),
         "a failing interval without a witness"),
        ("result", "piece-without-ownership", mutate(result, ["profile", 0, "lower_inclusive"]),
         "a piece without endpoint ownership"),
        ("result", "digest-malformed", mutate(result, ["ir_digest"], "09B3"), "a malformed digest"),
        ("result", "window-smallest-without-largest",
         mutate(result, ["size_windows"], [{"leg": "put", "status": "nonempty", "binding": [], "smallest": "1409"}]),
         "a size window with a smallest size but no largest"),
        ("result", "window-unknown-status",
         mutate(result, ["size_windows"], [{"leg": "put", "status": "maybe", "binding": []}]),
         "a size window that is neither empty nor nonempty"),
        ("result", "binding-site-unknown-side",
         mutate(result, ["size_windows"],
                [{"leg": "put", "status": "empty", "binding": [{"price": "60000", "side": "near"}]}]),
         "a binding site that is not at, above or below a price"),
        ("result", "certificate-one-weight",
         mutate(result, ["size_windows"],
                [{"leg": "put", "status": "empty", "binding": [],
                  "certificate": {"kind": "farkas", "weights": ["0.8"]}}]),
         "an infeasibility certificate with one weight instead of two"),
        ("result", "reduction-without-reason",
         mutate(result, ["reductions"], [{"leg": "put", "rule": "horizon_mismatch", "tight": True}]),
         "a reduction in a result without its reason code"),
        ("result", "alternative-without-keep",
         mutate(result, ["comparisons", "smallest_reduction", "keep_quantity"]),
         "an alternative that does not say how much to keep"),
        ("result", "alternative-missing", mutate(result, ["comparisons", "smallest_reduction"]),
         "a result without the no-premium alternative"),

        # ---- order envelopes. The cost bound is about ONE order; an envelope that
        # names a different one carries the bound somewhere it does not apply.
        ("result", "envelope-resting", mutate(result, ["order_envelope"], envelope(time_in_force="Gtc")),
         "an order envelope that would rest on the book instead of cancelling"),
        ("result", "envelope-sells", mutate(result, ["order_envelope"], envelope(side="sell")),
         "an order envelope on the sell side, which no ask walk bounds"),
        ("result", "envelope-without-limit", mutate(result, ["order_envelope"], envelope(drop="limit_price")),
         "an order envelope with no limit price"),
        ("result", "envelope-without-digest", mutate(result, ["order_envelope"], envelope(drop="input_digest")),
         "an order envelope that does not say which result it belongs to"),
        ("result", "envelope-coin-is-a-ticker", mutate(result, ["order_envelope"], envelope(coin="BTC")),
         "an order envelope naming a ticker where the venue's own id belongs"),

        # ---- registry entries
        ("registry-entry", "review-state-unknown", mutate(entry, ["review", "state"], "approved"),
         "an unknown review state"),
        ("registry-entry", "without-a-source", mutate(entry, ["sources"], []), "an entry without a source"),
        ("registry-entry", "evidence-label-unknown", mutate(entry, ["evidence", 0, "label"], "verified"),
         "an evidence label outside V, T, U"),
        # A digest, and no reviewer beside it. The whole review block is replaced so
        # the corruption is the same whether the entry on disk is a draft or reviewed:
        # setting the digest alone was enough while every entry was a draft, but once
        # an entry carries a real reviewer it produced a VALID block and the fixture
        # stopped corrupting anything.
        ("registry-entry", "review-digest-without-reviewer",
         mutate(entry, ["review"],
                {"state": "reviewed", "drafted_by": "model", "digest": canon.semantics_version(entry)}),
         "a review digest without a reviewer and a date"),

        # ---- comparisons
        ("comparison", "one-candidate", mutate(comparison, ["candidates"], comparison["candidates"][:1]),
         "a comparison of one candidate"),
        ("comparison", "candidate-not-a-digest", mutate(comparison, ["candidates", 0, "ir_digest"], "not-a-digest"),
         "a candidate cited by something other than a digest"),
        ("comparison", "ranking-rule-unknown", mutate(comparison, ["ranked_by"], "cheapest"),
         "an unknown ranking rule"),
        ("comparison", "shared-terms-missing", mutate(comparison, ["shared"]),
         "a comparison that does not state the terms its candidates share"),

        # ---- proposals: the same rules, on the document a person actually writes
        ("proposal", "leg-without-semantics-pin", mutate(proposal, ["legs", 0, "semantics_version"]),
         "a leg that pins no reading of its family"),
        ("proposal", "size-not-a-number", mutate(proposal, ["legs", 0, "size"], "many"),
         "a size that is not a number"),
        ("proposal", "assumptions-missing", mutate(proposal, ["assumptions"]),
         "a proposal that states no assumptions"),
        ("proposal", "capture-skew-fractional",
         mutate(proposal, ["capture", "skew_ms"], "-687.5"),
         "a skew in fractional milliseconds, which are counted rather than measured"),

        # ---- bundle manifests
        ("bundle-manifest", "expects-unknown-class", mutate(manifest, ["expects"], "SOMETHING_ELSE"),
         "an expectation outside the closed list of refusal classes"),
        ("bundle-manifest", "files-missing", mutate(manifest, ["files"]),
         "a manifest that lists no files"),
    ]


def generate():
    if OUT.exists():
        shutil.rmtree(OUT)
    written = 0
    for schema, name, document, why in cases():
        directory = OUT / schema
        directory.mkdir(parents=True, exist_ok=True)
        # Written with json, not canon: a rejected document may be outside the canonical
        # profile, which is sometimes the very thing being rejected.
        (directory / f"{name}.json").write_text(json.dumps(document, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        (directory / f"{name}.why").write_text(why + "\n")
        written += 1
    return written


def main():
    checking = "--check" in sys.argv
    before = {}
    if checking and OUT.exists():
        before = {path.relative_to(OUT): path.read_bytes() for path in sorted(OUT.rglob("*"))
                  if path.is_file()}
    written = generate()
    if checking:
        after = {path.relative_to(OUT): path.read_bytes() for path in sorted(OUT.rglob("*")) if path.is_file()}
        if before != after:
            changed = sorted({str(name) for name in set(before) | set(after) if before.get(name) != after.get(name)})
            print(f"rejected fixtures are stale: {', '.join(changed[:3])}", file=sys.stderr)
            return 1
    schemas = sorted({schema for schema, _, _, _ in cases()})
    print(f"{written} rejected documents across {len(schemas)} schemas: {', '.join(schemas)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
