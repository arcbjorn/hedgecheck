// Venue JSON: the second parser mode. A snapshot is EVIDENCE, not a contract document.

export const MAX_DEPTH = 32;

/** A JSON number, kept as the characters the venue sent. */
export interface VenueNumber {
  readonly lexeme: string;
}

export type VenueValue =
  | string
  | boolean
  | null
  | VenueNumber
  | VenueValue[]
  | { [key: string]: VenueValue };

export class VenueError extends Error {}

const UNESCAPE: Record<string, string> = {
  '"': '"',
  "\\": "\\",
  "/": "/",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "\t",
};

/** JSON's own number grammar, and nothing wider. */
const NUMBER = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?/;

export function isNumber(value: VenueValue): value is VenueNumber {
  return typeof value === "object" && value !== null && !Array.isArray(value) &&
    "lexeme" in value;
}

/** The characters of a number, for a caller that wants to look without converting. */
export function numberLexeme(value: VenueValue): string | null {
  return isNumber(value) ? value.lexeme : null;
}

export function parseVenue(raw: Uint8Array): VenueValue {
  if (raw.length >= 3 && raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf) {
    throw new VenueError("byte order mark");
  }
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(raw);
  } catch {
    throw new VenueError("invalid UTF-8");
  }
  let at = 0;

  const fail = (message: string): never => {
    throw new VenueError(`${message} at ${at}`);
  };
  const space = (): void => {
    while (
      at < text.length &&
      (text[at] === " " || text[at] === "\t" || text[at] === "\n" || text[at] === "\r")
    ) {
      at += 1;
    }
  };

  const string = (): string => {
    at += 1;
    let out = "";
    for (;;) {
      if (at >= text.length) fail("unterminated string");
      const char = text[at] as string;
      if (char === '"') {
        at += 1;
        break;
      }
      if (char < " ") fail("raw control character");
      if (char !== "\\") {
        out += char;
        at += 1;
        continue;
      }
      const escape = text[at + 1];
      if (escape === "u") {
        const hex = text.slice(at + 2, at + 6);
        if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail("bad \\u escape");
        out += String.fromCharCode(parseHex(hex));
        at += 6;
      } else if (escape !== undefined && escape in UNESCAPE) {
        out += UNESCAPE[escape] as string;
        at += 2;
      } else {
        fail("bad escape");
      }
    }
    // A lone surrogate is not text. It is rejected here rather than left to become
    // U+FFFD downstream, where it would silently change the bytes a digest covers.
    for (let index = 0; index < out.length; index += 1) {
      const code = out.charCodeAt(index);
      if (code >= 0xd800 && code <= 0xdbff) {
        const next = out.charCodeAt(index + 1);
        if (!(next >= 0xdc00 && next <= 0xdfff)) fail("lone high surrogate");
        index += 1;
      } else if (code >= 0xdc00 && code <= 0xdfff) {
        fail("lone low surrogate");
      }
    }
    return out;
  };

  const value = (depth: number): VenueValue => {
    if (depth > MAX_DEPTH) fail("nested deeper than 32");
    space();
    const char = text[at];
    if (char === '"') return string();
    if (char === "[") {
      at += 1;
      const list: VenueValue[] = [];
      space();
      if (text[at] === "]") {
        at += 1;
        return list;
      }
      for (;;) {
        list.push(value(depth + 1));
        space();
        if (text[at] === ",") {
          at += 1;
          continue;
        }
        if (text[at] === "]") {
          at += 1;
          return list;
        }
        fail("expected , or ]");
      }
    }
    if (char === "{") {
      at += 1;
      // A null prototype, so a key such as "__proto__" or "constructor" is data and
      // cannot reach Object.prototype. Venue keys are not constrained by a grammar
      // here, which makes this the place where that matters.
      const object: { [key: string]: VenueValue } = Object.create(null);
      space();
      if (text[at] === "}") {
        at += 1;
        return object;
      }
      for (;;) {
        space();
        if (text[at] !== '"') fail("expected a key");
        const name = string();
        if (Object.prototype.hasOwnProperty.call(object, name)) fail("duplicate key");
        space();
        if (text[at] !== ":") fail("expected :");
        at += 1;
        object[name] = value(depth + 1);
        space();
        if (text[at] === ",") {
          at += 1;
          continue;
        }
        if (text[at] === "}") {
          at += 1;
          return object;
        }
        fail("expected , or }");
      }
    }
    if (text.startsWith("true", at)) {
      at += 4;
      return true;
    }
    if (text.startsWith("false", at)) {
      at += 5;
      return false;
    }
    if (text.startsWith("null", at)) {
      at += 4;
      return null;
    }
    const match = NUMBER.exec(text.slice(at));
    if (match !== null && match[0].length > 0) {
      const lexeme = match[0];
      at += lexeme.length;
      return { lexeme };
    }
    return fail("not a JSON value");
  };

  const result = value(1);
  space();
  if (at !== text.length) fail("trailing text");
  return result;
}

function parseHex(hex: string): number {
  let code = 0;
  for (const digit of hex.toLowerCase()) code = code * 16 + "0123456789abcdef".indexOf(digit);
  return code;
}

// ---------------------------------------------------------------- reading

/** A field's value, or null when the path does not exist. */
export function at(value: VenueValue, path: readonly (string | number)[]): VenueValue | null {
  let here: VenueValue = value;
  for (const step of path) {
    if (typeof step === "number") {
      if (!Array.isArray(here) || step < 0 || step >= here.length) return null;
      here = here[step] as VenueValue;
      continue;
    }
    if (typeof here !== "object" || here === null || Array.isArray(here) || isNumber(here)) {
      return null;
    }
    if (!Object.prototype.hasOwnProperty.call(here, step)) return null;
    here = (here as { [key: string]: VenueValue })[step] as VenueValue;
  }
  return here;
}

/**
 * A quantity, read ONLY from a string field.
 */
export function quantityText(value: VenueValue, path: readonly (string | number)[]): string {
  const found = at(value, path);
  if (typeof found === "string") return found;
  if (isNumber(found)) {
    throw new VenueError(
      `${path.join(".")} is a JSON number; a quantity is read only from a string field`,
    );
  }
  throw new VenueError(`${path.join(".")} is not a string`);
}
