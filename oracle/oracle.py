"""Reference oracle for exact terminal evaluation. Standard library only.

This is NOT the product engine. It is the smallest exact evaluator that can state the
expected result for a fixture, so that the numbers and the example result in PLAN.md are
computed rather than transcribed. It is deliberately slow, generic and short.

Model: P&L is a function of one terminal reference price S on a closed domain [L, U].
Every function is an `Fn`: an exact pointwise rule TOGETHER WITH the breakpoints between
which it is affine. Constructors and sums are the only way to build one, so a function can
never be separated from its breakpoints. Every question is answered on "atoms" (each
breakpoint, and each open interval between neighbours) in rational arithmetic. Nothing is
sampled and nothing is rounded.

The affinity probe in atoms() is a tripwire for a constructor that hides a kink. It is not
a proof: it sees a hidden kink only when the kink falls between its probe points. The
guarantee comes from the representation, not from the probe.
"""

from fractions import Fraction as F
from math import ceil, floor

import canon
import exact

num = exact.parse
fmt = exact.format
digest = canon.digest


# ---------------------------------------------------------------- functions

class Fn:
    """An exact function of the reference price, inseparable from its breakpoints."""

    def __init__(self, breakpoints, rule, label=""):
        self.breakpoints = frozenset(F(b) for b in breakpoints)
        self._rule = rule
        self.label = label

    def __call__(self, price):
        return self._rule(F(price))

    def __add__(self, other):
        return Fn(self.breakpoints | other.breakpoints, lambda s: self(s) + other(s))

    def __neg__(self):
        return Fn(self.breakpoints, lambda s: -self(s))

    def __sub__(self, other):
        return self + (-other)


def linear(quantity, baseline):
    return Fn([], lambda s: quantity * (s - baseline), "linear")


def cash(amount):
    return Fn([], lambda s: F(amount), "cash")


def indicator(size, lower=None, lower_inclusive=True, upper=None, upper_inclusive=False):
    """Pays `size` on an interval with explicit endpoint ownership; a missing bound is unbounded.

    The one digital primitive. Which side owns a strike is data, never a convention.
    """
    if lower is not None and upper is not None and not (lower < upper or (lower == upper and lower_inclusive and upper_inclusive)):
        raise ValueError("empty interval")

    def rule(s):
        above = lower is None or s > lower or (s == lower and lower_inclusive)
        below_ = upper is None or s < upper or (s == upper and upper_inclusive)
        return size if above and below_ else F(0)
    return Fn([b for b in (lower, upper) if b is not None], rule, "indicator")


def digital_below(size, strike):
    """S < strike, strictly. Canonical priceBinary NO; priceBucket index 0 YES."""
    return indicator(size, upper=strike, upper_inclusive=False)


def digital_at_or_above(size, strike):
    """S >= strike, inclusive. Canonical priceBinary YES; priceBucket top YES."""
    return indicator(size, lower=strike, lower_inclusive=True)


def digital_range(size, low, high):
    """low <= S < high. Canonical priceBucket middle YES."""
    return indicator(size, lower=low, lower_inclusive=True, upper=high, upper_inclusive=False)


def ramp_short(size, low, high):
    """template:scalarPrice Short: `size` at or below low, 0 at or above high, linear between."""
    def rule(s):
        if s <= low:
            return size
        if s >= high:
            return F(0)
        return size * (high - s) / (high - low)
    return Fn([low, high], rule, "ramp_short")


def ramp_long(size, low, high):
    """template:scalarPrice Long: the complement of Short."""
    return cash(size) - ramp_short(size, low, high)


def total(parts):
    out = cash(0)
    for part in parts:
        out = out + part
    return out


# ---------------------------------------------------------------- atoms

def atoms(fn, lower, upper, cuts=()):
    """Yield ('point', x, value) and ('open', lo, hi, slope, intercept) in ascending order.

    `cuts` can only ADD boundaries (the ends of an objective clause, say). The function's own
    breakpoints are always used; there is no way to withhold them.
    """
    lower, upper = F(lower), F(upper)
    inside = {b for b in fn.breakpoints | {F(c) for c in cuts} if lower < b < upper}
    marks = sorted({lower, upper} | inside)
    out = []
    for index, mark in enumerate(marks):
        out.append(("point", mark, fn(mark)))
        if index + 1 < len(marks):
            lo, hi = mark, marks[index + 1]
            a, b = lo + (hi - lo) / 3, lo + 2 * (hi - lo) / 3
            slope = (fn(b) - fn(a)) / (b - a)
            intercept = fn(a) - slope * a
            mid = (lo + hi) / 2
            if fn(mid) != slope * mid + intercept:
                raise ValueError(f"not affine on ({lo}, {hi}): a constructor hides a breakpoint")
            out.append(("open", lo, hi, slope, intercept))
    return out


def profile(fn, lower, upper, cuts=()):
    """Maximal affine pieces with explicit endpoint ownership."""
    pieces = []
    for atom in atoms(fn, lower, upper, cuts):
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


def infimum(fn, lower, upper):
    """(infimum, attained, location). Location is the smallest attaining price, else the limit point."""
    best, attained, where = None, False, None
    for atom in atoms(fn, lower, upper):
        if atom[0] == "point":
            candidates = [(atom[2], True, atom[1])]
        else:
            _, lo, hi, slope, intercept = atom
            candidates = [(slope * lo + intercept, slope == 0, lo), (slope * hi + intercept, slope == 0, hi)]
        for value, is_attained, location in candidates:
            if best is None or value < best or (value == best and is_attained and not attained):
                best, attained, where = value, is_attained, location
    return best, attained, where


def below(fn, threshold, lower, upper, cuts=()):
    """Exact set {S in [lower, upper] : fn(S) < threshold} as maximal intervals."""
    parts = []
    for atom in atoms(fn, lower, upper, cuts):
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


def witness(fn, interval):
    """An admissible failing price: the attained minimum of the interval, else its midpoint."""
    lo, hi = interval["lower"], interval["upper"]
    if lo == hi:
        return {"price": lo, "pnl": fn(lo)}
    value, attained, where = infimum(fn, lo, hi)
    owned = (where != lo or interval["lower_inclusive"]) and (where != hi or interval["upper_inclusive"])
    price = where if attained and owned else (lo + hi) / 2
    return {"price": price, "pnl": fn(price)}


# ---------------------------------------------------------------- band infimum

def band_infimum(fn, band):
    """The worst value of fn anywhere within `band` of the price: inf over [S - band, S + band].

    This is the reduction for a leg, or a group of legs, observed on another reference under a
    declared basis bound. For a monotone payoff it is a shift; for the middle bucket it is NOT:
    [P1, P2) shrinks from both sides to [P1 + band, P2 - band). The result is again an Fn.
    Its breakpoints are a superset of the true ones: every original breakpoint, each shifted
    both ways, and every crossing of two candidate lines. Extra breakpoints are harmless.
    """
    band = F(band)
    if band < 0:
        raise ValueError("negative band")
    marks = sorted(fn.breakpoints)
    lo, hi = (marks[0], marks[-1]) if marks else (F(0), F(1))
    lines = []
    for atom in atoms(fn, lo - 2 * band - 1, hi + 2 * band + 1):
        if atom[0] == "open":
            _, _, _, slope, intercept = atom
            lines += [(slope, intercept - slope * band), (slope, intercept + slope * band)]
    cuts = {m + d for m in marks for d in (-band, F(0), band)}
    for i, (a1, c1) in enumerate(lines):
        for a2, c2 in lines[i + 1:]:
            if a1 != a2:
                cuts.add((c2 - c1) / (a1 - a2))
    return Fn(cuts, lambda s: infimum(fn, s - band, s + band)[0], "band_infimum")


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


def size_window(base, unit, levels, floor_pnl, lower, upper, lot=1):
    """Exact sizes n in [0, displayed depth] with base(S) + n*unit(S) - C(n) >= floor_pnl for all S.

    For a fixed size the P&L is affine on every open atom, so the condition holds on an atom
    exactly when it holds at the atom's endpoint limits. Each such site gives a constraint
    beta*n - C(n) >= floor_pnl - alpha, concave in n because C is convex, so the feasible
    sizes form one interval. Contiguity is asserted, not assumed.
    """
    cuts = base.breakpoints | unit.breakpoints
    sites = []
    for b_atom, u_atom in zip(atoms(base, lower, upper, cuts), atoms(unit, lower, upper, cuts)):
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

def text_interval(interval):
    return {key: (fmt(val) if isinstance(val, F) else val) for key, val in interval.items()}


def _leg(leg):
    if leg["kind"] != "indicator":
        raise ValueError(f"unsupported lowered leg: {leg['kind']}")
    on = leg["pays_on"]
    return indicator(num(leg["size"]),
                     lower=num(on["lower"]) if "lower" in on else None, lower_inclusive=on.get("lower_inclusive", True),
                     upper=num(on["upper"]) if "upper" in on else None, upper_inclusive=on.get("upper_inclusive", False))


def leg_cost(leg):
    """What one lowered leg cost, exactly.

    'fixed' is a hypothetical per-unit price and multiplies by size. 'walked' is
    already the total paid for the whole size along one path, so it is used as it
    stands: a walk over several book levels has no single per-unit price, and its
    average is a derived quantity, not the one that was observed.
    """
    premium = leg["premium"]
    if premium["kind"] == "walked":
        return num(premium["total"])
    return num(leg["size"]) * num(premium["price"])


def evaluate(lowered):
    """Expected result for a lowered proposal (schema/ir.schema.json)."""
    lower, upper = num(lowered["domain"]["lower"]), num(lowered["domain"]["upper"])
    baseline = num(lowered["baseline"]["price"])
    exposure = linear(num(lowered["exposure"]["quantity"]), baseline)
    premium = sum((leg_cost(leg) for leg in lowered["legs"]), F(0))
    other = num(lowered["other_costs"])
    pnl = total([exposure] + [_leg(leg) for leg in lowered["legs"]] + [cash(-premium - other)])

    failing, codes = [], []
    for clause in lowered["objective"]:
        for interval in below(pnl, num(clause["min_pnl"]), lower, upper):
            shown = text_interval(interval)
            shown["clause"] = clause["id"]
            point = witness(pnl, interval)
            shown["witness"] = {"price": fmt(point["price"]), "pnl": fmt(point["pnl"])}
            failing.append(shown)
    if failing:
        codes.append("LOSS_BOUND_EXCEEDED")
    worst, attained, where = infimum(pnl, lower, upper)
    bare_worst, _, bare_where = infimum(exposure, lower, upper)
    cap = min(num(clause["min_pnl"]) for clause in lowered["objective"])
    breakevens = []
    for piece in profile(pnl, lower, upper):
        if piece["slope"] != 0:
            root = -piece["intercept"] / piece["slope"]
            inside = (piece["lower"] < root < piece["upper"]
                      or (root == piece["lower"] and piece["lower_inclusive"])
                      or (root == piece["upper"] and piece["upper_inclusive"]))
            if inside:
                breakevens.append(fmt(root))
    return {
        "schema_version": "1",
        "units": lowered["units"],
        "model_result": "fails" if failing else "passes",
        "execution_readiness": "not_evaluated",
        "evaluation_scope": "exhaustive_supported_terminal_model",
        "baseline": lowered["baseline"],
        "objective_valuation_time": lowered["objective_valuation_time"],
        "leg_observation_times": [leg["observation_time"] for leg in lowered["legs"]],
        "worst_case": {"pnl": fmt(worst), "attained": attained, "price": fmt(where)},
        "failing_intervals": failing,
        "profile": [text_interval(piece) for piece in profile(pnl, lower, upper)],
        "cost": {"premium": fmt(premium), "other_costs": fmt(other),
                 "pnl_at_baseline": fmt(pnl(baseline)), "breakevens": breakevens},
        "comparisons": {"no_hedge": {
            "worst_case": {"pnl": fmt(bare_worst), "price": fmt(bare_where)},
            "failing_intervals": [text_interval(i) for i in below(exposure, cap, lower, upper)],
            "proposal_better": [text_interval(i) for i in below(exposure - pnl, F(0), lower, upper)],
            "proposal_worse": [text_interval(i) for i in below(pnl - exposure, F(0), lower, upper)]}},
        "reason_codes": codes,
        "assumptions": lowered["assumptions"],
        "checks_not_performed": ["LIVE_EXECUTION", "PATH_RISK"],
        "engine_version": "reference-oracle-2",
        "ir_digest": digest(lowered),
    }
