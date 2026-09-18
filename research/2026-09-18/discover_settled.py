"""Discover and retain the recurring instances that expired 17 and 18 September 2026.

Instance ids rotate and no listing endpoint for settled outcomes is known, so this probes
`settledOutcome` across the id gap between the 16 September and 19 September instances.
Recurring instances are created in runs of adjacent ids, so probing every third id and
then sweeping the neighbourhood of a hit finds them. Probes are paced well under the
documented info rate limit. Only recurring responses are retained, through the same
capture() used for the rest of the package.
"""

import json
import sys
import time
import urllib.error
import urllib.request

from capture import ENDPOINT, capture

LOW, HIGH, STEP = 3263, 3964, 3
PAUSE_SECONDS = 1.5


def probe(outcome):
    body = json.dumps({"type": "settledOutcome", "outcome": outcome}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as error:
        return None, str(error)
    time.sleep(PAUSE_SECONDS)
    return data, None


def is_recurring(data):
    return bool(data) and isinstance(data, dict) and data.get("spec", {}).get("name", "").startswith("Recurring")


def main():
    hits, swept = [], set()
    for outcome in range(LOW, HIGH + 1, STEP):
        data, error = probe(outcome)
        if error:
            print(f"probe {outcome}: {error}", file=sys.stderr)
            time.sleep(PAUSE_SECONDS)
            continue
        if not is_recurring(data):
            continue
        for neighbour in range(outcome - 6, outcome + 11):
            if neighbour in swept or not LOW <= neighbour <= HIGH:
                continue
            swept.add(neighbour)
            near, _ = probe(neighbour)
            if is_recurring(near):
                capture(f"settled-{neighbour}", {"type": "settledOutcome", "outcome": neighbour})
                hits.append(neighbour)
    print("retained recurring settlements:", sorted(hits))


if __name__ == "__main__":
    main()
