// Canonical JSON and digests: a strict profile of RFC 8785. No dependencies.
//
// JSON.parse is not used. It cannot reject duplicate keys, numbers, null or an escaped lone
// surrogate, and this is the trust boundary: the checker reads results and proposals that
// arrive over a network. Accepted documents are UTF-8 without a BOM and contain only
// objects, arrays, strings and booleans; keys match [a-z][a-z0-9_]* and are unique; strings
// are well-formed Unicode without U+FFFD; nesting is at most 32 deep.

export const MAX_DEPTH = 32;

export type Value = string | boolean | Value[] | { [key: string]: Value };

export class CanonError extends Error {}

const KEY = /^[a-z][a-z0-9_]*$/;
const SHORT: Record<string, string> = { '"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t" };
const UNESCAPE: Record<string, string> = { '"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t" };

export function parse(raw: Uint8Array): Value {
  if (raw.length >= 3 && raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf) {
    throw new CanonError("byte order mark");
  }
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(raw);
  } catch {
    throw new CanonError("invalid UTF-8");
  }
  let at = 0;

  const fail = (message: string): never => {
    throw new CanonError(`${message} at ${at}`);
  };
  const space = (): void => {
    while (at < text.length && (text[at] === " " || text[at] === "\t" || text[at] === "\n" || text[at] === "\r")) at += 1;
  };

  const string = (): string => {
    at += 1; // opening quote
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
        out += UNESCAPE[escape];
        at += 2;
      } else {
        fail("bad escape");
      }
    }
    wellFormed(out);
    return out;
  };

  const value = (depth: number): Value => {
    if (depth > MAX_DEPTH) fail("nested deeper than 32");
    space();
    const char = text[at];
    if (char === '"') return string();
    if (char === "[") {
      at += 1;
      const list: Value[] = [];
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
      const object: { [key: string]: Value } = Object.create(null);
      space();
      if (text[at] === "}") {
        at += 1;
        return object;
      }
      for (;;) {
        space();
        if (text[at] !== '"') fail("expected a key");
        const name = string();
        if (!KEY.test(name)) fail("key outside [a-z][a-z0-9_]*");
        if (name in object) fail("duplicate key");
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
    return fail("numbers, null and everything else are outside the profile");
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

function wellFormed(text: string): void {
  for (let index = 0; index < text.length; index += 1) {
    const unit = text.charCodeAt(index);
    if (unit === 0xfffd) throw new CanonError("U+FFFD in a string");
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = text.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new CanonError("lone surrogate in a string");
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      throw new CanonError("lone surrogate in a string");
    }
  }
}

function writeString(text: string): string {
  wellFormed(text);
  let out = '"';
  for (const char of text) {
    const short = SHORT[char];
    if (short !== undefined) out += short;
    else if (char < " ") out += `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`;
    else out += char;
  }
  return `${out}"`;
}

function write(value: Value, depth: number): string {
  if (depth > MAX_DEPTH) throw new CanonError("nested deeper than 32");
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "string") return writeString(value);
  if (Array.isArray(value)) return `[${value.map((item) => write(item, depth + 1)).join(",")}]`;
  if (typeof value !== "object" || value === null) throw new CanonError("unsupported value");
  // Keys are ASCII under the profile, so UTF-16 order, RFC 8785's order, is plain order.
  const names = Object.keys(value).sort();
  const members = names.map((name) => {
    if (!KEY.test(name)) throw new CanonError("key outside [a-z][a-z0-9_]*");
    return `${writeString(name)}:${write(value[name] as Value, depth + 1)}`;
  });
  return `{${members.join(",")}}`;
}

// The return type is inferred on purpose: current typings distinguish Uint8Array<ArrayBuffer>,
// which WebCrypto requires, from the wider Uint8Array that an annotation would produce.
export function canonical(value: Value) {
  return new TextEncoder().encode(write(value, 1));
}

export async function digest(value: Value): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", canonical(value));
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
