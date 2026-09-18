"""Verify preserved research evidence and exact economic calculations offline."""

from datetime import datetime
from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
CHECKS = 0


def check(condition, description):
    global CHECKS
    if not condition:
        raise AssertionError(description)
    CHECKS += 1


def read_capture(stem, expected_request):
    record = json.loads((ROOT / f"{stem}.request.json").read_text())
    check(record["response_file"] == f"{stem}.json", f"{stem}: response filename")
    raw = (ROOT / f"{stem}.json").read_bytes()
    check(sha256(raw).hexdigest() == record["response_sha256"], f"{stem}: SHA-256")
    check(record["request_body"] == expected_request, f"{stem}: request identity")
    check(record["http_status"] == 200, f"{stem}: HTTP status")
    check(record["method"] == "POST", f"{stem}: HTTP method")
    check(record["endpoint"] == "https://api.hyperliquid.xyz/info", f"{stem}: endpoint")
    started = datetime.fromisoformat(record["requested_at"])
    finished = datetime.fromisoformat(record["retrieved_at"])
    check(started.tzinfo is not None and finished.tzinfo is not None, f"{stem}: timezones")
    check(started <= finished, f"{stem}: timestamp ordering")
    check(finished.date().isoformat() == "2026-09-15", f"{stem}: capture date")
    return json.loads(raw), record


def ask_cost(book, quantity):
    remaining, cost = F(quantity), F(0)
    for level in book["levels"][1]:
        fill = min(remaining, F(level["sz"]))
        cost += fill * F(level["px"])
        remaining -= fill
        if remaining == 0:
            return cost
    raise ValueError("Captured ask depth is insufficient")


def synthetic_pnl(price, contracts=1000):
    price, contracts = F(price), F(contracts)
    return F("0.1") * (price - 100000) + contracts * (price < 90000) - F("0.2") * contracts


def main():
    meta, meta_record = read_capture("outcome-meta", {"type": "outcomeMeta"})
    templates, _ = read_capture("outcome-templates", {"type": "outcomeTemplates"})
    check(len(meta["outcomes"]) == 226, "catalogue outcome count")
    check(len(meta["questions"]) == 32, "catalogue question count")
    check(len(meta["deployers"]) == 3, "catalogue deployer count")
    check(len(templates) == 18, "template count")
    by_id = {item["outcome"]: item for item in meta["outcomes"]}
    check(len(by_id) == len(meta["outcomes"]), "unique outcome IDs")
    expiry = datetime(2026, 9, 15, 6, tzinfo=ZoneInfo("UTC"))
    check(datetime.fromisoformat(meta_record["retrieved_at"]) < expiry, "capture preceded expiry")
    for ident, symbol, target in [
        (3061, "BTC", "77583"), (3062, "ETH", "2516"),
        (3063, "SOL", "101.07"), (3064, "HYPE", "79.546"),
    ]:
        item = by_id[ident]
        expected = f"class:priceBinary|underlying:{symbol}|expiry:20260915-0600|targetPrice:{target}|period:1d"
        check(item["name"] == "Recurring", f"{symbol}: family")
        check(item["description"] == expected, f"{symbol}: instance terms")
        check(item["quoteToken"] == "USDC", f"{symbol}: quote asset")
        check(item["sideSpecs"] == [{"name": "Yes"}, {"name": "No"}], f"{symbol}: side order")

    for ident in (3176, 3057):
        settled, _ = read_capture(f"settled-{ident}", {"type": "settledOutcome", "outcome": ident})
        check(settled["spec"]["outcome"] == ident, f"{ident}: historical identity")
        check(settled["spec"]["name"] == "template:binaryPrice", f"{ident}: historical family")
        check(F(settled["settleFraction"]) == 1, f"{ident}: reported fraction")
        check(settled["details"] == "template", f"{ident}: no numerical price in details")
        check(ident not in by_id, f"{ident}: absent from live catalogue but retrievable historically")

    expected_books = {
        3061: ("0.9275", "0.942", "1000", [(100, "94.2"), (1000, "942"), (1500, "1416.7019")]),
        3063: ("0.79", "0.83427", "1688", [(100, "83.427"), (1000, "834.27"), (1500, "1251.405")]),
    }
    for ident, (bid, ask, size, costs) in expected_books.items():
        coin = f"#{10 * ident + 1}"
        book, _ = read_capture(f"book-{ident}-no", {"type": "l2Book", "coin": coin})
        check(book["coin"] == coin, f"{ident}: response coin")
        check(book["time"] == 1789450871880, f"{ident}: exchange timestamp")
        check(F(book["levels"][0][0]["px"]) == F(bid), f"{ident}: best bid")
        check(F(book["levels"][1][0]["px"]) == F(ask), f"{ident}: best ask")
        check(F(book["levels"][1][0]["sz"]) == F(size), f"{ident}: best ask size")
        for quantity, expected in costs:
            check(ask_cost(book, quantity) == F(expected), f"{ident}: cost for {quantity}")
        total_depth = sum(F(level["sz"]) for level in book["levels"][1])
        try:
            ask_cost(book, total_depth + 1)
        except ValueError:
            check(True, f"{ident}: insufficient depth rejected")
        else:
            check(False, f"{ident}: insufficient depth rejected")

    for price, expected in {
        110000: 800, 100000: -200, 95000: -700, 90000: -1200,
        89000: -300, 80000: -1200, 60000: -3200,
    }.items():
        check(synthetic_pnl(price) == expected, f"synthetic P&L at {price}")
    for price, passed in {
        "81999.99": False, "82000": True, "89999.99": True,
        "90000": False, "91999.99": False, "92000": True,
    }.items():
        check((synthetic_pnl(price) >= -1000) == passed, f"inclusive loss boundary at {price}")
    check(synthetic_pnl(90000, 0) == -1000, "unhedged exact boundary")
    check(synthetic_pnl("89999.99", 0) < -1000, "unhedged failure below 90000")
    check(synthetic_pnl(91000, 0) > -1000, "unhedged does not fail throughout 90000..92000")
    check(F("0.07") * (100000 - 60000) == 2800, "selling 0.03 BTC is insufficient")
    cash, remaining = F(7500), F("0.025")
    check(cash + remaining * 100000 == 10000, "retained cash preserves initial wealth")
    check(cash + remaining * 60000 - 10000 == -1000, "correct reduced-exposure loss")
    check(cash + remaining * 110000 - 10000 == 250, "correct reduced-exposure upside")
    upper = F(1000 - 1000) / F("0.2")
    lower = F(4000 - 1000) / F("0.8")
    check(upper == 0 and lower == 3750 and lower > upper, "incompatible size constraints")
    check(1000 + F("0.2") * 3000 == 4000 - F("0.8") * 3000 == 1600, "minimax intersection")

    deadline = datetime(2026, 10, 12, 23, 59, tzinfo=ZoneInfo("America/Los_Angeles"))
    check(deadline.astimezone(ZoneInfo("UTC")).isoformat() == "2026-10-13T06:59:00+00:00", "deadline UTC")
    check(deadline.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")).isoformat() == "2026-10-13T03:59:00-03:00", "deadline Buenos Aires")
    print(f"{CHECKS} evidence and arithmetic checks passed; 6 response hashes verified.")


if __name__ == "__main__":
    main()
