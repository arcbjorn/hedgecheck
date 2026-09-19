"""Offline checks for the live spike. No network: this runs inside `make check`.

    python3 spike/verify.py

Two things are held here. Discovery must find the live instruments in a retained
catalogue without being told which they are, and no file in `spike/` may contain a
literal outcome id or coin — an id that appears in source is configuration, and
configuration goes stale the moment the venue rolls the series over.
"""

from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PROJECT / "oracle"))

import canon  # noqa: E402
import exact  # noqa: E402

import check as checking  # noqa: E402
import discover  # noqa: E402

REPLAY = PROJECT / "fixtures" / "replay" / "2026-09-18"
CHECKS = 0

# Hand-derived, transcribed from git show 085ccfb:research/2026-09-18/verify.py.
# Discovery is given none of these: it is checked against them.
EXPECTED = {
    "expiry": "20260919-0600",
    "observation_time": "2026-09-19T06:00:00Z",
    "binary": {"outcome": "3965", "coin": "#39651", "target_price": "77457"},
    "bucket": {"outcome": "3971", "coin": "#39710", "thresholds": ["75908", "79007"]},
    "sizes": {"binary-no": "1409", "bucket0-yes": "924"},
    "costs": {"binary-no": "645.76904", "bucket0-yes": "160.76676"},
}


def check(condition, description):
    global CHECKS
    if not condition:
        raise AssertionError(description)
    CHECKS += 1


def no_literal_instruments():
    """No file under spike/ may name an outcome id or a coin.

    A four-digit integer in source is the shape an outcome id takes, and '#39651'
    is the shape a coin takes. Either one would pin the spike to a series that has
    already rolled over by the next morning.
    """
    coin = re.compile(r"[\"']#\d+[\"']")
    # Four- and five-digit bare integers, outside the obvious non-ids.
    ident = re.compile(r"(?<![\w.#/-])\d{4,5}(?![\w.])")
    # Prose may cite a historical id as evidence; code may not. Docstrings and comments
    # are stripped before the scan, so the rule bites exactly where it should.
    allowed = {"1500", "5000", "8785", "2026", "1000", "3000", "0000"}
    # This file is exempt and must be: it holds the hand-derived ids that discovery is
    # checked against. Those are expectations, not configuration -- if the spike's own
    # modules could name them, the check would be testing nothing.
    for path in sorted(ROOT.glob("*.py")):
        if path.name == "verify.py":
            continue
        source = path.read_text()
        code = _strip_prose(source)
        check(not coin.search(code), f"{path.name}: contains a literal coin")
        for line in code.splitlines():
            for found in ident.findall(line):
                check(found in allowed,
                      f"{path.name}: contains the literal {found}, which is the shape of an outcome id: {line.strip()[:70]}")


def _strip_prose(source):
    """Source with docstrings and comments removed, using the tokenizer, not a regex."""
    import io
    import tokenize

    out, previous = [], tokenize.INDENT
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            continue
        # A string in statement position is a docstring, never a value.
        if token.type == tokenize.STRING and previous in (tokenize.INDENT, tokenize.NEWLINE, tokenize.NL, tokenize.DEDENT):
            previous = token.type
            continue
        if token.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            out.append(token.string)
        previous = token.type
    return "\n".join(out)


def discovery_offline():
    """Discovery finds the live instruments in the retained catalogue, unaided."""
    catalogue = json.loads((REPLAY / "outcome-meta.json").read_text())
    expiry, legs = discover.candidates(catalogue, "BTC")
    check(expiry == EXPECTED["expiry"], f"discovery: soonest shared expiry is {EXPECTED['expiry']}")
    check(discover.expiry_to_iso(expiry) == EXPECTED["observation_time"], "discovery: expiry converts to the contract's instant")
    found = {leg["id"]: leg for leg in legs}
    check(set(found) == {"binary-no", "bucket0-yes"}, "discovery: both canonical candidates are found")
    check(found["binary-no"]["outcome"] == EXPECTED["binary"]["outcome"], "discovery: finds the binary instance without being told its id")
    check(found["binary-no"]["coin"] == EXPECTED["binary"]["coin"], "discovery: derives the binary NO coin from outcome and side")
    check(found["binary-no"]["terms"]["target_price"] == EXPECTED["binary"]["target_price"], "discovery: reads the target from the catalogue")
    check(found["bucket0-yes"]["outcome"] == EXPECTED["bucket"]["outcome"], "discovery: finds the bucket instance without being told its id")
    check(found["bucket0-yes"]["coin"] == EXPECTED["bucket"]["coin"], "discovery: derives the bucket YES coin from outcome and side")
    check(found["bucket0-yes"]["terms"]["thresholds"] == EXPECTED["bucket"]["thresholds"], "discovery: reads the thresholds from the parent question")
    check(found["bucket0-yes"]["terms"]["index"] == "0", "discovery: takes the lowest bucket, which is the one that pays below a threshold")

    # An underlying with no live series is not found, rather than guessed at.
    try:
        discover.candidates(catalogue, "DOGE")
        check(False, "discovery: refuses an underlying with no live series")
    except discover.NotFound:
        check(True, "discovery: refuses an underlying with no live series")

    # The retained catalogue holds exactly one binary and one bucket for BTC, so it
    # cannot exercise the choice between several. A synthetic catalogue does: a later
    # expiry must not be picked over a sooner one, and an expiry that has only one of
    # the two instruments is not a comparison and must not be chosen.
    later = _synthetic_catalogue()
    expiry, legs = discover.candidates(later, "BTC")
    check(expiry == "20260920-0600", "discovery: picks the soonest expiry that has both instruments")
    found = {leg["id"]: leg for leg in legs}
    check(found["binary-no"]["terms"]["target_price"] == "80000", "discovery: takes the binary from the chosen expiry, not another")
    check(found["bucket0-yes"]["terms"]["thresholds"] == ["79000", "81000"], "discovery: takes the bucket from the chosen expiry")
    check(found["bucket0-yes"]["coin"] == "#42010", "discovery: derives the coin from the chosen bucket's first named outcome")
    binary_only = {"outcomes": later["outcomes"], "questions": []}
    try:
        discover.candidates(binary_only, "BTC")
        check(False, "discovery: an expiry with only a binary is not a comparison")
    except discover.NotFound:
        check(True, "discovery: an expiry with only a binary is not a comparison")


def _synthetic_catalogue():
    """Two expiries, and one earlier expiry that has a binary but no bucket.

    Written here rather than retained: it is not evidence about the venue, it is a
    shape discovery has to handle and the real catalogue happens not to contain.
    """
    def binary(outcome, expiry, target):
        return {"outcome": outcome, "name": "Recurring",
                "description": f"class:priceBinary|underlying:BTC|expiry:{expiry}|targetPrice:{target}|period:1d",
                "sideSpecs": [{"name": "Yes"}, {"name": "No"}], "quoteToken": "USDC"}

    return {
        "outcomes": [
            binary(4300, "20260921-0600", "81000"),
            binary(4201, "20260920-0600", "80000"),
            binary(4100, "20260918-0600", "79000"),
        ] + [{"outcome": 4201 + offset, "name": "Recurring Named Outcome",
              "description": f"index:{offset}", "sideSpecs": [{"name": "Yes"}, {"name": "No"}],
              "quoteToken": "USDC"} for offset in (0, 1, 2)],
        "questions": [
            {"question": 400, "name": "Recurring",
             "description": "class:priceBucket|underlying:BTC|expiry:20260921-0600|priceThresholds:80000,82000|period:1d",
             "fallbackOutcome": 4310, "namedOutcomes": [4311, 4312, 4313], "settledNamedOutcomes": []},
            {"question": 401, "name": "Recurring",
             "description": "class:priceBucket|underlying:BTC|expiry:20260920-0600|priceThresholds:79000,81000|period:1d",
             "fallbackOutcome": 4200, "namedOutcomes": [4201, 4202, 4203], "settledNamedOutcomes": []},
        ],
    }


def evaluation_offline():
    """The same pure path the live run uses, driven from retained bytes."""
    raw, digests = {}, {}
    names = {"catalogue": "outcome-meta", "contexts": "meta-and-asset-ctxs",
             "binary-no": "book-3965-no", "bucket0-yes": "book-bucket0-3971-yes"}
    for name, stem in names.items():
        data = (REPLAY / f"{stem}.json").read_bytes()
        digest = sha256(data).hexdigest()
        raw[digest] = data
        digests[name] = digest
        record = json.loads((REPLAY / f"{stem}.request.json").read_text())
        check(record["response_sha256"] == digest, f"spike: {stem} matches its request record")

    capture = checking.parse_capture(raw, digests)
    baseline = checking.read_mark(capture["contexts"], "BTC")
    check(exact.format(baseline) == "77631.4", "spike: the baseline is read from the contexts snapshot")
    options = {"underlying": "BTC", "quantity": F("0.1"), "cap": F(1000), "floor": F(60000),
               "ceiling": F(110000), "baseline": baseline, "baseline_kind": "analysis_time",
               "valuation_time": None}
    evaluated = checking.evaluate_candidates(capture, options)
    check(evaluated["observation_time"] == EXPECTED["observation_time"], "spike: the observation time comes from the discovered expiry")

    for row in evaluated["rows"]:
        name = row["leg"]["id"]
        check(exact.format(row["size"]) == EXPECTED["sizes"][name], f"spike: {name} is sized at the smallest passing size")
        check(row["result"]["cost"]["premium"] == EXPECTED["costs"][name], f"spike: {name} costs the walked total")
        # The registry entries on disk are model drafts, so every leg is reduced by the
        # loose rule and nothing may be reported as a proven failure.
        check(row["result"]["model_result"] == "needs_review", f"spike: {name} needs review while its family is a draft")
        check(row["result"]["failing_intervals"] == [], f"spike: {name} proves no failure from a loose bound")

    reduction = checking.reduction_row(options)
    check(exact.format(reduction["keep"]) == "5000/88157", "spike: the reduction keeps 5000/88157 BTC")
    check(exact.format(reduction["worst"]) == "-1000", "spike: the reduction meets the cap exactly, with no premium")


def determinism():
    """The same bytes give the same result, which is what `replay` asserts live."""
    raw, digests = {}, {}
    names = {"catalogue": "outcome-meta", "contexts": "meta-and-asset-ctxs",
             "binary-no": "book-3965-no", "bucket0-yes": "book-bucket0-3971-yes"}
    for name, stem in names.items():
        data = (REPLAY / f"{stem}.json").read_bytes()
        raw[sha256(data).hexdigest()] = data
        digests[name] = sha256(data).hexdigest()
    options = {"underlying": "BTC", "quantity": F("0.1"), "cap": F(1000), "floor": F(60000),
               "ceiling": F(110000), "baseline": F("77631.4"), "baseline_kind": "analysis_time",
               "valuation_time": None}
    first = checking.evaluate_candidates(checking.parse_capture(raw, digests), options)
    second = checking.evaluate_candidates(checking.parse_capture(raw, digests), options)
    for left, right in zip(first["rows"], second["rows"]):
        check(canon.canonical(left["result"]) == canon.canonical(right["result"]),
              f"spike: {left['leg']['id']} evaluates to the same bytes twice")
        check(left["input_digest"] == right["input_digest"], f"spike: {left['leg']['id']} has a stable input_digest")


def network_isolation():
    """All network code lives in one module, checked on the import graph, not on prose.

    Every other file in spike/ must contain no import of a networking module at all,
    and live.py must not import net at module scope -- that is what lets `replay` run
    without the network module ever being loaded.
    """
    import ast

    networking = {"urllib", "urllib.request", "http", "http.client", "socket", "ssl", "requests", "httpx"}
    for path in sorted(ROOT.glob("*.py")):
        tree = ast.parse(path.read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        touches = imported & networking
        if path.name == "net.py":
            check(touches, "spike: net.py is the one module that imports a networking library")
        else:
            check(not touches, f"spike: {path.name} imports no networking library, it has {sorted(touches)}")

    # `import net` must appear only inside functions, so loading live.py does not load it.
    tree = ast.parse((ROOT / "live.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            check("net" not in {alias.name for alias in node.names},
                  "spike: live.py does not import net at module scope, so replay never loads it")
    check(True, "spike: live.py reaches the network only from inside the commands that need it")


def main():
    no_literal_instruments()
    discovery_offline()
    evaluation_offline()
    determinism()
    network_isolation()
    print(f"{CHECKS} checks passed; discovery finds the live instruments unaided and spike/ names no ids.")


if __name__ == "__main__":
    main()
