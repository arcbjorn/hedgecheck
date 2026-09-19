"""Find the live canonical instruments in a catalogue. Pure: a parsed catalogue in,
instrument descriptions out. No network, no clock, no ids.

An instance id is never configuration. It is discovered by class, underlying and
expiry, every run, because ids rotate: 3061 was pruned from the live catalogue
within a day of settling (EVIDENCE section 4). The same function runs against a
retained catalogue offline, which is how it is tested.
"""


class NotFound(Exception):
    """No live instance of this family for this underlying."""


def terms_of(description):
    """Parse a catalogue description, 'key:value|key:value'."""
    out = {}
    for part in description.split("|"):
        key, sep, value = part.partition(":")
        if not key or not sep:
            raise ValueError(f"description part {part!r} is not key:value")
        out[key] = value
    return out


def _side_coin(outcome, side):
    """The coin encodes outcome and side: '#' + (10*outcome + side), yes=0, no=1."""
    return f"#{10 * int(outcome) + (0 if side == 'yes' else 1)}"


def binaries(catalogue, underlying):
    """Every live recurring.priceBinary for this underlying, soonest expiry first."""
    out = []
    for item in catalogue.get("outcomes", []):
        if item.get("name") != "Recurring":
            continue
        try:
            terms = terms_of(item["description"])
        except ValueError:
            continue
        if terms.get("class") != "priceBinary" or terms.get("underlying") != underlying:
            continue
        out.append({
            "family": "recurring.priceBinary",
            "outcome": str(item["outcome"]),
            "expiry": terms["expiry"],
            "terms": {"underlying": underlying, "target_price": terms["targetPrice"],
                      "period": terms["period"]},
        })
    return sorted(out, key=lambda found: (found["expiry"], int(found["outcome"])))


def buckets(catalogue, underlying):
    """Every live recurring.priceBucket question for this underlying, soonest first.

    The thresholds live on the question; each named outcome carries only its index,
    and its position in `namedOutcomes` is the index the documented bucket order
    refers to. That ordering is observation, not documentation (EVIDENCE section 2),
    so the registry entry carries it as an assumption.
    """
    out = []
    for question in catalogue.get("questions", []):
        if question.get("name") != "Recurring":
            continue
        try:
            terms = terms_of(question["description"])
        except ValueError:
            continue
        if terms.get("class") != "priceBucket" or terms.get("underlying") != underlying:
            continue
        thresholds = terms["priceThresholds"].split(",")
        named = question.get("namedOutcomes", [])
        out.append({
            "family": "recurring.priceBucket",
            "question": str(question["question"]),
            "expiry": terms["expiry"],
            "thresholds": thresholds,
            "named_outcomes": [str(outcome) for outcome in named],
            "terms": {"underlying": underlying, "thresholds": thresholds,
                      "period": terms["period"]},
        })
    return sorted(out, key=lambda found: (found["expiry"], int(found["question"])))


def soonest_expiry(catalogue, underlying):
    """The earliest expiry shared by a live binary and a live bucket for this underlying.

    Both instruments must answer the same question for a comparison to mean anything,
    so the expiry is chosen where both exist rather than per instrument.
    """
    binary_expiries = {found["expiry"] for found in binaries(catalogue, underlying)}
    bucket_expiries = {found["expiry"] for found in buckets(catalogue, underlying)}
    shared = sorted(binary_expiries & bucket_expiries)
    if not shared:
        raise NotFound(f"no expiry with both a binary and a bucket for {underlying}")
    return shared[0]


def candidates(catalogue, underlying, expiry=None):
    """The canonical instruments to compare, at one expiry.

    Returns (expiry, legs). Each leg carries everything a proposal needs except the
    size: family, side, terms, and the instance with its outcome and coin.
    """
    expiry = expiry or soonest_expiry(catalogue, underlying)

    found_binary = [found for found in binaries(catalogue, underlying) if found["expiry"] == expiry]
    if not found_binary:
        raise NotFound(f"no live recurring.priceBinary for {underlying} expiring {expiry}")
    binary = found_binary[0]

    found_bucket = [found for found in buckets(catalogue, underlying) if found["expiry"] == expiry]
    if not found_bucket:
        raise NotFound(f"no live recurring.priceBucket for {underlying} expiring {expiry}")
    bucket = found_bucket[0]
    if not bucket["named_outcomes"]:
        raise NotFound(f"the {underlying} bucket question expiring {expiry} names no outcomes")

    # NO on the binary and YES on the lowest bucket both pay below a threshold, which is
    # what a long holder is hedging. They are the two canonical ways to buy that payoff.
    bucket_outcome = bucket["named_outcomes"][0]
    return expiry, [
        {"id": "binary-no", "family": binary["family"], "side": "no",
         "terms": dict(binary["terms"]), "outcome": binary["outcome"],
         "coin": _side_coin(binary["outcome"], "no"),
         "strike_term": "target_price"},
        {"id": "bucket0-yes", "family": bucket["family"], "side": "yes",
         "terms": dict(bucket["terms"], index="0"), "outcome": bucket_outcome,
         "coin": _side_coin(bucket_outcome, "yes"),
         "strike_term": "thresholds"},
    ]


def expiry_to_iso(expiry):
    """'20260919-0600' -> '2026-09-19T06:00:00Z'."""
    date, _, time = expiry.partition("-")
    if len(date) != 8 or len(time) != 4:
        raise ValueError(f"expiry {expiry!r} is not YYYYMMDD-HHMM")
    return f"{date[0:4]}-{date[4:6]}-{date[6:8]}T{time[0:2]}:{time[2:4]}:00Z"
