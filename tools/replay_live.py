"""Rebuild a store from a retained live bundle and replay it, offline.

    python3 tools/replay_live.py fixtures/live/2026-10-05

NO NETWORK, no key, nothing placed. Every byte comes from the bundle in the repository.

WHY THIS EXISTS. `hedgecheck retain` writes a bundle whose bytes ARE the evidence -- each
snapshot's digest is `sha256` of the file exactly as the venue sent it -- but `replay` reads a
STORE, not a directory, and the mapping between the two (`snapshots/<digest>.json`,
`runs/<input digest>.json`) is not something a reader should have to reconstruct by hand. A
piece of evidence nobody can check without first guessing a directory layout is not usable
evidence, so the reconstruction is a command.

It checks the digests BEFORE replaying, which is the part that matters: a bundle whose bytes no
longer hash to the digests its run document names has been edited, and replaying it would
report agreement between two things that were both changed together.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

# The four responses one `check --live` captures, and the file each is retained as.
SNAPSHOTS = {
    "binary-no": "binary-no.json",
    "bucket0-yes": "bucket0-yes.json",
    "catalogue": "catalogue.json",
    "contexts": "contexts.json",
}


def digest_of(path):
    """sha256 over the bytes AS RETAINED. Not canonicalised: the venue's bytes are the fact.

    `oracle/canon.py` deliberately refuses JSON numbers, because this project's own documents
    write exact values as strings. A venue response is full of raw numbers, so it is digested
    as received -- which is also what makes the digest a statement about what arrived rather
    than about our reading of it.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if len(sys.argv) != 2:
        print("python3 tools/replay_live.py fixtures/live/<date>")
        return 4
    bundle = Path(sys.argv[1])
    if not bundle.is_absolute():
        bundle = PROJECT / bundle
    runs = sorted(bundle.glob("*.run.json"))
    if len(runs) != 1:
        print(f"{bundle}: expected exactly one *.run.json, found {len(runs)}")
        return 4
    run = json.loads(runs[0].read_text())
    leg = run["leg"]
    input_digest = run["input_digests"][leg]

    # DIGESTS FIRST. An edited bundle must fail here, not quietly replay.
    for name, filename in SNAPSHOTS.items():
        path = bundle / filename
        if not path.exists():
            print(f"{bundle}: {filename} is missing")
            return 4
        found, stated = digest_of(path), run["digests"][name]
        if found != stated:
            print(f"{filename}: bytes hash to {found[:16]}, the run document names "
                  f"{stated[:16]} -- this bundle has been edited")
            return 1
    print(f"{len(SNAPSHOTS)} snapshot digests re-derived from the retained bytes")

    store = Path(tempfile.mkdtemp(prefix="hedgecheck-replay-"))
    try:
        for directory in ("snapshots", "runs", "results"):
            (store / directory).mkdir()
        for filename in SNAPSHOTS.values():
            path = bundle / filename
            found = digest_of(path)
            shutil.copyfile(path, store / "snapshots" / f"{found}.json")
            record = bundle / filename.replace(".json", ".request.json")
            if record.exists():
                shutil.copyfile(record, store / "snapshots" / f"{found}.request.json")
        shutil.copyfile(runs[0], store / "runs" / f"{input_digest}.json")

        done = subprocess.run(
            ["go", "run", "./cmd/hedgecheck", "replay",
             "--input-digest", input_digest, "--store", str(store),
             "--registry", str(PROJECT / "registry")],
            cwd=PROJECT / "engine", capture_output=True, text=True)
        sys.stdout.write(done.stdout)
        sys.stderr.write(done.stderr)
        return done.returncode
    finally:
        shutil.rmtree(store, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
