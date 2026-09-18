"""Capture public Hyperliquid info responses with request records (no signing, no account data)."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
ENDPOINT = "https://api.hyperliquid.xyz/info"

REQUESTS = [
    ("settled-2820", {"type": "settledOutcome", "outcome": 2820}),
    ("settled-2822", {"type": "settledOutcome", "outcome": 2822}),
    ("settled-2824", {"type": "settledOutcome", "outcome": 2824}),
    ("settled-2825", {"type": "settledOutcome", "outcome": 2825}),
    ("settled-3061", {"type": "settledOutcome", "outcome": 3061}),
    ("settled-3062", {"type": "settledOutcome", "outcome": 3062}),
    ("settled-3063", {"type": "settledOutcome", "outcome": 3063}),
    ("settled-3064", {"type": "settledOutcome", "outcome": 3064}),
    ("outcome-meta", {"type": "outcomeMeta"}),
    ("meta-and-asset-ctxs", {"type": "metaAndAssetCtxs"}),
]


def capture(stem, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(ENDPOINT, data=data, headers={"Content-Type": "application/json"})
    requested_at = datetime.now(timezone.utc)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        status = resp.status
        server_date = resp.headers.get("Date")
    retrieved_at = datetime.now(timezone.utc)
    (ROOT / f"{stem}.json").write_bytes(raw)
    record = {
        "endpoint": ENDPOINT,
        "method": "POST",
        "request_body": body,
        "requested_at": requested_at.isoformat(),
        "retrieved_at": retrieved_at.isoformat(),
        "http_status": status,
        "response_file": f"{stem}.json",
        "response_sha256": sha256(raw).hexdigest(),
        "server_date": server_date,
    }
    (ROOT / f"{stem}.request.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"{stem}: {status} {len(raw)} bytes sha256={record['response_sha256'][:16]} at {retrieved_at.isoformat()}")
    return json.loads(raw)


def main():
    meta = None
    for stem, body in REQUESTS:
        result = capture(stem, body)
        if stem == "outcome-meta":
            meta = result
    recurring = [o for o in meta["outcomes"] if o["name"] == "Recurring"]
    for item in recurring:
        if "underlying:BTC" in item["description"]:
            for side, label in ((0, "yes"), (1, "no")):
                capture(f"book-{item['outcome']}-{label}", {"type": "l2Book", "coin": f"#{10 * item['outcome'] + side}"})


if __name__ == "__main__":
    main()
