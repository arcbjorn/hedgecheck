package synthesise

import (
	"hedgecheck/engine/exact"
	"hedgecheck/engine/pwa"
)

// Weight is one entry of a Farkas certificate, NAMING the row it weights. A bare vector
// would be ordered by the rows, making row order an implicit contract between three
// implementations; naming the site lets each look it up among its own rows, so order stops
// mattering and an unknown site is a refusal rather than a silent misalignment.
type Weight struct {
	Price  exact.Q
	Side   Side
	Weight exact.Q
}

// Answer is what a synthesis concluded.
type Answer struct {
	// Status is "feasible", "infeasible" or "rounding_failed" -- the synthesis document's
	// vocabulary, not the solver's.
	Status  string
	Sizes   []exact.Q
	Cost    exact.Q
	Relaxed []exact.Q
	// RelaxedCost is the linear program's own optimum. It is UNIQUE even where the argmin is
	// not, so it is what two implementations can be held to.
	RelaxedCost exact.Q
	Certificate []Weight
}

// Synthesise finds cheapest whole-lot sizes meeting the objective, or certifies that none do.
//
// THE PROGRAM IS A RELAXATION. Sizes are whole contracts but the linear program solves over
// the rationals, so its answer is rounded UP -- rounding down can drop below the floor the
// program was solving for. The rounded structure is then RE-CHECKED against the same rows,
// arithmetic only, and reported only if it really meets the objective.
//
// INFEASIBILITY IS CLAIMED ONLY FOR THE RELAXATION. If the relaxed program is infeasible then
// no whole-contract answer exists either, since the integers are a subset of the rationals, so
// the certificate transfers. The converse does not hold and is not claimed: a feasible
// relaxation whose rounding fails the re-check is `rounding_failed`, which says the search
// found nothing, never that nothing exists.
func Synthesise(base pwa.Fn, units []pwa.Fn, prices []exact.Q, floor, lower, upper, lot exact.Q) Answer {
	derived := Rows(base, units, lower, upper)

	// THE PREMIUM IS PART OF THE CONSTRAINT, not only of the objective. Buying n contracts
	// costs n*price whatever the price does, so what one contract is worth at a site is its
	// payoff NET of its price. Leaving it out lets the program buy protection for free.
	matrix := make([][]exact.Q, len(derived))
	rhs := make([]exact.Q, len(derived))
	for j, row := range derived {
		net := make([]exact.Q, len(units))
		for i := range units {
			net[i] = row.Coefficients[i].Sub(prices[i])
		}
		matrix[j] = net
		rhs[j] = floor.Sub(row.Alpha)
	}

	solution := simplex(matrix, rhs, prices, len(units))
	switch solution.Status {
	case Infeasible:
		weights := []Weight{}
		for j, row := range derived {
			if solution.Certificate[j].Sign() == 0 {
				continue // a zero weight says nothing about its row, so it is not carried
			}
			weights = append(weights, Weight{Price: row.Price, Side: row.Side, Weight: solution.Certificate[j]})
		}
		return Answer{Status: "infeasible", Certificate: weights}
	case Unbounded:
		return Answer{Status: "unbounded"}
	}

	relaxedCost := exact.Zero()
	for i, value := range solution.Point {
		relaxedCost = relaxedCost.Add(prices[i].Mul(value))
	}

	sizes := make([]exact.Q, len(solution.Point))
	for i, value := range solution.Point {
		sizes[i] = ceilLot(value, lot)
	}

	// THE RE-CHECK. Every row, at the rounded sizes, with this package's own arithmetic.
	for _, row := range derived {
		value := row.Alpha
		for i, size := range sizes {
			value = value.Add(row.Coefficients[i].Sub(prices[i]).Mul(size))
		}
		if value.Less(floor) {
			return Answer{Status: "rounding_failed", Relaxed: solution.Point, RelaxedCost: relaxedCost}
		}
	}

	cost := exact.Zero()
	for i, size := range sizes {
		cost = cost.Add(prices[i].Mul(size))
	}
	return Answer{Status: "feasible", Sizes: sizes, Cost: cost,
		Relaxed: solution.Point, RelaxedCost: relaxedCost}
}

// ceilLot rounds up to the next whole multiple of the lot, using exact.Q's own CeilLot. Up,
// never down: rounding down can drop below the floor the program was solving for. A
// non-positive lot is not a lot size, and CeilLot refuses it, so the value stands.
func ceilLot(value, lot exact.Q) exact.Q {
	rounded, ok := value.CeilLot(lot)
	if !ok {
		return value
	}
	return rounded
}
