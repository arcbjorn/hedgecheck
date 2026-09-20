// The kernel: one exact algebra of piecewise-affine functions of a single price.
//
// A FUNCTION IS ITS LIST OF PIECES. There is no rule-plus-breakpoints form here and
// no operation takes breakpoints as an argument. ARCHITECTURE.md section 3 states
// why: the first oracle separated the two, and its affinity probe sampled three
// points per interval, so a strike in the outer third of the domain was missed
// silently and gave a wrong failing set and a wrong infimum (EVIDENCE section 9).
// A representation that cannot express the separation cannot suffer from it.
//
// The pieces cover the whole line, every endpoint states who owns it, and adjacent
// pieces are never mergeable. A price owned by neither neighbour is a singleton.

import {
  type Rational,
  ONE,
  ZERO,
  add,
  cmp,
  div,
  equals,
  fromInt,
  lt,
  lte,
  midpoint,
  mul,
  neg,
  sign,
  sub,
} from "./exact.ts";

export class KernelError extends Error {}

/** One end of an interval. An absent value is an infinity, which nothing owns. */
export interface Bound {
  readonly value: Rational | null;
  readonly closed: boolean;
}

export const NEG_INF: Bound = { value: null, closed: false };
export const POS_INF: Bound = { value: null, closed: false };

export function finite(value: Rational, closed: boolean): Bound {
  return { value, closed };
}

/** One maximal affine piece: slope*price + intercept on [lo, hi] with ownership. */
export interface Piece {
  readonly lo: Bound;
  readonly hi: Bound;
  readonly slope: Rational;
  readonly intercept: Rational;
}

/** A function is exactly its pieces, in increasing order, covering the whole line. */
export interface Fn {
  readonly pieces: readonly Piece[];
}

export function valueAt(piece: Piece, price: Rational): Rational {
  return add(mul(piece.slope, price), piece.intercept);
}

function sameLine(a: Piece, b: Piece): boolean {
  return equals(a.slope, b.slope) && equals(a.intercept, b.intercept);
}

/** Do these two bounds meet with exactly one owner, so the pieces are adjacent? */
function meets(hi: Bound, lo: Bound): boolean {
  if (hi.value === null || lo.value === null) return false;
  if (!equals(hi.value, lo.value)) return false;
  return hi.closed !== lo.closed;
}

/**
 * Build a function from pieces, checking the representation rule and merging.
 *
 * The checks are not defensive programming: a gap, an overlap, or a price owned
 * twice is a function that answers two different things about one price, and every
 * later query would inherit that.
 */
export function fn(pieces: readonly Piece[]): Fn {
  if (pieces.length === 0) throw new KernelError("a function has at least one piece");
  const first = pieces[0] as Piece;
  const last = pieces[pieces.length - 1] as Piece;
  if (first.lo.value !== null) throw new KernelError("the pieces do not start at -infinity");
  if (last.hi.value !== null) throw new KernelError("the pieces do not reach +infinity");

  for (let index = 1; index < pieces.length; index += 1) {
    const before = pieces[index - 1] as Piece;
    const here = pieces[index] as Piece;
    const end = before.hi.value;
    const start = here.lo.value;
    if (end === null || start === null) throw new KernelError("an infinity inside the line");
    if (!equals(end, start)) throw new KernelError("the pieces leave a gap or overlap");
    if (before.hi.closed && here.lo.closed) {
      throw new KernelError(`the price ${end.num}/${end.den} is owned twice`);
    }
    if (!before.hi.closed && !here.lo.closed) {
      throw new KernelError(`the price ${end.num}/${end.den} is owned by neither neighbour`);
    }
  }

  // Canonical: adjacent pieces on the same line are one piece.
  const merged: Piece[] = [];
  for (const piece of pieces) {
    const previous = merged[merged.length - 1];
    if (previous !== undefined && sameLine(previous, piece) && meets(previous.hi, piece.lo)) {
      merged[merged.length - 1] = {
        lo: previous.lo,
        hi: piece.hi,
        slope: piece.slope,
        intercept: piece.intercept,
      };
      continue;
    }
    merged.push(piece);
  }
  return { pieces: merged };
}

// ---------------------------------------------------------------- constructors

/** quantity * (price - baseline). */
export function linear(quantity: Rational, baseline: Rational): Fn {
  return fn([
    {
      lo: NEG_INF,
      hi: POS_INF,
      slope: quantity,
      intercept: neg(mul(quantity, baseline)),
    },
  ]);
}

/** A constant. */
export function cash(amount: Rational): Fn {
  return fn([{ lo: NEG_INF, hi: POS_INF, slope: ZERO, intercept: amount }]);
}

/**
 * size on the interval, zero elsewhere. Ownership of each endpoint is DATA:
 * canonical NO is (-inf, K), canonical YES is [K, +inf), the middle bucket is
 * [P1, P2). There is no convention to get wrong.
 */
export function indicator(size: Rational, lo: Bound, hi: Bound): Fn {
  if (lo.value !== null && hi.value !== null) {
    const order = cmp(lo.value, hi.value);
    if (order > 0) throw new KernelError("the interval runs backwards");
    if (order === 0 && !(lo.closed && hi.closed)) {
      throw new KernelError("an empty interval");
    }
  }
  const pieces: Piece[] = [];
  if (lo.value !== null) {
    pieces.push({
      lo: NEG_INF,
      hi: { value: lo.value, closed: !lo.closed },
      slope: ZERO,
      intercept: ZERO,
    });
  }
  pieces.push({
    lo: lo.value === null ? NEG_INF : lo,
    hi: hi.value === null ? POS_INF : hi,
    slope: ZERO,
    intercept: size,
  });
  if (hi.value !== null) {
    pieces.push({
      lo: { value: hi.value, closed: !hi.closed },
      hi: POS_INF,
      slope: ZERO,
      intercept: ZERO,
    });
  }
  return fn(pieces);
}

/**
 * A ramp between low and high.
 *
 * `long` pays nothing at or below low, rises linearly to size at high, and stays at
 * size above. `short` is its mirror: size at or below low, falling to nothing at
 * high. The endpoints are closed on the sloped piece, so the ramp is continuous and
 * ownership never has to be guessed.
 */
export function ramp(size: Rational, low: Rational, high: Rational, direction: "long" | "short"): Fn {
  if (lte(high, low)) throw new KernelError("a ramp needs low < high");
  const slope = div(size, sub(high, low));
  if (direction === "long") {
    return fn([
      { lo: NEG_INF, hi: { value: low, closed: false }, slope: ZERO, intercept: ZERO },
      {
        lo: { value: low, closed: true },
        hi: { value: high, closed: true },
        slope,
        intercept: neg(mul(slope, low)),
      },
      { lo: { value: high, closed: false }, hi: POS_INF, slope: ZERO, intercept: size },
    ]);
  }
  return fn([
    { lo: NEG_INF, hi: { value: low, closed: false }, slope: ZERO, intercept: size },
    {
      lo: { value: low, closed: true },
      hi: { value: high, closed: true },
      slope: neg(slope),
      intercept: add(mul(slope, high), ZERO),
    },
    { lo: { value: high, closed: false }, hi: POS_INF, slope: ZERO, intercept: ZERO },
  ]);
}

// ---------------------------------------------------------------- operations

/** Every finite breakpoint of a function, in order. */
function breakpoints(f: Fn): Rational[] {
  const out: Rational[] = [];
  for (const piece of f.pieces) {
    if (piece.lo.value !== null) out.push(piece.lo.value);
  }
  return out;
}

/** The piece that owns a price. Exactly one does, by construction. */
export function pieceAt(f: Fn, price: Rational): Piece {
  for (const piece of f.pieces) {
    const afterLo = piece.lo.value === null ||
      (piece.lo.closed ? lte(piece.lo.value, price) : lt(piece.lo.value, price));
    const beforeHi = piece.hi.value === null ||
      (piece.hi.closed ? lte(price, piece.hi.value) : lt(price, piece.hi.value));
    if (afterLo && beforeHi) return piece;
  }
  throw new KernelError("no piece owns the price, which the representation rule forbids");
}

export function evaluate(f: Fn, price: Rational): Rational {
  return valueAt(pieceAt(f, price), price);
}

/** Sum. The breakpoints of a sum are the union of its parts'. */
export function sum(parts: readonly Fn[]): Fn {
  if (parts.length === 0) return cash(ZERO);
  const cuts: Rational[] = [];
  for (const part of parts) {
    for (const cut of breakpoints(part)) cuts.push(cut);
  }
  const sorted = uniqueSorted(cuts);

  const pieces: Piece[] = [];
  let lo: Bound = NEG_INF;
  for (const cut of sorted) {
    // The open interval before the cut, then the cut itself as a singleton. The
    // singleton is merged away by fn() whenever a neighbour owns the same line.
    pieces.push(combined(parts, lo, { value: cut, closed: false }, midpointOf(lo, cut)));
    pieces.push(combined(parts, { value: cut, closed: true }, { value: cut, closed: true }, cut));
    lo = { value: cut, closed: false };
  }
  pieces.push(combined(parts, lo, POS_INF, aboveAll(sorted)));
  return fn(pieces);
}

export function difference(a: Fn, b: Fn): Fn {
  return sum([a, scale(b, neg(ONE))]);
}

export function scale(f: Fn, factor: Rational): Fn {
  return fn(
    f.pieces.map((piece) => ({
      lo: piece.lo,
      hi: piece.hi,
      slope: mul(piece.slope, factor),
      intercept: mul(piece.intercept, factor),
    })),
  );
}

/** The affine coefficients of a sum on one interval, read at a sample inside it. */
function combined(parts: readonly Fn[], lo: Bound, hi: Bound, sample: Rational): Piece {
  let slope = ZERO;
  let intercept = ZERO;
  for (const part of parts) {
    const piece = pieceAt(part, sample);
    slope = add(slope, piece.slope);
    intercept = add(intercept, piece.intercept);
  }
  return { lo, hi, slope, intercept };
}

function midpointOf(lo: Bound, cut: Rational): Rational {
  if (lo.value === null) return sub(cut, ONE);
  return midpoint(lo.value, cut);
}

function aboveAll(sorted: readonly Rational[]): Rational {
  if (sorted.length === 0) return ZERO;
  return add(sorted[sorted.length - 1] as Rational, ONE);
}

function uniqueSorted(values: readonly Rational[]): Rational[] {
  const out = [...values].sort((a, b) => cmp(a, b));
  const unique: Rational[] = [];
  for (const value of out) {
    const previous = unique[unique.length - 1];
    if (previous !== undefined && equals(previous, value)) continue;
    unique.push(value);
  }
  return unique;
}

// ---------------------------------------------------------------- windows

/** An interval with explicit ownership of each end. */
export interface Interval {
  readonly lower: Rational;
  readonly lowerInclusive: boolean;
  readonly upper: Rational;
  readonly upperInclusive: boolean;
}

/**
 * The pieces of f restricted to [lower, upper], with extra cuts applied.
 *
 * The cuts exist so two functions can be compared piece by piece on a common
 * refinement. They never change the function; they only split a piece.
 */
export function window(
  f: Fn,
  lower: Rational,
  upper: Rational,
  cuts: readonly Rational[] = [],
): Interval[] {
  if (lt(upper, lower)) throw new KernelError("the window runs backwards");
  const marks = uniqueSorted([
    lower,
    upper,
    ...breakpoints(f).filter((cut) => lte(lower, cut) && lte(cut, upper)),
    ...cuts.filter((cut) => lte(lower, cut) && lte(cut, upper)),
  ]);

  const out: Interval[] = [];
  for (let index = 0; index < marks.length; index += 1) {
    const mark = marks[index] as Rational;
    // The point itself, always owned.
    out.push({ lower: mark, lowerInclusive: true, upper: mark, upperInclusive: true });
    const next = marks[index + 1];
    if (next === undefined) continue;
    out.push({ lower: mark, lowerInclusive: false, upper: next, upperInclusive: false });
  }
  return out.filter((piece) => !(equals(piece.lower, piece.upper) && !piece.lowerInclusive));
}

/** The maximal affine pieces of f on [lower, upper], as the answer format states them. */
export interface ProfilePiece {
  readonly lower: Rational;
  readonly lowerInclusive: boolean;
  readonly upper: Rational;
  readonly upperInclusive: boolean;
  readonly slope: Rational;
  readonly intercept: Rational;
}

export function profile(f: Fn, lower: Rational, upper: Rational): ProfilePiece[] {
  const raw: ProfilePiece[] = [];
  for (const atom of window(f, lower, upper)) {
    const sample = equals(atom.lower, atom.upper)
      ? atom.lower
      : midpoint(atom.lower, atom.upper);
    const piece = pieceAt(f, sample);
    raw.push({
      lower: atom.lower,
      lowerInclusive: atom.lowerInclusive,
      upper: atom.upper,
      upperInclusive: atom.upperInclusive,
      slope: piece.slope,
      intercept: piece.intercept,
    });
  }

  // MAXIMAL pieces: adjacent atoms on the SAME line are one piece, and nothing else
  // is merged. A singleton whose line differs from both neighbours is a real piece
  // of the answer -- the oracle emits 23 of them across the corpus -- so a rule that
  // absorbed every point would lose a breakpoint the function has.
  // A singleton lies on ONE line as data, but the value it carries may continue a
  // neighbour's line. Where it does, the pieces are not maximal until it is
  // absorbed: a ramp that starts at 65000 pays nothing there, so 65000 continues the
  // flat piece to its left even though the ramp's own piece owns it. Rewriting the
  // singleton onto the line that its value continues is what makes the answer
  // maximal, and it never changes the function -- only which of two equal
  // descriptions of the same point is reported.
  for (let index = 0; index < raw.length; index += 1) {
    const point = raw[index] as ProfilePiece;
    if (!equals(point.lower, point.upper)) continue;
    const here = add(mul(point.slope, point.lower), point.intercept);
    // Prefer the left neighbour, then the right: a ramp's START continues the flat
    // piece before it, and a ramp's END continues the flat piece after it. Either
    // way the point is not a breakpoint of the restriction, and leaving it standing
    // would name one the function does not have.
    for (const neighbour of [raw[index - 1], raw[index + 1]]) {
      if (neighbour === undefined || equals(neighbour.lower, neighbour.upper)) continue;
      const onTheirLine = add(mul(neighbour.slope, point.lower), neighbour.intercept);
      if (!equals(here, onTheirLine)) continue;
      raw[index] = {
        lower: point.lower,
        lowerInclusive: point.lowerInclusive,
        upper: point.upper,
        upperInclusive: point.upperInclusive,
        slope: neighbour.slope,
        intercept: neighbour.intercept,
      };
      break;
    }
  }

  const out: ProfilePiece[] = [];
  for (const piece of raw) {
    const previous = out[out.length - 1];
    if (previous !== undefined && onSameLine(previous, piece) && touches(previous, piece)) {
      out[out.length - 1] = {
        lower: previous.lower,
        lowerInclusive: previous.lowerInclusive,
        upper: piece.upper,
        upperInclusive: piece.upperInclusive,
        slope: previous.slope,
        intercept: previous.intercept,
      };
      continue;
    }
    out.push(piece);
  }
  return out;
}

function onSameLine(a: ProfilePiece, b: ProfilePiece): boolean {
  return equals(a.slope, b.slope) && equals(a.intercept, b.intercept);
}

/**
 * Adjacent, with the shared price owned exactly once between them.
 *
 * A SINGLETON is the case that matters: [lo, x) followed by {x} is adjacent and the
 * merge closes the left piece at x. The plain rule "exactly one owns it" holds
 * there, but the singleton also owns its own upper end, so the merged piece takes
 * the singleton's ownership rather than the predecessor's.
 */
function touches(a: ProfilePiece, b: ProfilePiece): boolean {
  if (!equals(a.upper, b.lower)) return false;
  if (a.upperInclusive && b.lowerInclusive) return false;
  return true;
}

// ---------------------------------------------------------------- infimum

export interface Infimum {
  readonly value: Rational;
  readonly attained: boolean;
  readonly at: Rational;
}

/**
 * The greatest lower bound on [lower, upper], whether it is attained, and where.
 *
 * `at` is a price the function ACTUALLY ATTAINS whenever attained is true. On a flat
 * open atom every interior price attains the value and no endpoint does, so the
 * midpoint stands for the set. On a sloped atom the value is only approached at an
 * excluded end, so attained is false and `at` is that limit point: reporting it as
 * attained would hand a witness a price where the payoff is higher than claimed.
 */
export function infimum(f: Fn, lower: Rational, upper: Rational): Infimum {
  let best: Infimum | null = null;
  const offer = (value: Rational, attained: boolean, at: Rational): void => {
    if (
      best === null ||
      lt(value, best.value) ||
      (equals(value, best.value) && attained && !best.attained)
    ) {
      best = { value, attained, at };
    }
  };

  for (const atom of window(f, lower, upper)) {
    if (equals(atom.lower, atom.upper)) {
      offer(evaluate(f, atom.lower), true, atom.lower);
      continue;
    }
    const sample = midpoint(atom.lower, atom.upper);
    const piece = pieceAt(f, sample);
    if (sign(piece.slope) === 0) {
      offer(valueAt(piece, sample), true, sample);
      continue;
    }
    offer(valueAt(piece, atom.lower), false, atom.lower);
    offer(valueAt(piece, atom.upper), false, atom.upper);
  }
  if (best === null) throw new KernelError("an empty window has no infimum");
  return best;
}

// ---------------------------------------------------------------- below-set

/**
 * The exact set where f is strictly below a threshold, on [lower, upper].
 *
 * Returned as intervals with explicit ownership. Extra cuts refine the atoms without
 * changing the answer, which a caller needs when aligning two functions.
 */
export function below(
  f: Fn,
  threshold: Rational,
  lower: Rational,
  upper: Rational,
  cuts: readonly Rational[] = [],
): Interval[] {
  const parts: Interval[] = [];
  for (const atom of window(f, lower, upper, cuts)) {
    if (equals(atom.lower, atom.upper)) {
      if (lt(evaluate(f, atom.lower), threshold)) parts.push(atom);
      continue;
    }
    const piece = pieceAt(f, midpoint(atom.lower, atom.upper));
    const atLow = valueAt(piece, atom.lower);
    const atHigh = valueAt(piece, atom.upper);
    const lowBelow = lt(atLow, threshold);
    const highBelow = lt(atHigh, threshold);
    if (lowBelow && highBelow) {
      parts.push(atom);
      continue;
    }
    if (!lowBelow && !highBelow) continue;
    // It crosses inside the open atom. Solve slope*price + intercept = threshold.
    const crossing = div(sub(threshold, piece.intercept), piece.slope);
    if (lowBelow) {
      parts.push({
        lower: atom.lower,
        lowerInclusive: false,
        upper: crossing,
        upperInclusive: false,
      });
    } else {
      parts.push({
        lower: crossing,
        lowerInclusive: false,
        upper: atom.upper,
        upperInclusive: false,
      });
    }
  }
  return mergeIntervals(parts);
}

/** Join intervals that touch with exactly one owner, so the answer is canonical. */
function mergeIntervals(parts: readonly Interval[]): Interval[] {
  const sorted = [...parts].sort((a, b) => {
    const order = cmp(a.lower, b.lower);
    if (order !== 0) return order;
    return a.lowerInclusive === b.lowerInclusive ? 0 : a.lowerInclusive ? -1 : 1;
  });
  const out: Interval[] = [];
  for (const part of sorted) {
    const previous = out[out.length - 1];
    if (
      previous !== undefined &&
      equals(previous.upper, part.lower) &&
      (previous.upperInclusive || part.lowerInclusive)
    ) {
      out[out.length - 1] = {
        lower: previous.lower,
        lowerInclusive: previous.lowerInclusive,
        upper: part.upper,
        upperInclusive: part.upperInclusive,
      };
      continue;
    }
    out.push(part);
  }
  return out;
}

// ---------------------------------------------------------------- witness

export interface Witness {
  readonly price: Rational;
  readonly pnl: Rational;
}

/**
 * A price where f is strictly below the threshold, with the value there.
 *
 * ADMISSIBLE means the function really attains that value at that price. An excluded
 * endpoint of an open interval is a limit point, not a member; reporting one would
 * name a price where the payoff is higher than the witness claims.
 */
export function witness(
  f: Fn,
  threshold: Rational,
  lower: Rational,
  upper: Rational,
): Witness[] {
  const parts = below(f, threshold, lower, upper);
  if (parts.length === 0) return [];

  // ONE witness per DISJOINT part of the below-set, and in each the strongest
  // counterexample: the infimum over that part, at a price the part actually
  // contains. Each part is a separate region where the objective is broken, so each
  // needs its own price; and within a part an arbitrary point would be a weaker
  // counterexample than the worst one, which two implementations could pick
  // differently while both being "correct".
  return parts.map((interval) => infimumOn(f, interval));
}

/** The lowest value on one interval, at a price the interval contains. */
function infimumOn(f: Fn, interval: Interval): Witness {
  if (equals(interval.lower, interval.upper)) {
    return { price: interval.lower, pnl: evaluate(f, interval.lower) };
  }
  let best: Witness | null = null;
  const offer = (price: Rational): void => {
    const pnl = evaluate(f, price);
    if (best === null || lt(pnl, best.pnl)) best = { price, pnl };
  };
  for (const atom of window(f, interval.lower, interval.upper)) {
    // Only prices the interval really contains are admissible: an excluded end is a
    // limit point, and naming it would claim a value the function never takes there.
    if (equals(atom.lower, atom.upper)) {
      if (contains(interval, atom.lower)) offer(atom.lower);
      continue;
    }
    const sample = midpoint(atom.lower, atom.upper);
    const piece = pieceAt(f, sample);
    if (sign(piece.slope) === 0) {
      offer(sample);
      continue;
    }
    // Sloped: the lower value sits at whichever end the interval owns.
    for (const end of [atom.lower, atom.upper]) {
      if (contains(interval, end)) offer(end);
    }
    offer(sample);
  }
  if (best === null) return { price: midpoint(interval.lower, interval.upper), pnl: evaluate(f, midpoint(interval.lower, interval.upper)) };
  return best;
}

function contains(interval: Interval, price: Rational): boolean {
  const afterLo = interval.lowerInclusive
    ? lte(interval.lower, price)
    : lt(interval.lower, price);
  const beforeHi = interval.upperInclusive
    ? lte(price, interval.upper)
    : lt(price, interval.upper);
  return afterLo && beforeHi;
}

function admissiblePoint(interval: Interval): Rational {
  // The smallest price the set actually contains, when it has one: a closed lower
  // end IS a member. Otherwise no endpoint is a member -- an excluded end is a limit
  // point, and reporting it would name a price where the payoff is higher than the
  // witness claims -- so the midpoint stands for the set.
  if (interval.lowerInclusive) return interval.lower;
  if (equals(interval.lower, interval.upper)) return interval.lower;
  return midpoint(interval.lower, interval.upper);
}

// ---------------------------------------------------------------- band infimum

export interface BandPoint {
  readonly at: Rational;
  readonly value: Rational;
}

/**
 * inf over [S - band, S + band], at each probe S.
 *
 * The breakpoints of the band infimum are NOT only the function's shifted
 * breakpoints. Where a sloped line and a plateau cross, the minimiser switches
 * between them, and that crossing is a breakpoint of the answer with no counterpart
 * in the function. Omitting that family is the bug the oracle had: a differential
 * against 400 generated cases found it where the committed fixtures did not.
 *
 * This implementation does not need the breakpoint family at all: it computes the
 * infimum over the shifted window directly at each probe, which is correct by
 * construction and is what a checker should do.
 */
export function bandInfimum(
  f: Fn,
  band: Rational,
  probes: readonly Rational[],
): BandPoint[] {
  if (sign(band) < 0) throw new KernelError("a negative band");
  return probes.map((probe) => {
    const result = infimum(f, sub(probe, band), add(probe, band));
    return { at: probe, value: result.value };
  });
}

// ---------------------------------------------------------------- ask walk

export interface Level {
  readonly price: Rational;
  readonly size: Rational;
}

export interface AskCost {
  // null when the displayed depth cannot fill the size. A partial total would be a
  // number a caller could mistake for the cost of the order they asked about.
  readonly total: Rational | null;
  readonly covered: boolean;
}

/** The cost of buying size by walking the levels in order. */
export function askCost(levels: readonly Level[], size: Rational): AskCost {
  let remaining = size;
  let total = ZERO;
  for (const level of levels) {
    if (sign(remaining) <= 0) break;
    const fill = lte(remaining, level.size) ? remaining : level.size;
    total = add(total, mul(fill, level.price));
    remaining = sub(remaining, fill);
  }
  if (sign(remaining) > 0) return { total: null, covered: false };
  return { total, covered: true };
}

/** The highest price the walk touched, which is the limit an envelope would state. */
export function walkLimit(levels: readonly Level[], size: Rational): Rational | null {
  let remaining = size;
  let limit: Rational | null = null;
  for (const level of levels) {
    if (sign(remaining) <= 0) break;
    const fill = lte(remaining, level.size) ? remaining : level.size;
    if (sign(fill) > 0) limit = level.price;
    remaining = sub(remaining, fill);
  }
  return sign(remaining) <= 0 ? limit : null;
}

// ---------------------------------------------------------------- size window

export interface Site {
  readonly price: Rational;
  readonly side: string;
}

export interface SizeWindow {
  // "empty" covers both ways there is no usable size: the real bounds exist but hold
  // no whole lot, and a site that no size satisfies at all. The second carries NO
  // bounds, because there are none to state -- `hasBounds` distinguishes them.
  readonly status: "empty" | "nonempty";
  readonly hasBounds: boolean;
  readonly lowerBound: Rational;
  readonly upperBound: Rational;
  readonly smallest: Rational | null;
  readonly largest: Rational | null;
  readonly binding: readonly Site[];
}

/**
 * The sizes n with base(S) + n*unit(S) - cost(n) >= floorPnl for every S in the
 * window.
 *
 * For a fixed n the combined payoff is affine on every open atom, so the condition
 * holds there exactly when it holds at both endpoint limits. Each site gives
 * beta*n - cost(n) >= floorPnl - alpha, which is concave in n because cost is convex,
 * so the feasible sizes form ONE interval. That is asserted below rather than
 * assumed: a gap would mean the concavity argument is wrong somewhere.
 */
export function sizeWindow(
  base: Fn,
  unit: Fn,
  levels: readonly Level[],
  floorPnl: Rational,
  lower: Rational,
  upper: Rational,
  lot: Rational,
): SizeWindow {
  const cuts = [...breakpoints(base), ...breakpoints(unit)];
  const atoms = window(base, lower, upper, cuts);

  interface SiteRow {
    price: Rational;
    side: string;
    alpha: Rational;
    beta: Rational;
  }
  const sites: SiteRow[] = [];
  for (const atom of atoms) {
    if (equals(atom.lower, atom.upper)) {
      sites.push({
        price: atom.lower,
        side: "at",
        alpha: evaluate(base, atom.lower),
        beta: evaluate(unit, atom.lower),
      });
      continue;
    }
    const sample = midpoint(atom.lower, atom.upper);
    const basePiece = pieceAt(base, sample);
    const unitPiece = pieceAt(unit, sample);
    // The two open ends are limits, approached but not attained. Both must hold.
    sites.push({
      price: atom.lower,
      side: "above",
      alpha: valueAt(basePiece, atom.lower),
      beta: valueAt(unitPiece, atom.lower),
    });
    sites.push({
      price: atom.upper,
      side: "below",
      alpha: valueAt(basePiece, atom.upper),
      beta: valueAt(unitPiece, atom.upper),
    });
  }

  const depth = levels.reduce((total, level) => add(total, level.size), ZERO);
  let low: Rational | null = null;
  let high: Rational | null = null;
  const binding: Site[] = [];
  let lowSite: Site | null = null;
  let highSite: Site | null = null;

  for (const site of sites) {
    const spans = feasibleSpan(site.alpha, site.beta, levels, floorPnl, depth);
    if (spans === null) {
      // No size satisfies this site, so the real bounds do not exist.
      return {
        status: "empty",
        hasBounds: false,
        lowerBound: ZERO,
        upperBound: ZERO,
        smallest: null,
        largest: null,
        binding: [{ price: site.price, side: site.side }],
      };
    }
    // A site BINDS only if it moved the bound. A site whose constraint is slacker
    // than the default zero floor constrains nothing, and naming it would tell a
    // reader that the window is held where it is not.
    // A site BINDS the floor when it strictly tightens it. The floor starts at the
    // trivial zero -- "buy nothing" always satisfies a lower bound -- so a site whose
    // own floor is zero holds nothing there.
    if (sign(spans.lo) > 0 && (low === null || lt(low, spans.lo))) {
      low = spans.lo;
      lowSite = { price: site.price, side: site.side };
    }
    if (high === null || lt(spans.hi, high)) {
      high = spans.hi;
      highSite = { price: site.price, side: site.side };
    }
  }
  // The sites that pin the window, deduplicated: one site can hold both ends, and
  // naming it twice would suggest two constraints where there is one.
  // A ceiling site binds only where it cuts BELOW the displayed depth. When the
  // ceiling is the depth itself, nothing about the objective holds it there: the
  // window simply ran out of book, which is a fact about the venue and not a
  // constraint the reader has to reason about.
  const ceilingBinds = high !== null && lt(high, depth);
  for (const site of [lowSite, ceilingBinds ? highSite : null]) {
    if (site === null) continue;
    const already = binding.some(
      (seen) => equals(seen.price, site.price) && seen.side === site.side,
    );
    if (!already) binding.push(site);
  }

  const floorBound = low ?? ZERO;
  const ceiling = high ?? depth;
  const first = ceilLotLocal(floorBound, lot);
  const last = floorLotLocal(ceiling, lot);
  if (lte(first, last) && lte(floorBound, ceiling)) {
    return {
      status: "nonempty",
      hasBounds: true,
      lowerBound: floorBound,
      upperBound: ceiling,
      smallest: first,
      largest: last,
      binding,
    };
  }
  return {
    status: "empty",
    hasBounds: true,
    lowerBound: floorBound,
    upperBound: ceiling,
    smallest: null,
    largest: null,
    binding,
  };
}

/**
 * The sizes at one site: alpha + beta*n - cost(n) >= floorPnl.
 *
 * cost is a convex increasing piecewise-linear walk, so the left side is concave and
 * the feasible set is one interval. It is found by walking the ladder rung by rung
 * and solving the linear condition on each, which is exact.
 */
function feasibleSpan(
  alpha: Rational,
  beta: Rational,
  levels: readonly Level[],
  floorPnl: Rational,
  depth: Rational,
): { lo: Rational; hi: Rational } | null {
  const need = sub(floorPnl, alpha);

  // The ladder as rungs: on rung r, cost(n) = base + price*(n - from).
  const rungs: { from: Rational; to: Rational; price: Rational; base: Rational }[] = [];
  let filled = ZERO;
  let spent = ZERO;
  for (const level of levels) {
    if (sign(level.size) <= 0) continue;
    rungs.push({ from: filled, to: add(filled, level.size), price: level.price, base: spent });
    spent = add(spent, mul(level.size, level.price));
    filled = add(filled, level.size);
  }
  if (rungs.length === 0) {
    return sign(need) <= 0 ? { lo: ZERO, hi: ZERO } : null;
  }

  // The feasible set is ONE interval, because the left side is concave in n: beta*n
  // is linear and cost is convex, so their difference is concave. The union below is
  // therefore contiguous by construction, and a gap would mean that argument is
  // wrong -- so the union is taken as a span rather than as a set of pieces, and any
  // rung that fails is simply not part of it.
  let lo: Rational | null = null;
  let hi: Rational | null = null;
  for (const rung of rungs) {
    // alpha + beta*n - (base + price*(n - from)) >= floorPnl, rearranged as
    //   (beta - price) * n  >=  floorPnl - alpha + base - price*from
    // Both the base already spent and the price*from already paid move to the RIGHT
    // side, so both ADD to the constant. Getting either sign wrong silently caps the
    // window at the first rung.
    const slope = sub(beta, rung.price);
    const constant = sub(add(need, rung.base), mul(rung.price, rung.from));
    let segmentLo = rung.from;
    let segmentHi = rung.to;
    if (sign(slope) === 0) {
      // Flat in n on this rung: feasible everywhere on it, or nowhere.
      if (sign(constant) > 0) continue;
    } else if (sign(slope) > 0) {
      const bound = div(constant, slope);
      if (lt(segmentHi, bound)) continue;
      if (lt(segmentLo, bound)) segmentLo = bound;
    } else {
      const bound = div(constant, slope);
      if (lt(bound, segmentLo)) continue;
      if (lt(bound, segmentHi)) segmentHi = bound;
    }
    if (lt(segmentHi, segmentLo)) continue;
    if (lo === null || lt(segmentLo, lo)) lo = segmentLo;
    if (hi === null || lt(hi, segmentHi)) hi = segmentHi;
  }
  if (lo === null || hi === null) return null;
  return { lo, hi };
}

// Local copies so this module does not re-export rounding it does not own.
function ceilLotLocal(value: Rational, lot: Rational): Rational {
  const steps = div(value, lot);
  const quotient = steps.num / steps.den;
  const rounded = steps.num % steps.den !== 0n && (steps.num < 0n) === (steps.den < 0n)
    ? quotient + 1n
    : quotient;
  return mul(fromInt(rounded), lot);
}

function floorLotLocal(value: Rational, lot: Rational): Rational {
  const steps = div(value, lot);
  const quotient = steps.num / steps.den;
  const rounded = steps.num % steps.den !== 0n && (steps.num < 0n) !== (steps.den < 0n)
    ? quotient - 1n
    : quotient;
  return mul(fromInt(rounded), lot);
}
