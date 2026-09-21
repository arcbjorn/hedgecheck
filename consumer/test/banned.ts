// The patterns no file under `consumer/` may contain.
//
// They live in a module of their own so the scan can skip exactly ONE file -- this
// one, which necessarily quotes them -- instead of exempting the whole of
// `place.test.ts`. A blanket exemption on a test file that genuinely imports
// `readFileSync` is a hole: a key read smuggled in there was not caught, though the
// scan's own regex matched the line.

export const BANNED: readonly [RegExp, string][] = [
  [/readFileSync\s*\([^)]*key/i, "reads a key from a file"],
  [/console\.[a-z]+\([^)]*process\.env/i, "logs the environment"],
  [/console\.[a-z]+\([^)]*\bkey\b/i, "logs something called a key"],
  [/JSON\.stringify\s*\(\s*process\.env/i, "serialises the environment"],
  [/\bprocess\.env\b(?!\s*\))/, "reads process.env directly rather than an injected env"],
];

/** The one file the scan skips, because it is the one that quotes the patterns. */
export const SKIPPED = "banned.ts";
