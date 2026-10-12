// src/canon.ts
var MAX_DEPTH = 32;
var CanonError = class extends Error {
};
var KEY = /^[a-z][a-z0-9_]*$/;
var SHORT = {
  '"': '\\"',
  "\\": "\\\\",
  "\b": "\\b",
  "\f": "\\f",
  "\n": "\\n",
  "\r": "\\r",
  "	": "\\t"
};
var UNESCAPE = {
  '"': '"',
  "\\": "\\",
  "/": "/",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "	"
};
function parse(raw) {
  if (raw.length >= 3 && raw[0] === 239 && raw[1] === 187 && raw[2] === 191) {
    throw new CanonError("byte order mark");
  }
  let text2;
  try {
    text2 = new TextDecoder("utf-8", {
      fatal: true,
      ignoreBOM: true
    }).decode(raw);
  } catch {
    throw new CanonError("invalid UTF-8");
  }
  let at2 = 0;
  const fail = (message) => {
    throw new CanonError(`${message} at ${at2}`);
  };
  const space = () => {
    while (at2 < text2.length && (text2[at2] === " " || text2[at2] === "	" || text2[at2] === "\n" || text2[at2] === "\r")) at2 += 1;
  };
  const string = () => {
    at2 += 1;
    let out = "";
    for (; ; ) {
      if (at2 >= text2.length) fail("unterminated string");
      const char = text2[at2];
      if (char === '"') {
        at2 += 1;
        break;
      }
      if (char < " ") fail("raw control character");
      if (char !== "\\") {
        out += char;
        at2 += 1;
        continue;
      }
      const escape = text2[at2 + 1];
      if (escape === "u") {
        const hex = text2.slice(at2 + 2, at2 + 6);
        if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail("bad \\u escape");
        out += String.fromCharCode(parseHex(hex));
        at2 += 6;
      } else if (escape !== void 0 && escape in UNESCAPE) {
        out += UNESCAPE[escape];
        at2 += 2;
      } else {
        fail("bad escape");
      }
    }
    wellFormed(out);
    return out;
  };
  const value = (depth) => {
    if (depth > MAX_DEPTH) fail("nested deeper than 32");
    space();
    const char = text2[at2];
    if (char === '"') return string();
    if (char === "[") {
      at2 += 1;
      const list2 = [];
      space();
      if (text2[at2] === "]") {
        at2 += 1;
        return list2;
      }
      for (; ; ) {
        list2.push(value(depth + 1));
        space();
        if (text2[at2] === ",") {
          at2 += 1;
          continue;
        }
        if (text2[at2] === "]") {
          at2 += 1;
          return list2;
        }
        fail("expected , or ]");
      }
    }
    if (char === "{") {
      at2 += 1;
      const object2 = /* @__PURE__ */ Object.create(null);
      space();
      if (text2[at2] === "}") {
        at2 += 1;
        return object2;
      }
      for (; ; ) {
        space();
        if (text2[at2] !== '"') fail("expected a key");
        const name = string();
        if (!KEY.test(name)) fail("key outside [a-z][a-z0-9_]*");
        if (name in object2) fail("duplicate key");
        space();
        if (text2[at2] !== ":") fail("expected :");
        at2 += 1;
        object2[name] = value(depth + 1);
        space();
        if (text2[at2] === ",") {
          at2 += 1;
          continue;
        }
        if (text2[at2] === "}") {
          at2 += 1;
          return object2;
        }
        fail("expected , or }");
      }
    }
    if (text2.startsWith("true", at2)) {
      at2 += 4;
      return true;
    }
    if (text2.startsWith("false", at2)) {
      at2 += 5;
      return false;
    }
    return fail("numbers, null and everything else are outside the profile");
  };
  const result = value(1);
  space();
  if (at2 !== text2.length) fail("trailing text");
  return result;
}
function parseHex(hex) {
  let code = 0;
  for (const digit of hex.toLowerCase()) code = code * 16 + "0123456789abcdef".indexOf(digit);
  return code;
}
function wellFormed(text2) {
  for (let index = 0; index < text2.length; index += 1) {
    const unit = text2.charCodeAt(index);
    if (unit === 65533) throw new CanonError("U+FFFD in a string");
    if (unit >= 55296 && unit <= 56319) {
      const next = text2.charCodeAt(index + 1);
      if (!(next >= 56320 && next <= 57343)) throw new CanonError("lone surrogate in a string");
      index += 1;
    } else if (unit >= 56320 && unit <= 57343) {
      throw new CanonError("lone surrogate in a string");
    }
  }
}
function writeString(text2) {
  wellFormed(text2);
  let out = '"';
  for (const char of text2) {
    const short2 = SHORT[char];
    if (short2 !== void 0) out += short2;
    else if (char < " ") out += `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`;
    else out += char;
  }
  return `${out}"`;
}
function write(value, depth) {
  if (depth > MAX_DEPTH) throw new CanonError("nested deeper than 32");
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "string") return writeString(value);
  if (Array.isArray(value)) return `[${value.map((item) => write(item, depth + 1)).join(",")}]`;
  if (typeof value !== "object" || value === null) throw new CanonError("unsupported value");
  const names = Object.keys(value).sort();
  const members = names.map((name) => {
    if (!KEY.test(name)) throw new CanonError("key outside [a-z][a-z0-9_]*");
    return `${writeString(name)}:${write(value[name], depth + 1)}`;
  });
  return `{${members.join(",")}}`;
}
function canonical(value) {
  return new TextEncoder().encode(write(value, 1));
}
async function digest(value) {
  const hash = await crypto.subtle.digest("SHA-256", canonical(value));
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

// src/venue.ts
var MAX_DEPTH2 = 32;
var VenueError = class extends Error {
};
var UNESCAPE2 = {
  '"': '"',
  "\\": "\\",
  "/": "/",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "	"
};
var NUMBER = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?/;
function isNumber(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value) && "lexeme" in value;
}
function numberLexeme(value) {
  return isNumber(value) ? value.lexeme : null;
}
function parseVenue(raw) {
  if (raw.length >= 3 && raw[0] === 239 && raw[1] === 187 && raw[2] === 191) {
    throw new VenueError("byte order mark");
  }
  let text2;
  try {
    text2 = new TextDecoder("utf-8", {
      fatal: true,
      ignoreBOM: true
    }).decode(raw);
  } catch {
    throw new VenueError("invalid UTF-8");
  }
  let at2 = 0;
  const fail = (message) => {
    throw new VenueError(`${message} at ${at2}`);
  };
  const space = () => {
    while (at2 < text2.length && (text2[at2] === " " || text2[at2] === "	" || text2[at2] === "\n" || text2[at2] === "\r")) {
      at2 += 1;
    }
  };
  const string = () => {
    at2 += 1;
    let out = "";
    for (; ; ) {
      if (at2 >= text2.length) fail("unterminated string");
      const char = text2[at2];
      if (char === '"') {
        at2 += 1;
        break;
      }
      if (char < " ") fail("raw control character");
      if (char !== "\\") {
        out += char;
        at2 += 1;
        continue;
      }
      const escape = text2[at2 + 1];
      if (escape === "u") {
        const hex = text2.slice(at2 + 2, at2 + 6);
        if (!/^[0-9a-fA-F]{4}$/.test(hex)) fail("bad \\u escape");
        out += String.fromCharCode(parseHex2(hex));
        at2 += 6;
      } else if (escape !== void 0 && escape in UNESCAPE2) {
        out += UNESCAPE2[escape];
        at2 += 2;
      } else {
        fail("bad escape");
      }
    }
    for (let index = 0; index < out.length; index += 1) {
      const code = out.charCodeAt(index);
      if (code >= 55296 && code <= 56319) {
        const next = out.charCodeAt(index + 1);
        if (!(next >= 56320 && next <= 57343)) fail("lone high surrogate");
        index += 1;
      } else if (code >= 56320 && code <= 57343) {
        fail("lone low surrogate");
      }
    }
    return out;
  };
  const value = (depth) => {
    if (depth > MAX_DEPTH2) fail("nested deeper than 32");
    space();
    const char = text2[at2];
    if (char === '"') return string();
    if (char === "[") {
      at2 += 1;
      const list2 = [];
      space();
      if (text2[at2] === "]") {
        at2 += 1;
        return list2;
      }
      for (; ; ) {
        list2.push(value(depth + 1));
        space();
        if (text2[at2] === ",") {
          at2 += 1;
          continue;
        }
        if (text2[at2] === "]") {
          at2 += 1;
          return list2;
        }
        fail("expected , or ]");
      }
    }
    if (char === "{") {
      at2 += 1;
      const object2 = /* @__PURE__ */ Object.create(null);
      space();
      if (text2[at2] === "}") {
        at2 += 1;
        return object2;
      }
      for (; ; ) {
        space();
        if (text2[at2] !== '"') fail("expected a key");
        const name = string();
        if (Object.prototype.hasOwnProperty.call(object2, name)) fail("duplicate key");
        space();
        if (text2[at2] !== ":") fail("expected :");
        at2 += 1;
        object2[name] = value(depth + 1);
        space();
        if (text2[at2] === ",") {
          at2 += 1;
          continue;
        }
        if (text2[at2] === "}") {
          at2 += 1;
          return object2;
        }
        fail("expected , or }");
      }
    }
    if (text2.startsWith("true", at2)) {
      at2 += 4;
      return true;
    }
    if (text2.startsWith("false", at2)) {
      at2 += 5;
      return false;
    }
    if (text2.startsWith("null", at2)) {
      at2 += 4;
      return null;
    }
    const match = NUMBER.exec(text2.slice(at2));
    if (match !== null && match[0].length > 0) {
      const lexeme = match[0];
      at2 += lexeme.length;
      return {
        lexeme
      };
    }
    return fail("not a JSON value");
  };
  const result = value(1);
  space();
  if (at2 !== text2.length) fail("trailing text");
  return result;
}
function parseHex2(hex) {
  let code = 0;
  for (const digit of hex.toLowerCase()) code = code * 16 + "0123456789abcdef".indexOf(digit);
  return code;
}
function at(value, path) {
  let here = value;
  for (const step of path) {
    if (typeof step === "number") {
      if (!Array.isArray(here) || step < 0 || step >= here.length) return null;
      here = here[step];
      continue;
    }
    if (typeof here !== "object" || here === null || Array.isArray(here) || isNumber(here)) {
      return null;
    }
    if (!Object.prototype.hasOwnProperty.call(here, step)) return null;
    here = here[step];
  }
  return here;
}
function quantityText(value, path) {
  const found = at(value, path);
  if (typeof found === "string") return found;
  if (isNumber(found)) {
    throw new VenueError(`${path.join(".")} is a JSON number; a quantity is read only from a string field`);
  }
  throw new VenueError(`${path.join(".")} is not a string`);
}

// src/doc.ts
var DocError = class extends Error {
  at;
  constructor(at2, message) {
    super(at2 === "" ? message : `${at2}: ${message}`);
    this.at = at2;
  }
};
function problems(value, schemaName, all) {
  const schema = all.byName.get(schemaName);
  if (schema === void 0) throw new DocError("", `no schema named ${schemaName}`);
  const found = [];
  check(value, schema, {
    schemas: all,
    self: schema
  }, "$", found);
  return found;
}
function resolve(schema, context) {
  let here = schema;
  let where = context;
  for (let hops = 0; hops < 8; hops += 1) {
    const ref = here["$ref"];
    if (typeof ref !== "string") return {
      schema: here,
      context: where
    };
    const hash = ref.indexOf("#");
    const file = hash < 0 ? ref : ref.slice(0, hash);
    const pointer = hash < 0 ? "" : ref.slice(hash + 1);
    let root = where.self;
    if (file !== "") {
      const other = where.schemas.byName.get(file);
      if (other === void 0) throw new DocError("", `unresolved $ref ${ref}`);
      root = other;
      where = {
        schemas: where.schemas,
        self: other
      };
    }
    here = pointerInto(root, pointer, ref);
  }
  throw new DocError("", "a $ref chain longer than 8 hops");
}
function pointerInto(root, pointer, ref) {
  if (pointer === "") return root;
  let here = root;
  for (const rawStep of pointer.split("/")) {
    if (rawStep === "") continue;
    const step = rawStep.replace(/~1/g, "/").replace(/~0/g, "~");
    if (typeof here !== "object" || here === null) {
      throw new DocError("", `unresolved $ref ${ref}`);
    }
    here = here[step];
  }
  if (typeof here !== "object" || here === null) {
    throw new DocError("", `unresolved $ref ${ref}`);
  }
  return here;
}
function wholeKeyword(value) {
  if (typeof value === "number") return value;
  const lexeme = numberLexeme(value);
  if (lexeme === null || !/^[0-9]+$/.test(lexeme)) return null;
  let total = 0;
  for (const digit of lexeme) total = total * 10 + "0123456789".indexOf(digit);
  return total;
}
function typeOf(value) {
  if (Array.isArray(value)) return "array";
  if (typeof value === "string") return "string";
  if (typeof value === "boolean") return "boolean";
  return "object";
}
function check(value, rawSchema, rawContext, at2, found) {
  const { schema, context } = resolve(rawSchema, rawContext);
  const expected = schema["type"];
  if (typeof expected === "string" && typeOf(value) !== expected) {
    found.push(`${at2}: expected ${expected}, found ${typeOf(value)}`);
    return;
  }
  const constant = unwrap(schema["const"]);
  if (constant !== void 0 && value !== constant) {
    found.push(`${at2}: expected ${JSON.stringify(constant)}`);
  }
  const options = schema["enum"];
  if (Array.isArray(options) && !options.map(unwrap).includes(value)) {
    found.push(`${at2}: not one of ${JSON.stringify(options)}`);
  }
  const pattern = schema["pattern"];
  if (typeof pattern === "string" && typeof value === "string") {
    if (!new RegExp(pattern).test(value)) {
      found.push(`${at2}: ${JSON.stringify(value)} does not match ${pattern}`);
    }
  }
  const longest = wholeKeyword(schema["maxLength"]);
  if (longest !== null && typeof value === "string" && value.length > longest) {
    found.push(`${at2}: ${value.length} characters, at most ${longest} allowed`);
  }
  const alternatives = schema["oneOf"];
  if (Array.isArray(alternatives)) {
    let matched = 0;
    for (const alternative of alternatives) {
      const inner = [];
      check(value, alternative, context, at2, inner);
      if (inner.length === 0) matched += 1;
    }
    if (matched !== 1) {
      found.push(`${at2}: matches ${matched} of ${alternatives.length} alternatives, needs exactly one`);
    }
    if (schema["properties"] === void 0 && schema["items"] === void 0) return;
  }
  if (Array.isArray(value)) {
    const items = schema["items"];
    if (items !== void 0) {
      value.forEach((item, index) => {
        check(item, items, context, `${at2}[${index}]`, found);
      });
    }
    const least = wholeKeyword(schema["minItems"]);
    if (least !== null && value.length < least) {
      found.push(`${at2}: ${value.length} items, at least ${least} required`);
    }
    const most = wholeKeyword(schema["maxItems"]);
    if (most !== null && value.length > most) {
      found.push(`${at2}: ${value.length} items, at most ${most} allowed`);
    }
    return;
  }
  if (typeof value === "object" && value !== null) {
    const properties = schema["properties"] ?? {};
    const required = schema["required"];
    if (Array.isArray(required)) {
      for (const name of required) {
        if (!Object.prototype.hasOwnProperty.call(value, name)) {
          found.push(`${at2}.${String(name)}: missing`);
        }
      }
    }
    const fewest = wholeKeyword(schema["minProperties"]);
    if (fewest !== null && Object.keys(value).length < fewest) {
      found.push(`${at2}: ${Object.keys(value).length} properties, at least ${fewest} required`);
    }
    const dependent = schema["dependentRequired"];
    if (typeof dependent === "object" && dependent !== null) {
      for (const [trigger, names] of Object.entries(dependent)) {
        if (!Object.prototype.hasOwnProperty.call(value, trigger)) continue;
        if (!Array.isArray(names)) continue;
        for (const name of names) {
          if (!Object.prototype.hasOwnProperty.call(value, name)) {
            found.push(`${at2}.${String(name)}: required because ${trigger} is present`);
          }
        }
      }
    }
    const extra = schema["additionalProperties"];
    const allowExtra = extra === true;
    for (const name of Object.keys(value)) {
      const child = properties[name];
      if (child === void 0) {
        if (!allowExtra) found.push(`${at2}.${name}: unknown key`);
        continue;
      }
      check(value[name], child, context, `${at2}.${name}`, found);
    }
  }
}
function stringAt(value, path) {
  const found = walk(value, path);
  if (typeof found !== "string") {
    throw new DocError(path.join("."), "not a string");
  }
  return found;
}
function listAt(value, path) {
  const found = walk(value, path);
  if (!Array.isArray(found)) throw new DocError(path.join("."), "not an array");
  return found;
}
function objectAt(value, path) {
  const found = walk(value, path);
  if (typeof found !== "object" || Array.isArray(found)) {
    throw new DocError(path.join("."), "not an object");
  }
  return found;
}
function optional(value, path) {
  try {
    return walk(value, path);
  } catch {
    return void 0;
  }
}
function walk(value, path) {
  let here = value;
  for (const step of path) {
    if (typeof here !== "object" || here === null || Array.isArray(here)) {
      throw new DocError(path.join("."), "not an object");
    }
    if (!Object.prototype.hasOwnProperty.call(here, step)) {
      throw new DocError(path.join("."), "missing");
    }
    here = here[step];
  }
  return here;
}
function unwrap(value) {
  if (isNumber(value)) return numberLexeme(value);
  return value;
}

// src/exact.ts
var MAX_LENGTH = 80;
var GRAMMAR = /^(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|-?(?:0|[1-9][0-9]*)\/[1-9][0-9]*)$/;
var NumberError = class extends Error {
};
function gcd(a, b) {
  let x = a < 0n ? -a : a;
  let y = b < 0n ? -b : b;
  while (y !== 0n) {
    [x, y] = [
      y,
      x % y
    ];
  }
  return x;
}
function rational(num, den) {
  if (den === 0n) throw new NumberError("zero denominator");
  const sign2 = den < 0n ? -1n : 1n;
  const divisor = gcd(num, den) || 1n;
  return {
    num: sign2 * num / divisor,
    den: sign2 * den / divisor
  };
}
function parse2(text2) {
  if (typeof text2 !== "string" || text2.length > MAX_LENGTH || !GRAMMAR.test(text2)) {
    throw new NumberError("not in the number grammar");
  }
  const slash = text2.indexOf("/");
  if (slash >= 0) {
    return rational(BigInt(text2.slice(0, slash)), BigInt(text2.slice(slash + 1)));
  }
  const negative = text2.startsWith("-");
  const body = negative ? text2.slice(1) : text2;
  const point = body.indexOf(".");
  const whole = point < 0 ? body : body.slice(0, point);
  const fraction = point < 0 ? "" : body.slice(point + 1);
  const magnitude = BigInt(whole + fraction);
  return rational(negative ? -magnitude : magnitude, 10n ** BigInt(fraction.length));
}
function format(value) {
  let rest = value.den;
  for (const prime of [
    2n,
    5n
  ]) {
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
  const text2 = places > 0 ? `${digits.slice(0, cut)}.${digits.slice(cut)}` : digits;
  return value.num < 0n ? `-${text2}` : text2;
}
var ZERO = {
  num: 0n,
  den: 1n
};
var ONE = {
  num: 1n,
  den: 1n
};
function fromInt(value) {
  return {
    num: value,
    den: 1n
  };
}
function add(a, b) {
  return rational(a.num * b.den + b.num * a.den, a.den * b.den);
}
function sub(a, b) {
  return rational(a.num * b.den - b.num * a.den, a.den * b.den);
}
function mul(a, b) {
  return rational(a.num * b.num, a.den * b.den);
}
function div(a, b) {
  if (b.num === 0n) throw new NumberError("division by zero");
  return rational(a.num * b.den, a.den * b.num);
}
function neg(a) {
  return {
    num: -a.num,
    den: a.den
  };
}
function cmp(a, b) {
  const left = a.num * b.den;
  const right = b.num * a.den;
  return left < right ? -1 : left > right ? 1 : 0;
}
function sign(a) {
  return a.num < 0n ? -1 : a.num > 0n ? 1 : 0;
}
function equals(a, b) {
  return a.num === b.num && a.den === b.den;
}
function lt(a, b) {
  return cmp(a, b) < 0;
}
function lte(a, b) {
  return cmp(a, b) <= 0;
}
function midpoint(a, b) {
  return div(add(a, b), fromInt(2n));
}
function ceilDiv(num, den) {
  const quotient = num / den;
  return num % den !== 0n && num < 0n === den < 0n ? quotient + 1n : quotient;
}
function ceilLot(value, lot) {
  if (sign(lot) <= 0) throw new NumberError("the lot must be positive");
  const steps = div(value, lot);
  return mul(fromInt(ceilDiv(steps.num, steps.den)), lot);
}

// src/pwa.ts
var KernelError = class extends Error {
};
var NEG_INF = {
  value: null,
  closed: false
};
var POS_INF = {
  value: null,
  closed: false
};
function finite(value, closed) {
  return {
    value,
    closed
  };
}
function valueAt(piece, price) {
  return add(mul(piece.slope, price), piece.intercept);
}
function sameLine(a, b) {
  return equals(a.slope, b.slope) && equals(a.intercept, b.intercept);
}
function meets(hi, lo) {
  if (hi.value === null || lo.value === null) return false;
  if (!equals(hi.value, lo.value)) return false;
  return hi.closed !== lo.closed;
}
function fn(pieces) {
  if (pieces.length === 0) throw new KernelError("a function has at least one piece");
  const first = pieces[0];
  const last = pieces[pieces.length - 1];
  if (first.lo.value !== null) throw new KernelError("the pieces do not start at -infinity");
  if (last.hi.value !== null) throw new KernelError("the pieces do not reach +infinity");
  for (let index = 1; index < pieces.length; index += 1) {
    const before = pieces[index - 1];
    const here = pieces[index];
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
  const merged = [];
  for (const piece of pieces) {
    const previous = merged[merged.length - 1];
    if (previous !== void 0 && sameLine(previous, piece) && meets(previous.hi, piece.lo)) {
      merged[merged.length - 1] = {
        lo: previous.lo,
        hi: piece.hi,
        slope: piece.slope,
        intercept: piece.intercept
      };
      continue;
    }
    merged.push(piece);
  }
  return {
    pieces: merged
  };
}
function linear(quantity, baseline) {
  return fn([
    {
      lo: NEG_INF,
      hi: POS_INF,
      slope: quantity,
      intercept: neg(mul(quantity, baseline))
    }
  ]);
}
function cash(amount) {
  return fn([
    {
      lo: NEG_INF,
      hi: POS_INF,
      slope: ZERO,
      intercept: amount
    }
  ]);
}
function indicator(size, lo, hi) {
  if (lo.value !== null && hi.value !== null) {
    const order = cmp(lo.value, hi.value);
    if (order > 0) throw new KernelError("the interval runs backwards");
    if (order === 0 && !(lo.closed && hi.closed)) {
      throw new KernelError("an empty interval");
    }
  }
  const pieces = [];
  if (lo.value !== null) {
    pieces.push({
      lo: NEG_INF,
      hi: {
        value: lo.value,
        closed: !lo.closed
      },
      slope: ZERO,
      intercept: ZERO
    });
  }
  pieces.push({
    lo: lo.value === null ? NEG_INF : lo,
    hi: hi.value === null ? POS_INF : hi,
    slope: ZERO,
    intercept: size
  });
  if (hi.value !== null) {
    pieces.push({
      lo: {
        value: hi.value,
        closed: !hi.closed
      },
      hi: POS_INF,
      slope: ZERO,
      intercept: ZERO
    });
  }
  return fn(pieces);
}
function breakpoints(f) {
  const out = [];
  for (const piece of f.pieces) {
    if (piece.lo.value !== null) out.push(piece.lo.value);
  }
  return out;
}
function pieceAt(f, price) {
  for (const piece of f.pieces) {
    const afterLo = piece.lo.value === null || (piece.lo.closed ? lte(piece.lo.value, price) : lt(piece.lo.value, price));
    const beforeHi = piece.hi.value === null || (piece.hi.closed ? lte(price, piece.hi.value) : lt(price, piece.hi.value));
    if (afterLo && beforeHi) return piece;
  }
  throw new KernelError("no piece owns the price, which the representation rule forbids");
}
function evaluate(f, price) {
  return valueAt(pieceAt(f, price), price);
}
function sum(parts) {
  if (parts.length === 0) return cash(ZERO);
  const cuts = [];
  for (const part of parts) {
    for (const cut of breakpoints(part)) cuts.push(cut);
  }
  const sorted = uniqueSorted(cuts);
  const pieces = [];
  let lo = NEG_INF;
  for (const cut of sorted) {
    pieces.push(combined(parts, lo, {
      value: cut,
      closed: false
    }, midpointOf(lo, cut)));
    pieces.push(combined(parts, {
      value: cut,
      closed: true
    }, {
      value: cut,
      closed: true
    }, cut));
    lo = {
      value: cut,
      closed: false
    };
  }
  pieces.push(combined(parts, lo, POS_INF, aboveAll(sorted)));
  return fn(pieces);
}
function combined(parts, lo, hi, sample) {
  let slope = ZERO;
  let intercept = ZERO;
  for (const part of parts) {
    const piece = pieceAt(part, sample);
    slope = add(slope, piece.slope);
    intercept = add(intercept, piece.intercept);
  }
  return {
    lo,
    hi,
    slope,
    intercept
  };
}
function midpointOf(lo, cut) {
  if (lo.value === null) return sub(cut, ONE);
  return midpoint(lo.value, cut);
}
function aboveAll(sorted) {
  if (sorted.length === 0) return ZERO;
  return add(sorted[sorted.length - 1], ONE);
}
function uniqueSorted(values) {
  const out = [
    ...values
  ].sort((a, b) => cmp(a, b));
  const unique = [];
  for (const value of out) {
    const previous = unique[unique.length - 1];
    if (previous !== void 0 && equals(previous, value)) continue;
    unique.push(value);
  }
  return unique;
}
function window(f, lower, upper, cuts = []) {
  if (lt(upper, lower)) throw new KernelError("the window runs backwards");
  const marks = uniqueSorted([
    lower,
    upper,
    ...breakpoints(f).filter((cut) => lte(lower, cut) && lte(cut, upper)),
    ...cuts.filter((cut) => lte(lower, cut) && lte(cut, upper))
  ]);
  const out = [];
  for (let index = 0; index < marks.length; index += 1) {
    const mark = marks[index];
    out.push({
      lower: mark,
      lowerInclusive: true,
      upper: mark,
      upperInclusive: true
    });
    const next = marks[index + 1];
    if (next === void 0) continue;
    out.push({
      lower: mark,
      lowerInclusive: false,
      upper: next,
      upperInclusive: false
    });
  }
  return out.filter((piece) => !(equals(piece.lower, piece.upper) && !piece.lowerInclusive));
}
function profile(f, lower, upper) {
  const raw = [];
  for (const atom of window(f, lower, upper)) {
    const sample = equals(atom.lower, atom.upper) ? atom.lower : midpoint(atom.lower, atom.upper);
    const piece = pieceAt(f, sample);
    raw.push({
      lower: atom.lower,
      lowerInclusive: atom.lowerInclusive,
      upper: atom.upper,
      upperInclusive: atom.upperInclusive,
      slope: piece.slope,
      intercept: piece.intercept
    });
  }
  for (let index = 0; index < raw.length; index += 1) {
    const point = raw[index];
    if (!equals(point.lower, point.upper)) continue;
    const here = add(mul(point.slope, point.lower), point.intercept);
    for (const neighbour of [
      raw[index - 1],
      raw[index + 1]
    ]) {
      if (neighbour === void 0 || equals(neighbour.lower, neighbour.upper)) continue;
      const onTheirLine = add(mul(neighbour.slope, point.lower), neighbour.intercept);
      if (!equals(here, onTheirLine)) continue;
      raw[index] = {
        lower: point.lower,
        lowerInclusive: point.lowerInclusive,
        upper: point.upper,
        upperInclusive: point.upperInclusive,
        slope: neighbour.slope,
        intercept: neighbour.intercept
      };
      break;
    }
  }
  const out = [];
  for (const piece of raw) {
    const previous = out[out.length - 1];
    if (previous !== void 0 && onSameLine(previous, piece) && touches(previous, piece)) {
      out[out.length - 1] = {
        lower: previous.lower,
        lowerInclusive: previous.lowerInclusive,
        upper: piece.upper,
        upperInclusive: piece.upperInclusive,
        slope: previous.slope,
        intercept: previous.intercept
      };
      continue;
    }
    out.push(piece);
  }
  return out;
}
function onSameLine(a, b) {
  return equals(a.slope, b.slope) && equals(a.intercept, b.intercept);
}
function touches(a, b) {
  if (!equals(a.upper, b.lower)) return false;
  if (a.upperInclusive && b.lowerInclusive) return false;
  return true;
}
function infimum(f, lower, upper) {
  let best = null;
  const offer = (value, attained, at2) => {
    if (best === null || lt(value, best.value) || equals(value, best.value) && attained && !best.attained) {
      best = {
        value,
        attained,
        at: at2
      };
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
function below(f, threshold, lower, upper, cuts = []) {
  const parts = [];
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
    const crossing = div(sub(threshold, piece.intercept), piece.slope);
    if (lowBelow) {
      parts.push({
        lower: atom.lower,
        lowerInclusive: false,
        upper: crossing,
        upperInclusive: false
      });
    } else {
      parts.push({
        lower: crossing,
        lowerInclusive: false,
        upper: atom.upper,
        upperInclusive: false
      });
    }
  }
  return mergeIntervals(parts);
}
function mergeIntervals(parts) {
  const sorted = [
    ...parts
  ].sort((a, b) => {
    const order = cmp(a.lower, b.lower);
    if (order !== 0) return order;
    return a.lowerInclusive === b.lowerInclusive ? 0 : a.lowerInclusive ? -1 : 1;
  });
  const out = [];
  for (const part of sorted) {
    const previous = out[out.length - 1];
    if (previous !== void 0 && equals(previous.upper, part.lower) && (previous.upperInclusive || part.lowerInclusive)) {
      out[out.length - 1] = {
        lower: previous.lower,
        lowerInclusive: previous.lowerInclusive,
        upper: part.upper,
        upperInclusive: part.upperInclusive
      };
      continue;
    }
    out.push(part);
  }
  return out;
}
function bandInfimumFn(f, band) {
  if (sign(band) < 0) throw new KernelError("a negative band");
  if (sign(band) === 0) return f;
  const lines = [];
  const plateaus = [];
  const marks = [];
  for (const piece of f.pieces) {
    for (const delta of [
      neg(band),
      band
    ]) {
      lines.push({
        slope: piece.slope,
        intercept: add(piece.intercept, mul(piece.slope, delta))
      });
    }
    for (const bound of [
      piece.lo,
      piece.hi
    ]) {
      if (bound.value !== null) {
        marks.push(sub(bound.value, band), bound.value, add(bound.value, band));
        plateaus.push(add(mul(piece.slope, bound.value), piece.intercept));
      }
    }
  }
  for (let i = 0; i < lines.length; i += 1) {
    const a = lines[i];
    for (let j = i + 1; j < lines.length; j += 1) {
      const b = lines[j];
      if (!equals(a.slope, b.slope)) {
        marks.push(div(sub(b.intercept, a.intercept), sub(a.slope, b.slope)));
      }
    }
  }
  for (const line of lines) {
    if (sign(line.slope) !== 0) {
      for (const value of plateaus) {
        marks.push(div(sub(value, line.intercept), line.slope));
      }
    }
  }
  const cuts = uniqueSorted(marks);
  const at2 = (price) => infimum(f, sub(price, band), add(price, band)).value;
  return fromSamples(cuts, at2);
}
function fromSamples(cuts, at2) {
  const pieces = [];
  const edges = [
    ...cuts
  ];
  const spanLine = (lo, hi) => {
    const step = ONE;
    const left = lo === null ? sub(hi, add(step, step)) : hi === null ? add(lo, step) : midpoint(lo, hi);
    const right = lo === null ? sub(hi, step) : hi === null ? add(lo, add(step, step)) : midpoint(left, hi);
    const fl = at2(left);
    const fr = at2(right);
    const slope = equals(left, right) ? ZERO : div(sub(fr, fl), sub(right, left));
    return {
      slope,
      intercept: sub(fl, mul(slope, left))
    };
  };
  let previous = null;
  for (const edge of edges) {
    const line = spanLine(previous, edge);
    pieces.push({
      lo: {
        value: previous,
        closed: false
      },
      hi: {
        value: edge,
        closed: false
      },
      ...line
    });
    pieces.push({
      lo: {
        value: edge,
        closed: true
      },
      hi: {
        value: edge,
        closed: true
      },
      slope: ZERO,
      intercept: at2(edge)
    });
    previous = edge;
  }
  const tail = spanLine(previous, null);
  pieces.push({
    lo: {
      value: previous,
      closed: false
    },
    hi: {
      value: null,
      closed: false
    },
    ...tail
  });
  return fn(pieces);
}
function askCost(levels, size) {
  let remaining = size;
  let total = ZERO;
  for (const level of levels) {
    if (sign(remaining) <= 0) break;
    const fill = lte(remaining, level.size) ? remaining : level.size;
    total = add(total, mul(fill, level.price));
    remaining = sub(remaining, fill);
  }
  if (sign(remaining) > 0) return {
    total: null,
    covered: false
  };
  return {
    total,
    covered: true
  };
}
function walkLimit(levels, size) {
  let remaining = size;
  let limit = null;
  for (const level of levels) {
    if (sign(remaining) <= 0) break;
    const fill = lte(remaining, level.size) ? remaining : level.size;
    if (sign(fill) > 0) limit = level.price;
    remaining = sub(remaining, fill);
  }
  return sign(remaining) <= 0 ? limit : null;
}
function sizeWindow(base, unit, levels, floorPnl, lower, upper, lot) {
  const cuts = [
    ...breakpoints(base),
    ...breakpoints(unit)
  ];
  const atoms = window(base, lower, upper, cuts);
  const sites = [];
  for (const atom of atoms) {
    if (equals(atom.lower, atom.upper)) {
      sites.push({
        price: atom.lower,
        side: "at",
        alpha: evaluate(base, atom.lower),
        beta: evaluate(unit, atom.lower)
      });
      continue;
    }
    const sample = midpoint(atom.lower, atom.upper);
    const basePiece = pieceAt(base, sample);
    const unitPiece = pieceAt(unit, sample);
    sites.push({
      price: atom.lower,
      side: "above",
      alpha: valueAt(basePiece, atom.lower),
      beta: valueAt(unitPiece, atom.lower)
    });
    sites.push({
      price: atom.upper,
      side: "below",
      alpha: valueAt(basePiece, atom.upper),
      beta: valueAt(unitPiece, atom.upper)
    });
  }
  const depth = levels.reduce((total, level) => add(total, level.size), ZERO);
  let low = null;
  let high = null;
  const binding = [];
  let lowSite = null;
  let highSite = null;
  for (const site of sites) {
    const spans = feasibleSpan(site.alpha, site.beta, levels, floorPnl, depth);
    if (spans === null) {
      return {
        status: "empty",
        hasBounds: false,
        lowerBound: ZERO,
        upperBound: ZERO,
        smallest: null,
        largest: null,
        binding: [
          {
            price: site.price,
            side: site.side
          }
        ]
      };
    }
    if (sign(spans.lo) > 0 && (low === null || lt(low, spans.lo))) {
      low = spans.lo;
      lowSite = {
        price: site.price,
        side: site.side
      };
    }
    if (high === null || lt(spans.hi, high)) {
      high = spans.hi;
      highSite = {
        price: site.price,
        side: site.side
      };
    }
  }
  const ceilingBinds = high !== null && lt(high, depth);
  for (const site of [
    lowSite,
    ceilingBinds ? highSite : null
  ]) {
    if (site === null) continue;
    const already = binding.some((seen) => equals(seen.price, site.price) && seen.side === site.side);
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
      binding
    };
  }
  return {
    status: "empty",
    hasBounds: true,
    lowerBound: floorBound,
    upperBound: ceiling,
    smallest: null,
    largest: null,
    binding
  };
}
function feasibleSpan(alpha, beta, levels, floorPnl, depth) {
  const need = sub(floorPnl, alpha);
  const rungs = [];
  let filled = ZERO;
  let spent = ZERO;
  for (const level of levels) {
    if (sign(level.size) <= 0) continue;
    rungs.push({
      from: filled,
      to: add(filled, level.size),
      price: level.price,
      base: spent
    });
    spent = add(spent, mul(level.size, level.price));
    filled = add(filled, level.size);
  }
  if (rungs.length === 0) {
    return sign(need) <= 0 ? {
      lo: ZERO,
      hi: ZERO
    } : null;
  }
  let lo = null;
  let hi = null;
  for (const rung of rungs) {
    const slope = sub(beta, rung.price);
    const constant = sub(add(need, rung.base), mul(rung.price, rung.from));
    let segmentLo = rung.from;
    let segmentHi = rung.to;
    if (sign(slope) === 0) {
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
  return {
    lo,
    hi
  };
}
function ceilLotLocal(value, lot) {
  const steps = div(value, lot);
  const quotient = steps.num / steps.den;
  const rounded = steps.num % steps.den !== 0n && steps.num < 0n === steps.den < 0n ? quotient + 1n : quotient;
  return mul(fromInt(rounded), lot);
}
function floorLotLocal(value, lot) {
  const steps = div(value, lot);
  const quotient = steps.num / steps.den;
  const rounded = steps.num % steps.den !== 0n && steps.num < 0n !== steps.den < 0n ? quotient - 1n : quotient;
  return mul(fromInt(rounded), lot);
}

// src/synthesis.ts
function refuse(cls, at2, detail) {
  return {
    accepted: false,
    refusal: {
      class: cls,
      at: at2,
      detail
    }
  };
}
function paysOnBounds(on) {
  const lo = on["lower"] === void 0 ? NEG_INF : finite(parse2(String(on["lower"])), on["lower_inclusive"] === true);
  const hi = on["upper"] === void 0 ? POS_INF : finite(parse2(String(on["upper"])), on["upper_inclusive"] === true);
  return [
    lo,
    hi
  ];
}
function basePart(part) {
  const kind = String(part["kind"]);
  if (kind === "linear") {
    return linear(parse2(String(part["quantity"])), parse2(String(part["baseline"])));
  }
  if (kind === "indicator") {
    const [lo, hi] = paysOnBounds(objectAt(part, [
      "pays_on"
    ]));
    return indicator(parse2(String(part["size"])), lo, hi);
  }
  if (kind === "cash") {
    return cash(parse2(String(part["amount"])));
  }
  throw new Error(`unsupported base part: ${kind}`);
}
function rows(base, units, lower, upper) {
  const combined2 = sum([
    base,
    ...units
  ]);
  const SIDE_ORDER = {
    at: 0,
    below: 1,
    above: 2
  };
  const best = /* @__PURE__ */ new Map();
  const push = (price, side) => {
    const alpha = valueOf(base, price, side);
    const coefficients = units.map((unit) => valueOf(unit, price, side));
    const key = [
      format(alpha),
      ...coefficients.map(format)
    ].join("|");
    const held = best.get(key);
    if (held !== void 0 && SIDE_ORDER[held.side] <= SIDE_ORDER[side]) {
      return;
    }
    best.set(key, {
      price,
      side,
      alpha,
      coefficients
    });
  };
  for (const piece of profile(combined2, lower, upper)) {
    push(piece.lower, piece.lowerInclusive ? "at" : "above");
    if (!equals(piece.lower, piece.upper)) {
      push(piece.upper, piece.upperInclusive ? "at" : "below");
    }
  }
  return [
    ...best.values()
  ].sort((a, b) => {
    const byPrice = cmp(a.price, b.price);
    if (byPrice !== 0) return byPrice;
    return SIDE_ORDER[a.side] - SIDE_ORDER[b.side];
  });
}
function valueOf(f, price, side) {
  for (const piece of f.pieces) {
    const loBelow = piece.lo.value === null || lt(piece.lo.value, price);
    const hiAbove = piece.hi.value === null || lt(price, piece.hi.value);
    const owns = (loBelow || equals(piece.lo.value, price) && piece.lo.closed) && (hiAbove || equals(piece.hi.value, price) && piece.hi.closed);
    const leftOf = loBelow && piece.hi.value !== null && equals(piece.hi.value, price);
    const rightOf = hiAbove && piece.lo.value !== null && equals(piece.lo.value, price);
    const wanted = side === "at" ? owns : side === "below" ? leftOf : rightOf;
    if (wanted) return add(mul(piece.slope, price), piece.intercept);
  }
  for (const piece of f.pieces) {
    const afterLo = piece.lo.value === null || lt(piece.lo.value, price) || equals(piece.lo.value, price) && piece.lo.closed;
    const beforeHi = piece.hi.value === null || lt(price, piece.hi.value) || equals(piece.hi.value, price) && piece.hi.closed;
    if (afterLo && beforeHi) return add(mul(piece.slope, price), piece.intercept);
  }
  throw new Error(`no piece covers ${format(price)}`);
}
function verifySynthesis(document) {
  const request = objectAt(document, [
    "request"
  ]);
  const objective = objectAt(document, [
    "request",
    "objective"
  ]);
  const floor = parse2(String(objective["min_pnl"]));
  const domain = objectAt(document, [
    "request",
    "domain"
  ]);
  const lower = parse2(String(domain["lower"]));
  const upper = parse2(String(domain["upper"]));
  if (!lt(lower, upper)) {
    return refuse("OBJECTIVE_MISMATCH", "$.request.domain", "the domain is empty");
  }
  const baseParts = listAt(document, [
    "request",
    "base"
  ]);
  const base = baseParts.length === 0 ? cash(ZERO) : sum(baseParts.map((part) => basePart(part)));
  const candidates = listAt(document, [
    "request",
    "candidates"
  ]);
  const units = [];
  const prices = [];
  const ids = [];
  for (const raw of candidates) {
    const candidate = raw;
    const [lo, hi] = paysOnBounds(objectAt(raw, [
      "pays_on"
    ]));
    units.push(indicator(parse2("1"), lo, hi));
    prices.push(parse2(String(candidate["price"])));
    ids.push(String(candidate["id"]));
  }
  const derived = rows(base, units, lower, upper).map((row) => ({
    ...row,
    coefficients: row.coefficients.map((value, index) => sub(value, prices[index]))
  }));
  const status = stringAt(document, [
    "status"
  ]);
  if (status === "feasible") {
    return checkFeasible(document, derived, ids, prices, floor);
  }
  if (status === "infeasible") {
    return checkCertificate(document, derived, floor);
  }
  if (optional(document, [
    "sizes"
  ]) !== void 0) {
    return refuse("VERDICT_MISMATCH", "$.sizes", "a refused rounding reports sizes, which it did not establish");
  }
  return {
    accepted: true
  };
}
function checkFeasible(document, derived, ids, prices, floor) {
  const reported = listAt(document, [
    "sizes"
  ]);
  if (reported.length !== ids.length) {
    return refuse("SIZE_WINDOW", "$.sizes", `${reported.length} sizes for ${ids.length} candidates`);
  }
  const sizes = [];
  for (let index = 0; index < reported.length; index += 1) {
    const entry = reported[index];
    if (String(entry["candidate"]) !== ids[index]) {
      return refuse("SIZE_WINDOW", `$.sizes[${index}].candidate`, `names ${String(entry["candidate"])}, the request's candidate ${index} is ${ids[index]}`);
    }
    const size = parse2(String(entry["size"]));
    if (sign(size) < 0) {
      return refuse("SIZE_WINDOW", `$.sizes[${index}].size`, "a negative size");
    }
    sizes.push(size);
  }
  for (const row of derived) {
    let value = row.alpha;
    for (let index = 0; index < sizes.length; index += 1) {
      value = add(value, mul(row.coefficients[index], sizes[index]));
    }
    if (lt(value, floor)) {
      return refuse("SIZE_WINDOW", `$.sizes`, `at ${format(row.price)} (${row.side}) the structure is worth ${format(value)}, which misses the floor of ${format(floor)}`);
    }
  }
  const stated = optional(document, [
    "cost"
  ]);
  if (stated === void 0) {
    return refuse("COST_MISMATCH", "$.cost", "a feasible answer does not say what it costs");
  }
  let cost = ZERO;
  for (let index = 0; index < sizes.length; index += 1) {
    cost = add(cost, mul(prices[index], sizes[index]));
  }
  if (!equals(parse2(String(stated)), cost)) {
    return refuse("COST_MISMATCH", "$.cost", `states ${String(stated)}, the sizes at the request's prices cost ${format(cost)}`);
  }
  const lotText = optional(document, [
    "request",
    "lot"
  ]);
  const lot = lotText === void 0 ? parse2("1") : parse2(String(lotText));
  if (sign(lot) > 0) {
    for (let index = 0; index < sizes.length; index += 1) {
      const size = sizes[index];
      if (!equals(ceilLot(size, lot), size)) {
        return refuse("SIZE_WINDOW", `$.sizes[${index}].size`, `${format(size)} is not a whole multiple of the lot ${format(lot)}`);
      }
    }
  }
  return {
    accepted: true
  };
}
function checkCertificate(document, derived, floor) {
  const weights = listAt(document, [
    "certificate",
    "weights"
  ]);
  const index = /* @__PURE__ */ new Map();
  for (const row of derived) index.set(`${format(row.price)}|${row.side}`, row);
  const y = /* @__PURE__ */ new Map();
  for (let position = 0; position < weights.length; position += 1) {
    const entry = weights[position];
    const key = `${format(parse2(String(entry["price"])))}|${String(entry["side"])}`;
    const row = index.get(key);
    if (row === void 0) {
      return refuse("CERTIFICATE_WEIGHTS", `$.certificate.weights[${position}]`, `names the site ${key.replace("|", " ")}, which is not a row of this program`);
    }
    if (y.has(key)) {
      return refuse("CERTIFICATE_WEIGHTS", `$.certificate.weights[${position}]`, `names the site ${key.replace("|", " ")} twice`);
    }
    const weight = parse2(String(entry["weight"]));
    if (sign(weight) <= 0) {
      return refuse("CERTIFICATE_WEIGHTS", `$.certificate.weights[${position}].weight`, `${format(weight)} is not strictly positive`);
    }
    y.set(key, weight);
  }
  const columns = derived[0]?.coefficients.length ?? 0;
  for (let column = 0; column < columns; column += 1) {
    let total = ZERO;
    for (const row of derived) {
      const weight = y.get(`${format(row.price)}|${row.side}`);
      if (weight === void 0) continue;
      total = add(total, mul(weight, row.coefficients[column]));
    }
    if (sign(total) > 0) {
      return refuse("CERTIFICATE_WEIGHTS", "$.certificate.weights", `column ${column} of A^T y is ${format(total)}, which is positive, so the weights do not cancel the sizes`);
    }
  }
  let right = ZERO;
  for (const row of derived) {
    const weight = y.get(`${format(row.price)}|${row.side}`);
    if (weight === void 0) continue;
    right = add(right, mul(weight, sub(floor, row.alpha)));
  }
  if (sign(right) <= 0) {
    return refuse("CERTIFICATE_WEIGHTS", "$.certificate.weights", `b . y is ${format(right)}, which is not positive, so the rows are not contradictory`);
  }
  return {
    accepted: true
  };
}

// src/verify.ts
function exposureReduction(proposal) {
  const exposure = object(proposal["exposure"], "$proposal.exposure");
  if (text(exposure["kind"], "$proposal.exposure.kind") !== "isolated_perp") return [];
  const domain = object(proposal["domain"], "$proposal.domain");
  const baseline = number(object(proposal["baseline"], "$proposal.baseline")["price"], "$proposal.baseline.price");
  const low = lt(number(domain["lower"], "$proposal.domain.lower"), baseline) ? number(domain["lower"], "$proposal.domain.lower") : baseline;
  const high = lt(baseline, number(domain["upper"], "$proposal.domain.upper")) ? number(domain["upper"], "$proposal.domain.upper") : baseline;
  const price = number(exposure["liquidation_price"], "$proposal.exposure.liquidation_price");
  if (lt(price, low) || lt(high, price)) return [];
  return [
    {
      leg: "exposure",
      rule: "liquidated_in_path",
      tight: true
    }
  ];
}
var Refused = class extends Error {
  refusal;
  constructor(refusal) {
    super(`${refusal.class} at ${refusal.at}: ${refusal.detail}`);
    this.refusal = refusal;
  }
};
function refuse2(className, at2, detail) {
  throw new Refused({
    class: className,
    at: at2,
    detail
  });
}
async function verify(bundle, options = {}) {
  try {
    return {
      accepted: true,
      result: await establish(bundle, options)
    };
  } catch (error) {
    if (error instanceof Refused) return {
      accepted: false,
      refusal: error.refusal
    };
    return {
      accepted: false,
      refusal: {
        class: "ENGINE_DISAGREES",
        at: "$",
        detail: error instanceof Error ? error.message : String(error)
      }
    };
  }
}
async function establish(bundle, options) {
  const evidence = await readEvidence(bundle, options);
  const rebuilt = relower(evidence);
  await compareLowering(evidence, rebuilt);
  evaluateAndCompare(evidence, rebuilt);
  return evidence.result;
}
async function readEvidence(bundle, options) {
  const proposal = object(readDocument(bundle.proposal, "proposal"), "$proposal");
  const lowered = object(readDocument(bundle.lowered, "lowered"), "$lowered");
  const result = object(readDocument(bundle.result, "result"), "$result");
  if (options.schemas !== void 0) {
    for (const [name, value, schema] of [
      [
        "proposal",
        proposal,
        "proposal.schema.json"
      ],
      [
        "lowered",
        lowered,
        "ir.schema.json"
      ],
      [
        "result",
        result,
        "result.schema.json"
      ]
    ]) {
      const found = problems(value, schema, options.schemas);
      if (found.length > 0) {
        refuse2(classForSchemaProblem(found[0]), `$${name}`, found[0]);
      }
    }
  }
  const snapshots = /* @__PURE__ */ new Map();
  for (const [claimed, raw] of bundle.snapshots) {
    const actual = await sha256(raw);
    if (actual !== claimed) {
      refuse2("SNAPSHOT_BYTES", `$snapshots.${short(claimed)}`, `the bytes hash to ${short(actual)}`);
    }
    snapshots.set(actual, raw);
  }
  for (const cited of citedSnapshots(proposal)) {
    if (!snapshots.has(cited)) {
      refuse2("SNAPSHOT_NOT_CITED", `$proposal`, `${short(cited)} is cited but not supplied`);
    }
  }
  const entries = /* @__PURE__ */ new Map();
  for (const [family, raw] of bundle.registry) {
    const entry = object(readDocument(raw, `registry ${family}`), `$registry.${family}`);
    if (options.schemas !== void 0) {
      const found = problems(entry, "registry-entry.schema.json", options.schemas);
      if (found.length > 0) {
        refuse2("ENGINE_DISAGREES", `$registry.${family}`, `not a valid entry: ${found[0]}`);
      }
    }
    const withoutReview = {};
    for (const [key, value] of Object.entries(entry)) {
      if (key !== "review") withoutReview[key] = value;
    }
    const version = await digest(withoutReview);
    entries.set(family, {
      value: entry,
      version,
      reviewed: isReviewed(entry, version, options.allowlist ?? /* @__PURE__ */ new Set())
    });
  }
  for (const leg of list(proposal["legs"], "$proposal.legs")) {
    const item = object(leg, "$proposal.legs[]");
    const family = text(item["family"], "$proposal.legs[].family");
    const pin = text(item["semantics_version"], "$proposal.legs[].semantics_version");
    const entry = entries.get(family);
    if (entry === void 0) {
      refuse2("SEMANTICS_PIN", `$proposal.legs.${family}`, "no registry entry was supplied");
    }
    if (entry.version !== pin) {
      refuse2("SEMANTICS_PIN", `$proposal.legs.${family}`, `the pin is ${short(pin)}, the entry's semantics_version is ${short(entry.version)}`);
    }
    const status = text(entry.value["status"], `$registry.${family}.status`);
    if (status !== "computed") {
      refuse2("SEMANTICS_PIN", `$proposal.legs.${family}`, `the entry's status is ${status}, and only a computed family has a terminal payoff to check`);
    }
  }
  return {
    proposal,
    lowered,
    result,
    entries,
    snapshots
  };
}
function classForSchemaProblem(problem) {
  if (problem.includes(".reductions")) return "REDUCTION_UNDECLARED";
  if (problem.includes(".objective")) return "OBJECTIVE_MISMATCH";
  if (problem.includes(".profile") || problem.includes(".upper_profile")) return "PROFILE_COVERAGE";
  if (problem.includes("_intervals")) return "INTERVAL_MISMATCH";
  if (problem.includes(".size_windows")) return "SIZE_WINDOW";
  if (problem.includes(".witness")) return "WITNESS_INADMISSIBLE";
  if (problem.includes(".cost")) return "COST_MISMATCH";
  return "ENGINE_DISAGREES";
}
function isReviewed(entry, version, allowlist) {
  const review = entry["review"];
  if (typeof review !== "object" || review === null || Array.isArray(review)) return false;
  const state = review["state"];
  const claimed = review["digest"];
  if (state !== "reviewed") return false;
  if (claimed !== version) return false;
  return allowlist.has(version);
}
function relower(evidence) {
  const proposal = evidence.proposal;
  const domain = object(proposal["domain"], "$proposal.domain");
  const domainLower = number(domain["lower"], "$proposal.domain.lower");
  const domainUpper = number(domain["upper"], "$proposal.domain.upper");
  const exposure = object(proposal["exposure"], "$proposal.exposure");
  const quantity = number(exposure["quantity"], "$proposal.exposure.quantity");
  const valuationTime = text(proposal["objective_valuation_time"], "$proposal.objective_valuation_time");
  const baselineBlock = object(proposal["baseline"], "$proposal.baseline");
  const claimedBaseline = number(baselineBlock["price"], "$proposal.baseline.price");
  if (baselineBlock["kind"] === "analysis_time") {
    const source = object(baselineBlock["source"], "$proposal.baseline.source");
    const snapshot = text(source["snapshot"], "$proposal.baseline.source.snapshot");
    const coin = text(source["coin"], "$proposal.baseline.source.coin");
    const raw = evidence.snapshots.get(snapshot);
    if (raw === void 0) {
      refuse2("SNAPSHOT_NOT_CITED", "$proposal.baseline.source", `${short(snapshot)} was not supplied`);
    }
    const found = markPrice(parseVenue(raw), coin);
    if (!equals(found, claimedBaseline)) {
      refuse2("TERMS_MISMATCH", "$proposal.baseline.price", `the proposal says ${format(claimedBaseline)}, the snapshot says ${format(found)}`);
    }
  }
  const legs = [];
  const references = /* @__PURE__ */ new Map();
  const bandGroups = [];
  let premium = ZERO;
  for (const rawLeg of list(proposal["legs"], "$proposal.legs")) {
    const leg = object(rawLeg, "$proposal.legs[]");
    const id = text(leg["id"], "$proposal.legs[].id");
    const family = text(leg["family"], "$proposal.legs[].family");
    const side = text(leg["side"], "$proposal.legs[].side");
    const size = number(leg["size"], `$proposal.legs.${id}.size`);
    const terms = object(leg["terms"], `$proposal.legs.${id}.terms`);
    const entry = evidence.entries.get(family);
    if (entry === void 0) refuse2("SEMANTICS_PIN", `$proposal.legs.${id}`, "no entry");
    checkInstance(evidence, leg, terms, id, family);
    const parts = resolvePayoff(entry.value, side, terms, size, id);
    const acquisition = object(leg["acquisition"], `$proposal.legs.${id}.acquisition`);
    const { total, levels } = priceLeg(evidence, acquisition, size, id);
    premium = add(premium, total);
    const observationTime = text(terms["expiry"], `$proposal.legs.${id}.terms.expiry`);
    const rules = [];
    if (observationTime !== valuationTime) {
      rules.push({
        rule: "horizon_mismatch",
        tight: true
      });
    }
    if (!entry.reviewed) {
      rules.push({
        rule: "unreviewed_family",
        tight: false
      });
    }
    if (text(entry.value["settlement"], `$registry.${family}.settlement`) === "deployer") {
      rules.push({
        rule: "deployer_settled",
        tight: false
      });
    }
    const reduced = rules.length > 0;
    const rule = reduced ? rules[0].rule : null;
    const tight = rules.some((entry2) => entry2.tight);
    const instance = object(leg["instance"], `$proposal.legs.${id}.instance`);
    const coin = text(instance["coin"], `$proposal.legs.${id}.instance.coin`);
    legs.push({
      id,
      parts,
      size,
      premium: total,
      observationTime,
      reduced,
      reductionRule: rule,
      tight,
      levels,
      coin,
      family,
      version: entry.version,
      reductionRules: rules
    });
    references.set(id, legReference(entry.value, terms, id, family));
  }
  const objectiveReference = proposal["objective_reference"];
  if (typeof objectiveReference === "string") {
    const declared = /* @__PURE__ */ new Map();
    for (const raw of list(proposal["basis_bounds"] ?? [], "$proposal.basis_bounds")) {
      const item = object(raw, "$proposal.basis_bounds[]");
      const pair = list(item["between"], "$proposal.basis_bounds[].between");
      const left = text(pair[0], "$proposal.basis_bounds[].between[0]");
      const right = text(pair[1], "$proposal.basis_bounds[].between[1]");
      declared.set([
        left,
        right
      ].sort().join("\0"), number(item["bound"], "$proposal.basis_bounds[].bound"));
    }
    const groups = /* @__PURE__ */ new Map();
    for (const [id, reference] of references) {
      if (reference === objectiveReference) continue;
      const members = groups.get(reference) ?? [];
      members.push(id);
      groups.set(reference, members);
    }
    for (const reference of [
      ...groups.keys()
    ].sort()) {
      const members = groups.get(reference).slice().sort();
      const bound = declared.get([
        objectiveReference,
        reference
      ].sort().join("\0"));
      const head = members[0];
      const leg = legs.find((each) => each.id === head);
      leg.reductionRules.push({
        rule: bound === void 0 ? "basis_unbridged" : "basis_band",
        tight: false
      });
      bandGroups.push({
        leg: head,
        members,
        bound
      });
    }
  }
  return {
    legs,
    bandGroups,
    baseline: claimedBaseline,
    quantity,
    // The holding, valued as the verdict values it. Derived from the proposal's own exposure
    // and the path domain, never from what the result says about either.
    holding: exposureReduction(proposal).length > 0 ? cash(neg(number(exposure["isolated_margin"], "$proposal.exposure.isolated_margin"))) : linear(quantity, claimedBaseline),
    domainLower,
    domainUpper,
    otherCosts: number(proposal["other_costs"], "$proposal.other_costs"),
    premium,
    valuationTime
  };
}
function legReference(entry, terms, id, family) {
  const template = text(entry["reference"], `$registry.${family}.reference`);
  return template.replace(/\{([a-z_]+)\}/g, (_match, name) => {
    const value = terms[name];
    if (typeof value !== "string") {
      refuse2("SEMANTICS_PIN", `$proposal.legs.${id}.terms.${name}`, `the entry's reference names {${name}}, which the leg's terms do not carry as a single value`);
    }
    return value;
  });
}
function checkInstance(evidence, leg, terms, id, family) {
  const instance = leg["instance"];
  if (typeof instance !== "object" || instance === null || Array.isArray(instance)) return;
  const fields = instance;
  const catalogueDigest = text(fields["catalogue"], `$proposal.legs.${id}.instance.catalogue`);
  const outcome = text(fields["outcome"], `$proposal.legs.${id}.instance.outcome`);
  const coin = text(fields["coin"], `$proposal.legs.${id}.instance.coin`);
  const side = text(leg["side"], `$proposal.legs.${id}.side`);
  const raw = evidence.snapshots.get(catalogueDigest);
  if (raw === void 0) {
    refuse2("SNAPSHOT_NOT_CITED", `$proposal.legs.${id}.instance`, `${short(catalogueDigest)} was not supplied`);
  }
  const catalogue = parseVenue(raw);
  const offset = side === "yes" || side === "long" ? 0 : 1;
  const expectedCoin = `#${BigInt(outcome) * 10n + BigInt(offset)}`;
  if (coin !== expectedCoin) {
    refuse2("TERMS_MISMATCH", `$proposal.legs.${id}.instance.coin`, `outcome ${outcome} side ${side} encodes ${expectedCoin}, the leg says ${coin}`);
  }
  const described = describedTerms(catalogue, outcome, family);
  if (described === null) {
    refuse2("TERMS_MISMATCH", `$proposal.legs.${id}.instance.outcome`, `${outcome} is not in the catalogue`);
  }
  for (const [name, wanted] of Object.entries(described)) {
    const claimed = terms[name];
    if (claimed === void 0) continue;
    const claimedText = Array.isArray(claimed) ? claimed.map((item) => String(item)).join(",") : String(claimed);
    if (claimedText !== wanted) {
      refuse2("TERMS_MISMATCH", `$proposal.legs.${id}.terms.${name}`, `the catalogue says ${wanted}, the leg says ${claimedText}`);
    }
  }
}
function describedTerms(catalogue, outcome, family) {
  const collection = family.endsWith("priceBucket") ? "questions" : "outcomes";
  const items = at(catalogue, [
    collection
  ]);
  if (!Array.isArray(items)) return null;
  for (const item of items) {
    if (typeof item !== "object" || item === null || Array.isArray(item)) continue;
    const fields = item;
    const id = fields["outcome"] ?? fields["question"];
    const idText = typeof id === "string" ? id : numberText(id);
    const named = fields["namedOutcomes"];
    const matchesNamed = Array.isArray(named) && named.some((entry) => (typeof entry === "string" ? entry : numberText(entry)) === outcome);
    if (idText !== outcome && !matchesNamed) continue;
    const description = fields["description"];
    if (typeof description !== "string") return {};
    return parseDescription(description);
  }
  return null;
}
function numberText(value) {
  if (value === void 0) return null;
  if (typeof value === "object" && value !== null && "lexeme" in value) {
    return value.lexeme;
  }
  return null;
}
function parseDescription(description) {
  const out = {};
  for (const part of description.split("|")) {
    const colon = part.indexOf(":");
    if (colon < 0) continue;
    const key = part.slice(0, colon);
    const value = part.slice(colon + 1);
    if (key === "targetPrice") out["target_price"] = value;
    else if (key === "priceThresholds") out["thresholds"] = value;
    else if (key === "underlying") out["underlying"] = value;
    else if (key === "period") out["period"] = value;
  }
  return out;
}
function resolvePayoff(entry, side, terms, size, id) {
  const payoffs = list(entry["payoffs"], "$registry.payoffs");
  const index = typeof terms["index"] === "string" ? terms["index"] : null;
  for (const rawPayoff of payoffs) {
    const payoff = object(rawPayoff, "$registry.payoffs[]");
    const select = object(payoff["select"], "$registry.payoffs[].select");
    if (select["side"] !== side) continue;
    const wantedIndex = select["index"];
    if (wantedIndex !== void 0 && wantedIndex !== index) continue;
    const parts = [];
    for (const rawPays of list(payoff["pays"], "$registry.payoffs[].pays")) {
      const pays = object(rawPays, "$registry.payoffs[].pays[]");
      if (pays["primitive"] !== "indicator") {
        refuse2("ENGINE_DISAGREES", `$registry.payoffs`, `unsupported primitive ${String(pays["primitive"])}`);
      }
      const paysOn = object(pays["pays_on"], "$registry.payoffs[].pays[].pays_on");
      parts.push(indicator(size, boundFrom(paysOn, "lower", terms, id), boundFrom(paysOn, "upper", terms, id)));
    }
    if (parts.length === 0) {
      refuse2("ENGINE_DISAGREES", `$registry.payoffs`, `${id} resolves to no payoff`);
    }
    return parts;
  }
  refuse2("TERMS_MISMATCH", `$proposal.legs.${id}`, `the entry has no payoff for side ${side}`);
}
function boundFrom(paysOn, which, terms, id) {
  const reference = paysOn[which];
  if (reference === void 0) return which === "lower" ? NEG_INF : POS_INF;
  const closed = paysOn[`${which}_inclusive`];
  if (typeof closed !== "boolean") {
    refuse2("ENDPOINT_OWNERSHIP", `$registry.payoffs.${which}`, "a bound with no owner");
  }
  const spec = object(reference, `$registry.payoffs.${which}`);
  const termName = text(spec["term"], `$registry.payoffs.${which}.term`);
  const raw = terms[termName];
  const positionText = spec["at"];
  if (typeof positionText === "string") {
    if (!Array.isArray(raw)) {
      refuse2("TERMS_MISMATCH", `$proposal.legs.${id}.terms.${termName}`, "expected a list");
    }
    const item = raw[digitsOf(positionText)];
    if (typeof item !== "string") {
      refuse2("TERMS_MISMATCH", `$proposal.legs.${id}.terms.${termName}`, `no item at ${positionText}`);
    }
    return finite(parse2(item), closed);
  }
  if (typeof raw !== "string") {
    refuse2("TERMS_MISMATCH", `$proposal.legs.${id}.terms.${termName}`, "expected a number as text");
  }
  return finite(parse2(raw), closed);
}
function priceLeg(evidence, acquisition, size, id) {
  const kind = acquisition["kind"];
  if (kind === "fixed") {
    const price = number(acquisition["price"], `$proposal.legs.${id}.acquisition.price`);
    return {
      total: mul(price, size),
      levels: []
    };
  }
  const snapshot = text(acquisition["snapshot"], `$proposal.legs.${id}.acquisition.snapshot`);
  const raw = evidence.snapshots.get(snapshot);
  if (raw === void 0) {
    refuse2("SNAPSHOT_NOT_CITED", `$proposal.legs.${id}.acquisition`, `${short(snapshot)} was not supplied`);
  }
  const levels = asksOf(parseVenue(raw), id);
  const walked = askCost(levels, size);
  if (!walked.covered || walked.total === null) {
    refuse2("COST_MISMATCH", `$proposal.legs.${id}.acquisition`, "the displayed depth cannot fill the size");
  }
  return {
    total: walked.total,
    levels
  };
}
function asksOf(book, id) {
  const sides = at(book, [
    "levels"
  ]);
  if (!Array.isArray(sides) || sides.length !== 2 || !Array.isArray(sides[1])) {
    refuse2("SNAPSHOT_NOT_CITED", `$proposal.legs.${id}.acquisition.snapshot`, "the cited snapshot is not an l2Book response, so this leg cites no book");
  }
  const rows2 = sides[1];
  return rows2.map((row, position) => ({
    price: parse2(quantityText(row, [
      "px"
    ])),
    size: parse2(quantityText(row, [
      "sz"
    ]))
  }));
}
function markPrice(contexts, coin) {
  if (!Array.isArray(contexts) || contexts.length !== 2) {
    refuse2("TERMS_MISMATCH", "$proposal.baseline.source", "not a contexts response");
  }
  const universe = at(contexts[0], [
    "universe"
  ]);
  const states = contexts[1];
  if (!Array.isArray(universe) || !Array.isArray(states)) {
    refuse2("TERMS_MISMATCH", "$proposal.baseline.source", "not a contexts response");
  }
  for (let index = 0; index < universe.length; index += 1) {
    const asset = universe[index];
    if (at(asset, [
      "name"
    ]) !== coin) continue;
    const state = states[index];
    if (state === void 0) break;
    return parse2(quantityText(state, [
      "markPx"
    ]));
  }
  refuse2("TERMS_MISMATCH", "$proposal.baseline.source", `${coin} is not in the snapshot`);
}
async function compareLowering(evidence, rebuilt) {
  const lowered = evidence.lowered;
  const cited = new Set(citedSnapshots(evidence.proposal));
  for (const rawLeg of list(lowered["legs"], "$lowered.legs")) {
    const leg = object(rawLeg, "$lowered.legs[]");
    const premium = leg["premium"];
    if (typeof premium !== "object" || premium === null || Array.isArray(premium)) continue;
    const snapshot = premium["snapshot"];
    if (typeof snapshot !== "string") continue;
    if (!cited.has(snapshot)) {
      refuse2("SNAPSHOT_NOT_CITED", `$lowered.legs.${String(leg["id"])}.premium.snapshot`, `${short(snapshot)} priced this leg, but the proposal cites no such snapshot`);
    }
  }
  compareObjective(evidence, rebuilt);
  const claimedLegs = list(lowered["legs"], "$lowered.legs");
  if (claimedLegs.length !== rebuilt.legs.length) {
    refuse2("ENGINE_DISAGREES", "$lowered.legs", `the lowered proposal has ${claimedLegs.length} legs, the proposal has ${rebuilt.legs.length}`);
  }
  for (let index = 0; index < claimedLegs.length; index += 1) {
    const claimed2 = object(claimedLegs[index], "$lowered.legs[]");
    const mine = rebuilt.legs[index];
    if (claimed2["id"] !== mine.id) {
      refuse2("ENGINE_DISAGREES", `$lowered.legs[${index}].id`, `expected ${mine.id}`);
    }
    const premium = object(claimed2["premium"], `$lowered.legs.${mine.id}.premium`);
    const claimedTotal = number(premium["total"], `$lowered.legs.${mine.id}.premium.total`);
    if (!equals(claimedTotal, mine.premium)) {
      refuse2("COST_MISMATCH", `$lowered.legs.${mine.id}.premium.total`, `the walk gives ${format(mine.premium)}, the lowered proposal says ${format(claimedTotal)}`);
    }
  }
  const irDigest = await digest(lowered);
  const claimed = evidence.result["ir_digest"];
  if (claimed !== irDigest) {
    refuse2("ENGINE_DISAGREES", "$result.ir_digest", `the result cites ${short(String(claimed))}, the lowered proposal digests to ${short(irDigest)}`);
  }
}
function evaluateAndCompare(evidence, rebuilt) {
  const result = evidence.result;
  const lowerParts = [
    rebuilt.holding,
    cash(neg(add(rebuilt.premium, rebuilt.otherCosts)))
  ];
  const upperParts = [
    ...lowerParts
  ];
  let upperCeiling = ZERO;
  const bandedLegs = /* @__PURE__ */ new Set();
  for (const group of rebuilt.bandGroups) {
    if (group.bound === void 0) continue;
    for (const member of group.members) bandedLegs.add(member);
    const parts = [];
    for (const leg of rebuilt.legs) {
      if (group.members.includes(leg.id)) parts.push(...leg.parts);
    }
    lowerParts.push(bandInfimumFn(sum(parts), group.bound));
    upperParts.push(...parts);
  }
  for (const leg of rebuilt.legs) {
    if (bandedLegs.has(leg.id)) continue;
    if (leg.reduced || leg.reductionRules.length > 0) {
      upperCeiling = add(upperCeiling, leg.size);
      continue;
    }
    for (const part of leg.parts) lowerParts.push(part);
    for (const part of leg.parts) upperParts.push(part);
  }
  const lowerFn = sum(lowerParts);
  const upperFn = sum([
    ...upperParts,
    cash(upperCeiling)
  ]);
  compareReductions(evidence, rebuilt);
  const mine = profile(lowerFn, rebuilt.domainLower, rebuilt.domainUpper);
  compareProfile(mine, list(result["profile"], "$result.profile"), "$result.profile");
  compareWorstCase(evidence, rebuilt, lowerFn);
  compareVerdict(evidence, rebuilt, lowerFn, upperFn);
  compareCost(evidence, rebuilt, lowerFn);
  compareSizeWindows(evidence, rebuilt);
  compareWitnesses(evidence, rebuilt, upperFn);
  compareCertificates(evidence);
  compareEnvelope(evidence, rebuilt);
}
function compareEnvelope(evidence, rebuilt) {
  const result = evidence.result;
  const readiness = result["execution_readiness"];
  const raw = result["order_envelope"];
  const present = raw !== void 0;
  if (present !== (readiness === "envelope_issued")) {
    refuse2("ENVELOPE_MISMATCH", "$result.execution_readiness", `readiness is ${String(readiness)} and an envelope is ${present ? "present" : "absent"}`);
  }
  if (!present) return;
  const envelope = object(raw, "$result.order_envelope");
  const verdict = result["model_result"];
  if (verdict !== "passes") {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope", `an envelope on a ${String(verdict)}`);
  }
  if (rebuilt.legs.length !== 1) {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope", `the proposal has ${rebuilt.legs.length} legs; an envelope describes one order`);
  }
  const leg = rebuilt.legs[0];
  if (leg.levels.length === 0) {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope", "the leg is not priced on a book");
  }
  if (envelope["coin"] !== leg.coin) {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope.coin", `the envelope names ${String(envelope["coin"])}, the proposal names ${leg.coin}`);
  }
  if (envelope["side"] !== "buy") {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope.side", `side is ${String(envelope["side"])}`);
  }
  if (envelope["time_in_force"] !== "Ioc") {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope.time_in_force", `time in force is ${String(envelope["time_in_force"])}`);
  }
  const size = number(envelope["size"], "$result.order_envelope.size");
  if (!equals(size, leg.size)) {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope.size", `the envelope buys ${format(size)}, the proposal asks for ${format(leg.size)}`);
  }
  const limit = walkLimit(leg.levels, leg.size);
  if (limit === null) {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope.limit_price", "the depth does not fill the size");
  }
  const claimedLimit = number(envelope["limit_price"], "$result.order_envelope.limit_price");
  if (!equals(claimedLimit, limit)) {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope.limit_price", `the envelope says ${format(claimedLimit)}, the walk ends in ${format(limit)}`);
  }
  const walked = askCost(leg.levels, leg.size);
  if (!walked.covered || walked.total === null) {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope.max_cost", "the depth does not fill the size");
  }
  const claimedCost = number(envelope["max_cost"], "$result.order_envelope.max_cost");
  if (!equals(claimedCost, walked.total)) {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope.max_cost", `the envelope says ${format(claimedCost)}, the walk costs ${format(walked.total)}`);
  }
  const stated = result["input_digest"];
  if (stated === void 0) {
    refuse2("ENVELOPE_MISMATCH", "$result.input_digest", "an envelope was issued for a result that does not name its input digest");
  }
  if (envelope["input_digest"] !== stated) {
    refuse2("ENVELOPE_MISMATCH", "$result.order_envelope.input_digest", `the envelope belongs to ${short(String(envelope["input_digest"]))}, the result is ${short(String(stated))}`);
  }
}
function compareProfile(mine, claimed, at2) {
  if (claimed.length !== mine.length) {
    refuse2("PROFILE_COVERAGE", at2, `the result states ${claimed.length} pieces, the proposal gives ${mine.length}`);
  }
  for (let index = 0; index < mine.length; index += 1) {
    const piece = object(claimed[index], `${at2}[${index}]`);
    const want = mine[index];
    const where = `${at2}[${index}]`;
    if (!equals(number(piece["lower"], `${where}.lower`), want.lower)) {
      refuse2("PROFILE_COVERAGE", where, `lower is ${String(piece["lower"])}, expected ${format(want.lower)}`);
    }
    if (!equals(number(piece["upper"], `${where}.upper`), want.upper)) {
      refuse2("PROFILE_COVERAGE", where, `upper is ${String(piece["upper"])}, expected ${format(want.upper)}`);
    }
    if (piece["lower_inclusive"] !== want.lowerInclusive || piece["upper_inclusive"] !== want.upperInclusive) {
      refuse2("ENDPOINT_OWNERSHIP", where, `ownership is [${String(piece["lower_inclusive"])}, ${String(piece["upper_inclusive"])}], expected [${want.lowerInclusive}, ${want.upperInclusive}]`);
    }
    if (!equals(number(piece["slope"], `${where}.slope`), want.slope)) {
      refuse2("PROFILE_VALUE", where, `slope is ${String(piece["slope"])}, expected ${format(want.slope)}`);
    }
    if (!equals(number(piece["intercept"], `${where}.intercept`), want.intercept)) {
      refuse2("PROFILE_VALUE", where, `intercept is ${String(piece["intercept"])}, expected ${format(want.intercept)}`);
    }
  }
}
function compareObjective(evidence, rebuilt) {
  const proposalObjective = canonical(evidence.proposal["objective"]);
  const loweredObjective = canonical(evidence.lowered["objective"]);
  if (new TextDecoder().decode(proposalObjective) !== new TextDecoder().decode(loweredObjective)) {
    refuse2("OBJECTIVE_MISMATCH", "$lowered.objective", "the lowered proposal states a different objective from the proposal");
  }
  const claimedTime = evidence.result["objective_valuation_time"];
  if (claimedTime !== rebuilt.valuationTime) {
    refuse2("OBJECTIVE_MISMATCH", "$result.objective_valuation_time", `the result says ${String(claimedTime)}, the proposal says ${rebuilt.valuationTime}`);
  }
}
function clausesOf(evidence) {
  return list(evidence.proposal["objective"], "$proposal.objective").map((raw) => {
    const clause = object(raw, "$proposal.objective[]");
    const on = clause["on"];
    return {
      id: text(clause["id"], "$proposal.objective[].id"),
      minPnl: number(clause["min_pnl"], "$proposal.objective[].min_pnl"),
      on: on === void 0 ? null : intervalOf(object(on, "$proposal.objective[].on"))
    };
  });
}
function intervalOf(raw) {
  return {
    lower: number(raw["lower"], "$.lower"),
    lowerInclusive: raw["lower_inclusive"] === true,
    upper: number(raw["upper"], "$.upper"),
    upperInclusive: raw["upper_inclusive"] === true
  };
}
function compareVerdict(evidence, rebuilt, lowerFn, upperFn) {
  const clauses = clausesOf(evidence);
  const anyLoose = rebuilt.legs.some((leg) => leg.reductionRules.some((each) => !each.tight));
  let broken = false;
  for (const clause of clauses) {
    const lower = clause.on === null ? rebuilt.domainLower : clause.on.lower;
    const upper = clause.on === null ? rebuilt.domainUpper : clause.on.upper;
    if (below(lowerFn, clause.minPnl, lower, upper).length > 0) broken = true;
  }
  let expected;
  if (!broken) expected = "passes";
  else expected = anyLoose ? "needs_review" : "fails";
  const claimed = evidence.result["model_result"];
  if (claimed !== expected) {
    refuse2("VERDICT_MISMATCH", "$result.model_result", `the result says ${String(claimed)}, the evidence gives ${expected}`);
  }
  void upperFn;
  compareIntervals(evidence, rebuilt, lowerFn, clauses);
}
function compareIntervals(evidence, rebuilt, lowerFn, clauses) {
  const stated = [
    ...list(evidence.result["failing_intervals"] ?? [], "$result.failing_intervals"),
    ...list(evidence.result["undecided_intervals"] ?? [], "$result.undecided_intervals")
  ];
  const mine = [];
  for (const clause of clauses) {
    const lower = clause.on === null ? rebuilt.domainLower : clause.on.lower;
    const upper = clause.on === null ? rebuilt.domainUpper : clause.on.upper;
    for (const interval of below(lowerFn, clause.minPnl, lower, upper)) mine.push(interval);
  }
  if (stated.length !== mine.length) {
    refuse2("INTERVAL_MISMATCH", "$result.failing_intervals", `the result states ${stated.length} intervals, the evidence gives ${mine.length}`);
  }
  for (let index = 0; index < mine.length; index += 1) {
    const claimed = object(stated[index], `$result.intervals[${index}]`);
    const want = mine[index];
    const where = `$result.intervals[${index}]`;
    if (!equals(number(claimed["lower"], `${where}.lower`), want.lower) || !equals(number(claimed["upper"], `${where}.upper`), want.upper)) {
      refuse2("INTERVAL_MISMATCH", where, `the result says [${String(claimed["lower"])}, ${String(claimed["upper"])}], the evidence gives [${format(want.lower)}, ${format(want.upper)}]`);
    }
    if (claimed["lower_inclusive"] !== want.lowerInclusive || claimed["upper_inclusive"] !== want.upperInclusive) {
      refuse2("INTERVAL_MISMATCH", where, "the interval's endpoint ownership differs");
    }
  }
}
function compareReductions(evidence, rebuilt) {
  const stated = list(evidence.result["reductions"] ?? [], "$result.reductions");
  const mine = rebuilt.legs.filter((leg) => leg.reductionRules.length > 0);
  const declaredFor = new Set(stated.map((entry) => text(object(entry, "$result.reductions[]")["leg"], "$result.reductions[].leg")));
  for (const leg of mine) {
    if (leg.reductionRule === "unreviewed_family" && !declaredFor.has(leg.id)) {
      refuse2("REDUCTION_UNDECLARED", "$result.reductions", `leg ${leg.id} rests on ${leg.family} at version ${leg.version}, which is not in this checker's allowlist, so this checker reduces it under unreviewed_family; the result declares no reduction for that leg`);
    }
  }
  const expected = [
    ...exposureReduction(evidence.proposal),
    ...mine.flatMap((leg) => leg.reductionRules.map((each) => ({
      leg: leg.id,
      rule: each.rule,
      tight: each.tight
    })))
  ];
  if (stated.length !== expected.length) {
    refuse2("REDUCTION_UNDECLARED", "$result.reductions", `the result declares ${stated.length} reductions, the evidence requires ${expected.length}`);
  }
  for (let index = 0; index < expected.length; index += 1) {
    const claimed = object(stated[index], `$result.reductions[${index}]`);
    const want = expected[index];
    const where = `$result.reductions[${index}]`;
    if (claimed["leg"] !== want.leg) {
      refuse2("REDUCTION_UNDECLARED", where, `expected the reduction on ${want.leg}`);
    }
    if (claimed["rule"] !== want.rule) {
      refuse2("REDUCTION_UNSOUND", where, `expected the rule ${want.rule}`);
    }
    if (claimed["tight"] !== want.tight) {
      refuse2("REDUCTION_UNSOUND", where, `the result calls ${want.rule} ${claimed["tight"] === true ? "tight" : "loose"}; it is not`);
    }
    if (typeof claimed["reason_code"] !== "string" || claimed["reason_code"] === "") {
      refuse2("REDUCTION_UNDECLARED", where, "the reduction states no reason code");
    }
  }
}
function compareWorstCase(evidence, rebuilt, lowerFn) {
  const stated = object(evidence.result["worst_case"], "$result.worst_case");
  const mine = infimum(lowerFn, rebuilt.domainLower, rebuilt.domainUpper);
  const claimedPnl = number(stated["pnl"], "$result.worst_case.pnl");
  if (!equals(claimedPnl, mine.value)) {
    refuse2("PROFILE_VALUE", "$result.worst_case.pnl", `the result says ${format(claimedPnl)}, the payoff's infimum is ${format(mine.value)}`);
  }
  const claimedAttained = stated["attained"];
  if (typeof claimedAttained !== "boolean") {
    refuse2("ENGINE_DISAGREES", "$result.worst_case.attained", "expected a boolean");
  }
  if (claimedAttained !== mine.attained) {
    refuse2("PROFILE_VALUE", "$result.worst_case.attained", `the result says ${String(claimedAttained)}, the infimum is ${mine.attained ? "attained" : "only approached"}`);
  }
  const claimedPrice = number(stated["price"], "$result.worst_case.price");
  if (lt(claimedPrice, rebuilt.domainLower) || lt(rebuilt.domainUpper, claimedPrice)) {
    refuse2("PROFILE_VALUE", "$result.worst_case.price", `${format(claimedPrice)} is outside the domain`);
  }
  if (claimedAttained === true) {
    const there = evaluate(lowerFn, claimedPrice);
    if (!equals(there, mine.value)) {
      refuse2("PROFILE_VALUE", "$result.worst_case.price", `the payoff at ${format(claimedPrice)} is ${format(there)}, not the claimed ${format(mine.value)}`);
    }
  }
}
function compareCost(evidence, rebuilt, lowerFn) {
  const cost = object(evidence.result["cost"], "$result.cost");
  const claimedPremium = number(cost["premium"], "$result.cost.premium");
  if (!equals(claimedPremium, rebuilt.premium)) {
    refuse2("COST_MISMATCH", "$result.cost.premium", `the result says ${format(claimedPremium)}, the walks give ${format(rebuilt.premium)}`);
  }
  const claimedOther = number(cost["other_costs"], "$result.cost.other_costs");
  if (!equals(claimedOther, rebuilt.otherCosts)) {
    refuse2("COST_MISMATCH", "$result.cost.other_costs", "the result states different other costs");
  }
  const mine = below(lowerFn, ZERO, rebuilt.domainLower, rebuilt.domainUpper);
  const claimedBreakevens = list(cost["breakevens"] ?? [], "$result.cost.breakevens");
  const crossings = /* @__PURE__ */ new Set();
  for (const interval of mine) {
    if (!equals(interval.upper, rebuilt.domainUpper)) crossings.add(format(interval.upper));
    if (!equals(interval.lower, rebuilt.domainLower)) crossings.add(format(interval.lower));
  }
  for (const claimed of claimedBreakevens) {
    if (typeof claimed !== "string" || !crossings.has(claimed)) {
      refuse2("COST_MISMATCH", "$result.cost.breakevens", `${String(claimed)} is not where the payoff crosses zero`);
    }
  }
}
function compareSizeWindows(evidence, rebuilt) {
  const stated = evidence.result["size_windows"];
  if (stated === void 0) return;
  const windows = list(stated, "$result.size_windows");
  const clauses = clausesOf(evidence);
  if (clauses.length === 0) return;
  const floorPnl = clauses[0].minPnl;
  for (let index = 0; index < windows.length; index += 1) {
    const claimed = object(windows[index], `$result.size_windows[${index}]`);
    const legId = text(claimed["leg"], `$result.size_windows[${index}].leg`);
    const leg = rebuilt.legs.find((candidate) => candidate.id === legId);
    if (leg === void 0) {
      refuse2("SIZE_WINDOW", `$result.size_windows[${index}]`, `no leg named ${legId}`);
    }
    const baseParts = [
      rebuilt.holding
    ];
    for (const other of rebuilt.legs) {
      if (other.id === legId || other.reduced) continue;
      for (const part of other.parts) baseParts.push(part);
    }
    const unitParts = leg.parts.map((_, position) => unitOf(evidence, leg, position));
    const window2 = sizeWindow(sum(baseParts), sum(unitParts), leg.levels, floorPnl, rebuilt.domainLower, rebuilt.domainUpper, parse2("1"));
    const claimedSmallest = claimed["smallest"];
    if (typeof claimedSmallest === "string" && window2.smallest !== null) {
      if (!equals(parse2(claimedSmallest), window2.smallest)) {
        refuse2("SIZE_WINDOW", `$result.size_windows[${index}].smallest`, `the result says ${claimedSmallest}, the evidence gives ${format(window2.smallest)}`);
      }
    }
  }
}
function unitOf(evidence, leg, position) {
  const scaled = leg.parts[position];
  const unitSize = parse2("1");
  const pieces = scaled.pieces.map((piece) => ({
    lo: piece.lo,
    hi: piece.hi,
    slope: piece.slope,
    intercept: sign(piece.intercept) === 0 ? piece.intercept : equals(piece.intercept, leg.size) ? unitSize : piece.intercept
  }));
  return {
    pieces
  };
}
function compareWitnesses(evidence, rebuilt, upperFn) {
  const clauses = clausesOf(evidence);
  const byId = new Map(clauses.map((clause) => [
    clause.id,
    clause
  ]));
  const looseLegs = new Set(rebuilt.legs.filter((leg) => leg.reduced && !leg.tight).map((leg) => leg.id));
  const reducedRules = new Map(rebuilt.legs.filter((leg) => leg.reduced).map((leg) => [
    leg.id,
    String(leg.reductionRule)
  ]));
  for (const reduction of exposureReduction(evidence.proposal)) {
    reducedRules.set(reduction.leg, reduction.rule);
  }
  for (const [field, className] of [
    [
      "failing_intervals",
      "WITNESS_INADMISSIBLE"
    ],
    [
      "undecided_intervals",
      "WITNESS_INADMISSIBLE"
    ]
  ]) {
    for (const raw of list(evidence.result[field] ?? [], `$result.${field}`)) {
      const interval = object(raw, `$result.${field}[]`);
      const claimed = interval["witness"];
      if (claimed === void 0) continue;
      const found = object(claimed, `$result.${field}[].witness`);
      const price = number(found["price"], `$result.${field}[].witness.price`);
      const clauseId = interval["clause"];
      const clause = typeof clauseId === "string" ? byId.get(clauseId) : void 0;
      if (clause === void 0) {
        refuse2(className, `$result.${field}[]`, `the witness names no clause this proposal has`);
      }
      if (field === "failing_intervals" && looseLegs.size > 0) {
        const best = evaluateOn(upperFn, price);
        if (!lt(best, clause.minPnl)) {
          refuse2(className, `$result.${field}[].witness`, `at ${format(price)} the upper profile gives ${format(best)}, which meets ${format(clause.minPnl)}`);
        }
      }
      for (const rawState of list(found["adverse_states"] ?? [], `$result.${field}[].witness.adverse_states`)) {
        const state = object(rawState, `$result.${field}[].witness.adverse_states[]`);
        const legId = text(state["leg"], `$...adverse_states[].leg`);
        const reducedBy = reducedRules.get(legId);
        if (reducedBy === void 0) {
          refuse2(className, `$result.${field}[].witness.adverse_states`, `${legId} was not reduced, so no rule can produce an adverse state for it`);
        }
        if (state["rule"] !== reducedBy) {
          refuse2(className, `$result.${field}[].witness.adverse_states`, `${legId} was reduced by ${reducedBy}, not ${String(state["rule"])}`);
        }
      }
    }
  }
}
function evaluateOn(fn2, price) {
  for (const piece of fn2.pieces) {
    const afterLo = piece.lo.value === null || (piece.lo.closed ? lte(piece.lo.value, price) : lt(piece.lo.value, price));
    const beforeHi = piece.hi.value === null || (piece.hi.closed ? lte(price, piece.hi.value) : lt(price, piece.hi.value));
    if (afterLo && beforeHi) return add(mul(piece.slope, price), piece.intercept);
  }
  refuse2("WITNESS_INADMISSIBLE", "$result.witness.price", "the price is outside the profile");
}
function compareCertificates(evidence) {
  for (const rawWindow of list(evidence.result["size_windows"] ?? [], "$result.size_windows")) {
    const window2 = object(rawWindow, "$result.size_windows[]");
    const certificate = window2["certificate"];
    if (certificate === void 0) continue;
    const found = object(certificate, "$result.size_windows[].certificate");
    const leg = String(window2["leg"] ?? "");
    const where = `$result.size_windows.${leg}.certificate.weights`;
    for (const raw of list(found["weights"] ?? [], where)) {
      const weight = number(raw, where);
      if (sign(weight) < 0) {
        refuse2("CERTIFICATE_WEIGHTS", where, `${format(weight)} is negative; a negative weight reverses the inequality it multiplies`);
      }
    }
  }
}
function readDocument(raw, what) {
  try {
    return parse(raw);
  } catch (error) {
    refuse2("ENGINE_DISAGREES", `$${what}`, error instanceof Error ? error.message : String(error));
  }
}
function object(value, at2) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    refuse2("ENGINE_DISAGREES", at2, "expected an object");
  }
  return value;
}
function list(value, at2) {
  if (!Array.isArray(value)) refuse2("ENGINE_DISAGREES", at2, "expected an array");
  return value;
}
function text(value, at2) {
  if (typeof value !== "string") refuse2("ENGINE_DISAGREES", at2, "expected a string");
  return value;
}
function number(value, at2) {
  if (typeof value !== "string") refuse2("ENGINE_DISAGREES", at2, "expected a number as text");
  try {
    return parse2(value);
  } catch {
    refuse2("ENGINE_DISAGREES", at2, `${value} is not in the number grammar`);
  }
}
function citedSnapshots(proposal) {
  const out = [];
  const baseline = proposal["baseline"];
  if (typeof baseline === "object" && baseline !== null && !Array.isArray(baseline)) {
    const source = baseline["source"];
    if (typeof source === "object" && source !== null && !Array.isArray(source)) {
      const snapshot = source["snapshot"];
      if (typeof snapshot === "string") out.push(snapshot);
    }
  }
  const legs = proposal["legs"];
  if (Array.isArray(legs)) {
    for (const rawLeg of legs) {
      if (typeof rawLeg !== "object" || rawLeg === null || Array.isArray(rawLeg)) continue;
      const leg = rawLeg;
      const instance = leg["instance"];
      if (typeof instance === "object" && instance !== null && !Array.isArray(instance)) {
        const catalogue = instance["catalogue"];
        if (typeof catalogue === "string") out.push(catalogue);
      }
      const acquisition = leg["acquisition"];
      if (typeof acquisition === "object" && acquisition !== null && !Array.isArray(acquisition)) {
        const snapshot = acquisition["snapshot"];
        if (typeof snapshot === "string") out.push(snapshot);
      }
    }
  }
  return out;
}
async function sha256(raw) {
  const hash = await crypto.subtle.digest("SHA-256", raw);
  return [
    ...new Uint8Array(hash)
  ].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
function digitsOf(text2) {
  let total = 0;
  for (const digit of text2) {
    const place = "0123456789".indexOf(digit);
    if (place < 0) refuse2("ENGINE_DISAGREES", "$registry.payoffs.at", `${text2} is not a position`);
    total = total * 10 + place;
  }
  return total;
}
function short(hex) {
  return hex.length <= 12 ? hex : hex.slice(0, 12);
}
export {
  rows as synthesisRows,
  verify,
  verifySynthesis
};
