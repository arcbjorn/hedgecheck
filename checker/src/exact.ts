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
