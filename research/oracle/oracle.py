"""Reference oracle for exact terminal evaluation. Standard library only.

This is NOT the product engine. It is the smallest exact evaluator that can state the
expected result for a fixture, so that the numbers and the example result in PLAN.md are
computed rather than transcribed. The engine and its independent checker must agree with
it on every fixture; it is deliberately slow, generic and short.

Model: P&L is a function of one terminal reference price S on a closed domain [L, U].
Each leg is an exact pointwise function plus the breakpoints between which it is affine.
A sum of such legs is affine between the union of breakpoints, so every question below is
answered on "atoms" (each breakpoint, and each open interval between neighbours) with
rational arithmetic. Nothing is sampled and nothing is rounded.
"""

from fractions import Fraction as F
from hashlib import sha256
import json
from math import ceil, floor


# ---------------------------------------------------------------- numbers

def num(text):
    return F(str(text))


def fmt(value):
    """Exact text: a terminating decimal when one exists, otherwise 'p/q'. Never rounded."""
    value = F(value)
    den = value.denominator
    for prime in (2, 5):
        while den % prime == 0:
            den //= prime
    if den != 1:
        return f"{value.numerator}/{value.denominator}"
    places = 0
    while (value * 10 ** places).denominator != 1:
        places += 1
    digits = str(abs(value.numerator * 10 ** places // value.denominator)).rjust(places + 1, "0")
    text = digits[: len(digits) - places] + ("." + digits[len(digits) - places:] if places else "")
    return ("-" if value < 0 else "") + text


# ---------------------------------------------------------------- legs

class Leg:
    def __init__(self, label, breakpoints, value):
        self.label, self.breakpoints, self.value = label, [F(b) for b in breakpoints], value


def linear(quantity, baseline):
    return Leg("linear", [], lambda s: quantity * (s - baseline))


def cash(amount):
    return Leg("cash", [], lambda s: F(amount))


def digital_below(size, strike):
    """Pays `size` when S < strike, strictly. Canonical priceBinary NO; priceBucket index 0 YES."""
    return Leg("digital_below", [strike], lambda s: size if s < strike else F(0))


def digital_at_or_above(size, strike):
    """Pays `size` when S >= strike, inclusive. Canonical priceBinary YES; priceBucket top YES."""
    return Leg("digital_at_or_above", [strike], lambda s: size if s >= strike else F(0))


def digital_range(size, low, high):
    """Pays `size` when low <= S < high. Canonical priceBucket middle YES."""
    return Leg("digital_range", [low, high], lambda s: size if low <= s < high else F(0))


def scalar_short(size, low, high):
    """template:scalarPrice Short: 1 at or below low, 0 at or above high, linear between."""
    def value(s):
        if s <= low:
            return size
        if s >= high:
            return F(0)
        return size * (high - s) / (high - low)
    return Leg("scalar_short", [low, high], value)


def total(legs):
    return lambda s: sum((leg.value(s) for leg in legs), F(0))


# ---------------------------------------------------------------- atoms

def atoms(fn, lower, upper, breakpoints):
    """Yield ('point', x, value) and ('open', lo, hi, slope, intercept) in ascending order."""
    cuts = sorted({F(lower), F(upper)} | {F(b) for b in breakpoints if lower < b < upper})
    out = []
    for index, cut in enumerate(cuts):
        out.append(("point", cut, fn(cut)))
        if index + 1 < len(cuts):
            lo, hi = cut, cuts[index + 1]
            a, b = lo + (hi - lo) / 3, lo + 2 * (hi - lo) / 3
            slope = (fn(b) - fn(a)) / (b - a)
            intercept = fn(a) - slope * a
            mid = (lo + hi) / 2
            if fn(mid) != slope * mid + intercept:
                raise ValueError(f"not affine on ({lo}, {hi}): a breakpoint is undeclared")
            out.append(("open", lo, hi, slope, intercept))
    return out


def profile(fn, lower, upper, breakpoints):
    """Maximal affine pieces with explicit endpoint ownership."""
    pieces = []
    for atom in atoms(fn, lower, upper, breakpoints):
        if atom[0] == "point":
            _, x, value = atom
            last = pieces[-1] if pieces else None
            if last and last["upper"] == x and last["slope"] * x + last["intercept"] == value:
                last["upper_inclusive"] = True
            else:
                pieces.append({"lower": x, "lower_inclusive": True, "upper": x, "upper_inclusive": True,
                               "slope": None, "intercept": value})
        else:
            _, lo, hi, slope, intercept = atom
            last = pieces[-1]
            joins = last["upper"] == lo and last["upper_inclusive"] and (
                (last["slope"] is None and slope * lo + intercept == last["intercept"])
                or (last["slope"] == slope and last["intercept"] == intercept))
            if joins:
                last.update(upper=hi, upper_inclusive=False, slope=slope, intercept=intercept)
            else:
                pieces.append({"lower": lo, "lower_inclusive": False, "upper": hi, "upper_inclusive": False,
                               "slope": slope, "intercept": intercept})
    for piece in pieces:
        if piece["slope"] is None:
            piece["slope"] = F(0)
    return pieces


def infimum(fn, lower, upper, breakpoints):
    """(infimum, attained, location). Location is the smallest attaining price, else the limit point."""
    best, attained, where = None, False, None
    for atom in atoms(fn, lower, upper, breakpoints):
        if atom[0] == "point":
            candidates = [(atom[2], True, atom[1])]
        else:
            _, lo, hi, slope, intercept = atom
            candidates = [(slope * lo + intercept, slope == 0, lo), (slope * hi + intercept, slope == 0, hi)]
        for value, is_attained, location in candidates:
            if best is None or value < best or (value == best and is_attained and not attained):
                best, attained, where = value, is_attained, location
    return best, attained, where


def below(fn, threshold, lower, upper, breakpoints):
    """Exact set {S in [lower, upper] : fn(S) < threshold} as maximal intervals."""
    parts = []
    for atom in atoms(fn, lower, upper, breakpoints):
        if atom[0] == "point":
            if atom[2] < threshold:
                parts.append([atom[1], True, atom[1], True])
            continue
        _, lo, hi, slope, intercept = atom
        if slope == 0:
            if intercept < threshold:
                parts.append([lo, False, hi, False])
            continue
        cross = (threshold - intercept) / slope
        start, end = (lo, min(hi, cross)) if slope > 0 else (max(lo, cross), hi)
        if start < end:
            parts.append([start, False, end, False])
    merged = []
    for part in parts:
        last = merged[-1] if merged else None
        if last and last[2] == part[0] and (last[3] or part[1]):
            last[2], last[3] = part[2], part[3]
        else:
            merged.append(part)
    return [{"lower": p[0], "lower_inclusive": p[1], "upper": p[2], "upper_inclusive": p[3]} for p in merged]


def witness(fn, interval, breakpoints):
    """An admissible failing price: the attained minimum of the interval, else its midpoint."""
    lo, hi = interval["lower"], interval["upper"]
    inside = [b for b in breakpoints if lo < b < hi]
    value, attained, where = infimum(fn, lo, hi, inside)
    owned = (where != lo or interval["lower_inclusive"]) and (where != hi or interval["upper_inclusive"])
    price = where if attained and owned else (lo + hi) / 2
    return {"price": price, "pnl": fn(price)}


# ---------------------------------------------------------------- displayed-depth cost and sizing

def ask_cost(levels, size):
    """Cost of buying `size` by walking displayed asks; None when displayed depth is insufficient."""
    remaining, cost = F(size), F(0)
    for price, available in levels:
        fill = min(remaining, available)
        cost, remaining = cost + fill * price, remaining - fill
        if remaining == 0:
            return cost
    return None


def size_window(base, unit, levels, floor_pnl, lower, upper, breakpoints, lot=1):
    """Exact sizes n in [0, displayed depth] with base(S) + n*unit(S) - C(n) >= floor_pnl for all S.

    For a fixed size the P&L is affine on every open atom, so the condition holds on an atom
    exactly when it holds at the atom's endpoint limits. Each such site gives a constraint
    beta*n - C(n) >= floor_pnl - alpha, concave in n because C is convex, so the feasible
    sizes form one interval. Contiguity is asserted, not assumed.
    """
    sites = []
    for b_atom, u_atom in zip(atoms(base, lower, upper, breakpoints), atoms(unit, lower, upper, breakpoints)):
        if b_atom[0] == "point":
            sites.append((b_atom[1], "at", b_atom[2], u_atom[2]))
        else:
            _, lo, hi, bs, bi = b_atom
            _, _, _, us, ui = u_atom
            sites.append((lo, "above", bs * lo + bi, us * lo + ui))
            sites.append((hi, "below", bs * hi + bi, us * hi + ui))
    depth = sum((available for _, available in levels), F(0))
    low, high, low_site, high_site = F(0), depth, None, None
    for price_at, side, alpha, beta in sites:
        start, spent, spans = F(0), F(0), []
        for price, available in levels:
            end = start + available
            gain, need = beta - price, floor_pnl - alpha + spent - price * start
            if gain == 0:
                span = (start, end) if need <= 0 else None
            elif gain > 0:
                span = (max(start, need / gain), end)
            else:
                span = (start, min(end, need / gain))
            if span and span[0] <= span[1]:
                spans.append(span)
            start, spent = end, spent + price * available
        if not spans:
            return {"status": "empty", "binding": [(price_at, side)], "lower_bound": None, "upper_bound": None}
        for left, right in zip(spans, spans[1:]):
            if left[1] != right[0]:
                raise AssertionError("feasible sizes are not contiguous; cost is not convex")
        if spans[0][0] > low:
            low, low_site = spans[0][0], (price_at, side)
        if spans[-1][1] < high:
            high, high_site = spans[-1][1], (price_at, side)
    lot = F(lot)
    first, last = ceil(low / lot) * lot, floor(high / lot) * lot
    return {"status": "nonempty" if first <= last else "empty", "lower_bound": low, "upper_bound": high,
            "smallest": first if first <= last else None, "largest": last if first <= last else None,
            "binding": [low_site, high_site]}


# ---------------------------------------------------------------- results

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def digest(obj):
    return sha256(canonical(obj).encode()).hexdigest()


def text_interval(interval):
    return {key: (fmt(val) if isinstance(val, F) else val) for key, val in interval.items()}


LEG_KINDS = {"digital_below": digital_below, "digital_at_or_above": digital_at_or_above}


def evaluate(proposal):
    """Expected result for a normalized single-reference proposal. Fixed premiums only."""
    lower, upper = num(proposal["domain"]["lower"]), num(proposal["domain"]["upper"])
    baseline = num(proposal["baseline"]["price"])
    exposure = linear(num(proposal["exposure"]["quantity"]), baseline)
    legs, premium = [exposure], F(0)
    for leg in proposal["legs"]:
        size = num(leg["size"])
        legs.append(LEG_KINDS[leg["kind"]](size, num(leg["strike"])))
        premium += size * num(leg["premium"]["price"])
    other = num(proposal["other_costs"])
    legs.append(cash(-premium - other))
    breakpoints = [b for leg in legs for b in leg.breakpoints]
    pnl, unhedged = total(legs), exposure.value

    failing, codes = [], []
    for clause in proposal["objective"]:
        for interval in below(pnl, num(clause["min_pnl"]), lower, upper, breakpoints):
            shown = text_interval(interval)
            shown["clause"] = clause["id"]
            point = witness(pnl, interval, breakpoints)
            shown["witness"] = {"price": fmt(point["price"]), "pnl": fmt(point["pnl"])}
            failing.append(shown)
    if failing:
        codes.append("LOSS_BOUND_EXCEEDED")
    worst, attained, where = infimum(pnl, lower, upper, breakpoints)
    bare_worst, _, bare_where = infimum(unhedged, lower, upper, [])
    cap = min(num(clause["min_pnl"]) for clause in proposal["objective"])
    better = below(lambda s: unhedged(s) - pnl(s), F(0), lower, upper, breakpoints)
    worse = below(lambda s: pnl(s) - unhedged(s), F(0), lower, upper, breakpoints)
    breakevens = []
    for piece in profile(pnl, lower, upper, breakpoints):
        if piece["slope"] != 0:
            root = -piece["intercept"] / piece["slope"]
            inside = (piece["lower"] < root < piece["upper"]
                      or (root == piece["lower"] and piece["lower_inclusive"])
                      or (root == piece["upper"] and piece["upper_inclusive"]))
            if inside:
                breakevens.append(fmt(root))
    return {
        "schema_version": "1",
        "units": proposal["units"],
        "model_result": "fails" if failing else "passes",
        "execution_readiness": "not_evaluated",
        "evaluation_scope": "exhaustive_supported_terminal_model",
        "baseline": proposal["baseline"],
        "objective_valuation_time": proposal["objective_valuation_time"],
        "leg_observation_times": [leg["observation_time"] for leg in proposal["legs"]],
        "worst_case": {"pnl": fmt(worst), "attained": attained, "price": fmt(where)},
        "failing_intervals": failing,
        "profile": [{**text_interval(piece)} for piece in profile(pnl, lower, upper, breakpoints)],
        "cost": {"premium": fmt(premium), "other_costs": fmt(other),
                 "pnl_at_baseline": fmt(pnl(baseline)), "breakevens": breakevens},
        "comparisons": {"no_hedge": {
            "worst_case": {"pnl": fmt(bare_worst), "price": fmt(bare_where)},
            "failing_intervals": [text_interval(i) for i in below(unhedged, cap, lower, upper, [])],
            "proposal_better": [text_interval(i) for i in better],
            "proposal_worse": [text_interval(i) for i in worse]}},
        "reason_codes": codes,
        "assumptions": proposal["assumptions"],
        "checks_not_performed": ["LIVE_EXECUTION", "PATH_RISK"],
        "engine_version": "reference-oracle-1",
        "proposal_digest": digest(proposal),
    }
