"""T1 live spike: discover, capture, lower, evaluate, replay. T2 deletes this.

    python3 spike/live.py check --underlying BTC --quantity 0.1 --cap 1000 \
        --floor 60000 --ceiling 110000 --baseline analysis_time --valuation-time next-expiry
    python3 spike/live.py replay <input_digest>
    python3 spike/live.py retain <input_digest>

`check` is the only command that touches the network, and it reaches it through
`spike/net.py` alone. `replay` and `retain` never import that module: a replay that
could fetch would not be a replay.

There are no defaults for `--baseline` or `--valuation-time`. Both decide what the
answer means, so both are stated every run. `next-expiry` is an explicit choice of
the contract's own time, and it is echoed back as that time.
"""

import argparse
from datetime import datetime, timezone
from fractions import Fraction as F
import json
from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(PROJECT / "oracle"))

import canon  # noqa: E402
import exact  # noqa: E402

import check as checking  # noqa: E402
import store as storage  # noqa: E402

VAR = PROJECT / "var" / "store"

# The contexts response carries no venue timestamp; books do. So the only measurable
# skew in a captured set is between a book's venue time and our own local retrieval
# time, which bundles clock error, network latency and the gap between the two calls.
# MAX_SKEW is a proposal from measurement, not a documented figure: see EVIDENCE
# section 4 and `python3 spike/live.py skew`.
MAX_SKEW_MS = 5000


def utc_now():
    return datetime.now(timezone.utc)


def parse_iso(text):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", text):
        raise argparse.ArgumentTypeError(f"{text!r} is not an instant like 2026-09-19T06:00:00Z")
    return text


def parse_baseline(text):
    if text == "analysis_time":
        return "analysis_time", None
    if text.startswith("explicit:"):
        return "explicit", exact.parse(text.split(":", 1)[1])
    raise argparse.ArgumentTypeError("--baseline is analysis_time or explicit:<price>")


def measure_skew(record, book_records, books):
    """Book venue time against our local retrieval time, per book, in milliseconds.

    Positive means the book's venue clock reads later than our clock did when the
    response arrived. The contexts response has no venue time at all, so its own
    retrieval time is the anchor everything else is measured against.
    """
    anchor = datetime.fromisoformat(record["retrieved_at"])
    out = {}
    for name, book in books.items():
        venue_ms = int(book["time"])
        local_ms = int(datetime.fromisoformat(book_records[name]["retrieved_at"]).timestamp() * 1000)
        out[name] = {
            "book_venue_ms": venue_ms,
            "local_retrieved_ms": local_ms,
            "skew_ms": venue_ms - local_ms,
            "contexts_gap_ms": local_ms - int(anchor.timestamp() * 1000),
        }
    return out


def capture_live(client, underlying, expiry=None):
    """One coherent set: catalogue, contexts, then a book per candidate leg.

    The catalogue comes first because the coins are discovered from it, and the
    contexts come before the books so the baseline is never newer than the prices
    it is compared against.
    """
    import net  # imported here so `replay` and `retain` never load it
    import discover

    catalogue_digest, catalogue_raw, catalogue_record = net.catalogue(client)
    catalogue = json.loads(catalogue_raw)
    expiry, legs = discover.candidates(catalogue, underlying, expiry)

    contexts_digest, contexts_raw, contexts_record = net.contexts(client)

    snapshots = {catalogue_digest: catalogue_raw, contexts_digest: contexts_raw}
    digests = {"catalogue": catalogue_digest, "contexts": contexts_digest}
    books, book_records = {}, {}
    for leg in legs:
        digest, raw, record = net.book(client, leg["coin"])
        snapshots[digest] = raw
        digests[leg["id"]] = digest
        books[leg["id"]] = json.loads(raw)
        book_records[leg["id"]] = record

    skew = measure_skew(contexts_record, book_records, books)
    return snapshots, digests, expiry, skew, {"catalogue": catalogue_record, "contexts": contexts_record}


def fmt_intervals(intervals):
    if not intervals:
        return "nowhere"
    return ", ".join(f"{'[' if i['lower_inclusive'] else '('}{i['lower']}, "
                     f"{i['upper']}{']' if i['upper_inclusive'] else ')'}" for i in intervals)


def print_table(evaluated, reduction, options):
    rows = []
    for row in evaluated["rows"]:
        result = row.get("result")
        if not result:
            rows.append((row["leg"]["id"], "no size on the displayed book", "-", "-", "-", "-"))
            continue
        better = result["comparisons"]["smallest_reduction"]["proposal_better"]
        rows.append((
            f"{row['leg']['id']} x{row['size']}",
            result["model_result"],
            result["cost"]["premium"],
            result["cost"]["pnl_at_baseline"],
            ", ".join(result["cost"]["breakevens"]) or "none",
            fmt_intervals(better),
        ))
    rows.append((
        f"sell {exact.format(reduction['sell'])} BTC, keep {exact.format(reduction['keep'])}",
        "passes", "0", exact.format(reduction["pnl_at_baseline"]), "none", "-",
    ))

    headers = ("instrument", "verdict", "cost", "P&L if flat", "break-evens", "beats the reduction on")
    widths = [max(len(str(row[i])) for row in (headers,) + tuple(rows)) for i in range(len(headers))]
    line = "  ".join(header.ljust(width) for header, width in zip(headers, widths))
    print(line)
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(str(cell).ljust(width) for cell, width in zip(row, widths)))


def command_check(args):
    import net  # the one module that reaches the network

    baseline_kind, explicit_price = args.baseline
    store = storage.Store(VAR)
    client = net.Client(store)

    snapshots, digests, expiry, skew, _records = capture_live(client, args.underlying)
    capture = checking.parse_capture(snapshots, digests, expiry)

    worst_skew = max(abs(entry["skew_ms"]) for entry in skew.values()) if skew else 0
    if worst_skew > MAX_SKEW_MS:
        print(f"refused: worst book-to-local skew {worst_skew} ms exceeds MAX_SKEW {MAX_SKEW_MS} ms", file=sys.stderr)
        return 2

    baseline = explicit_price if baseline_kind == "explicit" else checking.read_mark(capture["contexts"], args.underlying)
    observation_time = __import__("discover").expiry_to_iso(expiry)
    valuation_time = observation_time if args.valuation_time == "next-expiry" else args.valuation_time

    options = {"underlying": args.underlying, "quantity": args.quantity, "cap": args.cap,
               "floor": args.floor, "ceiling": args.ceiling, "baseline": baseline,
               "baseline_kind": baseline_kind, "valuation_time": valuation_time}
    # The capturer asserts what it measured. A pure evaluator cannot re-derive this,
    # so the result records the claim rather than establishing it.
    provenance = {"skew_ms": str(worst_skew), "max_skew_ms": str(MAX_SKEW_MS),
                  "measured_by": "spike/live.py check"}
    evaluated = checking.evaluate_candidates(capture, options, provenance=provenance)
    reduction = checking.reduction_row(options)

    print(f"captured {len(digests)} snapshots, {client.spent} requests")
    print(f"expiry {expiry} -> observation {evaluated['observation_time']}")
    print(f"valuation time {evaluated['valuation_time']}"
          + (" (the contract's own time, chosen by --valuation-time next-expiry)"
             if args.valuation_time == "next-expiry" else ""))
    print(f"baseline {exact.format(baseline)} ({baseline_kind})")
    for name, entry in skew.items():
        print(f"skew {name}: book venue - local retrieval = {entry['skew_ms']} ms"
              f", contexts to book gap {entry['contexts_gap_ms']} ms")
    print()
    print_table(evaluated, reduction, options)
    print()

    document = checking.run_document(capture, evaluated, options, skew, provenance)
    for row in evaluated["rows"]:
        if row.get("input_digest"):
            store.put_run(row["input_digest"], dict(document, leg=row["leg"]["id"]))
            print(f"{row['leg']['id']}: input_digest {row['input_digest']}")
    if any(row.get("result", {}).get("model_result") == "needs_review" for row in evaluated["rows"]):
        print()
        print("needs_review: the registry entries are still model drafts, so each hedge leg is")
        print("valued at zero by the loose rule unreviewed_family. Nothing here is proven to fail.")
    return 0


def command_replay(args):
    """Recompute a result from stored snapshots only. No network module is imported."""
    store = storage.Store(VAR)
    document = store.run(args.input_digest)
    digests = document["digests"]
    snapshots = {digest: store.get(digest) for digest in digests.values()}
    capture = checking.parse_capture(snapshots, digests, document["expiry"])

    options = dict(document["options"])
    for key in ("quantity", "cap", "floor", "ceiling", "baseline"):
        options[key] = exact.parse(options[key])
    stored = document.get("capture")
    evaluated = checking.evaluate_candidates(capture, options, provenance=stored)

    leg_id = document["leg"]
    row = next(row for row in evaluated["rows"] if row["leg"]["id"] == leg_id)
    before = canon.canonical(document["results"][leg_id])
    after = canon.canonical(row["result"])
    if before != after:
        print(f"replay differs for {leg_id}", file=sys.stderr)
        return 1
    if row["input_digest"] != args.input_digest:
        print(f"replay recomputed a different input_digest: {row['input_digest']}", file=sys.stderr)
        return 1
    print(f"replay of {args.input_digest[:16]} ({leg_id}): byte-identical, {len(after)} bytes")
    print(f"verdict {row['result']['model_result']}, cost {row['result']['cost']['premium']}")
    return 0


def command_retain(args):
    """Copy a run's snapshots and documents into fixtures/ for the owner to commit."""
    store = storage.Store(VAR)
    document = store.run(args.input_digest)
    target = PROJECT / "fixtures" / "replay" / utc_now().strftime("%Y-%m-%d")
    target.mkdir(parents=True, exist_ok=True)
    for name, digest in document["digests"].items():
        (target / f"{name}.json").write_bytes(store.get(digest))
        (target / f"{name}.request.json").write_text(json.dumps(store.record(digest), indent=2) + "\n")
    (target / f"{document['leg']}.run.json").write_text(json.dumps(document, indent=2) + "\n")
    print(f"retained {len(document['digests'])} snapshots and the run document into {target.relative_to(PROJECT)}")
    print("the bytes are unchanged and each keeps its request record; commit them as evidence")
    return 0


def command_skew(args):
    """Measure the book-to-local skew over several capture sets, to propose MAX_SKEW."""
    import net
    import discover

    store = storage.Store(VAR)
    client = net.Client(store, budget=min(args.samples * 3 + 2, net.MAX_REQUESTS))
    catalogue_digest, catalogue_raw, _ = net.catalogue(client)
    catalogue = json.loads(catalogue_raw)
    expiry, legs = discover.candidates(catalogue, args.underlying)

    samples = []
    while len(samples) < args.samples and client.spent + 2 <= client.budget:
        _, _, contexts_record = net.contexts(client)
        digest, raw, record = net.book(client, legs[0]["coin"])
        book = json.loads(raw)
        measured = measure_skew(contexts_record, {"book": record}, {"book": book})["book"]
        samples.append(measured)
        print(f"  sample {len(samples):2d}: skew {measured['skew_ms']:6d} ms, "
              f"contexts to book {measured['contexts_gap_ms']:5d} ms")

    values = sorted(sample["skew_ms"] for sample in samples)
    gaps = sorted(sample["contexts_gap_ms"] for sample in samples)
    print()
    print(f"{len(values)} samples of book venue time minus local retrieval time:")
    print(f"  min {values[0]} ms, median {values[len(values) // 2]} ms, max {values[-1]} ms")
    print(f"  contexts-to-book gap: min {gaps[0]} ms, median {gaps[len(gaps) // 2]} ms, max {gaps[-1]} ms")
    print(f"current MAX_SKEW_MS is {MAX_SKEW_MS}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="spike/live.py", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("check", help="capture, evaluate and print the comparison")
    run.add_argument("--underlying", required=True)
    run.add_argument("--quantity", required=True, type=exact.parse)
    run.add_argument("--cap", required=True, type=exact.parse)
    run.add_argument("--floor", required=True, type=exact.parse)
    run.add_argument("--ceiling", required=True, type=exact.parse)
    run.add_argument("--baseline", required=True, type=parse_baseline,
                     help="analysis_time, or explicit:<price>. No default: it decides what the answer means")
    run.add_argument("--valuation-time", required=True,
                     help="an instant like 2026-09-19T06:00:00Z, or next-expiry to choose the contract's own time")
    run.set_defaults(handler=command_check)

    replay = commands.add_parser("replay", help="recompute a stored result from stored snapshots")
    replay.add_argument("input_digest")
    replay.set_defaults(handler=command_replay)

    retain = commands.add_parser("retain", help="copy a run's snapshots into fixtures/ as evidence")
    retain.add_argument("input_digest")
    retain.set_defaults(handler=command_retain)

    skew = commands.add_parser("skew", help="measure the capture skew distribution")
    skew.add_argument("--underlying", required=True)
    skew.add_argument("--samples", type=int, default=20)
    skew.set_defaults(handler=command_skew)

    args = parser.parse_args(argv)
    if args.command == "check" and args.valuation_time != "next-expiry":
        parse_iso(args.valuation_time)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
