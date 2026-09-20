"""Check that the Python refuser accepts bundles the Go engine built.

    python3 tools/cross_accept.py

This is the first whole-result agreement between two implementations. Until now the
two agreed on numbers; here one writes a complete certificate bundle and the other
reads it, accepts the good one, and refuses each corrupted one with its stated class.

Offline. The Go binary is built from the tree, and the bundles are written to a
temporary directory that nothing else reads.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "oracle"))

import canon  # noqa: E402
import refuse  # noqa: E402

REPLAY = PROJECT / "fixtures" / "replay" / "2026-09-18"
CHECKS = 0


def check(condition, description):
    global CHECKS
    if not condition:
        raise AssertionError(description)
    CHECKS += 1


def build_engine(into):
    """Build the CLI from the tree, so this tests what is committed."""
    binary = into / "hedgecheck"
    result = subprocess.run(
        ["go", "build", "-o", str(binary), "./cmd/hedgecheck"],
        cwd=PROJECT / "engine", capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"go build failed:\n{result.stderr}")
    return binary


def go_bundle(binary, proposal, into, name):
    """Have Go write a bundle, and return its directory and exit status."""
    directory = into / name
    result = subprocess.run(
        [str(binary), "bundle", "--proposal", str(proposal),
         "--registry", str(PROJECT / "registry"), "--snapshots", str(REPLAY),
         "--out", str(directory), "--reviewed"],
        capture_output=True, text=True)
    if result.returncode not in (0, 1, 2):
        raise AssertionError(f"go bundle {name}: exit {result.returncode}\n{result.stderr}")
    return directory, result.returncode


def corrupt(directory, into, name, mutate):
    """A copy of a Go bundle with exactly one documented change."""
    target = into / name
    shutil.copytree(directory, target)
    mutate(target)
    return target


def main():
    with tempfile.TemporaryDirectory() as workspace:
        workspace = Path(workspace)
        binary = build_engine(workspace)

        # ---- the good bundles: Go writes, Python accepts
        accepted = 0
        for proposal in sorted(REPLAY.glob("*.proposal.json")):
            name = proposal.name.replace(".proposal.json", "")
            directory, status = go_bundle(binary, proposal, workspace, name)
            outcome = refuse.refuse_directory(directory)
            detail = "" if outcome["accepted"] else outcome["refusal"]["detail"]
            check(outcome["accepted"],
                  f"{name}: the Python refuser accepts the Go bundle ({detail})")
            manifest = canon.loads((directory / "manifest.json").read_bytes())
            check(manifest["expects"] == "accept", f"{name}: a good bundle expects acceptance")
            check(status in (0, 1, 2), f"{name}: the exit status is a verdict, not an error")
            accepted += 1
        check(accepted >= 3, "every replay proposal bundles")

        # ---- the corruptions, applied to a GO-produced bundle
        base, _ = go_bundle(binary, REPLAY / "bucket0.proposal.json", workspace, "base")

        def edit(path, change):
            def apply(directory):
                document = canon.loads((directory / path).read_bytes())
                change(document)
                (directory / path).write_bytes(canon.canonical(document) + b"\n")
            return apply

        def drop_strike(document):
            profile = document["profile"]
            merged = dict(profile[0])
            merged["upper"] = profile[1]["upper"]
            merged["upper_inclusive"] = profile[1]["upper_inclusive"]
            document["profile"] = [merged] + profile[2:]

        corruptions = [
            ("strike-removed", "PROFILE_COVERAGE", edit("result.json", drop_strike)),
            ("ownership-swapped", "ENDPOINT_OWNERSHIP", edit("result.json", swap_ownership)),
            ("verdict-changed", "VERDICT_MISMATCH", edit("result.json", flip_verdict)),
            ("interval-widened", "INTERVAL_MISMATCH", edit("result.json", widen_interval)),
            ("book-byte-changed", "SNAPSHOT_BYTES", change_a_book),
        ]
        refused = 0
        for name, expected, mutate in corruptions:
            directory = corrupt(base, workspace, name, mutate)
            outcome = refuse.refuse_directory(directory)
            actual = "accept" if outcome["accepted"] else outcome["refusal"]["class"]
            check(actual == expected,
                  f"{name}: a corrupted Go bundle is refused with {expected}, got {actual}")
            refused += 1

        print(f"cross-acceptance: {accepted} Go bundles accepted by the Python refuser, "
              f"{refused} corruptions refused by class ({CHECKS} checks)")
    return 0


def swap_ownership(document):
    profile = document["profile"]
    if len(profile) < 2:
        raise AssertionError("the bundle has no strike to swap")
    profile[0]["upper_inclusive"] = not profile[0]["upper_inclusive"]
    profile[1]["lower_inclusive"] = not profile[1]["lower_inclusive"]


def flip_verdict(document):
    document["model_result"] = "fails" if document["model_result"] != "fails" else "passes"


def widen_interval(document):
    for key in ("failing_intervals", "undecided_intervals"):
        if document.get(key):
            interval = document[key][0]
            interval["upper"] = _bump(interval["upper"])
            return
    # A passing bundle has neither, so invent a failing interval the payoff denies.
    document["failing_intervals"] = [{
        "lower": document["profile"][0]["lower"], "lower_inclusive": True,
        "upper": document["profile"][0]["upper"], "upper_inclusive": False,
        "clause": document.get("reason_codes") and "loss_cap" or "loss_cap",
        "witness": {"price": document["profile"][0]["lower"], "pnl": "0"},
    }]


def _bump(text):
    from fractions import Fraction as F
    sys.path.insert(0, str(PROJECT / "oracle"))
    import exact
    return exact.format(exact.parse(text) + F(1, 100))


def change_a_book(directory):
    for path in sorted(directory.glob("snapshot-*.json")):
        raw = path.read_bytes()
        if b'"levels"' in raw and b'"0.17399"' in raw:
            path.write_bytes(raw.replace(b'"0.17399"', b'"0.17398"', 1))
            return
    raise AssertionError("no book snapshot to change")


if __name__ == "__main__":
    sys.exit(main())
