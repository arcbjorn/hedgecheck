// Package exact parses and formats exact numbers under the one grammar every
// implementation shares. big.Rat is not the specification: it reads "0x10" as 16 and
// accepts "1e3", "+5", ".5", "1_000" and "05". The grammar is enforced first.
package exact

import (
	"errors"
	"math/big"
	"regexp"
	"strings"
)

// MaxLength bounds a number string, in characters.
const MaxLength = 80

var grammar = regexp.MustCompile(`\A(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?|-?(?:0|[1-9][0-9]*)/[1-9][0-9]*)\z`)

// ErrGrammar reports a string outside the number grammar.
var ErrGrammar = errors.New("not in the number grammar")

// Parse returns the exact value of text, or ErrGrammar.
func Parse(text string) (*big.Rat, error) {
	if len(text) > MaxLength || !grammar.MatchString(text) {
		return nil, ErrGrammar
	}
	value, ok := new(big.Rat).SetString(text)
	if !ok {
		return nil, ErrGrammar
	}
	return value, nil
}

// Format returns the canonical text of value: a terminating decimal when one exists,
// otherwise "p/q" in lowest terms.
func Format(value *big.Rat) string {
	num, den := new(big.Int).Set(value.Num()), new(big.Int).Set(value.Denom())
	rest := new(big.Int).Set(den)
	for _, prime := range []int64{2, 5} {
		p, mod := big.NewInt(prime), new(big.Int)
		for mod.Mod(rest, p).Sign() == 0 {
			rest.Div(rest, p)
		}
	}
	if rest.Cmp(big.NewInt(1)) != 0 {
		return num.String() + "/" + den.String()
	}
	places, scale, ten := 0, big.NewInt(1), big.NewInt(10)
	for new(big.Int).Mod(scale, den).Sign() != 0 {
		scale.Mul(scale, ten)
		places++
	}
	scaled := new(big.Int).Mul(new(big.Int).Abs(num), new(big.Int).Div(scale, den))
	digits := scaled.String()
	if len(digits) < places+1 {
		digits = strings.Repeat("0", places+1-len(digits)) + digits
	}
	text := digits[:len(digits)-places]
	if places > 0 {
		text += "." + digits[len(digits)-places:]
	}
	if num.Sign() < 0 {
		text = "-" + text
	}
	return text
}
