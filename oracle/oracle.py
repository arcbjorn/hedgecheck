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
    """(infimum, attained, location).

    `location` is a price the function **actually attains** whenever `attained` is
    true: the smallest such price when the attaining set has a minimum, otherwise the
    midpoint of the first attaining open piece. An open piece's excluded endpoints are
    limit points, not members — reporting one would hand a witness a price where the
    payoff is higher than the value claimed, which is inadmissible.

    When the infimum is only approached, `attained` is false and `location` is the
    limit point it is approached at.
    """
    best, attained, where = None, False, None

    def offer(value, is_attained, location):
        nonlocal best, attained, where
        if best is None or value < best or (value == best and is_attained and not attained):
            best, attained, where = value, is_attained, location

    # MAXIMAL pieces, not raw atoms. `atoms` splits at every breakpoint the function
    # CARRIES, and a carried breakpoint need not be a kink: a leg whose payoff cancels
    # leaves one behind with the same slope either side. Splitting a flat run there makes
    # "the midpoint of the first attaining open piece" the midpoint of an arbitrary
    # fragment of it -- on case-0266 the flat run (65000, 110000) carries a phantom mark at
    # 77457, and reading atoms reported 71228.5 where the maximal piece gives 87500. Both
    # prices attain the same value, so no arithmetic check catches it; only the Go engine,
    # which windows maximal pieces, disagreed.
    for piece in profile(fn, lower, upper):
        lo, hi, slope, intercept = piece["lower"], piece["upper"], piece["slope"], piece["intercept"]
        if lo == hi:
            offer(intercept + slope * lo, True, lo)
            continue
        if slope == 0:
            # Flat: every price in the piece attains the value. The endpoints attain it too
            # when they are owned, and then the attaining set HAS a minimum -- the smallest
            # owned price -- which the documented rule prefers to the midpoint.
            owned_min = lo if piece["lower_inclusive"] else None
            offer(intercept, True, owned_min if owned_min is not None else (lo + hi) / 2)
            continue
        # Sloped: the extremes sit at the ends, attained only where the end is owned.
        offer(slope * lo + intercept, piece["lower_inclusive"], lo)
        offer(slope * hi + intercept, piece["upper_inclusive"], hi)
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

    Its breakpoints must be a superset of the true ones, and getting that superset right is the
    whole difficulty. Three families are needed, and omitting the third was a bug until 20 Sep
    (EVIDENCE section 9):

      1. every original breakpoint, shifted both ways and unshifted;
      2. every crossing of two candidate lines, which is where the envelope switches
         which piece attains the minimum;
      3. every crossing of a candidate line with a *constant* equal to a jump value,
         which is where the band slides off the end of a piece and a plateau takes over.

    Extra breakpoints are harmless; a missing one makes `profile` describe a function that
    is not this one, silently, because the affinity tripwire samples inside the span.
    """
    band = F(band)
    if band < 0:
        raise ValueError("negative band")
    marks = sorted(fn.breakpoints)
    lo, hi = (marks[0], marks[-1]) if marks else (F(0), F(1))
    lines, values = [], []
    for atom in atoms(fn, lo - 2 * band - 1, hi + 2 * band + 1):
        if atom[0] == "open":
            _, _, _, slope, intercept = atom
            lines += [(slope, intercept - slope * band), (slope, intercept + slope * band)]
        else:
            # A point's value becomes a plateau of the envelope wherever the band covers it.
            values.append(atom[2])
    cuts = {m + d for m in marks for d in (-band, F(0), band)}
    for i, (a1, c1) in enumerate(lines):
        for a2, c2 in lines[i + 1:]:
            if a1 != a2:
                cuts.add((c2 - c1) / (a1 - a2))
    # Where a sloped candidate meets a plateau value, the envelope changes which one wins.
    for slope, intercept in lines:
        if slope != 0:
            for value in values:
                cuts.add((value - intercept) / slope)
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


# ---------------------------------------------------------------- synthesis

def _simplex(rows, cost, columns):
    """Exact simplex on   minimise cost . n   s.t.   A n >= b,  n >= 0.

    Returns `(status, point, certificate)`. `status` is "optimal" with a point, or
    "infeasible" with a Farkas certificate `y >= 0` satisfying `A^T y <= 0` and `b . y > 0`,
    which is exactly the statement that no non-negative `n` can satisfy `A n >= b`.

    Rationals throughout: no float ever touches this. The objective row is carried INSIDE
    the tableau and pivoted with it, so reduced costs are read rather than recomputed --
    recomputing them against a mutating basis is where the first attempt at this went
    wrong, silently returning a point that violated its own constraints.

    BLAND'S RULE, not the steepest edge: the lowest-index eligible column, and the lowest
    basis index among tied ratios. Cycling is then impossible, so termination is a fact
    rather than a hope. These programs have single-digit rows and columns, so trading speed
    for a termination proof is the right trade.
    """
    # Every right-hand side is made non-negative, so the artificial basis starts feasible.
    prepared = []
    for coeffs, rhs in rows:
        if rhs < 0:
            prepared.append(([-c for c in coeffs], -rhs, True))
        else:
            prepared.append(([F(c) for c in coeffs], F(rhs), False))

    m, n = len(prepared), columns
    surplus, artificial = n, n + m
    width = n + 2 * m

    # Rows: A n - s + a = b, with `s` the surplus and `a` the artificial. A row flipped for
    # a negative rhs was multiplied through by -1, surplus included, so its sign flips too.
    table = []
    for j, (coeffs, rhs, flipped) in enumerate(prepared):
        row = [F(0)] * (width + 1)
        for i, value in enumerate(coeffs):
            row[i] = value
        row[surplus + j] = F(1) if flipped else F(-1)
        row[artificial + j] = F(1)
        row[width] = rhs
        table.append(row)
    basis = [artificial + j for j in range(m)]

    def pivot(objective, pr, pc):
        factor = table[pr][pc]
        table[pr] = [value / factor for value in table[pr]]
        for r in range(m):
            if r != pr and table[r][pc] != 0:
                scale = table[r][pc]
                table[r] = [a - scale * b for a, b in zip(table[r], table[pr])]
        if objective[pc] != 0:
            scale = objective[pc]
            for k in range(width + 1):
                objective[k] -= scale * table[pr][k]
        basis[pr] = pc

    def run(objective, allowed):
        """Pivot to optimality over `allowed` columns. Returns False if unbounded."""
        while True:
            entering = next((j for j in allowed if objective[j] < 0), None)
            if entering is None:
                return True
            ratios = [(table[r][width] / table[r][entering], basis[r], r)
                      for r in range(m) if table[r][entering] > 0]
            if not ratios:
                return False
            pivot(objective, min(ratios)[2], entering)

    # ---- phase one: minimise the sum of the artificials
    phase = [F(0)] * (width + 1)
    for j in range(m):
        phase[artificial + j] = F(1)
    # Price out the artificial basis so the objective row is consistent with it.
    for r in range(m):
        for k in range(width + 1):
            phase[k] -= table[r][k]
    run(phase, range(artificial))

    # The phase-one optimum is -phase[width] because the objective row was reduced.
    if -phase[width] > 0:
        # INFEASIBLE. y_j is the phase-one reduced cost of artificial column j, taken back
        # to the caller's sign convention: a row flipped for a negative rhs had its whole
        # inequality multiplied by -1, so its multiplier flips with it.
        # y_j is the simplex multiplier on row j. After phase one the objective row holds
        # each artificial's REDUCED cost, which is `1 - y_j` because the artificial's own
        # cost is 1. A row flipped for a negative right-hand side had its whole inequality
        # multiplied by -1, so its multiplier carries that sign back.
        y = []
        for j, (_, _, flipped) in enumerate(prepared):
            value = F(1) - phase[artificial + j]
            y.append(-value if flipped else value)
        return "infeasible", None, y

    # ---- phase two: the real cost, with the artificials pinned out of play
    objective = [F(0)] * (width + 1)
    for i, value in enumerate(cost):
        objective[i] = F(value)
    for r in range(m):
        if objective[basis[r]] != 0:
            scale = objective[basis[r]]
            for k in range(width + 1):
                objective[k] -= scale * table[r][k]
    if not run(objective, range(artificial)):
        return "unbounded", None, None

    point = [F(0)] * n
    for r in range(m):
        if basis[r] < n:
            point[basis[r]] = table[r][width]
    return "optimal", point, None


# ---------------------------------------------------------------- synthesis

def constraints(base, units, floor_pnl, lower, upper):
    """The objective as finitely many exact linear constraints on the sizes.

    Returns rows `(price, side, alpha, coefficients)` meaning

        alpha + sum(coefficients[i] * n[i]) >= floor_pnl

    where `alpha` is the base P&L at that site and `coefficients[i]` is what one unit of
    instrument `i` pays there. Feasibility over the WHOLE domain is exactly feasibility at
    these rows.

    WHY FINITELY MANY. For fixed sizes the P&L is affine on every open atom, so the
    condition holds on an atom exactly when it holds at the atom's endpoint limits -- the
    same argument `size_window` uses for one instrument. And the breakpoint SET does not
    depend on the sizes: it is the strikes, which come from the instruments' own terms. So
    one atom walk with unit sizes gives the sites that serve every member of the family,
    and "cheapest sizes meeting the objective" is a linear program with fixed rows.

    A SLOPED open piece never attains its infimum at an excluded end; the constraint there
    is a limit. Imposing it is still sound, because `>=` is closed: if the limit meets the
    floor then every interior price does, and if it does not, prices arbitrarily close to
    the end violate the objective. So the row is imposed as written, and no size is called
    feasible on the strength of a price the domain excludes.
    """
    cuts = base.breakpoints
    for unit in units:
        cuts = cuts | unit.breakpoints
    rows = []
    streams = [atoms(base, lower, upper, cuts)] + [atoms(unit, lower, upper, cuts) for unit in units]
    for pieces in zip(*streams):
        head = pieces[0]
        if head[0] == "point":
            rows.append((head[1], "at", head[2], [piece[2] for piece in pieces[1:]]))
            continue
        _, lo, hi, slope, intercept = head
        for at, side in ((lo, "above"), (hi, "below")):
            rows.append((at, side, slope * at + intercept,
                         [piece[3] * at + piece[4] for piece in pieces[1:]]))
    return rows


def synthesise(base, units, prices, floor_pnl, lower, upper, lot=1):
    """Cheapest whole-contract sizes meeting the objective, or a certificate that none do.

    `base` is the P&L of what the holder already has; `units` are the candidate
    instruments, one unit each; `prices[i]` is what one contract of instrument `i` costs.
    Returns a dict: `{"status": "feasible", "sizes": [...], "cost": ...}` or
    `{"status": "infeasible", "certificate": {...}}`.

    THE PROGRAM IS A RELAXATION. Sizes are whole contracts, but the linear program solves
    over the rationals; its answer is rounded UP, because rounding down could drop below
    the floor the program was solving for. The rounded structure is then RE-CHECKED with
    the evaluator -- `constraints` again, arithmetic only, no solver -- and reported only
    if it really meets the objective. PLAN section 3 states the rule and this obeys it: a
    structure is claimed because it was checked, never because a solver proposed it.

    INFEASIBILITY IS CLAIMED ONLY FOR THE RELAXATION. If the relaxed program is infeasible
    then no whole-contract answer exists either, since the integers are a subset of the
    rationals -- so the certificate transfers. The converse does not hold and is not
    claimed: a feasible relaxation whose rounding fails the re-check is reported as
    `rounding_failed`, which says the search did not find one, not that none exists.
    """
    rows = constraints(base, units, floor_pnl, lower, upper)
    # THE PREMIUM IS PART OF THE CONSTRAINT, not only of the objective. Buying `n` contracts
    # costs `n * price` whatever the price does, so the P&L at a site is
    #   alpha + sum(n_i * (payoff_i - price_i)),
    # and the coefficient is the payoff NET of its price. Leaving it out lets the program
    # buy protection for free: on the PLAN section 3 example that turned a case PLAN proves
    # infeasible -- minimax loss 1,600 against a 1,000 cap -- into "feasible".
    #
    # It is also what makes the certificate the one PLAN names: at the floor the net
    # coefficient is 1 - p and at the strike it is -p, so weighting those two rows by
    # (1 - p, p) cancels n and leaves -(D + p*A) >= cap, false whatever the size.
    net = [(at, side, alpha, [c - F(price) for c, price in zip(coefficients, prices)])
           for at, side, alpha, coefficients in rows]
    program = [(coefficients, floor_pnl - alpha) for _, _, alpha, coefficients in net]
    status, point, certificate = _simplex(program, [F(p) for p in prices], len(units))

    if status == "infeasible":
        # THE CERTIFICATE NAMES ITS SITES, and carries only the non-zero weights.
        #
        # A bare weight vector would be ordered by the rows, which makes row ORDER an
        # implicit contract between three implementations -- unchecked, and the kind that
        # drifts. Naming each site lets a checker look it up among its own rows: order stops
        # mattering, and a site the checker cannot find is a refusal rather than a silent
        # misalignment against the wrong constraint.
        #
        # Sparse because a Farkas certificate is sparse: PLAN section 3's is two rows out of
        # ten. It is also then readable -- "the floor at 60,000 weighted 0.2 against the
        # strike at 90,000 weighted 0.8" is a sentence someone can check by hand.
        weights = [{"price": at, "side": side, "weight": weight}
                   for (at, side, _, _), weight in zip(net, certificate) if weight != 0]
        return {"status": "infeasible", "certificate": {"kind": "farkas", "weights": weights}}
    if status != "optimal":
        return {"status": status}

    lot = F(lot)
    sizes = [(-((-value) // lot)) * lot for value in point]  # ceiling to the lot
    # THE RE-CHECK. Exactly the constraint rows, evaluated at the rounded sizes. This is
    # the evaluator's own arithmetic, not the solver's: a rounding that satisfies the
    # relaxation can still miss a row, and reporting it unchecked is how a "smallest size"
    # that then fails gets published (EVIDENCE section 9).
    met = all(alpha + sum(c * n for c, n in zip(coefficients, sizes)) >= floor_pnl
              for _, _, alpha, coefficients in net)
    if not met:
        return {"status": "rounding_failed", "relaxed": list(point)}
    return {"status": "feasible", "sizes": sizes,
            "cost": sum((F(p) * n for p, n in zip(prices, sizes)), F(0)),
            "relaxed": list(point)}


def _base_part(part):
    """One term of what the holder already has.

    Its own reader, not `_leg`: that one decodes an IR leg, whose `kind` is part of the
    frozen IR contract. A synthesis request describes a HOLDING, which may be linear spot
    exposure or a position already taken, so widening `_leg` would put a shape into the IR
    that the IR does not have.
    """
    kind = part["kind"]
    if kind == "linear":
        return linear(num(part["quantity"]), num(part["baseline"]))
    if kind == "indicator":
        return indicator(num(part["size"]), **_pays_on_kwargs(part["pays_on"]))
    if kind == "cash":
        return cash(num(part["amount"]))
    raise ValueError(f"unsupported base part: {kind}")


def synthesis_document(request):
    """A synthesis answer as a document, self-contained enough to check without this code.

    `request` is the question, as data (schema/synthesis.schema.json): the objective's floor
    and domain, the `base` legs the holder already has, the `candidates` offered with their
    prices, and the lot. The answer is appended; nothing else is.

    THE DOCUMENT CARRIES THE QUESTION, not just the answer. A checker rebuilds the rows from
    `base` and `candidates` and checks the answer against them -- which is the only way the
    answer means anything, since a checker that re-added the numbers this solver emitted
    would be confirming arithmetic rather than verifying a claim.

    IT CARRIES NO SOLVER STATE. No tableau, no pivot order, no basis. A certificate that
    needed the search replayed would not be a certificate; `weights` is checked by one
    multiplication and the feasible case by one evaluation.
    """
    floor_pnl = num(request["objective"]["min_pnl"])
    lower, upper = num(request["domain"]["lower"]), num(request["domain"]["upper"])
    base = total([_base_part(part) for part in request["base"]]) if request["base"] else cash(F(0))
    units = [indicator(F(1), **_pays_on_kwargs(candidate["pays_on"]))
             for candidate in request["candidates"]]
    prices = [num(candidate["price"]) for candidate in request["candidates"]]
    lot = num(request.get("lot", "1"))

    answer = synthesise(base, units, prices, floor_pnl, lower, upper, lot=lot)
    out = {"schema_version": "1", "request": request, "status": answer["status"]}
    if answer["status"] == "feasible":
        out["sizes"] = [{"candidate": candidate["id"], "size": fmt(size)}
                        for candidate, size in zip(request["candidates"], answer["sizes"])]
        out["cost"] = fmt(answer["cost"])
        out["relaxed"] = [fmt(value) for value in answer["relaxed"]]
    elif answer["status"] == "infeasible":
        out["certificate"] = {
            "kind": "farkas",
            "weights": [{"price": fmt(weight["price"]), "side": weight["side"],
                         "weight": fmt(weight["weight"])}
                        for weight in answer["certificate"]["weights"]],
        }
    elif answer["status"] == "rounding_failed":
        # The relaxation was feasible and no whole-contract rounding of it met the objective.
        # That is a statement about this SEARCH, never about existence: PLAN section 3 allows
        # claiming infeasibility only when the relaxation itself is infeasible.
        out["relaxed"] = [fmt(value) for value in answer["relaxed"]]
    return out


def _pays_on_kwargs(pays_on):
    """A `pays_on` document as keyword arguments for `indicator`."""
    kwargs = {}
    if "lower" in pays_on:
        kwargs["lower"] = num(pays_on["lower"])
        kwargs["lower_inclusive"] = pays_on["lower_inclusive"]
    if "upper" in pays_on:
        kwargs["upper"] = num(pays_on["upper"])
        kwargs["upper_inclusive"] = pays_on["upper_inclusive"]
    return kwargs


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


def smallest_reduction(quantity, baseline, cap, lower):
    """The smallest exposure reduction meeting the cap, as a kept quantity.

    Selling (quantity - keep) at the baseline and holding the cash leaves a linear
    P&L of keep*(S - baseline), whose worst case on the domain is keep*(lower -
    baseline). Setting that equal to the cap gives keep = -cap / (baseline - lower),
    the largest holding that still meets the cap, so the smallest sale that does.
    """
    keep = -cap / (baseline - lower)
    return min(keep, quantity)


def _breakevens(fn, lower, upper):
    out = []
    for piece in profile(fn, lower, upper):
        if piece["slope"] != 0:
            root = -piece["intercept"] / piece["slope"]
            if (piece["lower"] < root < piece["upper"]
                    or (root == piece["lower"] and piece["lower_inclusive"])
                    or (root == piece["upper"] and piece["upper_inclusive"])):
                out.append(fmt(root))
    return out


def _sized_leg_window(lowered, leg, lower, upper, baseline, cap):
    """The exact and whole-contract sizes of one book-walked leg that meet the cap.

    Only meaningful when this leg is the one being sized, so the rest of the
    proposal is the base. Returns None when the leg was not walked on a book: a
    hypothetical fixed price says nothing about what depth would allow.
    """
    if leg["premium"]["kind"] != "walked" or "levels" not in leg["premium"]:
        return None
    # The base is the LOWER profile: every other leg valued exactly as the verdict
    # values it, so a reduced leg contributes nothing while its premium still counts.
    #
    # Sizing against full value instead would answer a question the verdict does not
    # ask, and the answer can be wrong in the direction that matters: on 20 Sep, with
    # the base crediting reduced legs, a reported smallest size of one generated case
    # gave a worst P&L of -4923.49676 against a -4000 cap. A size window that names a
    # size which then fails is worse than no size window (EVIDENCE section 9).
    zeroed = {reduction["leg"] for reduction in lowered.get("reductions", [])}
    others = [other for other in lowered["legs"] if other["id"] != leg["id"]]
    base = total([linear(num(lowered["exposure"]["quantity"]), baseline)]
                 + [_leg(other) for other in others if other["id"] not in zeroed]
                 + [cash(-sum((leg_cost(other) for other in others), F(0)) - num(lowered["other_costs"]))])
    unit = _leg(dict(leg, size="1"))
    levels = [(num(price), num(size)) for price, size in leg["premium"]["levels"]]
    window = size_window(base, unit, levels, cap, lower, upper)
    out = {"leg": leg["id"], "status": window["status"]}
    if window["lower_bound"] is not None:
        out["lower_bound"] = fmt(window["lower_bound"])
        out["upper_bound"] = fmt(window["upper_bound"])
    # A SITE, not a price, may be absent. `size_window` returns `[low_site, high_site]` and
    # leaves a site None when no constraint binds there -- a wide cap binds at neither end,
    # so the whole entry is None, not a pair with a None price. Filtering on `price is not
    # None` unpacked first and crashed; the filter has to come before the unpacking.
    out["binding"] = [{"price": fmt(site[0]), "side": site[1]}
                      for site in window["binding"] if site is not None and site[0] is not None]
    if window["status"] == "nonempty":
        out["smallest"] = fmt(window["smallest"])
        out["largest"] = fmt(window["largest"])
    elif len(levels) == 1:
        # One flat price: the infeasibility has a two-line certificate. With D the loss
        # at the strike and A the further loss to the floor, the constraints at those two
        # sites are -D - p*n >= cap and -D - A + n*(1-p) >= cap. Weighting them by (1-p, p)
        # cancels n and leaves -(D + p*A) >= cap, which is false whatever the size.
        price = levels[0][0]
        out["certificate"] = {"kind": "farkas", "weights": [fmt(F(1) - price), fmt(price)]}
    return out


def evaluate(lowered):
    """Expected result for a lowered proposal (schema/ir.schema.json).

    Every reduction gives a *lower* profile, which is what the verdict rests on, and
    an *upper* profile, which is the best the proposal could be if the reduction were
    undone. With no reductions the two coincide. A violation that survives only on the
    lower profile, and only because of a rule that is not tight, is `needs_review`:
    the loose bound proves nothing about the real payoff, so it can never say `fails`.
    """
    lower, upper = num(lowered["domain"]["lower"]), num(lowered["domain"]["upper"])
    baseline = num(lowered["baseline"]["price"])
    quantity = num(lowered["exposure"]["quantity"])
    exposure = linear(quantity, baseline)
    premium = sum((leg_cost(leg) for leg in lowered["legs"]), F(0))
    other = num(lowered["other_costs"])
    reductions = lowered.get("reductions", [])

    # A BAND REDUCTION IS BANDED, NOT ZEROED.
    #
    # Every other reduction worst-cases its leg to zero. A declared basis bound says more
    # than that: the group is observed on another series that cannot move more than `b`
    # away, so its worth is the infimum of the group's SUMMED payoff over [S - b, S + b].
    # Zeroing it would throw the bound away and make a declared bound worth exactly as
    # much as none -- which it was until this rule existed.
    #
    # GROUPED. The infimum of a sum is not the sum of infima: two legs whose payoffs
    # cancel have a flat sum no basis move can hurt, while each alone is stepped.
    banded, band_parts = set(), []
    for reduction in reductions:
        if reduction["rule"] != "basis_band":
            continue
        members = [reduction["leg"]] + list(reduction.get("with", []))
        banded.update(members)
        group = [_leg(leg) for leg in lowered["legs"] if leg["id"] in set(members)]
        band_parts.append(band_infimum(total(group), num(reduction["bound"])))

    # A TOUCH-BOUNDED LEG IS KEPT, NOT ZEROED, for the same reason a banded group is.
    #
    # Its `pays_on` already IS the bound: lowering replaced the path-dependent payoff with
    # the inclusive terminal digital at the target, on the side the reference must travel.
    # Zeroing it here would discard that bound and make a sound lower bound worth exactly
    # as much as none. The leg is still REDUCED -- the bound is loose, so it can only make
    # a proposal need review -- but its value is the bound, not zero.
    bounded = {reduction["leg"] for reduction in reductions if reduction["rule"] == "price_touch"}
    # A ZEROING RULE WINS OVER A BOUND. `price_touch` says the leg is worth at least the
    # terminal digital; `deployer_settled` says it may be worth nothing at any price,
    # because the deployer submits the fraction. Both can apply to one leg, and the lower
    # of the two is the one the verdict may rest on -- crediting the bound over a zeroing
    # rule would raise the lower profile on a leg that may pay nothing, which is the one
    # direction that can turn a failing proposal into a passing one.
    zeroing = {reduction["leg"] for reduction in reductions if reduction["rule"] != "price_touch"}
    bounded -= zeroing
    zeroed = ({reduction["leg"] for reduction in reductions} - banded - bounded)
    loose_legs = {reduction["leg"] for reduction in reductions if not reduction["tight"]}

    # A reduced leg is valued at zero in the lower profile. Its premium still counts:
    # it was paid whatever the leg turns out to be worth.
    costs = cash(-premium - other)
    kept = [leg for leg in lowered["legs"] if leg["id"] not in zeroed and leg["id"] not in banded]
    pnl = total([exposure] + [_leg(leg) for leg in kept] + band_parts + [costs])
    # A long fully collateralized token is worth at most its size (EVIDENCE section 1),
    # so the upper profile credits every reduced leg with its full size.
    ceiling = sum((num(leg["size"]) for leg in lowered["legs"] if leg["id"] in zeroed), F(0))
    upper_pnl = (pnl + cash(ceiling)) if ceiling else pnl
    # A BANDED group's upper bound is its UNBANDED payoff, not its size.
    #
    # The band already gives a real lower bound, so crediting the full size here would be
    # looser than what is known. The best the group can be worth is what it pays when the
    # basis does not move at all -- so the correction is the unbanded payoff less the
    # banded one, which is non-negative everywhere by construction.
    if banded:
        upper_parts = [_leg(leg) for leg in lowered["legs"] if leg["id"] in banded]
        upper_pnl = total([upper_pnl] + upper_parts + [-part for part in band_parts])
    # A TOUCH-BOUNDED leg's upper bound is its FULL SIZE, not the bound.
    #
    # The bound pays only where the terminal price proves a touch; the leg itself pays on
    # every path that ever reached the target, including those that retraced. At any
    # terminal price below the target the true payoff may still be the full size, so the
    # best case is the whole size everywhere. The correction is size less the bound, which
    # is non-negative everywhere because the bound pays at most the size.
    for leg in lowered["legs"]:
        if leg["id"] in bounded:
            upper_pnl = total([upper_pnl, cash(num(leg["size"])), -_leg(leg)])

    failing, undecided, codes = [], [], []
    for clause in lowered["objective"]:
        threshold = num(clause["min_pnl"])
        # A clause may apply to a sub-interval of the domain. Evaluating it outside its
        # own interval would report a failure the objective never asked about.
        clause_lower, clause_upper = lower, upper
        if "on" in clause:
            clause_lower = max(lower, num(clause["on"]["lower"]))
            clause_upper = min(upper, num(clause["on"]["upper"]))
        if clause_upper < clause_lower:
            continue
        for interval in below(pnl, threshold, clause_lower, clause_upper):
            # The upper profile is the best the proposal could be. Where it also violates
            # the clause, the failure is real whatever the loose legs are worth. Where it
            # does not, the violation rests only on a loose bound, which proves nothing
            # about the real payoff: that is `needs_review`, never `fails`.
            established = below(upper_pnl, threshold, *_clip(interval, lower, upper)) if loose_legs else None
            if loose_legs and not established:
                shown = text_interval(interval)
                shown["clause"] = clause["id"]
                point = witness(pnl, interval)
                shown["witness"] = {"price": fmt(point["price"]), "pnl": fmt(point["pnl"])}
                shown["responsible_legs"] = sorted(loose_legs)
                undecided.append(shown)
                continue
            # A FAILURE IS REPORTED ONLY WHERE IT IS ESTABLISHED, witness included.
            #
            # The lower profile can violate across a wider span than the upper one does, and
            # the part where only the lower violates rests on the loose bound alone. Taking
            # the witness from the whole lower-profile interval could land it there -- on
            # case-0166 the lower profile fails across [60000, 95151.35] while the upper
            # fails only on [60000, 65000), and the witness came back at 77575.675, a price
            # where the best case MEETS the clause. So the established sub-intervals are the
            # ones reported, each with its own witness.
            for part in (established if established is not None else [interval]):
                shown = text_interval(part)
                shown["clause"] = clause["id"]
                point = witness(pnl, part)
                shown["witness"] = {"price": fmt(point["price"]), "pnl": fmt(point["pnl"])}
                # Once any leg has been bounded, a price alone is not a counterexample:
                # the witness has to carry the adverse state of each reduced leg.
                if zeroed:
                    shown["witness"]["adverse_states"] = _adverse(reductions)
                failing.append(shown)
    if failing:
        codes.append("LOSS_BOUND_EXCEEDED")
    for reduction in reductions:
        if reduction["reason_code"] not in codes:
            codes.append(reduction["reason_code"])
    # Sorted, not joined. A verdict code and the reduction codes come from two loops,
    # so the order they met in was an accident; two implementations would each pick a
    # different accident. ARCHITECTURE section 4 states the rule for every array.
    codes.sort()
    if undecided and not failing:
        verdict = "needs_review"
    else:
        verdict = "fails" if failing else "passes"

    worst, attained, where = infimum(pnl, lower, upper)
    bare_worst, _, bare_where = infimum(exposure, lower, upper)
    cap = min(num(clause["min_pnl"]) for clause in lowered["objective"])

    # The smallest exposure reduction that meets the same clauses, with no premium.
    keep = smallest_reduction(quantity, baseline, cap, lower)
    reduced = linear(keep, baseline)
    reduced_worst, _, reduced_where = infimum(reduced, lower, upper)

    result = {
        "schema_version": "1",
        "units": lowered["units"],
        "model_result": verdict,
        "execution_readiness": "not_evaluated",
        "evaluation_scope": "exhaustive_supported_terminal_model",
        "baseline": lowered["baseline"],
        "objective_valuation_time": lowered["objective_valuation_time"],
        "leg_observation_times": [leg["observation_time"] for leg in lowered["legs"]],
        "worst_case": {"pnl": fmt(worst), "attained": attained, "price": fmt(where)},
        "failing_intervals": failing,
        "profile": [text_interval(piece) for piece in profile(pnl, lower, upper)],
        "cost": {"premium": fmt(premium), "other_costs": fmt(other),
                 "pnl_at_baseline": fmt(pnl(baseline)), "breakevens": _breakevens(pnl, lower, upper)},
        "comparisons": {
            "no_hedge": {
                "worst_case": {"pnl": fmt(bare_worst), "price": fmt(bare_where)},
                "failing_intervals": [text_interval(i) for i in below(exposure, cap, lower, upper)],
                "proposal_better": [text_interval(i) for i in below(exposure - pnl, F(0), lower, upper)],
                "proposal_worse": [text_interval(i) for i in below(pnl - exposure, F(0), lower, upper)]},
            "smallest_reduction": {
                "keep_quantity": fmt(keep), "sell_quantity": fmt(quantity - keep), "sell_at": fmt(baseline),
                "worst_case": {"pnl": fmt(reduced_worst), "price": fmt(reduced_where)},
                "proposal_better": [text_interval(i) for i in below(reduced - pnl, F(0), lower, upper)],
                "proposal_worse": [text_interval(i) for i in below(pnl - reduced, F(0), lower, upper)]}},
        "reason_codes": codes,
        "assumptions": lowered["assumptions"],
        "checks_not_performed": ["LIVE_EXECUTION", "PATH_RISK"],
        "engine_version": "reference-oracle-3",
        "ir_digest": digest(lowered),
        "snapshots": sorted(_snapshots_of(lowered)),
    }
    # How the evidence was captured, as asserted by whatever captured it. Carried so a
    # reader sees the spread the result rests on; a pure evaluator cannot re-derive it.
    if "capture" in lowered:
        result["capture"] = lowered["capture"]
    if undecided:
        result["undecided_intervals"] = undecided
    if reductions:
        result["reductions"] = reductions
        result["upper_profile"] = [text_interval(piece) for piece in profile(upper_pnl, lower, upper)]
    # A LEG IN A MULTI-LEG BAND GROUP HAS NO SIZE WINDOW.
    #
    # "The smallest size of this leg that still meets the objective" presumes the rest of
    # the answer holds still while this leg moves. For a banded GROUP it does not: the
    # verdict values the group at the infimum of its SUMMED payoff over the band, so
    # resizing one member changes the sum and therefore the infimum. Measured on
    # good-basis-grouped, sizing binary-no at 0 / 500 / 1409 / 3000 moves the group's value
    # at 76,000 to 0 / 500 / 1409 / 3000 -- the other member's contribution is neither zero
    # nor its full payoff, and no per-leg base can stand for it.
    #
    # The two implementations answered it anyway and disagreed: the oracle credited a banded
    # sibling with zero, Go with its full unbanded payoff, so they reported different
    # binding prices for the same bundle. Neither is right. A size window that presumes a
    # separability the evaluator does not have is worse than none -- the same rule that took
    # sizing off the full-value base on 20 Sep (EVIDENCE section 9).
    joint = set()
    for reduction in reductions:
        members = [reduction["leg"]] + list(reduction.get("with", []))
        if len(members) > 1:
            joint.update(members)
    windows = [w for w in (_sized_leg_window(lowered, leg, lower, upper, baseline, cap)
                           for leg in lowered["legs"]
                           if leg["id"] not in zeroed and leg["id"] not in joint) if w]
    if windows:
        result["size_windows"] = windows
    return result


def compare(labelled):
    """Rank independently evaluated proposals (schema/comparison.schema.json).

    Takes (label, lowered, result) triples that were each evaluated on their own.
    Nothing here re-evaluates anything: the comparison cites results by `ir_digest`
    and restates none of their numbers, so each result stays about one proposal and
    stays independently checkable. A checker verifies the results first, then
    re-derives this ranking from them.

    Comparing proposals that do not share an objective, domain, baseline and
    valuation time would rank answers to different questions, so that is an error.
    """
    first = labelled[0][1]
    shared = {"domain": first["domain"], "baseline": first["baseline"],
              "objective": first["objective"], "objective_valuation_time": first["objective_valuation_time"]}
    for label, lowered, _ in labelled:
        if {key: lowered[key] for key in shared} != shared:
            raise ValueError(f"{label} does not share the objective, domain, baseline and valuation time")
    candidates = [{"label": label, "ir_digest": result["ir_digest"],
                   "model_result": result["model_result"], "cost": result["cost"]["premium"]}
                  for label, _, result in labelled]
    # Only a passing candidate is ranked: a cost that bought an unestablished result
    # has no place in an ordering by cost.
    passing = [c for c in candidates if c["model_result"] == "passes"]
    out = {"schema_version": "1", "shared": shared, "candidates": candidates,
           "ranked_by": "cost_of_smallest_passing_size", "engine_version": "reference-oracle-3"}
    if passing:
        out["ranking"] = [c["label"] for c in sorted(passing, key=lambda c: num(c["cost"]))]
    return out


def _snapshots_of(lowered):
    """Every snapshot the lowered proposal rests on, by hash."""
    out = set()
    source = lowered.get("baseline", {}).get("source")
    if source:
        out.add(source["snapshot"])
    for leg in lowered["legs"]:
        premium = leg.get("premium", {})
        if premium.get("kind") == "walked":
            out.add(premium["snapshot"])
    return out


def _clip(interval, lower, upper):
    """The interval as (lower, upper) bounds for a nested `below` call."""
    return max(interval["lower"], lower), min(interval["upper"], upper)


ADVERSE_STATES = {
    "price_touch": "the leg pays only where the terminal price proves a touch",
    "horizon_mismatch": "the leg's own observation pays zero",
    "unreviewed_family": "nothing is established about what the leg pays",
    "deployer_settled": "the deployer chooses what the leg pays",
}


def _adverse(reductions):
    """Why a price alone is not a counterexample once a leg has been bounded."""
    return [{"leg": reduction["leg"], "rule": reduction["rule"],
             "state": ADVERSE_STATES.get(reduction["rule"], "the leg is valued at zero")}
            for reduction in reductions]
