"""Canonical JSON and digests: a strict profile of RFC 8785. Standard library only.

Accepted documents are UTF-8 without a BOM and contain only objects, arrays, strings and
booleans. No numbers (every quantity is an exact string), no null (absence is absence).
Object keys match [a-z][a-z0-9_]* and are unique. Strings are well-formed Unicode and do
not contain U+FFFD: at least one standard decoder substitutes it silently for malformed
input, so admitting it would let two implementations digest different strings. Nesting is
at most 32 deep. On this domain the canonical form is exactly RFC 8785: keys sorted,
no whitespace, minimal escapes, everything else literal UTF-8.
"""

from hashlib import sha256
import json
import re

MAX_DEPTH = 32
_KEY = re.compile(r"[a-z][a-z0-9_]*")
_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


class CanonError(ValueError):
    pass


def _reject_number(text):
    raise CanonError(f"numbers are not allowed; write an exact string: {text}")


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise CanonError(f"duplicate key: {key}")
        out[key] = value
    return out


def loads(raw):
    """Parse bytes under the profile. Anything outside it is an error, never a best effort."""
    if not isinstance(raw, (bytes, bytearray)):
        raise CanonError("input is bytes")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise CanonError("byte order mark")
    try:
        text = bytes(raw).decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=_pairs, parse_float=_reject_number,
                           parse_int=_reject_number, parse_constant=_reject_number)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise CanonError(str(error)) from None
    _check(value, 1)
    return value


def _check(value, depth):
    if depth > MAX_DEPTH:
        raise CanonError("nested deeper than 32")
    if isinstance(value, bool):
        return
    if isinstance(value, str):
        if "�" in value:
            raise CanonError("U+FFFD in a string")
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise CanonError("lone surrogate in a string") from None
        return
    if isinstance(value, list):
        for item in value:
            _check(item, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not _KEY.fullmatch(key):
                raise CanonError(f"key outside [a-z][a-z0-9_]*: {key!r}")
            _check(item, depth + 1)
        return
    raise CanonError("null" if value is None else f"unsupported value: {type(value).__name__}")


def _string(text):
    out = ['"']
    for char in text:
        if char in _SHORT:
            out.append(_SHORT[char])
        elif char < " ":
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _write(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(_write(item) for item in value) + "]"
    # Keys are ASCII under the profile, so code-point order equals RFC 8785's UTF-16 order.
    return "{" + ",".join(_string(key) + ":" + _write(value[key]) for key in sorted(value)) + "}"


def canonical(value):
    _check(value, 1)
    return _write(value).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()
