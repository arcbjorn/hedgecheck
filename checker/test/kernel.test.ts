// The kernel gate: fixtures/kernel/cases.json, the same file the Go engine passes.
//
// Two implementations are asked the same question, not handed the same answer: the
// case describes legs in the lowered-proposal vocabulary and the checker builds the
// function through its own constructors.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { format, parse, type Rational } from "../src/exact.ts";
import {
  askCost,
  bandInfimum,
  below,
  cash,
  finite,
  type Fn,
  indicator,
  infimum,
  type Level,
  linear,
  NEG_INF,
  POS_INF,
  profile,
  ramp,
  sizeWindow,
  sum,
  witness,
} from "../src/pwa.ts";

const here = (path: string) => new URL(path, import.meta.url);

interface Leg {
  kind: string;
  quantity?: string;
  baseline?: string;
  amount?: string;
  size?: string;
  lower?: string;
  lower_inclusive?: boolean;
  upper?: string;
  upper_inclusive?: boolean;
  low?: string;
  high?: string;
}

interface Case {
  name: string;
  query: string;
  legs?: Leg[];
  base_legs?: Leg[];
  unit_legs?: Leg[];
  lower: string;
  upper: string;
  threshold?: string;
  cuts?: string[];
  band?: string;
  probes?: string[];
  levels?: string[][];
  size?: string;
  floor_pnl?: string;
  answer: unknown;
}

function build(legs: readonly Leg[]): Fn {
  const parts = legs.map((leg) => {
    switch (leg.kind) {
      case "linear":
        return linear(parse(leg.quantity as string), parse(leg.baseline as string));
      case "cash":
        return cash(parse(leg.amount as string));
      case "indicator": {
        const lo = leg.lower === undefined
          ? NEG_INF
          : finite(parse(leg.lower), leg.lower_inclusive === true);
        const hi = leg.upper === undefined
          ? POS_INF
          : finite(parse(leg.upper), leg.upper_inclusive === true);
        return indicator(parse(leg.size as string), lo, hi);
      }
      case "ramp_long":
        return ramp(parse(leg.size as string), parse(leg.low as string), parse(leg.high as string), "long");
      case "ramp_short":
        return ramp(parse(leg.size as string), parse(leg.low as string), parse(leg.high as string), "short");
      default:
        throw new Error(`unknown leg kind ${leg.kind}`);
    }
  });
  return sum(parts);
}

function levelsOf(rows: readonly string[][]): Level[] {
  return rows.map((row) => ({ price: parse(row[0] as string), size: parse(row[1] as string) }));
}

/** The answer, rendered as the fixture states it: canonical text, never a number. */
function answerFor(testCase: Case): unknown {
  const lower = parse(testCase.lower);
  const upper = parse(testCase.upper);
  switch (testCase.query) {
    case "profile":
      return build(testCase.legs ?? []).pieces.length === 0 ? [] : profile(build(testCase.legs ?? []), lower, upper).map((piece) => ({
        intercept: format(piece.intercept),
        lower: format(piece.lower),
        lower_inclusive: piece.lowerInclusive,
        slope: format(piece.slope),
        upper: format(piece.upper),
        upper_inclusive: piece.upperInclusive,
      }));
    case "infimum": {
      const result = infimum(build(testCase.legs ?? []), lower, upper);
      return { at: format(result.at), attained: result.attained, value: format(result.value) };
    }
    case "below":
      return below(
        build(testCase.legs ?? []),
        parse(testCase.threshold as string),
        lower,
        upper,
        (testCase.cuts ?? []).map(parse),
      ).map((interval) => ({
        lower: format(interval.lower),
        lower_inclusive: interval.lowerInclusive,
        upper: format(interval.upper),
        upper_inclusive: interval.upperInclusive,
      }));
    case "witness":
      return witness(build(testCase.legs ?? []), parse(testCase.threshold as string), lower, upper)
        .map((found) => ({ pnl: format(found.pnl), price: format(found.price) }));
    case "band":
      return bandInfimum(
        build(testCase.legs ?? []),
        parse(testCase.band as string),
        (testCase.probes ?? []).map(parse),
      ).map((point) => ({ at: format(point.at), value: format(point.value) }));
    case "ask_cost": {
      const result = askCost(levelsOf(testCase.levels ?? []), parse(testCase.size as string));
      return {
        covered: result.covered,
        total: result.total === null ? null : format(result.total),
      };
    }
    case "size_window": {
      const result = sizeWindow(
        build(testCase.base_legs ?? []),
        build(testCase.unit_legs ?? []),
        levelsOf(testCase.levels ?? []),
        parse(testCase.floor_pnl as string),
        lower,
        upper,
        parse("1"),
      );
      const out: Record<string, unknown> = {
        binding: result.binding.map((site) => ({ price: format(site.price), side: site.side })),
        status: result.status,
      };
      if (result.hasBounds) {
        out["lower_bound"] = format(result.lowerBound);
        out["upper_bound"] = format(result.upperBound);
      }
      if (result.smallest !== null) out["smallest"] = format(result.smallest);
      if (result.largest !== null) out["largest"] = format(result.largest);
      return out;
    }
    default:
      throw new Error(`unknown query ${testCase.query}`);
  }
}

/** Stable text, so comparison is on content and not on key order. */
function canonicalText(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalText).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([key, item]) => `"${key}":${canonicalText(item)}`).join(",")}}`;
  }
  if (typeof value === "string") return `"${value}"`;
  return String(value);
}

test("every kernel case agrees with the oracle", () => {
  const file = JSON.parse(readFileSync(here("../../fixtures/kernel/cases.json"), "utf8")) as {
    cases: Case[];
  };
  assert.ok(file.cases.length > 0, "the test is not looking where it should");

  const failures: string[] = [];
  const seen: Record<string, number> = {};
  for (const testCase of file.cases) {
    seen[testCase.query] = (seen[testCase.query] ?? 0) + 1;
    let got: unknown;
    try {
      got = answerFor(testCase);
    } catch (error) {
      failures.push(`${testCase.name} (${testCase.query}): threw ${String(error)}`);
      continue;
    }
    const want = canonicalText(testCase.answer);
    const mine = canonicalText(got);
    if (mine !== want) {
      failures.push(`${testCase.name} (${testCase.query})\n  want ${want}\n  got  ${mine}`);
    }
  }
  assert.deepEqual(
    failures.slice(0, 3),
    [],
    `${failures.length} of ${file.cases.length} kernel cases disagree with the oracle`,
  );
  assert.ok(Object.keys(seen).length >= 7, `only ${Object.keys(seen).length} query kinds exercised`);
});
