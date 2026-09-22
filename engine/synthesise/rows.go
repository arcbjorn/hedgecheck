// Package synthesise answers "what sizes over these instruments meet this objective", or
// certifies that none do.
//
// It SOLVES, which is the engine's job: the engine is what answers in production, the
// checker verifies what an engine claims, and the oracle is the reference both agree with.
//
// AGREEMENT IS NOT BYTE EQUALITY HERE. A linear program's optimum is unique but its argmin
// is not, so two implementations can return different optimal vertices and both be right --
// measured, with two candidates at the same price `(1250, 0)` and `(0, 1250)` are both
// optimal at a relaxed cost of 250, and which comes back depends on the pivot order.
// Demanding one would test the pivot rule rather than the arithmetic. The bar is the STATUS
// and the RELAXED OPTIMUM COST, both determined facts about the program, with each answer
// then checked valid against the rows. PLAN section 7 states it.
package synthesise

import (
	"sort"

	"hedgecheck/engine/exact"
	"hedgecheck/engine/pwa"
)

// Side says which constraint at a price: the value attained there, or the limit from either
// side of it. A jump makes the three different numbers, and a sloped piece attains its
// infimum only in the limit, so the side is part of the site.
type Side string

const (
	At    Side = "at"
	Above Side = "above"
	Below Side = "below"
)

var sideOrder = map[Side]int{At: 0, Below: 1, Above: 2}

// Row is one constraint: `Alpha + sum(Coefficients[i] * n[i]) >= floor`, at a named site.
type Row struct {
	Price        exact.Q
	Side         Side
	Alpha        exact.Q
	Coefficients []exact.Q
}

// Rows turns the objective into finitely many exact constraints.
//
// For fixed sizes the P&L is affine on every piece, so the objective holds on a piece exactly
// when it holds at the piece's ends -- and an end is a constraint whether it is owned or only
// approached, because `>=` is closed: if the limit meets the floor then so does every interior
// price, and if it does not, prices arbitrarily close to it violate the objective.
//
// The breakpoint set does not depend on the sizes; it is the strikes, which come from the
// instruments' own terms. So one walk with unit sizes gives the rows for the whole family,
// which is what makes "cheapest sizes meeting the objective" a program with fixed rows.
//
// THE NAME IS CANONICAL: `at` before `below` before `above`, then sorted by price. The
// surviving name must not depend on the walk, because a certificate NAMES its sites and
// three implementations walk differently -- the oracle's atom walk calls the domain's top
// `below` where a maximal-piece walk calls it `at`.
//
// In THIS walk the rule is defensive rather than load-bearing: a maximal piece is visited
// low end first, and a low end is usually closed, so `at` arrives first anyway and mutating
// the tiebreak away changes nothing here. It is kept because the rule is what makes the
// three implementations' names agree, and because a future walk order -- or a piece whose
// low end is open where its neighbour's high end is closed -- would depend on it. Stated
// plainly so nobody reads a passing suite as evidence that this line is exercised.
func Rows(base pwa.Fn, units []pwa.Fn, lower, upper exact.Q) []Row {
	parts := append([]pwa.Fn{base}, units...)
	combined := pwa.Sum(parts...)

	// DISTINCT CONSTRAINTS ONLY, keyed by the WHOLE inequality. A price where the function is
	// continuous yields the same row from two adjacent pieces, and the same inequality written
	// twice says nothing more than once -- while a duplicate site name would make a
	// certificate weight ambiguous. Two rows at one price with different coefficients are
	// different constraints and both survive, which is the case at a strike.
	best := map[string]Row{}
	add := func(price exact.Q, side Side) {
		alpha := valueOf(base, price, side)
		coefficients := make([]exact.Q, len(units))
		for index, unit := range units {
			coefficients[index] = valueOf(unit, price, side)
		}
		key := alpha.String()
		for _, value := range coefficients {
			key += "|" + value.String()
		}
		if held, seen := best[key]; seen && sideOrder[held.Side] <= sideOrder[side] {
			return
		}
		best[key] = Row{Price: price, Side: side, Alpha: alpha, Coefficients: coefficients}
	}

	for _, piece := range combined.Profile(lower, upper) {
		lo, hi := piece.Lo, piece.Hi
		if lo.Unbounded || hi.Unbounded {
			continue // the domain is finite, so a profile piece over it is too
		}
		if lo.Closed {
			add(lo.Value, At)
		} else {
			add(lo.Value, Above)
		}
		if !lo.Value.Equal(hi.Value) {
			if hi.Closed {
				add(hi.Value, At)
			} else {
				add(hi.Value, Below)
			}
		}
	}

	out := make([]Row, 0, len(best))
	for _, row := range best {
		out = append(out, row)
	}
	sort.Slice(out, func(i, j int) bool {
		if c := out[i].Price.Cmp(out[j].Price); c != 0 {
			return c < 0
		}
		return sideOrder[out[i].Side] < sideOrder[out[j].Side]
	})
	return out
}

// valueOf is what one unit of f is worth at a price, FROM A GIVEN SIDE.
//
// `At` is the value the function attains there: the piece that owns the price. `Above` is the
// limit from the right and `Below` from the left, taken by evaluating the affine rule of the
// piece on that side -- which is not the same number wherever f jumps. A digital jumps at its
// strike, so this is the difference between "the protection pays" and "the protection has
// expired worthless". The TypeScript checker had exactly this bug before it was written this
// way: reading the point value for a `below` site made the strike's constraint say a contract
// pays nothing just below it, when it pays in full.
func valueOf(f pwa.Fn, price exact.Q, side Side) exact.Q {
	for _, piece := range f.Pieces() {
		loBelow := piece.Lo.Unbounded || piece.Lo.Value.Less(price)
		hiAbove := piece.Hi.Unbounded || price.Less(piece.Hi.Value)
		var wanted bool
		switch side {
		case At:
			wanted = (loBelow || (!piece.Lo.Unbounded && piece.Lo.Value.Equal(price) && piece.Lo.Closed)) &&
				(hiAbove || (!piece.Hi.Unbounded && piece.Hi.Value.Equal(price) && piece.Hi.Closed))
		case Below:
			// The piece whose interior lies to the LEFT of the price, so the price is its high end.
			wanted = loBelow && !piece.Hi.Unbounded && piece.Hi.Value.Equal(price)
		case Above:
			wanted = hiAbove && !piece.Lo.Unbounded && piece.Lo.Value.Equal(price)
		}
		if wanted {
			return piece.At(price)
		}
	}
	// At the domain's own ends there is nothing beyond, so the limit from inside is the value.
	return f.At(price)
}
