"""Content-addressed snapshot store. No network, no clock.

A snapshot is its bytes: the file name is the SHA-256 of the response, so the same
response captured twice is one file, and a file that does not hash to its own name
is not the snapshot it claims to be. `get` re-verifies on every read, which is what
makes `replay` a check rather than a copy.
"""

from hashlib import sha256
import json
from pathlib import Path


class Corrupt(Exception):
    """A stored file does not hash to its own name."""


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.snapshots = self.root / "snapshots"
        self.runs = self.root / "runs"

    def put(self, digest, raw, record):
        if sha256(raw).hexdigest() != digest:
            raise Corrupt(f"{digest[:12]}: bytes do not hash to the name they are stored under")
        self.snapshots.mkdir(parents=True, exist_ok=True)
        (self.snapshots / f"{digest}.json").write_bytes(raw)
        (self.snapshots / f"{digest}.request.json").write_text(json.dumps(record, indent=2) + "\n")
        return digest

    def get(self, digest):
        """The exact stored bytes, re-verified against the name they are stored under."""
        path = self.snapshots / f"{digest}.json"
        if not path.exists():
            raise FileNotFoundError(f"snapshot {digest[:12]} is not in the store")
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != digest:
            raise Corrupt(f"{digest[:12]}: stored bytes no longer hash to their name")
        return raw

    def record(self, digest):
        return json.loads((self.snapshots / f"{digest}.request.json").read_text())

    def put_run(self, input_digest, document):
        self.runs.mkdir(parents=True, exist_ok=True)
        (self.runs / f"{input_digest}.json").write_text(json.dumps(document, indent=2) + "\n")

    def run(self, input_digest):
        path = self.runs / f"{input_digest}.json"
        if not path.exists():
            raise FileNotFoundError(f"no run {input_digest[:12]} in the store")
        return json.loads(path.read_text())

    def runs_available(self):
        if not self.runs.exists():
            return []
        return sorted(path.stem for path in self.runs.glob("*.json"))
