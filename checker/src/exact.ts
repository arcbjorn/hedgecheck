// Exact numbers: one grammar in, one canonical form out. No dependencies.
//
// The grammar is enforced before any arithmetic. It is the same expression the Go engine
// and the Python oracle enforce, because their rational libraries disagree with it and
// with each other about strings such as "0x10", "1e3", "+5" and " 5".

export const MAX_LENGTH = 80;

const GRAMMAR = /^(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|-?(?:0|[1-9][0-9]*)\/[1-9][0-9]*)$/;

/** A rational in lowest terms with a positive denominator. */
export interface Rational {
  readonly num: bigint;
  readonly den: bigint;
}

export class NumberError extends Error {}

function gcd(a: bigint, b: bigint): bigint {
  let x = a < 0n ? -a : a;
  let y = b < 0n ? -b : b;
  while (y !== 0n) {
    [x, y] = [y, x % y];
  }
  return x;
}

export function rational(num: bigint, den: bigint): Rational {
  if (den === 0n) throw new NumberError("zero denominator");
  const sign = den < 0n ? -1n : 1n;
  const divisor = gcd(num, den) || 1n;
  return { num: (sign * num) / divisor, den: (sign * den) / divisor };
}

export function parse(text: string): Rational {
  if (typeof text !== "string" || text.length > MAX_LENGTH || !GRAMMAR.test(text)) {
    throw new NumberError("not in the number grammar");
  }
  const slash = text.indexOf("/");
  if (slash >= 0) {
    return rational(BigInt(text.slice(0, slash)), BigInt(text.slice(slash + 1)));
  }
  const negative = text.startsWith("-");
  const body = negative ? text.slice(1) : text;
  const point = body.indexOf(".");
  const whole = point < 0 ? body : body.slice(0, point);
  const fraction = point < 0 ? "" : body.slice(point + 1);
  const magnitude = BigInt(whole + fraction);
  return rational(negative ? -magnitude : magnitude, 10n ** BigInt(fraction.length));
}

/** Canonical text: a terminating decimal when one exists, otherwise "p/q" in lowest terms. */
export function format(value: Rational): string {
  let rest = value.den;
  for (const prime of [2n, 5n]) {
    while (rest % prime === 0n) rest /= prime;
  }
  if (rest !== 1n) return `${value.num}/${value.den}`;
  let places = 0;
  let scale = 1n;
  while (scale % value.den !== 0n) {
    scale *= 10n;
    places += 1;
  }
  const magnitude = (value.num < 0n ? -value.num : value.num) * (scale / value.den);
  const digits = magnitude.toString().padStart(places + 1, "0");
  const cut = digits.length - places;
  const text = places > 0 ? `${digits.slice(0, cut)}.${digits.slice(cut)}` : digits;
  return value.num < 0n ? `-${text}` : text;
}

// ---------------------------------------------------------------- arithmetic
//
// Every operation returns a NEW value and touches neither operand. The interface is
// readonly, which the type checker enforces, but the discipline matters beyond the
// types: a shared rational that one caller normalised in place would be a silent
// wrong answer rather than a crash, and this kernel stores coefficients in pieces and
// reuses them across sums.

export const ZERO: Rational = { num: 0n, den: 1n };
export const ONE: Rational = { num: 1n, den: 1n };

export function fromInt(value: bigint): Rational {
  return { num: value, den: 1n };
}

export function add(a: Rational, b: Rational): Rational {
  return rational(a.num * b.den + b.num * a.den, a.den * b.den);
}

export function sub(a: Rational, b: Rational): Rational {
  return rational(a.num * b.den - b.num * a.den, a.den * b.den);
}

export function mul(a: Rational, b: Rational): Rational {
  return rational(a.num * b.num, a.den * b.den);
}

/** Division. Dividing by zero is an error, never an infinity. */
export function div(a: Rational, b: Rational): Rational {
  if (b.num === 0n) throw new NumberError("division by zero");
  return rational(a.num * b.den, a.den * b.num);
}

export function neg(a: Rational): Rational {
  return { num: -a.num, den: a.den };
}

/** -1, 0 or 1 as a is less than, equal to or greater than b. */
export function cmp(a: Rational, b: Rational): number {
  const left = a.num * b.den;
  const right = b.num * a.den;
  return left < right ? -1 : left > right ? 1 : 0;
}

export function sign(a: Rational): number {
  return a.num < 0n ? -1 : a.num > 0n ? 1 : 0;
}

export function equals(a: Rational, b: Rational): boolean {
  return a.num === b.num && a.den === b.den;
}

export function lt(a: Rational, b: Rational): boolean {
  return cmp(a, b) < 0;
}

export function lte(a: Rational, b: Rational): boolean {
  return cmp(a, b) <= 0;
}

export function min(a: Rational, b: Rational): Rational {
  return lte(a, b) ? a : b;
}

export function max(a: Rational, b: Rational): Rational {
  return lte(a, b) ? b : a;
}

export function abs(a: Rational): Rational {
  return a.num < 0n ? neg(a) : a;
}

/** The midpoint of two values, exactly. */
export function midpoint(a: Rational, b: Rational): Rational {
  return div(add(a, b), fromInt(2n));
}

// floorLot and ceilLot round to a multiple of a lot.
//
// BigInt division truncates toward zero, so a negative quotient needs a correction:
// -7n / 2n is -3n, and the floor is -4n. Sizes are nonnegative in practice, but a
// rounding function that is wrong on half its domain is a trap for the first caller
// who passes a difference.

function floorDiv(num: bigint, den: bigint): bigint {
  const quotient = num / den;
  return num % den !== 0n && (num < 0n) !== (den < 0n) ? quotient - 1n : quotient;
}

function ceilDiv(num: bigint, den: bigint): bigint {
  const quotient = num / den;
  return num % den !== 0n && (num < 0n) === (den < 0n) ? quotient + 1n : quotient;
}

/** The largest multiple of lot that is at most value. */
export function floorLot(value: Rational, lot: Rational): Rational {
  if (sign(lot) <= 0) throw new NumberError("the lot must be positive");
  const steps = div(value, lot);
  return mul(fromInt(floorDiv(steps.num, steps.den)), lot);
}

/** The smallest multiple of lot that is at least value. */
export function ceilLot(value: Rational, lot: Rational): Rational {
  if (sign(lot) <= 0) throw new NumberError("the lot must be positive");
  const steps = div(value, lot);
  return mul(fromInt(ceilDiv(steps.num, steps.den)), lot);
}
