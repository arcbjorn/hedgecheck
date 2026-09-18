"""Capture public Hyperliquid info responses with request records (no signing, no account data).

Discovers the live BTC recurring instances (priceBinary and priceBucket) instead of
hard-coding them, then retains their books, the perp contexts, the template registry,
and the settlements of the instances that expired 2026-09-16 06:00 UTC.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
ENDPOINT = "https://api.hyperliquid.xyz/info"
PAUSE_SECONDS = 1.5

# Known from research/2026-09-15-settlement/outcome-meta.json: the instances that were
# live on 15 September and expired 2026-09-16 06:00 UTC. Historical ids are data, not
# configuration; live instances below are always discovered.
EXPIRED_20260916 = [3253, 3254, 3255, 3256, 3259, 3260, 3261, 3262]


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
    time.sleep(PAUSE_SECONDS)
    return json.loads(raw)


def parse_description(text):
    return dict(part.split(":", 1) for part in text.split("|"))


def main():
    meta = capture("outcome-meta", {"type": "outcomeMeta"})

    # The binary first, so its two books and the perp contexts are as close in time as possible.
    binary = next(
        o for o in meta["outcomes"]
        if o["name"] == "Recurring" and parse_description(o["description"]).get("underlying") == "BTC"
    )
    ident = binary["outcome"]
    capture("meta-and-asset-ctxs", {"type": "metaAndAssetCtxs"})
    capture(f"book-{ident}-no", {"type": "l2Book", "coin": f"#{10 * ident + 1}"})
    capture(f"book-{ident}-yes", {"type": "l2Book", "coin": f"#{10 * ident + 0}"})

    # The BTC priceBucket question and the YES book of each named outcome.
    bucket = next(
        (q for q in meta["questions"]
         if q["name"] == "Recurring" and "class:priceBucket" in q["description"] and "underlying:BTC" in q["description"]),
        None,
    )
    if bucket is None:
        print("no live BTC priceBucket question", file=sys.stderr)
    else:
        for index, outcome in enumerate(bucket["namedOutcomes"]):
            capture(f"book-bucket{index}-{outcome}-yes", {"type": "l2Book", "coin": f"#{10 * outcome + 0}"})

    capture("outcome-templates", {"type": "outcomeTemplates"})
    for outcome in EXPIRED_20260916:
        capture(f"settled-{outcome}", {"type": "settledOutcome", "outcome": outcome})


if __name__ == "__main__":
    main()
