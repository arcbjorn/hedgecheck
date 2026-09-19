"""Write the conformance vectors every implementation must reproduce.

    python3 tools/make_vectors.py            # write
    python3 tools/make_vectors.py --check    # fail if the files on disk are stale

Inputs and expected canonical text are written BY HAND below; no implementation produces
them. The script only encodes inputs as hex (several are not valid UTF-8, so they cannot
live inside a JSON string) and adds the SHA-256 of the expected text. Implementations
agree with the vectors, never the other way round.
"""

from hashlib import sha256
import json
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent.parent / "fixtures" / "vectors"

# (name, input bytes, expected canonical text, or None when the input must be rejected)
CANONICAL = [
    ("keys are sorted", b'{"b":"1","a":"2"}', '{"a":"2","b":"1"}'),
    ("whitespace is dropped", b' {\n "a" : [ "x" , true , false ] }\t', '{"a":["x",true,false]}'),
    ("html-sensitive and non-ascii characters stay literal", '{"label":"cap <1000 & é"}'.encode(), '{"label":"cap <1000 & é"}'),
    ("needless escapes are removed", b'{"s":"\\u00e9\\u003c\\/"}', '{"s":"é</"}'),
    ("control characters keep short or lowercase escapes", b'{"s":"\\n\\u001F\\b\\u0000"}', '{"s":"\\n\\u001f\\b\\u0000"}'),
    ("quote and backslash stay escaped", b'{"s":"\\"\\\\"}', '{"s":"\\"\\\\"}'),
    ("DEL stays raw", b'{"s":"\x7f"}', '{"s":"\x7f"}'),
    ("U+2028 stays raw", '{"s":"\u2028"}'.encode(), '{"s":"\u2028"}'),
    ("an escaped surrogate pair becomes one character", b'{"s":"\\ud83d\\ude00"}', '{"s":"\U0001f600"}'),
    ("sorting is recursive and arrays keep their order", b'{"z":{"b":"1","a":"2"},"a":[{"d":"1","c":"2"},"y","x"]}', '{"a":[{"c":"2","d":"1"},"y","x"],"z":{"a":"2","b":"1"}}'),
    ("empty containers", b'{"a":{},"b":[]}', '{"a":{},"b":[]}'),
    ("digits sort before underscore", b'{"a_1":"3","a1":"2","a":"1"}', '{"a":"1","a1":"2","a_1":"3"}'),
    ("a top-level array is a document", b'["b","a"]', '["b","a"]'),
    ("a container at depth 32 is accepted", b"[" * 32 + b"]" * 32, "[" * 32 + "]" * 32),
    ("a string at depth 32 is accepted", b"[" * 31 + b'"x"' + b"]" * 31, "[" * 31 + '"x"' + "]" * 31),
    ("a container at depth 33 is rejected", b"[" * 33 + b"]" * 33, None),
    ("a string at depth 33 is rejected", b"[" * 32 + b'"x"' + b"]" * 32, None),
    ("an integer is rejected", b'{"a":1}', None),
    ("a decimal is rejected", b'{"a":"1","b":1.5}', None),
    ("negative zero is rejected", b'{"a":-0}', None),
    ("an exponent is rejected", b'{"a":1e3}', None),
    ("NaN is rejected", b'{"a":NaN}', None),
    ("Infinity is rejected", b'{"a":Infinity}', None),
    ("null is rejected", b'{"a":null}', None),
    ("a top-level number is rejected", b"1", None),
    ("a top-level null is rejected", b"null", None),
    ("a duplicate key is rejected", b'{"a":"1","a":"2"}', None),
    ("a duplicate key written with an escape is rejected", b'{"a":"1","\\u0061":"2"}', None),
    ("an uppercase key is rejected", b'{"A":"1"}', None),
    ("a non-ascii key is rejected", '{"é":"1"}'.encode(), None),
    ("an empty key is rejected", b'{"":"1"}', None),
    ("a key starting with a digit is rejected", b'{"1a":"x"}', None),
    ("a byte order mark is rejected", b'\xef\xbb\xbf{"a":"1"}', None),
    ("trailing text is rejected", b'{"a":"1"} x', None),
    ("two documents are rejected", b"{}{}", None),
    ("an invalid UTF-8 byte is rejected", b'{"a":"\xff"}', None),
    ("a surrogate encoded as UTF-8 is rejected", b'{"a":"\xed\xa0\x80"}', None),
    ("an escaped lone surrogate is rejected", b'{"a":"\\ud800"}', None),
    ("a reversed surrogate pair is rejected", b'{"a":"\\ude00\\ud83d"}', None),
    ("a literal U+FFFD is rejected", '{"a":"\ufffd"}'.encode(), None),
    ("an escaped U+FFFD is rejected", b'{"a":"\\ufffd"}', None),
    ("a raw control character is rejected", b'{"a":"\x01"}', None),
    ("a raw newline in a string is rejected", b'{"a":"\n"}', None),
    ("single quotes are rejected", b"{'a':'1'}", None),
    ("a trailing comma is rejected", b'{"a":"1",}', None),
    ("a comment is rejected", b'{"a":"1"} // note', None),
    ("empty input is rejected", b"", None),
    ("whitespace alone is rejected", b"  \n", None),
]

# (input, canonical form, or None when the grammar rejects it)
NUMBERS = [
    ("0", "0"), ("-0", "0"), ("5", "5"), ("-5", "-5"), ("0.1", "0.1"), ("0.10", "0.1"), ("-0.50", "-0.5"),
    ("1.000", "1"), ("0.00001", "0.00001"), ("77631.4", "77631.4"), ("268000/3", "268000/3"), ("6/4", "1.5"),
    ("10/4", "2.5"), ("1/3", "1/3"), ("-2/6", "-1/3"), ("0/7", "0"), ("-0/7", "0"), ("1/1", "1"), ("3/8", "0.375"),
    ("123456789012345678901234567890.123456789", "123456789012345678901234567890.123456789"),
    ("1" * 80, "1" * 80),
    ("", None), (" ", None), ("1e3", None), ("1E3", None), ("+5", None), (".5", None), ("5.", None), ("0x10", None),
    ("0b101", None), ("0b101/3", None), ("1_000", None), ("1,000", None), (" 5", None), ("5 ", None), ("5\n", None),
    ("05", None), ("00", None), ("-", None), ("--5", None), ("-.5", None), ("5/0", None), ("5/00", None), ("5/01", None),
    ("1/3e2", None), ("1/-3", None), ("1.5/2", None), ("1/ 3", None), ("0.1.2", None), ("NaN", None), ("Infinity", None),
    ("inf", None), ("\u0665", None), ("\uff15", None), ("1" * 81, None),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    canonical = []
    for name, raw, expected in CANONICAL:
        row = {"name": name, "input_hex": raw.hex()}
        if expected is None:
            row["accepted"] = False
        else:
            row.update(accepted=True, canonical=expected, sha256=sha256(expected.encode()).hexdigest())
        canonical.append(row)
    numbers = [{"input": text, "accepted": form is not None, **({"canonical": form} if form is not None else {})}
               for text, form in NUMBERS]
    stale = []
    for stem, rows in (("canonical-json", canonical), ("numbers", numbers)):
        text = json.dumps({"vectors": rows}, indent=1, ensure_ascii=True) + "\n"
        path = OUT / f"{stem}.json"
        if "--check" in sys.argv:
            if not path.exists() or path.read_text() != text:
                stale.append(path.name)
        else:
            path.write_text(text)
        print(f"{stem}: {len(rows)} vectors, {sum(r['accepted'] for r in rows)} accepted")
    if stale:
        sys.exit(f"stale: {', '.join(stale)}. Run python3 tools/make_vectors.py and commit the result.")


if __name__ == "__main__":
    main()
