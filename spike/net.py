"""The only module in the spike that touches the network. Standard library only.

Read-only `POST https://api.hyperliquid.xyz/info`, three request types, one request
per 1.5 seconds, at most 40 per run. No other endpoint, no websocket, no key, no
signing, no account data. Every other module in `spike/` imports nothing from here
except through an explicit capture handed to it, which is what lets `replay` run
with this module never imported at all.

A response is evidence, not contract: stored as exact bytes under its SHA-256,
beside a request record. Nothing here parses it into a contract document.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
import time
import urllib.request

ENDPOINT = "https://api.hyperliquid.xyz/info"
ALLOWED_TYPES = ("outcomeMeta", "metaAndAssetCtxs", "l2Book")
PAUSE_SECONDS = 1.5
MAX_REQUESTS = 40


class Budget(Exception):
    """The per-run request budget is spent."""


class Client:
    """A rate-limited, budgeted, read-only caller of one endpoint."""

    def __init__(self, store, pause=PAUSE_SECONDS, budget=MAX_REQUESTS):
        self.store = store
        self.pause = pause
        self.budget = budget
        self.spent = 0
        self._last = None

    def fetch(self, body):
        """One request. Returns (sha256, raw bytes, record) and stores both."""
        if body.get("type") not in ALLOWED_TYPES:
            raise ValueError(f"request type {body.get('type')!r} is not one of {ALLOWED_TYPES}")
        if self.spent >= self.budget:
            raise Budget(f"the {self.budget}-request budget for this run is spent")
        if self._last is not None:
            slept = time.monotonic() - self._last
            if slept < self.pause:
                time.sleep(self.pause - slept)

        payload = json.dumps(body).encode()
        request = urllib.request.Request(ENDPOINT, data=payload, headers={"Content-Type": "application/json"})
        requested_at = datetime.now(timezone.utc)
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            status = response.status
            server_date = response.headers.get("Date")
        retrieved_at = datetime.now(timezone.utc)
        self._last = time.monotonic()
        self.spent += 1

        digest = sha256(raw).hexdigest()
        record = {
            "endpoint": ENDPOINT,
            "method": "POST",
            "request_body": body,
            "requested_at": requested_at.isoformat(),
            "retrieved_at": retrieved_at.isoformat(),
            "http_status": status,
            "response_file": f"{digest}.json",
            "response_sha256": digest,
            "server_date": server_date,
        }
        self.store.put(digest, raw, record)
        return digest, raw, record


def catalogue(client):
    return client.fetch({"type": "outcomeMeta"})


def contexts(client):
    return client.fetch({"type": "metaAndAssetCtxs"})


def book(client, coin):
    """The order book for one coin. The coin is discovered, never configured."""
    return client.fetch({"type": "l2Book", "coin": coin})
