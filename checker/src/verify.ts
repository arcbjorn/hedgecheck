// The checker: accept a certificate bundle, or refuse it with a class from the closed
// list in schema/refusal.schema.json.

import { canonical, digest, parse, type Value } from "./canon.ts";
import { problems, type Schemas } from "./doc.ts";
import {
  add,
  cmp,
  equals,
  format,
  lt,
  lte,
  mul,
  neg,
  parse as parseNumber,
  type Rational,
  sign,
  sub,
  ZERO,
} from "./exact.ts";
import {
  askCost,
  below,
  cash,
  finite,
  type Fn,
  indicator,
  infimum,
  type Interval,
  type Level,
  linear,
  NEG_INF,
  POS_INF,
  profile,
  type ProfilePiece,
  sizeWindow,
  sum,
  walkLimit,
  witness,
} from "./pwa.ts";
import { parseVenue, quantityText, type VenueValue, at as venueAt } from "./venue.ts";

/** The closed list. A fault that fits none of these is ENGINE_DISAGREES. */
export type RefusalClass =
  | "SNAPSHOT_BYTES"
  | "SNAPSHOT_NOT_CITED"
  | "SEMANTICS_PIN"
  | "TERMS_MISMATCH"
  | "COST_MISMATCH"
  | "PROFILE_COVERAGE"
  | "PROFILE_VALUE"
  | "ENDPOINT_OWNERSHIP"
  | "OBJECTIVE_MISMATCH"
  | "VERDICT_MISMATCH"
  | "INTERVAL_MISMATCH"
  | "WITNESS_INADMISSIBLE"
  | "REDUCTION_UNDECLARED"
  | "REDUCTION_UNSOUND"
  | "SIZE_WINDOW"
  | "CERTIFICATE_WEIGHTS"
  | "ENVELOPE_MISMATCH"
  | "ENGINE_DISAGREES";

export interface Refusal {
  readonly class: RefusalClass;
  readonly at: string;
  readonly detail: string;
}

export type Outcome = { readonly accepted: true } | { readonly accepted: false; readonly refusal: Refusal };

/** Everything a bundle holds, already read as bytes. */
export interface Bundle {
  readonly proposal: Uint8Array;
  readonly lowered: Uint8Array;
  readonly result: Uint8Array;
  readonly manifest: Uint8Array;
  /** By SHA-256, as the proposal cites them. */
  readonly snapshots: ReadonlyMap<string, Uint8Array>;
  /** By family. */
  readonly registry: ReadonlyMap<string, Uint8Array>;
}

export interface Options {
  /** The registry digests this checker accepts as reviewed. Empty is correct today. */
  readonly allowlist?: ReadonlySet<string>;
  /** The schemas, for the document checks. */
  readonly schemas?: Schemas;
}

class Refused extends Error {
  readonly refusal: Refusal;
  constructor(refusal: Refusal) {
    super(`${refusal.class} at ${refusal.at}: ${refusal.detail}`);
    this.refusal = refusal;
  }
}

function refuse(className: RefusalClass, at: string, detail: string): never {
  throw new Refused({ class: className, at, detail });
}

export async function verify(bundle: Bundle, options: Options = {}): Promise<Outcome> {
  try {
    await establish(bundle, options);
    return { accepted: true };
  } catch (error) {
    if (error instanceof Refused) return { accepted: false, refusal: error.refusal };
    // An unexpected fault is still a refusal: a bundle this checker cannot finish
    // reading has not been established, and returning "accept" for it would be the
    // one answer that is never safe.
    return {
      accepted: false,
      refusal: {
        class: "ENGINE_DISAGREES",
        at: "$",
        detail: error instanceof Error ? error.message : String(error),
      },
    };
  }
}

// ---------------------------------------------------------------- 1. evidence

interface Evidence {
  readonly proposal: Record<string, Value>;
  readonly lowered: Record<string, Value>;
  readonly result: Record<string, Value>;
  readonly entries: Map<string, { value: Record<string, Value>; version: string; reviewed: boolean }>;
  readonly snapshots: ReadonlyMap<string, Uint8Array>;
}

async function establish(bundle: Bundle, options: Options): Promise<void> {
  const evidence = await readEvidence(bundle, options);
  const rebuilt = relower(evidence);
  await compareLowering(evidence, rebuilt);
  evaluateAndCompare(evidence, rebuilt);
}

async function readEvidence(bundle: Bundle, options: Options): Promise<Evidence> {
  const proposal = object(readDocument(bundle.proposal, "proposal"), "$proposal");
  const lowered = object(readDocument(bundle.lowered, "lowered"), "$lowered");
  const result = object(readDocument(bundle.result, "result"), "$result");

  // A document that does not satisfy its schema is refused -- but with the class the
  // FAULT belongs to, not a generic one. "A reduction lost its reason code" is
  // REDUCTION_UNDECLARED wherever it is noticed; saying ENGINE_DISAGREES because the
  // schema happened to catch it first would name the messenger.
  if (options.schemas !== undefined) {
    for (const [name, value, schema] of [
      ["proposal", proposal, "proposal.schema.json"],
      ["lowered", lowered, "ir.schema.json"],
      ["result", result, "result.schema.json"],
    ] as const) {
      const found = problems(value as Value, schema, options.schemas);
      if (found.length > 0) {
        refuse(classForSchemaProblem(found[0] as string), `$${name}`, found[0] as string);
      }
    }
  }

  // Every cited snapshot hashes to its citation. A snapshot supplied under a name it
  // does not hash to is not the evidence the proposal cites, whatever it contains.
  const snapshots = new Map<string, Uint8Array>();
  for (const [claimed, raw] of bundle.snapshots) {
    const actual = await sha256(raw);
    if (actual !== claimed) {
      refuse("SNAPSHOT_BYTES", `$snapshots.${short(claimed)}`, `the bytes hash to ${short(actual)}`);
    }
    snapshots.set(actual, raw);
  }
  for (const cited of citedSnapshots(proposal)) {
    if (!snapshots.has(cited)) {
      refuse("SNAPSHOT_NOT_CITED", `$proposal`, `${short(cited)} is cited but not supplied`);
    }
  }

  // Each pinned entry's semantics_version is RECOMPUTED, without its review key, so
  // a pin cannot be satisfied by an entry that has since been edited.
  const entries = new Map<string, { value: Record<string, Value>; version: string; reviewed: boolean }>();
  for (const [family, raw] of bundle.registry) {
    const entry = object(readDocument(raw, `registry ${family}`), `$registry.${family}`);
    if (options.schemas !== undefined) {
      const found = problems(entry as Value, "registry-entry.schema.json", options.schemas);
      if (found.length > 0) {
        refuse("ENGINE_DISAGREES", `$registry.${family}`, `not a valid entry: ${found[0]}`);
      }
    }
    const withoutReview: Record<string, Value> = {};
    for (const [key, value] of Object.entries(entry)) {
      if (key !== "review") withoutReview[key] = value;
    }
    const version = await digest(withoutReview as Value);
    entries.set(family, {
      value: entry,
      version,
      reviewed: isReviewed(entry, version, options.allowlist ?? new Set()),
    });
  }

  for (const leg of list(proposal["legs"], "$proposal.legs")) {
    const item = object(leg, "$proposal.legs[]");
    const family = text(item["family"], "$proposal.legs[].family");
    const pin = text(item["semantics_version"], "$proposal.legs[].semantics_version");
    const entry = entries.get(family);
    if (entry === undefined) {
      refuse("SEMANTICS_PIN", `$proposal.legs.${family}`, "no registry entry was supplied");
    }
    if (entry.version !== pin) {
      refuse(
        "SEMANTICS_PIN",
        `$proposal.legs.${family}`,
        `the pin is ${short(pin)}, the entry's semantics_version is ${short(entry.version)}`,
      );
    }
  }

  return { proposal, lowered, result, entries, snapshots };
}

/**
 * The refusal class a schema violation belongs to.
 */
function classForSchemaProblem(problem: string): RefusalClass {
  if (problem.includes(".reductions")) return "REDUCTION_UNDECLARED";
  if (problem.includes(".objective")) return "OBJECTIVE_MISMATCH";
  if (problem.includes(".profile") || problem.includes(".upper_profile")) return "PROFILE_COVERAGE";
  if (problem.includes("_intervals")) return "INTERVAL_MISMATCH";
  if (problem.includes(".size_windows")) return "SIZE_WINDOW";
  if (problem.includes(".witness")) return "WITNESS_INADMISSIBLE";
  if (problem.includes(".cost")) return "COST_MISMATCH";
  return "ENGINE_DISAGREES";
}

/**
 * An entry counts as reviewed only when ALL THREE hold: its state is `reviewed`, its
 * review digest still matches its semantics_version, and that version is in this
 * checker's allowlist.
 */
function isReviewed(
  entry: Record<string, Value>,
  version: string,
  allowlist: ReadonlySet<string>,
): boolean {
  const review = entry["review"];
  if (typeof review !== "object" || review === null || Array.isArray(review)) return false;
  const state = (review as Record<string, Value>)["state"];
  const claimed = (review as Record<string, Value>)["digest"];
  if (state !== "reviewed") return false;
  if (claimed !== version) return false;
  return allowlist.has(version);
}

// ---------------------------------------------------------------- 2. lowering

interface RebuiltLeg {
  readonly id: string;
  readonly parts: Fn[];
  readonly size: Rational;
  readonly premium: Rational;
  readonly observationTime: string;
  readonly reduced: boolean;
  readonly reductionRule: string | null;
  readonly tight: boolean;
  readonly levels: Level[];
  /** The venue's own id, from the proposal. The IR does not carry it, by design. */
  readonly coin: string;
}

interface Rebuilt {
  readonly legs: RebuiltLeg[];
  readonly baseline: Rational;
  readonly quantity: Rational;
  readonly domainLower: Rational;
  readonly domainUpper: Rational;
  readonly otherCosts: Rational;
  readonly premium: Rational;
  readonly valuationTime: string;
}

function relower(evidence: Evidence): Rebuilt {
  const proposal = evidence.proposal;
  const domain = object(proposal["domain"], "$proposal.domain");
  const domainLower = number(domain["lower"], "$proposal.domain.lower");
  const domainUpper = number(domain["upper"], "$proposal.domain.upper");
  const exposure = object(proposal["exposure"], "$proposal.exposure");
  const quantity = number(exposure["quantity"], "$proposal.exposure.quantity");
  const valuationTime = text(
    proposal["objective_valuation_time"],
    "$proposal.objective_valuation_time",
  );

  // The baseline is RE-READ from the cited snapshot, so a hand-edited price cannot
  // reach the kernel.
  const baselineBlock = object(proposal["baseline"], "$proposal.baseline");
  const claimedBaseline = number(baselineBlock["price"], "$proposal.baseline.price");
  if (baselineBlock["kind"] === "analysis_time") {
    const source = object(baselineBlock["source"], "$proposal.baseline.source");
    const snapshot = text(source["snapshot"], "$proposal.baseline.source.snapshot");
    const coin = text(source["coin"], "$proposal.baseline.source.coin");
    const raw = evidence.snapshots.get(snapshot);
    if (raw === undefined) {
      refuse("SNAPSHOT_NOT_CITED", "$proposal.baseline.source", `${short(snapshot)} was not supplied`);
    }
    const found = markPrice(parseVenue(raw), coin);
    if (!equals(found, claimedBaseline)) {
      refuse(
        "TERMS_MISMATCH",
        "$proposal.baseline.price",
        `the proposal says ${format(claimedBaseline)}, the snapshot says ${format(found)}`,
      );
    }
  }

  const legs: RebuiltLeg[] = [];
  let premium = ZERO;
  for (const rawLeg of list(proposal["legs"], "$proposal.legs")) {
    const leg = object(rawLeg, "$proposal.legs[]");
    const id = text(leg["id"], "$proposal.legs[].id");
    const family = text(leg["family"], "$proposal.legs[].family");
    const side = text(leg["side"], "$proposal.legs[].side");
    const size = number(leg["size"], `$proposal.legs.${id}.size`);
    const terms = object(leg["terms"], `$proposal.legs.${id}.terms`);
    const entry = evidence.entries.get(family);
    if (entry === undefined) refuse("SEMANTICS_PIN", `$proposal.legs.${id}`, "no entry");

    checkInstance(evidence, leg, terms, id, family);
    const parts = resolvePayoff(entry.value, side, terms, size, id);

    const acquisition = object(leg["acquisition"], `$proposal.legs.${id}.acquisition`);
    const { total, levels } = priceLeg(evidence, acquisition, size, id);
    premium = add(premium, total);

    // The reductions this checker DERIVES, not the ones the result declares.
    const observationTime = text(terms["expiry"], `$proposal.legs.${id}.terms.expiry`);
    let reduced = false;
    let rule: string | null = null;
    let tight = false;
    if (observationTime !== valuationTime) {
      reduced = true;
      rule = "horizon_mismatch";
      tight = true;
    } else if (!entry.reviewed) {
      reduced = true;
      rule = "unreviewed_family";
      tight = false;
    }
    const instance = object(leg["instance"], `$proposal.legs.${id}.instance`);
    const coin = text(instance["coin"], `$proposal.legs.${id}.instance.coin`);
    legs.push({ id, parts, size, premium: total, observationTime, reduced, reductionRule: rule, tight, levels, coin });
  }

  return {
    legs,
    baseline: claimedBaseline,
    quantity,
    domainLower,
    domainUpper,
    otherCosts: number(proposal["other_costs"], "$proposal.other_costs"),
    premium,
    valuationTime,
  };
}

/** The instance the leg names really is the one the catalogue describes. */
function checkInstance(
  evidence: Evidence,
  leg: Record<string, Value>,
  terms: Record<string, Value>,
  id: string,
  family: string,
): void {
  const instance = leg["instance"];
  if (typeof instance !== "object" || instance === null || Array.isArray(instance)) return;
  const fields = instance as Record<string, Value>;
  const catalogueDigest = text(fields["catalogue"], `$proposal.legs.${id}.instance.catalogue`);
  const outcome = text(fields["outcome"], `$proposal.legs.${id}.instance.outcome`);
  const coin = text(fields["coin"], `$proposal.legs.${id}.instance.coin`);
  const side = text(leg["side"], `$proposal.legs.${id}.side`);

  const raw = evidence.snapshots.get(catalogueDigest);
  if (raw === undefined) {
    refuse("SNAPSHOT_NOT_CITED", `$proposal.legs.${id}.instance`, `${short(catalogueDigest)} was not supplied`);
  }
  const catalogue = parseVenue(raw);

  // The coin encodes the outcome and the side: '#' + (10*outcome + side), yes = 0.
  const offset = side === "yes" || side === "long" ? 0 : 1;
  const expectedCoin = `#${BigInt(outcome) * 10n + BigInt(offset)}`;
  if (coin !== expectedCoin) {
    refuse(
      "TERMS_MISMATCH",
      `$proposal.legs.${id}.instance.coin`,
      `outcome ${outcome} side ${side} encodes ${expectedCoin}, the leg says ${coin}`,
    );
  }

  const described = describedTerms(catalogue, outcome, family);
  if (described === null) {
    refuse("TERMS_MISMATCH", `$proposal.legs.${id}.instance.outcome`, `${outcome} is not in the catalogue`);
  }
  // The numbers come from the CATALOGUE, not from the leg. A leg whose terms say
  // something the venue does not is refused rather than quietly evaluated.
  for (const [name, wanted] of Object.entries(described)) {
    const claimed = terms[name];
    if (claimed === undefined) continue;
    const claimedText = Array.isArray(claimed) ? claimed.map((item) => String(item)).join(",") : String(claimed);
    if (claimedText !== wanted) {
      refuse(
        "TERMS_MISMATCH",
        `$proposal.legs.${id}.terms.${name}`,
        `the catalogue says ${wanted}, the leg says ${claimedText}`,
      );
    }
  }
}

/** The terms the catalogue states for an outcome, as text, or null when absent. */
function describedTerms(
  catalogue: VenueValue,
  outcome: string,
  family: string,
): Record<string, string> | null {
  const collection = family.endsWith("priceBucket") ? "questions" : "outcomes";
  const items = venueAt(catalogue, [collection]);
  if (!Array.isArray(items)) return null;
  for (const item of items) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) continue;
    const fields = item as Record<string, VenueValue>;
    const id = fields["outcome"] ?? fields["question"];
    const idText = typeof id === "string" ? id : numberText(id);
    const named = fields["namedOutcomes"];
    const matchesNamed = Array.isArray(named) &&
      named.some((entry) => (typeof entry === "string" ? entry : numberText(entry)) === outcome);
    if (idText !== outcome && !matchesNamed) continue;
    const description = fields["description"];
    if (typeof description !== "string") return {};
    return parseDescription(description);
  }
  return null;
}

function numberText(value: VenueValue | undefined): string | null {
  if (value === undefined) return null;
  if (typeof value === "object" && value !== null && "lexeme" in value) {
    return (value as { lexeme: string }).lexeme;
  }
  return null;
}

/** "key:value|key:value" as the catalogue writes it. */
function parseDescription(description: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of description.split("|")) {
    const colon = part.indexOf(":");
    if (colon < 0) continue;
    const key = part.slice(0, colon);
    const value = part.slice(colon + 1);
    // The catalogue's own names, mapped to the terms a leg states.
    if (key === "targetPrice") out["target_price"] = value;
    else if (key === "priceThresholds") out["thresholds"] = value;
    else if (key === "underlying") out["underlying"] = value;
    else if (key === "period") out["period"] = value;
  }
  return out;
}

/** The registry entry's payoff for this side and index, as indicators. */
function resolvePayoff(
  entry: Record<string, Value>,
  side: string,
  terms: Record<string, Value>,
  size: Rational,
  id: string,
): Fn[] {
  const payoffs = list(entry["payoffs"], "$registry.payoffs");
  const index = typeof terms["index"] === "string" ? terms["index"] : null;
  for (const rawPayoff of payoffs) {
    const payoff = object(rawPayoff, "$registry.payoffs[]");
    const select = object(payoff["select"], "$registry.payoffs[].select");
    if (select["side"] !== side) continue;
    const wantedIndex = select["index"];
    if (wantedIndex !== undefined && wantedIndex !== index) continue;
    const parts: Fn[] = [];
    for (const rawPays of list(payoff["pays"], "$registry.payoffs[].pays")) {
      const pays = object(rawPays, "$registry.payoffs[].pays[]");
      if (pays["primitive"] !== "indicator") {
        refuse("ENGINE_DISAGREES", `$registry.payoffs`, `unsupported primitive ${String(pays["primitive"])}`);
      }
      const paysOn = object(pays["pays_on"], "$registry.payoffs[].pays[].pays_on");
      parts.push(indicator(size, boundFrom(paysOn, "lower", terms, id), boundFrom(paysOn, "upper", terms, id)));
    }
    if (parts.length === 0) {
      refuse("ENGINE_DISAGREES", `$registry.payoffs`, `${id} resolves to no payoff`);
    }
    return parts;
  }
  refuse("TERMS_MISMATCH", `$proposal.legs.${id}`, `the entry has no payoff for side ${side}`);
}

function boundFrom(
  paysOn: Record<string, Value>,
  which: "lower" | "upper",
  terms: Record<string, Value>,
  id: string,
) {
  const reference = paysOn[which];
  if (reference === undefined) return which === "lower" ? NEG_INF : POS_INF;
  const closed = paysOn[`${which}_inclusive`];
  if (typeof closed !== "boolean") {
    // A bound with no owner is exactly the thing the kernel refuses to guess about.
    refuse("ENDPOINT_OWNERSHIP", `$registry.payoffs.${which}`, "a bound with no owner");
  }
  const spec = object(reference, `$registry.payoffs.${which}`);
  const termName = text(spec["term"], `$registry.payoffs.${which}.term`);
  const raw = terms[termName];
  const positionText = spec["at"];
  if (typeof positionText === "string") {
    if (!Array.isArray(raw)) {
      refuse("TERMS_MISMATCH", `$proposal.legs.${id}.terms.${termName}`, "expected a list");
    }
    // Digit by digit, not parseInt: no `number` holds a value read from a document.
    const item = raw[digitsOf(positionText)];
    if (typeof item !== "string") {
      refuse("TERMS_MISMATCH", `$proposal.legs.${id}.terms.${termName}`, `no item at ${positionText}`);
    }
    return finite(parseNumber(item), closed);
  }
  if (typeof raw !== "string") {
    refuse("TERMS_MISMATCH", `$proposal.legs.${id}.terms.${termName}`, "expected a number as text");
  }
  return finite(parseNumber(raw), closed);
}

/** The premium, re-walked from the cited book at the requested size. */
function priceLeg(
  evidence: Evidence,
  acquisition: Record<string, Value>,
  size: Rational,
  id: string,
): { total: Rational; levels: Level[] } {
  const kind = acquisition["kind"];
  if (kind === "fixed") {
    const price = number(acquisition["price"], `$proposal.legs.${id}.acquisition.price`);
    return { total: mul(price, size), levels: [] };
  }
  const snapshot = text(acquisition["snapshot"], `$proposal.legs.${id}.acquisition.snapshot`);
  const raw = evidence.snapshots.get(snapshot);
  if (raw === undefined) {
    refuse("SNAPSHOT_NOT_CITED", `$proposal.legs.${id}.acquisition`, `${short(snapshot)} was not supplied`);
  }
  const levels = asksOf(parseVenue(raw), id);
  const walked = askCost(levels, size);
  if (!walked.covered || walked.total === null) {
    refuse("COST_MISMATCH", `$proposal.legs.${id}.acquisition`, "the displayed depth cannot fill the size");
  }
  return { total: walked.total, levels };
}

function asksOf(book: VenueValue, id: string): Level[] {
  // A HASH IDENTIFIES BYTES, NOT A SHAPE. A leg citing the catalogue where a book
  // belongs is refused, never a crash -- T1 found this by crashing.
  const sides = venueAt(book, ["levels"]);
  if (!Array.isArray(sides) || sides.length !== 2 || !Array.isArray(sides[1])) {
    refuse(
      "SNAPSHOT_NOT_CITED",
      `$proposal.legs.${id}.acquisition.snapshot`,
      "the cited snapshot is not an l2Book response, so this leg cites no book",
    );
  }
  const rows = sides[1];
  return rows.map((row, position) => ({
    price: parseNumber(quantityText(row as VenueValue, ["px"])),
    size: parseNumber(quantityText(row as VenueValue, ["sz"])),
  }));
}

function markPrice(contexts: VenueValue, coin: string): Rational {
  if (!Array.isArray(contexts) || contexts.length !== 2) {
    refuse("TERMS_MISMATCH", "$proposal.baseline.source", "not a contexts response");
  }
  const universe = venueAt(contexts[0] as VenueValue, ["universe"]);
  const states = contexts[1];
  if (!Array.isArray(universe) || !Array.isArray(states)) {
    refuse("TERMS_MISMATCH", "$proposal.baseline.source", "not a contexts response");
  }
  for (let index = 0; index < universe.length; index += 1) {
    const asset = universe[index] as VenueValue;
    if (venueAt(asset, ["name"]) !== coin) continue;
    const state = states[index];
    if (state === undefined) break;
    return parseNumber(quantityText(state as VenueValue, ["markPx"]));
  }
  refuse("TERMS_MISMATCH", "$proposal.baseline.source", `${coin} is not in the snapshot`);
}

/** The recomputed ir_digest must equal the bundle's. */
async function compareLowering(evidence: Evidence, rebuilt: Rebuilt): Promise<void> {
  const lowered = evidence.lowered;

  // Every snapshot the LOWERED proposal rests on is one the PROPOSAL cites. A
  // lowered proposal priced from a book the proposal never named is resting on
  // evidence outside the bundle's own chain, whatever that book contains.
  const cited = new Set(citedSnapshots(evidence.proposal));
  for (const rawLeg of list(lowered["legs"], "$lowered.legs")) {
    const leg = object(rawLeg, "$lowered.legs[]");
    const premium = leg["premium"];
    if (typeof premium !== "object" || premium === null || Array.isArray(premium)) continue;
    const snapshot = (premium as Record<string, Value>)["snapshot"];
    if (typeof snapshot !== "string") continue;
    if (!cited.has(snapshot)) {
      refuse(
        "SNAPSHOT_NOT_CITED",
        `$lowered.legs.${String(leg["id"])}.premium.snapshot`,
        `${short(snapshot)} priced this leg, but the proposal cites no such snapshot`,
      );
    }
  }

  // The objective FIRST. A lowered proposal that answers a different question from
  // the proposal is an objective mismatch, and saying only "the digests differ"
  // would name the symptom while the cause is right here.
  compareObjective(evidence, rebuilt);

  // Every leg the lowered proposal states matches the one this checker rebuilt.
  const claimedLegs = list(lowered["legs"], "$lowered.legs");
  if (claimedLegs.length !== rebuilt.legs.length) {
    refuse(
      "ENGINE_DISAGREES",
      "$lowered.legs",
      `the lowered proposal has ${claimedLegs.length} legs, the proposal has ${rebuilt.legs.length}`,
    );
  }
  for (let index = 0; index < claimedLegs.length; index += 1) {
    const claimed = object(claimedLegs[index], "$lowered.legs[]");
    const mine = rebuilt.legs[index] as RebuiltLeg;
    if (claimed["id"] !== mine.id) {
      refuse("ENGINE_DISAGREES", `$lowered.legs[${index}].id`, `expected ${mine.id}`);
    }
    const premium = object(claimed["premium"], `$lowered.legs.${mine.id}.premium`);
    const claimedTotal = number(premium["total"], `$lowered.legs.${mine.id}.premium.total`);
    if (!equals(claimedTotal, mine.premium)) {
      refuse(
        "COST_MISMATCH",
        `$lowered.legs.${mine.id}.premium.total`,
        `the walk gives ${format(mine.premium)}, the lowered proposal says ${format(claimedTotal)}`,
      );
    }
  }

  // The digest over the lowered proposal is what the result cites.
  const irDigest = await digest(lowered as Value);
  const claimed = evidence.result["ir_digest"];
  if (claimed !== irDigest) {
    refuse(
      "ENGINE_DISAGREES",
      "$result.ir_digest",
      `the result cites ${short(String(claimed))}, the lowered proposal digests to ${short(irDigest)}`,
    );
  }
}

// ---------------------------------------------------------------- 3. evaluation

function evaluateAndCompare(evidence: Evidence, rebuilt: Rebuilt): void {
  const result = evidence.result;

  // THE LOWER PROFILE, rebuilt: a reduced leg is worth nothing, and its premium
  // still counts. This is what the verdict rests on.
  const lowerParts: Fn[] = [linear(rebuilt.quantity, rebuilt.baseline), cash(neg(add(rebuilt.premium, rebuilt.otherCosts)))];
  const upperParts: Fn[] = [...lowerParts];
  let upperCeiling = ZERO;
  for (const leg of rebuilt.legs) {
    if (leg.reduced) {
      // The upper profile credits a reduced leg with its full size: a long, fully
      // collateralized token pays at most that.
      upperCeiling = add(upperCeiling, leg.size);
      continue;
    }
    for (const part of leg.parts) lowerParts.push(part);
    for (const part of leg.parts) upperParts.push(part);
  }
  const lowerFn = sum(lowerParts);
  const upperFn = sum([...upperParts, cash(upperCeiling)]);

  const mine = profile(lowerFn, rebuilt.domainLower, rebuilt.domainUpper);
  compareProfile(mine, list(result["profile"], "$result.profile"), "$result.profile");

  // The verdict, re-derived under the tight and loose rules.
  compareVerdict(evidence, rebuilt, lowerFn, upperFn);

  // Reductions: every one this checker derived is declared, with its reason code.
  compareReductions(evidence, rebuilt);

  // Cost and break-evens.
  compareCost(evidence, rebuilt, lowerFn);

  // Size windows, where the result states them.
  compareSizeWindows(evidence, rebuilt);

  // Witnesses, on the UPPER profile.
  compareWitnesses(evidence, rebuilt, upperFn);

  // Infeasibility certificates, where present.
  compareCertificates(evidence);

  // The order envelope, against this checker's OWN re-walk of the book.
  compareEnvelope(evidence, rebuilt);
}

/**
 * An order envelope is the statement of which order the cost bound is about, so it is
 * checked against the walk this checker did, never against the levels the result
 * carries. `rebuilt.legs[].levels` came out of the snapshot bytes in `priceLeg`.
 */
function compareEnvelope(evidence: Evidence, rebuilt: Rebuilt): void {
  const result = evidence.result;
  const readiness = result["execution_readiness"];
  const raw = result["order_envelope"];
  const present = raw !== undefined;

  if (present !== (readiness === "envelope_issued")) {
    refuse(
      "ENVELOPE_MISMATCH",
      "$result.execution_readiness",
      `readiness is ${String(readiness)} and an envelope is ${present ? "present" : "absent"}`,
    );
  }
  if (!present) return;

  const envelope = object(raw, "$result.order_envelope");
  const verdict = result["model_result"];
  if (verdict !== "passes") {
    refuse("ENVELOPE_MISMATCH", "$result.order_envelope", `an envelope on a ${String(verdict)}`);
  }
  if (rebuilt.legs.length !== 1) {
    refuse(
      "ENVELOPE_MISMATCH",
      "$result.order_envelope",
      `the proposal has ${rebuilt.legs.length} legs; an envelope describes one order`,
    );
  }
  const leg = rebuilt.legs[0] as RebuiltLeg;
  if (leg.levels.length === 0) {
    refuse("ENVELOPE_MISMATCH", "$result.order_envelope", "the leg is not priced on a book");
  }

  if (envelope["coin"] !== leg.coin) {
    refuse(
      "ENVELOPE_MISMATCH",
      "$result.order_envelope.coin",
      `the envelope names ${String(envelope["coin"])}, the proposal names ${leg.coin}`,
    );
  }
  if (envelope["side"] !== "buy") {
    refuse("ENVELOPE_MISMATCH", "$result.order_envelope.side", `side is ${String(envelope["side"])}`);
  }
  if (envelope["time_in_force"] !== "Ioc") {
    refuse(
      "ENVELOPE_MISMATCH",
      "$result.order_envelope.time_in_force",
      `time in force is ${String(envelope["time_in_force"])}`,
    );
  }

  const size = number(envelope["size"], "$result.order_envelope.size");
  if (!equals(size, leg.size)) {
    refuse(
      "ENVELOPE_MISMATCH",
      "$result.order_envelope.size",
      `the envelope buys ${format(size)}, the proposal asks for ${format(leg.size)}`,
    );
  }

  const limit = walkLimit(leg.levels, leg.size);
  if (limit === null) {
    refuse("ENVELOPE_MISMATCH", "$result.order_envelope.limit_price", "the depth does not fill the size");
  }
  const claimedLimit = number(envelope["limit_price"], "$result.order_envelope.limit_price");
  if (!equals(claimedLimit, limit)) {
    refuse(
      "ENVELOPE_MISMATCH",
      "$result.order_envelope.limit_price",
      `the envelope says ${format(claimedLimit)}, the walk ends in ${format(limit)}`,
    );
  }

  // The cost this checker walked, not the one the result states -- though the two
  // were already required to agree by compareCost.
  const walked = askCost(leg.levels, leg.size);
  if (!walked.covered || walked.total === null) {
    refuse("ENVELOPE_MISMATCH", "$result.order_envelope.max_cost", "the depth does not fill the size");
  }
  const claimedCost = number(envelope["max_cost"], "$result.order_envelope.max_cost");
  if (!equals(claimedCost, walked.total)) {
    refuse(
      "ENVELOPE_MISMATCH",
      "$result.order_envelope.max_cost",
      `the envelope says ${format(claimedCost)}, the walk costs ${format(walked.total)}`,
    );
  }

  // The envelope belongs to THIS result. A digest that does not match the result's is
  // an envelope carried over from another answer, which is the one way a stale bound
  // reaches a live order.
  const stated = result["input_digest"];
  if (stated === undefined) {
    refuse(
      "ENVELOPE_MISMATCH",
      "$result.input_digest",
      "an envelope was issued for a result that does not name its input digest",
    );
  }
  if (envelope["input_digest"] !== stated) {
    refuse(
      "ENVELOPE_MISMATCH",
      "$result.order_envelope.input_digest",
      `the envelope belongs to ${short(String(envelope["input_digest"]))}, the result is ${short(String(stated))}`,
    );
  }
}

function compareProfile(mine: ProfilePiece[], claimed: Value[], at: string): void {
  if (claimed.length !== mine.length) {
    refuse(
      "PROFILE_COVERAGE",
      at,
      `the result states ${claimed.length} pieces, the proposal gives ${mine.length}`,
    );
  }
  for (let index = 0; index < mine.length; index += 1) {
    const piece = object(claimed[index], `${at}[${index}]`);
    const want = mine[index] as ProfilePiece;
    const where = `${at}[${index}]`;
    if (!equals(number(piece["lower"], `${where}.lower`), want.lower)) {
      refuse("PROFILE_COVERAGE", where, `lower is ${String(piece["lower"])}, expected ${format(want.lower)}`);
    }
    if (!equals(number(piece["upper"], `${where}.upper`), want.upper)) {
      refuse("PROFILE_COVERAGE", where, `upper is ${String(piece["upper"])}, expected ${format(want.upper)}`);
    }
    if (piece["lower_inclusive"] !== want.lowerInclusive || piece["upper_inclusive"] !== want.upperInclusive) {
      refuse(
        "ENDPOINT_OWNERSHIP",
        where,
        `ownership is [${String(piece["lower_inclusive"])}, ${String(piece["upper_inclusive"])}], ` +
          `expected [${want.lowerInclusive}, ${want.upperInclusive}]`,
      );
    }
    if (!equals(number(piece["slope"], `${where}.slope`), want.slope)) {
      refuse("PROFILE_VALUE", where, `slope is ${String(piece["slope"])}, expected ${format(want.slope)}`);
    }
    if (!equals(number(piece["intercept"], `${where}.intercept`), want.intercept)) {
      refuse("PROFILE_VALUE", where, `intercept is ${String(piece["intercept"])}, expected ${format(want.intercept)}`);
    }
  }
}

function compareObjective(evidence: Evidence, rebuilt: Rebuilt): void {
  const proposalObjective = canonical(evidence.proposal["objective"] as Value);
  const loweredObjective = canonical(evidence.lowered["objective"] as Value);
  if (new TextDecoder().decode(proposalObjective) !== new TextDecoder().decode(loweredObjective)) {
    refuse(
      "OBJECTIVE_MISMATCH",
      "$lowered.objective",
      "the lowered proposal states a different objective from the proposal",
    );
  }
  const claimedTime = evidence.result["objective_valuation_time"];
  if (claimedTime !== rebuilt.valuationTime) {
    refuse(
      "OBJECTIVE_MISMATCH",
      "$result.objective_valuation_time",
      `the result says ${String(claimedTime)}, the proposal says ${rebuilt.valuationTime}`,
    );
  }
}

interface Clause {
  readonly id: string;
  readonly minPnl: Rational;
  readonly on: Interval | null;
}

function clausesOf(evidence: Evidence): Clause[] {
  return list(evidence.proposal["objective"], "$proposal.objective").map((raw) => {
    const clause = object(raw, "$proposal.objective[]");
    const on = clause["on"];
    return {
      id: text(clause["id"], "$proposal.objective[].id"),
      minPnl: number(clause["min_pnl"], "$proposal.objective[].min_pnl"),
      on: on === undefined ? null : intervalOf(object(on, "$proposal.objective[].on")),
    };
  });
}

function intervalOf(raw: Record<string, Value>): Interval {
  return {
    lower: number(raw["lower"], "$.lower"),
    lowerInclusive: raw["lower_inclusive"] === true,
    upper: number(raw["upper"], "$.upper"),
    upperInclusive: raw["upper_inclusive"] === true,
  };
}

function compareVerdict(evidence: Evidence, rebuilt: Rebuilt, lowerFn: Fn, upperFn: Fn): void {
  const clauses = clausesOf(evidence);
  const anyLoose = rebuilt.legs.some((leg) => leg.reduced && !leg.tight);

  let broken = false;
  for (const clause of clauses) {
    const lower = clause.on === null ? rebuilt.domainLower : clause.on.lower;
    const upper = clause.on === null ? rebuilt.domainUpper : clause.on.upper;
    if (below(lowerFn, clause.minPnl, lower, upper).length > 0) broken = true;
  }

  // ARCHITECTURE section 4, the two-profile table:
  let expected: string;
  if (!broken) expected = anyLoose ? "needs_review" : "passes";
  else expected = anyLoose ? "needs_review" : "fails";

  const claimed = evidence.result["model_result"];
  if (claimed !== expected) {
    refuse(
      "VERDICT_MISMATCH",
      "$result.model_result",
      `the result says ${String(claimed)}, the evidence gives ${expected}`,
    );
  }
  void upperFn;

  compareIntervals(evidence, rebuilt, lowerFn, clauses);
}

function compareIntervals(
  evidence: Evidence,
  rebuilt: Rebuilt,
  lowerFn: Fn,
  clauses: readonly Clause[],
): void {
  const stated = [
    ...list(evidence.result["failing_intervals"] ?? [], "$result.failing_intervals"),
    ...list(evidence.result["undecided_intervals"] ?? [], "$result.undecided_intervals"),
  ];
  const mine: Interval[] = [];
  for (const clause of clauses) {
    const lower = clause.on === null ? rebuilt.domainLower : clause.on.lower;
    const upper = clause.on === null ? rebuilt.domainUpper : clause.on.upper;
    for (const interval of below(lowerFn, clause.minPnl, lower, upper)) mine.push(interval);
  }
  if (stated.length !== mine.length) {
    refuse(
      "INTERVAL_MISMATCH",
      "$result.failing_intervals",
      `the result states ${stated.length} intervals, the evidence gives ${mine.length}`,
    );
  }
  for (let index = 0; index < mine.length; index += 1) {
    const claimed = object(stated[index], `$result.intervals[${index}]`);
    const want = mine[index] as Interval;
    const where = `$result.intervals[${index}]`;
    if (
      !equals(number(claimed["lower"], `${where}.lower`), want.lower) ||
      !equals(number(claimed["upper"], `${where}.upper`), want.upper)
    ) {
      refuse(
        "INTERVAL_MISMATCH",
        where,
        `the result says [${String(claimed["lower"])}, ${String(claimed["upper"])}], ` +
          `the evidence gives [${format(want.lower)}, ${format(want.upper)}]`,
      );
    }
    if (
      claimed["lower_inclusive"] !== want.lowerInclusive ||
      claimed["upper_inclusive"] !== want.upperInclusive
    ) {
      refuse("INTERVAL_MISMATCH", where, "the interval's endpoint ownership differs");
    }
  }
}

function compareReductions(evidence: Evidence, rebuilt: Rebuilt): void {
  const stated = list(evidence.result["reductions"] ?? [], "$result.reductions");
  const mine = rebuilt.legs.filter((leg) => leg.reduced);
  if (stated.length !== mine.length) {
    refuse(
      "REDUCTION_UNDECLARED",
      "$result.reductions",
      `the result declares ${stated.length} reductions, the evidence requires ${mine.length}`,
    );
  }
  for (let index = 0; index < mine.length; index += 1) {
    const claimed = object(stated[index], `$result.reductions[${index}]`);
    const want = mine[index] as RebuiltLeg;
    const where = `$result.reductions[${index}]`;
    if (claimed["leg"] !== want.id) {
      refuse("REDUCTION_UNDECLARED", where, `expected the reduction on ${want.id}`);
    }
    if (claimed["rule"] !== want.reductionRule) {
      refuse("REDUCTION_UNSOUND", where, `expected the rule ${String(want.reductionRule)}`);
    }
    if (claimed["tight"] !== want.tight) {
      refuse(
        "REDUCTION_UNSOUND",
        where,
        `the result calls ${want.reductionRule} ${claimed["tight"] === true ? "tight" : "loose"}; it is not`,
      );
    }
    // A declared reduction without its reason code cannot be read back by anyone.
    if (typeof claimed["reason_code"] !== "string" || claimed["reason_code"] === "") {
      refuse("REDUCTION_UNDECLARED", where, "the reduction states no reason code");
    }
  }
}

function compareCost(evidence: Evidence, rebuilt: Rebuilt, lowerFn: Fn): void {
  const cost = object(evidence.result["cost"], "$result.cost");
  const claimedPremium = number(cost["premium"], "$result.cost.premium");
  if (!equals(claimedPremium, rebuilt.premium)) {
    refuse(
      "COST_MISMATCH",
      "$result.cost.premium",
      `the result says ${format(claimedPremium)}, the walks give ${format(rebuilt.premium)}`,
    );
  }
  const claimedOther = number(cost["other_costs"], "$result.cost.other_costs");
  if (!equals(claimedOther, rebuilt.otherCosts)) {
    refuse("COST_MISMATCH", "$result.cost.other_costs", "the result states different other costs");
  }
  // Break-evens are where the payoff crosses zero.
  const mine = below(lowerFn, ZERO, rebuilt.domainLower, rebuilt.domainUpper);
  const claimedBreakevens = list(cost["breakevens"] ?? [], "$result.cost.breakevens");
  const crossings = new Set<string>();
  for (const interval of mine) {
    if (!equals(interval.upper, rebuilt.domainUpper)) crossings.add(format(interval.upper));
    if (!equals(interval.lower, rebuilt.domainLower)) crossings.add(format(interval.lower));
  }
  for (const claimed of claimedBreakevens) {
    if (typeof claimed !== "string" || !crossings.has(claimed)) {
      refuse(
        "COST_MISMATCH",
        "$result.cost.breakevens",
        `${String(claimed)} is not where the payoff crosses zero`,
      );
    }
  }
}

function compareSizeWindows(evidence: Evidence, rebuilt: Rebuilt): void {
  const stated = evidence.result["size_windows"];
  if (stated === undefined) return;
  const windows = list(stated, "$result.size_windows");
  const clauses = clausesOf(evidence);
  if (clauses.length === 0) return;
  const floorPnl = (clauses[0] as Clause).minPnl;

  for (let index = 0; index < windows.length; index += 1) {
    const claimed = object(windows[index], `$result.size_windows[${index}]`);
    const legId = text(claimed["leg"], `$result.size_windows[${index}].leg`);
    const leg = rebuilt.legs.find((candidate) => candidate.id === legId);
    if (leg === undefined) {
      refuse("SIZE_WINDOW", `$result.size_windows[${index}]`, `no leg named ${legId}`);
    }
    // The base is the holding and the OTHER legs; the unit is one contract of this.
    const baseParts: Fn[] = [linear(rebuilt.quantity, rebuilt.baseline)];
    for (const other of rebuilt.legs) {
      if (other.id === legId || other.reduced) continue;
      for (const part of other.parts) baseParts.push(part);
    }
    const unitParts = leg.parts.map((_, position) =>
      unitOf(evidence, leg, position)
    );
    const window = sizeWindow(
      sum(baseParts),
      sum(unitParts),
      leg.levels,
      floorPnl,
      rebuilt.domainLower,
      rebuilt.domainUpper,
      parseNumber("1"),
    );
    const claimedSmallest = claimed["smallest"];
    if (typeof claimedSmallest === "string" && window.smallest !== null) {
      if (!equals(parseNumber(claimedSmallest), window.smallest)) {
        refuse(
          "SIZE_WINDOW",
          `$result.size_windows[${index}].smallest`,
          `the result says ${claimedSmallest}, the evidence gives ${format(window.smallest)}`,
        );
      }
    }
  }
}

/** One contract of a leg's payoff, for the size window. */
function unitOf(evidence: Evidence, leg: RebuiltLeg, position: number): Fn {
  // The leg's own indicator, at size one. Rebuilding it from the registry keeps this
  // independent of the size the proposal happened to request.
  const scaled = leg.parts[position] as Fn;
  const unitSize = parseNumber("1");
  const pieces = scaled.pieces.map((piece) => ({
    lo: piece.lo,
    hi: piece.hi,
    slope: piece.slope,
    intercept: sign(piece.intercept) === 0
      ? piece.intercept
      : (equals(piece.intercept, leg.size) ? unitSize : piece.intercept),
  }));
  return { pieces };
}

function compareWitnesses(evidence: Evidence, rebuilt: Rebuilt, upperFn: Fn): void {
  const clauses = clausesOf(evidence);
  const byId = new Map(clauses.map((clause) => [clause.id, clause]));
  const looseLegs = new Set(rebuilt.legs.filter((leg) => leg.reduced && !leg.tight).map((leg) => leg.id));
  const reducedLegs = new Map(rebuilt.legs.filter((leg) => leg.reduced).map((leg) => [leg.id, leg]));

  for (const [field, className] of [
    ["failing_intervals", "WITNESS_INADMISSIBLE"],
    ["undecided_intervals", "WITNESS_INADMISSIBLE"],
  ] as const) {
    for (const raw of list(evidence.result[field] ?? [], `$result.${field}`)) {
      const interval = object(raw, `$result.${field}[]`);
      const claimed = interval["witness"];
      if (claimed === undefined) continue;
      const found = object(claimed, `$result.${field}[].witness`);
      const price = number(found["price"], `$result.${field}[].witness.price`);
      const clauseId = interval["clause"];
      const clause = typeof clauseId === "string" ? byId.get(clauseId) : undefined;
      if (clause === undefined) {
        refuse(className, `$result.${field}[]`, `the witness names no clause this proposal has`);
      }

      // EVALUATED ON THE UPPER PROFILE, but only where a LOOSE rule is responsible.
      if (field === "failing_intervals" && looseLegs.size > 0) {
        const best = evaluateOn(upperFn, price);
        if (!lt(best, clause.minPnl)) {
          refuse(
            className,
            `$result.${field}[].witness`,
            `at ${format(price)} the upper profile gives ${format(best)}, which meets ${format(clause.minPnl)}`,
          );
        }
      }

      // An adverse state must name a leg a rule really reduced, and the rule that
      // reduced it. A state for a leg that was not reduced is a claim about a
      // possibility the lowering never established.
      for (const rawState of list(found["adverse_states"] ?? [], `$result.${field}[].witness.adverse_states`)) {
        const state = object(rawState, `$result.${field}[].witness.adverse_states[]`);
        const legId = text(state["leg"], `$...adverse_states[].leg`);
        const reduced = reducedLegs.get(legId);
        if (reduced === undefined) {
          refuse(
            className,
            `$result.${field}[].witness.adverse_states`,
            `${legId} was not reduced, so no rule can produce an adverse state for it`,
          );
        }
        if (state["rule"] !== reduced.reductionRule) {
          refuse(
            className,
            `$result.${field}[].witness.adverse_states`,
            `${legId} was reduced by ${String(reduced.reductionRule)}, not ${String(state["rule"])}`,
          );
        }
      }
    }
  }
}

function evaluateOn(fn: Fn, price: Rational): Rational {
  for (const piece of fn.pieces) {
    const afterLo = piece.lo.value === null ||
      (piece.lo.closed ? lte(piece.lo.value, price) : lt(piece.lo.value, price));
    const beforeHi = piece.hi.value === null ||
      (piece.hi.closed ? lte(price, piece.hi.value) : lt(price, piece.hi.value));
    if (afterLo && beforeHi) return add(mul(piece.slope, price), piece.intercept);
  }
  refuse("WITNESS_INADMISSIBLE", "$result.witness.price", "the price is outside the profile");
}

/**
 * An infeasibility certificate: nonnegative weights that combine the constraints into
 * a contradiction.
 */
function compareCertificates(evidence: Evidence): void {
  // A certificate sits on the SIZE WINDOW it explains: it is the proof that no size
  // in some range can meet the objective, so it belongs to the window that says so.
  for (const rawWindow of list(evidence.result["size_windows"] ?? [], "$result.size_windows")) {
    const window = object(rawWindow, "$result.size_windows[]");
    const certificate = window["certificate"];
    if (certificate === undefined) continue;
    const found = object(certificate, "$result.size_windows[].certificate");
    const leg = String(window["leg"] ?? "");
    const where = `$result.size_windows.${leg}.certificate.weights`;
    for (const raw of list(found["weights"] ?? [], where)) {
      const weight = number(raw, where);
      // A NEGATIVE WEIGHT IS NOT A PROOF. Combining constraints requires nonnegative
      // multipliers: a negative one reverses the inequality it multiplies, so the
      // "contradiction" it produces is an artefact of the arithmetic rather than a
      // fact about the problem.
      if (sign(weight) < 0) {
        refuse(
          "CERTIFICATE_WEIGHTS",
          where,
          `${format(weight)} is negative; a negative weight reverses the inequality it multiplies`,
        );
      }
    }
  }
}

// ---------------------------------------------------------------- reading

function readDocument(raw: Uint8Array, what: string): Value {
  try {
    return parse(raw);
  } catch (error) {
    refuse("ENGINE_DISAGREES", `$${what}`, error instanceof Error ? error.message : String(error));
  }
}

function object(value: Value | undefined, at: string): Record<string, Value> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    refuse("ENGINE_DISAGREES", at, "expected an object");
  }
  return value as Record<string, Value>;
}

function list(value: Value | undefined, at: string): Value[] {
  if (!Array.isArray(value)) refuse("ENGINE_DISAGREES", at, "expected an array");
  return value;
}

function text(value: Value | undefined, at: string): string {
  if (typeof value !== "string") refuse("ENGINE_DISAGREES", at, "expected a string");
  return value;
}

function number(value: Value | undefined, at: string): Rational {
  if (typeof value !== "string") refuse("ENGINE_DISAGREES", at, "expected a number as text");
  try {
    return parseNumber(value);
  } catch {
    refuse("ENGINE_DISAGREES", at, `${value} is not in the number grammar`);
  }
}

function citedSnapshots(proposal: Record<string, Value>): string[] {
  const out: string[] = [];
  const baseline = proposal["baseline"];
  if (typeof baseline === "object" && baseline !== null && !Array.isArray(baseline)) {
    const source = (baseline as Record<string, Value>)["source"];
    if (typeof source === "object" && source !== null && !Array.isArray(source)) {
      const snapshot = (source as Record<string, Value>)["snapshot"];
      if (typeof snapshot === "string") out.push(snapshot);
    }
  }
  const legs = proposal["legs"];
  if (Array.isArray(legs)) {
    for (const rawLeg of legs) {
      if (typeof rawLeg !== "object" || rawLeg === null || Array.isArray(rawLeg)) continue;
      const leg = rawLeg as Record<string, Value>;
      const instance = leg["instance"];
      if (typeof instance === "object" && instance !== null && !Array.isArray(instance)) {
        const catalogue = (instance as Record<string, Value>)["catalogue"];
        if (typeof catalogue === "string") out.push(catalogue);
      }
      const acquisition = leg["acquisition"];
      if (typeof acquisition === "object" && acquisition !== null && !Array.isArray(acquisition)) {
        const snapshot = (acquisition as Record<string, Value>)["snapshot"];
        if (typeof snapshot === "string") out.push(snapshot);
      }
    }
  }
  return out;
}

async function sha256(raw: Uint8Array): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", raw as unknown as ArrayBuffer);
  return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** A small nonnegative integer, read from its digits. */
function digitsOf(text: string): number {
  let total = 0;
  for (const digit of text) {
    const place = "0123456789".indexOf(digit);
    if (place < 0) refuse("ENGINE_DISAGREES", "$registry.payoffs.at", `${text} is not a position`);
    total = total * 10 + place;
  }
  return total;
}

function short(hex: string): string {
  return hex.length <= 12 ? hex : hex.slice(0, 12);
}

// Kept for the size-window comparison, which needs the infimum and witness helpers
// the kernel exports; referencing them here keeps the import list honest.
void infimum;
void witness;
void cmp;
void sub;
