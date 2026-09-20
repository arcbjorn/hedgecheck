package exact

import (
	"math/big"
	"strings"
)

// Q is an exact rational, immutable by construction.
//
// big.Rat mutates its receiver: `a.Add(a, b)` rewrites a in place, and two variables
// holding the same *big.Rat are the same number until one of them is written to. In a
// kernel that stores coefficients in pieces and reuses them across sums, an aliased Rat
// is a silent wrong answer, not a crash. Q wraps the pointer unexported and every
// operation allocates, so a value can be shared freely and nothing can reach through it.
//
// The zero Q is exactly zero, so a Q is usable without construction.
type Q struct {
	r *big.Rat
}

func wrap(r *big.Rat) Q { return Q{r: r} }

// rat returns a private copy. Callers outside this package never see a *big.Rat, and
// callers inside it never see the stored pointer, so no operation can write through one.
func (q Q) rat() *big.Rat {
	if q.r == nil {
		return new(big.Rat)
	}
	return new(big.Rat).Set(q.r)
}

// Zero, One and FromInt build a Q without parsing.
func Zero() Q           { return wrap(new(big.Rat)) }
func One() Q            { return FromInt(1) }
func FromInt(n int64) Q { return wrap(new(big.Rat).SetInt64(n)) }

// ParseQ returns the exact value of text, or ErrGrammar. The grammar is enforced
// before big.Rat sees the string.
func ParseQ(text string) (Q, error) {
	r, err := Parse(text)
	if err != nil {
		return Q{}, err
	}
	return wrap(r), nil
}

// MustParseQ is ParseQ for text known to be in the grammar; it panics otherwise.
// Only tests and constants use it.
func MustParseQ(text string) Q {
	q, err := ParseQ(text)
	if err != nil {
		panic("exact: " + text + ": " + err.Error())
	}
	return q
}

// String returns the canonical text: a terminating decimal when one exists, otherwise
// "p/q" in lowest terms. Identical to the oracle's and the checker's formatting.
func (q Q) String() string { return Format(q.rat()) }

// Add, Sub, Mul, Div and Neg each return a new Q and never touch their operands.
func (q Q) Add(other Q) Q { return wrap(new(big.Rat).Add(q.rat(), other.rat())) }
func (q Q) Sub(other Q) Q { return wrap(new(big.Rat).Sub(q.rat(), other.rat())) }
func (q Q) Mul(other Q) Q { return wrap(new(big.Rat).Mul(q.rat(), other.rat())) }
func (q Q) Neg() Q        { return wrap(new(big.Rat).Neg(q.rat())) }

// Div returns q/other and false when other is zero. Division by zero is a caller
// error, never a panic in a pure kernel.
func (q Q) Div(other Q) (Q, bool) {
	if other.Sign() == 0 {
		return Q{}, false
	}
	return wrap(new(big.Rat).Quo(q.rat(), other.rat())), true
}

// Cmp reports -1, 0 or +1 as q is less than, equal to, or greater than other.
func (q Q) Cmp(other Q) int { return q.rat().Cmp(other.rat()) }

// Sign reports -1, 0 or +1.
func (q Q) Sign() int { return q.rat().Sign() }

// Equal, Less and LessEqual read as the comparisons they are.
func (q Q) Equal(other Q) bool     { return q.Cmp(other) == 0 }
func (q Q) Less(other Q) bool      { return q.Cmp(other) < 0 }
func (q Q) LessEqual(other Q) bool { return q.Cmp(other) <= 0 }

// Min and Max return the smaller or larger operand, q when equal.
func Min(a, b Q) Q {
	if b.Less(a) {
		return b
	}
	return a
}

func Max(a, b Q) Q {
	if a.Less(b) {
		return b
	}
	return a
}

// IsInt reports whether q is a whole number.
func (q Q) IsInt() bool { return q.rat().IsInt() }

// FloorLot returns the largest multiple of lot that is <= q, and Ceil the smallest
// multiple that is >= q. lot must be positive; both return false otherwise. Sizes are
// counted in whole contracts, so rounding is a lot operation, never a float one.
func (q Q) FloorLot(lot Q) (Q, bool) {
	steps, ok := q.divSteps(lot)
	if !ok {
		return Q{}, false
	}
	return wrap(new(big.Rat).Mul(new(big.Rat).SetInt(floorInt(steps)), lot.rat())), true
}

func (q Q) CeilLot(lot Q) (Q, bool) {
	steps, ok := q.divSteps(lot)
	if !ok {
		return Q{}, false
	}
	return wrap(new(big.Rat).Mul(new(big.Rat).SetInt(ceilInt(steps)), lot.rat())), true
}

func (q Q) divSteps(lot Q) (*big.Rat, bool) {
	if lot.Sign() <= 0 {
		return nil, false
	}
	return new(big.Rat).Quo(q.rat(), lot.rat()), true
}

// floorInt and ceilInt round a rational to an integer, away from and toward zero as
// the sign requires. big.Int.Div truncates toward zero for negatives, so the remainder
// decides whether to step.
func floorInt(r *big.Rat) *big.Int {
	quotient, remainder := new(big.Int).QuoRem(r.Num(), r.Denom(), new(big.Int))
	if remainder.Sign() < 0 {
		quotient.Sub(quotient, big.NewInt(1))
	}
	return quotient
}

func ceilInt(r *big.Rat) *big.Int {
	quotient, remainder := new(big.Int).QuoRem(r.Num(), r.Denom(), new(big.Int))
	if remainder.Sign() > 0 {
		quotient.Add(quotient, big.NewInt(1))
	}
	return quotient
}

// DecimalPlaces returns q rounded to places decimal digits, half away from zero.
//
// This is a LOSSY rendering and the only one in the codebase. Nothing in an
// evaluation path may call it: a rounded number that flowed back into arithmetic
// would make the answer depend on how it was displayed. It exists so a drawing can
// have pixel coordinates -- an SVG cannot accept "26106927533/288000", and a chart is
// a picture of the answer, never the answer.
//
// Rounding is half away from zero rather than to even, so -1/2 renders "-1" and not
// "0": a reader should never see a loss drawn as nothing. A value that genuinely
// rounds to zero loses its sign, because "-0.00" names a number the drawing does not
// have; ask for more places to see which side of zero it was on.
func (q Q) DecimalPlaces(places int) string {
	if places < 0 {
		places = 0
	}
	scale := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(places)), nil)
	scaled := new(big.Rat).Mul(q.rat(), new(big.Rat).SetInt(scale))

	// Round half away from zero: add or subtract a half, then truncate.
	half := big.NewRat(1, 2)
	if scaled.Sign() < 0 {
		scaled.Sub(scaled, half)
	} else {
		scaled.Add(scaled, half)
	}
	whole := new(big.Int).Quo(scaled.Num(), scaled.Denom())

	negative := whole.Sign() < 0
	digits := new(big.Int).Abs(whole).String()
	if places == 0 {
		if negative {
			return "-" + digits
		}
		return digits
	}
	if len(digits) < places+1 {
		digits = strings.Repeat("0", places+1-len(digits)) + digits
	}
	text := digits[:len(digits)-places] + "." + digits[len(digits)-places:]
	if negative {
		return "-" + text
	}
	return text
}
