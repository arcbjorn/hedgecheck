// Contract documents: strict typed decoding from a canonical value.
//
// The SCHEMAS are the specification. Rather than transcribe sixty fields by hand into
// this file -- where they would drift from `schema/` the first time either changed --
// the decoder reads the schema and checks the document against it. The keyword set is
// small and closed: type, enum, const, pattern, maxLength, required, properties,
// additionalProperties, minProperties, dependentRequired, items, minItems, maxItems,
// oneOf, $ref, $defs. The list is checked against the files by a test, because a
// keyword the decoder silently ignores is a constraint that stops being enforced.
//
// Unknown keys are rejected. Every schema in `schema/` sets additionalProperties
// false, and this treats a missing additionalProperties as false too: a document
// carrying a field this checker does not understand cannot be verified by ignoring it.
//
// Optional fields are ABSENT, never null. The canonical profile has no null at all, so
// this is a property of the parser rather than a rule enforced here -- but a decoder
// that turned an absent field into a null would put it back, and a decode-then-encode
// round trip would stop reproducing the bytes a digest covers.

import { canonical, type Value } from "./canon.ts";
import { isNumber, numberLexeme, type VenueValue } from "./venue.ts";

export class DocError extends Error {
  readonly at: string;
  constructor(at: string, message: string) {
    super(at === "" ? message : `${at}: ${message}`);
    this.at = at;
  }
}

/** A JSON Schema, as the files in schema/ write one. */
export type Schema = { [key: string]: unknown };

export interface Schemas {
  readonly byName: ReadonlyMap<string, Schema>;
}

/**
 * Index the schema files by their file name, so $ref can resolve across them.
 *
 * A SCHEMA IS NOT A CONTRACT DOCUMENT. It carries `$schema`, `$id`, `$comment` and
 * numeric keywords such as minItems, all of which the canonical profile refuses --
 * correctly, because a contract document containing them would be a defect. Schema
 * files are read with the venue parser, which is as strict about syntax and allows
 * the shapes tooling legitimately uses.
 */
export function schemas(files: ReadonlyMap<string, VenueValue>): Schemas {
  const byName = new Map<string, Schema>();
  for (const [name, value] of files) {
    byName.set(name, value as unknown as Schema);
  }
  return { byName };
}

interface Context {
  readonly schemas: Schemas;
  readonly self: Schema;
}

/**
 * Check a document against a named schema. Returns the problems found, in document
 * order; an empty list means the document is valid.
 *
 * Every problem is returned rather than only the first, because a caller refusing a
 * document should be able to say everything that is wrong with it.
 */
export function problems(value: Value, schemaName: string, all: Schemas): string[] {
  const schema = all.byName.get(schemaName);
  if (schema === undefined) throw new DocError("", `no schema named ${schemaName}`);
  const found: string[] = [];
  check(value, schema, { schemas: all, self: schema }, "$", found);
  return found;
}

/** True when the document satisfies the schema. */
export function valid(value: Value, schemaName: string, all: Schemas): boolean {
  return problems(value, schemaName, all).length === 0;
}

function resolve(schema: Schema, context: Context): { schema: Schema; context: Context } {
  let here = schema;
  let where = context;
  // A $ref chain is followed to its end. The files here use at most one hop, but a
  // loop would hang, so the depth is bounded.
  for (let hops = 0; hops < 8; hops += 1) {
    const ref = here["$ref"];
    if (typeof ref !== "string") return { schema: here, context: where };
    const hash = ref.indexOf("#");
    const file = hash < 0 ? ref : ref.slice(0, hash);
    const pointer = hash < 0 ? "" : ref.slice(hash + 1);
    let root = where.self;
    if (file !== "") {
      const other = where.schemas.byName.get(file);
      if (other === undefined) throw new DocError("", `unresolved $ref ${ref}`);
      root = other;
      where = { schemas: where.schemas, self: other };
    }
    here = pointerInto(root, pointer, ref);
  }
  throw new DocError("", "a $ref chain longer than 8 hops");
}

function pointerInto(root: Schema, pointer: string, ref: string): Schema {
  if (pointer === "") return root;
  let here: unknown = root;
  for (const rawStep of pointer.split("/")) {
    if (rawStep === "") continue;
    const step = rawStep.replace(/~1/g, "/").replace(/~0/g, "~");
    if (typeof here !== "object" || here === null) {
      throw new DocError("", `unresolved $ref ${ref}`);
    }
    here = (here as Record<string, unknown>)[step];
  }
  if (typeof here !== "object" || here === null) {
    throw new DocError("", `unresolved $ref ${ref}`);
  }
  return here as Schema;
}

/** A schema's own integer keyword, read from its digits. */
function wholeKeyword(value: unknown): number | null {
  if (typeof value === "number") return value;
  const lexeme = numberLexeme(value as VenueValue);
  if (lexeme === null || !/^[0-9]+$/.test(lexeme)) return null;
  let total = 0;
  for (const digit of lexeme) total = total * 10 + "0123456789".indexOf(digit);
  return total;
}

function typeOf(value: Value): string {
  if (Array.isArray(value)) return "array";
  if (typeof value === "string") return "string";
  if (typeof value === "boolean") return "boolean";
  return "object";
}

function check(
  value: Value,
  rawSchema: Schema,
  rawContext: Context,
  at: string,
  found: string[],
): void {
  const { schema, context } = resolve(rawSchema, rawContext);

  const expected = schema["type"];
  if (typeof expected === "string" && typeOf(value) !== expected) {
    found.push(`${at}: expected ${expected}, found ${typeOf(value)}`);
    return;
  }

  const constant = unwrap(schema["const"]);
  if (constant !== undefined && value !== constant) {
    found.push(`${at}: expected ${JSON.stringify(constant)}`);
  }

  const options = schema["enum"];
  if (Array.isArray(options) && !options.map(unwrap).includes(value as unknown)) {
    found.push(`${at}: not one of ${JSON.stringify(options)}`);
  }

  const pattern = schema["pattern"];
  if (typeof pattern === "string" && typeof value === "string") {
    if (!new RegExp(pattern).test(value)) {
      found.push(`${at}: ${JSON.stringify(value)} does not match ${pattern}`);
    }
  }

  const longest = wholeKeyword(schema["maxLength"]);
  if (longest !== null && typeof value === "string" && value.length > longest) {
    found.push(`${at}: ${value.length} characters, at most ${longest} allowed`);
  }

  const alternatives = schema["oneOf"];
  if (Array.isArray(alternatives)) {
    let matched = 0;
    for (const alternative of alternatives) {
      const inner: string[] = [];
      check(value, alternative as Schema, context, at, inner);
      if (inner.length === 0) matched += 1;
    }
    if (matched !== 1) {
      found.push(`${at}: matches ${matched} of ${alternatives.length} alternatives, needs exactly one`);
    }
    // The ALTERNATIVES own the object and array checks. A schema that delegates to
    // oneOf declares no properties of its own, so falling through would find every
    // key unknown against an empty property set -- and would report that instead of
    // the real answer, which the branches already gave.
    if (schema["properties"] === undefined && schema["items"] === undefined) return;
  }

  if (Array.isArray(value)) {
    const items = schema["items"];
    if (items !== undefined) {
      value.forEach((item, index) => {
        check(item, items as Schema, context, `${at}[${index}]`, found);
      });
    }
    // minItems and maxItems arrive from the venue parser as lexemes, never as
    // JavaScript numbers. A count is small and exact, so reading the digits is safe
    // here in a way that reading a PRICE would not be.
    const least = wholeKeyword(schema["minItems"]);
    if (least !== null && value.length < least) {
      found.push(`${at}: ${value.length} items, at least ${least} required`);
    }
    const most = wholeKeyword(schema["maxItems"]);
    if (most !== null && value.length > most) {
      found.push(`${at}: ${value.length} items, at most ${most} allowed`);
    }
    return;
  }

  if (typeof value === "object" && value !== null) {
    const properties = (schema["properties"] ?? {}) as Record<string, Schema>;
    const required = schema["required"];
    if (Array.isArray(required)) {
      for (const name of required) {
        if (!Object.prototype.hasOwnProperty.call(value, name as string)) {
          found.push(`${at}.${String(name)}: missing`);
        }
      }
    }
    const fewest = wholeKeyword(schema["minProperties"]);
    if (fewest !== null && Object.keys(value).length < fewest) {
      found.push(`${at}: ${Object.keys(value).length} properties, at least ${fewest} required`);
    }

    // dependentRequired is what makes "a present bound always states who owns it" a
    // rule rather than a hope: naming `upper` obliges the document to name
    // `upper_inclusive` too. Without it, a bound with no owner passes every other
    // check, and the kernel's whole endpoint discipline is unenforced at the door.
    const dependent = schema["dependentRequired"];
    if (typeof dependent === "object" && dependent !== null) {
      for (const [trigger, names] of Object.entries(dependent as Record<string, unknown>)) {
        if (!Object.prototype.hasOwnProperty.call(value, trigger)) continue;
        if (!Array.isArray(names)) continue;
        for (const name of names) {
          if (!Object.prototype.hasOwnProperty.call(value, name as string)) {
            found.push(`${at}.${String(name)}: required because ${trigger} is present`);
          }
        }
      }
    }

    // An unknown key is refused unless the schema explicitly allows one. The default
    // is refusal, not acceptance: a document carrying a field this checker does not
    // understand cannot be verified by ignoring it.
    const extra = schema["additionalProperties"];
    const allowExtra = extra === true;
    for (const name of Object.keys(value)) {
      const child = properties[name];
      if (child === undefined) {
        if (!allowExtra) found.push(`${at}.${name}: unknown key`);
        continue;
      }
      check((value as Record<string, Value>)[name] as Value, child, context, `${at}.${name}`, found);
    }
  }
}

// ---------------------------------------------------------------- round trip

/**
 * Decode then encode reproduces the canonical bytes.
 *
 * The decoder above does not build a second representation, so a round trip is the
 * identity on a valid document -- which is the point. A decoder that normalised
 * anything, dropped an absent optional field or added one, would change the bytes a
 * digest covers, and a checker whose own reading of a document differs from the bytes
 * it hashed is checking something else.
 */
export function roundTrip(value: Value): Uint8Array {
  return canonical(value);
}

// ---------------------------------------------------------------- typed readers

/** The verdict a result states. */
export type Verdict = "passes" | "fails" | "needs_review";

export function stringAt(value: Value, path: readonly string[]): string {
  const found = walk(value, path);
  if (typeof found !== "string") {
    throw new DocError(path.join("."), "not a string");
  }
  return found;
}

export function boolAt(value: Value, path: readonly string[]): boolean {
  const found = walk(value, path);
  if (typeof found !== "boolean") {
    throw new DocError(path.join("."), "not a boolean");
  }
  return found;
}

export function listAt(value: Value, path: readonly string[]): Value[] {
  const found = walk(value, path);
  if (!Array.isArray(found)) throw new DocError(path.join("."), "not an array");
  return found;
}

export function objectAt(value: Value, path: readonly string[]): { [key: string]: Value } {
  const found = walk(value, path);
  if (typeof found !== "object" || Array.isArray(found)) {
    throw new DocError(path.join("."), "not an object");
  }
  return found;
}

/** Present, or undefined. An optional field is ABSENT, never null. */
export function optional(value: Value, path: readonly string[]): Value | undefined {
  try {
    return walk(value, path);
  } catch {
    return undefined;
  }
}

function walk(value: Value, path: readonly string[]): Value {
  let here: Value = value;
  for (const step of path) {
    if (typeof here !== "object" || here === null || Array.isArray(here)) {
      throw new DocError(path.join("."), "not an object");
    }
    if (!Object.prototype.hasOwnProperty.call(here, step)) {
      throw new DocError(path.join("."), "missing");
    }
    here = (here as Record<string, Value>)[step] as Value;
  }
  return here;
}

/** A schema literal, with a venue number unwrapped to its lexeme. */
function unwrap(value: unknown): unknown {
  if (isNumber(value as VenueValue)) return numberLexeme(value as VenueValue);
  return value;
}
