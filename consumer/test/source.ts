// Reading a source file as CODE, with its comments removed and its strings kept.
//
// The guards that grep for `fetch(`, `Date.` or `process.env` used to strip comments
// with `source.replace(/\/\/.*$/gm, "")`. That regex has no idea what a string is, so
// the `//` inside any URL deleted the rest of that line before the patterns were
// applied -- and `place.ts` holds two exchange URLs as module constants. A real
// violation sharing a line with a URL simply vanished.
//
// This walks the text instead, tracking whether it is inside a string, a template or
// a comment. It is not a TypeScript parser and does not need to be: it needs to know
// that `//` inside quotes is not a comment, which is exactly the bug.

import { readFileSync } from "node:fs";

/** The file with comments blanked out and every string literal left intact. */
export function code(path: string | URL): string {
  const text = readFileSync(path, "utf8");
  let out = "";
  let at = 0;

  while (at < text.length) {
    const ch = text[at] as string;
    const next = text[at + 1];

    if (ch === '"' || ch === "'" || ch === "`") {
      const quote = ch;
      out += ch;
      at += 1;
      while (at < text.length) {
        const inner = text[at] as string;
        out += inner;
        at += 1;
        if (inner === "\\") {
          // An escape consumes the next character, so a \" does not end the string.
          if (at < text.length) {
            out += text[at] as string;
            at += 1;
          }
          continue;
        }
        if (inner === quote) break;
      }
      continue;
    }

    if (ch === "/" && next === "/") {
      // Blanked to the end of the line, keeping the newline so line numbers hold.
      while (at < text.length && text[at] !== "\n") at += 1;
      continue;
    }

    if (ch === "/" && next === "*") {
      at += 2;
      while (at < text.length && !(text[at] === "*" && text[at + 1] === "/")) {
        // Newlines are kept so a banned pattern cannot be smuggled across the gap
        // left behind by a block comment.
        if (text[at] === "\n") out += "\n";
        at += 1;
      }
      at += 2;
      continue;
    }

    out += ch;
    at += 1;
  }
  return out;
}
