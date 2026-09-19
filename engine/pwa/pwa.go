// Package pwa is the kernel: a piecewise-affine function of one price.
//
// A function IS its list of pieces. The oracle stores a closure and samples it to
// recover the pieces, which is why it needs a tripwire for a constructor that hides a
// breakpoint. Here the pieces are the representation, so a hidden breakpoint cannot
// exist: every constructor states its own boundaries, and the only way to build a
// function from raw pieces validates the invariants.
//
// Consequences worth stating, because they are the point:
//   - Two equal functions are structurally equal. Comparing them is comparing slices.
//   - No API accepts breakpoints. A caller cannot withhold one.
//   - A point owned by neither neighbour is a singleton piece, so "unowned" is a thing
//     the representation can say rather than a gap it has to imply.
package pwa

import (
	"fmt"
	"sort"

	"hedgecheck/engine/exact"
)

// Bound is one end of a piece. Unbounded means the piece runs to infinity that way,
// and Closed says whether the bound's own price belongs to the piece.
type Bound struct {
	Value     exact.Q
	Unbounded bool
	Closed    bool
}

// Below and Above build finite bounds; NegInf and PosInf build unbounded ones. An
// unbounded end is never closed: infinity is not a price.
func Finite(value exact.Q, closed bool) Bound { return Bound{Value: value, Closed: closed} }
func NegInf() Bound                           { return Bound{Unbounded: true} }
func PosInf() Bound                           { return Bound{Unbounded: true} }

// Piece is an affine segment: value(price) = Slope*price + Intercept on [Lo, Hi].
type Piece struct {
	Lo, Hi           Bound
	Slope, Intercept exact.Q
}

// Singleton reports whether the piece is a single price owned by neither neighbour.
func (p Piece) Singleton() bool {
	return !p.Lo.Unbounded && !p.Hi.Unbounded && p.Lo.Value.Equal(p.Hi.Value)
}

// At returns the piece's value at a price, without checking membership.
func (p Piece) At(price exact.Q) exact.Q { return p.Slope.Mul(price).Add(p.Intercept) }

// Contains reports whether the price belongs to this piece.
func (p Piece) Contains(price exact.Q) bool {
	if !p.Lo.Unbounded {
		switch cmp := price.Cmp(p.Lo.Value); {
		case cmp < 0:
			return false
		case cmp == 0 && !p.Lo.Closed:
			return false
		}
	}
	if !p.Hi.Unbounded {
		switch cmp := price.Cmp(p.Hi.Value); {
		case cmp > 0:
			return false
		case cmp == 0 && !p.Hi.Closed:
			return false
		}
	}
	return true
}

// Fn is a total function of one price: pieces covering the whole real line, in order.
type Fn struct {
	pieces []Piece
}

// Pieces returns a copy, so a caller cannot reach into the function and change it.
func (f Fn) Pieces() []Piece {
	out := make([]Piece, len(f.pieces))
	copy(out, f.pieces)
	return out
}

// New validates the invariants and is the only way to build an Fn from raw pieces:
// sorted, contiguous, covering the line, every boundary owned exactly once, and no
// two adjacent pieces mergeable. The last rule is what makes equality structural.
func New(pieces []Piece) (Fn, error) {
	if len(pieces) == 0 {
		return Fn{}, fmt.Errorf("pwa: a function has at least one piece")
	}
	if !pieces[0].Lo.Unbounded || !pieces[len(pieces)-1].Hi.Unbounded {
		return Fn{}, fmt.Errorf("pwa: the pieces must cover the whole line")
	}
	for index, piece := range pieces {
		if !piece.Lo.Unbounded && !piece.Hi.Unbounded {
			if piece.Hi.Value.Less(piece.Lo.Value) {
				return Fn{}, fmt.Errorf("pwa: piece %d runs backwards", index)
			}
			if piece.Singleton() && (!piece.Lo.Closed || !piece.Hi.Closed) {
				return Fn{}, fmt.Errorf("pwa: piece %d is a single price that owns neither end", index)
			}
		}
		if piece.Lo.Unbounded && piece.Lo.Closed || piece.Hi.Unbounded && piece.Hi.Closed {
			return Fn{}, fmt.Errorf("pwa: piece %d closes an unbounded end", index)
		}
	}
	for index := 0; index+1 < len(pieces); index++ {
		left, right := pieces[index], pieces[index+1]
		if left.Hi.Unbounded || right.Lo.Unbounded {
			return Fn{}, fmt.Errorf("pwa: piece %d and %d are not contiguous", index, index+1)
		}
		if !left.Hi.Value.Equal(right.Lo.Value) {
			return Fn{}, fmt.Errorf("pwa: a gap between piece %d and %d", index, index+1)
		}
		if left.Hi.Closed == right.Lo.Closed {
			side := "neither"
			if left.Hi.Closed {
				side = "both"
			}
			return Fn{}, fmt.Errorf("pwa: %s piece owns the boundary at %s", side, left.Hi.Value)
		}
		if left.Slope.Equal(right.Slope) && left.Intercept.Equal(right.Intercept) {
			return Fn{}, fmt.Errorf("pwa: piece %d and %d are mergeable; a function has one representation", index, index+1)
		}
	}
	out := make([]Piece, len(pieces))
	copy(out, pieces)
	return Fn{pieces: out}, nil
}

func mustNew(pieces []Piece) Fn {
	f, err := New(pieces)
	if err != nil {
		panic(err)
	}
	return f
}

// Constant is a function with one piece and no breakpoints.
func Constant(value exact.Q) Fn {
	return mustNew([]Piece{{Lo: NegInf(), Hi: PosInf(), Slope: exact.Zero(), Intercept: value}})
}

// Cash is a constant, named for what it is in a payoff.
func Cash(amount exact.Q) Fn { return Constant(amount) }

// Linear is quantity*(price - baseline): a holding valued from a baseline.
func Linear(quantity, baseline exact.Q) Fn {
	return mustNew([]Piece{{
		Lo: NegInf(), Hi: PosInf(),
		Slope:     quantity,
		Intercept: quantity.Mul(baseline).Neg(),
	}})
}

// Indicator pays size on the interval between the bounds and nothing outside it.
// Each bound states who owns it, so an unowned strike is expressible.
func Indicator(size exact.Q, lo, hi Bound) (Fn, error) {
	zero, pieces := exact.Zero(), []Piece{}
	if !lo.Unbounded && !hi.Unbounded && hi.Value.Less(lo.Value) {
		return Fn{}, fmt.Errorf("pwa: the indicator's interval runs backwards")
	}
	if !lo.Unbounded {
		pieces = append(pieces, Piece{Lo: NegInf(), Hi: Bound{Value: lo.Value, Closed: !lo.Closed}, Slope: zero, Intercept: zero})
	}
	pieces = append(pieces, Piece{
		Lo:    boundOrNegInf(lo),
		Hi:    boundOrPosInf(hi),
		Slope: zero, Intercept: size,
	})
	if !hi.Unbounded {
		pieces = append(pieces, Piece{Lo: Bound{Value: hi.Value, Closed: !hi.Closed}, Hi: PosInf(), Slope: zero, Intercept: zero})
	}
	return New(dropMergeable(pieces))
}

// Ramp is the scalar payoff: size*(price-low)/(high-low), clamped to [0, size].
// Long pays at the high end, Short is its complement.
func RampLong(size, low, high exact.Q) (Fn, error) {
	span := high.Sub(low)
	if span.Sign() <= 0 {
		return Fn{}, fmt.Errorf("pwa: a ramp needs high above low")
	}
	slope, _ := size.Div(span)
	return New([]Piece{
		{Lo: NegInf(), Hi: Finite(low, false), Slope: exact.Zero(), Intercept: exact.Zero()},
		{Lo: Finite(low, true), Hi: Finite(high, true), Slope: slope, Intercept: slope.Mul(low).Neg()},
		{Lo: Finite(high, false), Hi: PosInf(), Slope: exact.Zero(), Intercept: size},
	})
}

func RampShort(size, low, high exact.Q) (Fn, error) {
	long, err := RampLong(size, low, high)
	if err != nil {
		return Fn{}, err
	}
	return Constant(size).Sub(long), nil
}

func boundOrNegInf(b Bound) Bound {
	if b.Unbounded {
		return NegInf()
	}
	return b
}

func boundOrPosInf(b Bound) Bound {
	if b.Unbounded {
		return PosInf()
	}
	return b
}

// dropMergeable folds adjacent pieces with the same line into one, which is what makes
// two equal functions structurally equal.
func dropMergeable(pieces []Piece) []Piece {
	out := []Piece{}
	for _, piece := range pieces {
		if n := len(out); n > 0 {
			last := out[n-1]
			if last.Slope.Equal(piece.Slope) && last.Intercept.Equal(piece.Intercept) &&
				!last.Hi.Unbounded && !piece.Lo.Unbounded && last.Hi.Value.Equal(piece.Lo.Value) &&
				last.Hi.Closed != piece.Lo.Closed {
				out[n-1].Hi = piece.Hi
				continue
			}
		}
		out = append(out, piece)
	}
	return out
}

// At evaluates the function. Every price belongs to exactly one piece.
func (f Fn) At(price exact.Q) exact.Q {
	for _, piece := range f.pieces {
		if piece.Contains(price) {
			return piece.At(price)
		}
	}
	panic("pwa: the pieces do not cover " + price.String())
}

// Add returns the sum. Its breakpoints are the union of both sides', which is why a
// sum can never lose one.
func (f Fn) Add(other Fn) Fn {
	return mustNew(dropMergeable(combine(f, other, func(a, b exact.Q) exact.Q { return a.Add(b) })))
}

func (f Fn) Sub(other Fn) Fn {
	return mustNew(dropMergeable(combine(f, other, func(a, b exact.Q) exact.Q { return a.Sub(b) })))
}

func (f Fn) Neg() Fn { return Constant(exact.Zero()).Sub(f) }

// Sum adds any number of functions. An empty sum is zero.
func Sum(parts ...Fn) Fn {
	out := Constant(exact.Zero())
	for _, part := range parts {
		out = out.Add(part)
	}
	return out
}

// combine walks both piece lists together, splitting at every boundary either side has.
func combine(left, right Fn, op func(a, b exact.Q) exact.Q) []Piece {
	cuts := boundaries(left, right)
	out := []Piece{}
	for _, span := range spans(cuts) {
		l := left.pieceAt(span)
		r := right.pieceAt(span)
		out = append(out, Piece{
			Lo: span.Lo, Hi: span.Hi,
			Slope:     op(l.Slope, r.Slope),
			Intercept: op(l.Intercept, r.Intercept),
		})
	}
	return out
}

// boundaries is every finite boundary price either function has, in order, once each.
func boundaries(left, right Fn) []exact.Q {
	seen := []exact.Q{}
	add := func(q exact.Q) {
		for _, already := range seen {
			if already.Equal(q) {
				return
			}
		}
		seen = append(seen, q)
	}
	for _, f := range []Fn{left, right} {
		for _, piece := range f.pieces {
			if !piece.Lo.Unbounded {
				add(piece.Lo.Value)
			}
			if !piece.Hi.Unbounded {
				add(piece.Hi.Value)
			}
		}
	}
	sort.Slice(seen, func(i, j int) bool { return seen[i].Less(seen[j]) })
	return seen
}

// spans turns a sorted boundary list into the pieces of a partition of the line:
// open intervals between boundaries, and a singleton at each boundary.
func spans(cuts []exact.Q) []Piece {
	if len(cuts) == 0 {
		return []Piece{{Lo: NegInf(), Hi: PosInf()}}
	}
	out := []Piece{{Lo: NegInf(), Hi: Finite(cuts[0], false)}}
	for index, cut := range cuts {
		out = append(out, Piece{Lo: Finite(cut, true), Hi: Finite(cut, true)})
		if index+1 < len(cuts) {
			out = append(out, Piece{Lo: Finite(cut, false), Hi: Finite(cuts[index+1], false)})
		}
	}
	return append(out, Piece{Lo: Finite(cuts[len(cuts)-1], false), Hi: PosInf()})
}

// pieceAt finds the piece covering a span. The span lies wholly within one piece,
// because the spans were cut at every boundary both functions have.
func (f Fn) pieceAt(span Piece) Piece {
	probe := spanProbe(span)
	for _, piece := range f.pieces {
		if piece.Contains(probe) {
			return piece
		}
	}
	panic("pwa: no piece covers the probe " + probe.String())
}

// spanProbe is a price strictly inside the span, or the span's own price when it is a
// singleton. Interior, so it cannot land on a neighbour's boundary.
func spanProbe(span Piece) exact.Q {
	switch {
	case span.Singleton():
		return span.Lo.Value
	case span.Lo.Unbounded && span.Hi.Unbounded:
		return exact.Zero()
	case span.Lo.Unbounded:
		return span.Hi.Value.Sub(exact.One())
	case span.Hi.Unbounded:
		return span.Lo.Value.Add(exact.One())
	default:
		half, _ := span.Lo.Value.Add(span.Hi.Value).Div(exact.FromInt(2))
		return half
	}
}
