"""Exact numbers: one grammar in, one canonical form out. Standard library only.

Every implementation enforces this grammar BEFORE its rational library sees the string.
The libraries are not the specification: Go's big.Rat reads "0x10" as 16, Python's
Fraction accepts " 5", and both accept "1e3", "+5", ".5", "1_000" and "05".
"""

from fractions import Fraction
import re

MAX_LENGTH = 80
GRAMMAR = r"-?(0|[1-9][0-9]*)(\.[0-9]+)?|-?(0|[1-9][0-9]*)/[1-9][0-9]*"
_GRAMMAR = re.compile(GRAMMAR)


class NumberError(ValueError):
    pass


def parse(text):
    if not isinstance(text, str):
        raise NumberError("a number is a string")
    if len(text) > MAX_LENGTH:
        raise NumberError("number longer than 80 characters")
    if not _GRAMMAR.fullmatch(text):
        raise NumberError(f"not in the number grammar: {text!r}")
    return Fraction(text)


def format(value):
    """Canonical text: a terminating decimal when one exists, otherwise 'p/q' in lowest terms."""
    value = Fraction(value)
    rest = value.denominator
    for prime in (2, 5):
        while rest % prime == 0:
            rest //= prime
    if rest != 1:
        return f"{value.numerator}/{value.denominator}"
    places = 0
    while (value * 10 ** places).denominator != 1:
        places += 1
    digits = str(abs(value.numerator) * 10 ** places // value.denominator).rjust(places + 1, "0")
    text = digits[: len(digits) - places] + ("." + digits[len(digits) - places:] if places else "")
    return ("-" if value < 0 else "") + text
