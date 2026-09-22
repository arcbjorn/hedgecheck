package synthesise

import "hedgecheck/engine/exact"

// Status is what the program turned out to be.
type Status string

const (
	// Optimal: a feasible point was found and the cost minimised.
	Optimal Status = "optimal"
	// Infeasible: no non-negative sizes satisfy the rows, and the certificate proves it.
	Infeasible Status = "infeasible"
	// Unbounded: cannot happen here, because every cost is non-negative and sizes are
	// bounded below by zero. Reported rather than ignored, so a violated assumption surfaces.
	Unbounded Status = "unbounded"
)

// Solution is the program's answer. On Infeasible, Certificate is a Farkas witness:
// `y >= 0` with `A^T y <= 0` and `b . y > 0`, which is exactly the statement that no
// non-negative n satisfies `A n >= b`.
type Solution struct {
	Status      Status
	Point       []exact.Q
	Certificate []exact.Q
}

// simplex solves   minimise cost . n   subject to   A n >= b,  n >= 0.
//
// Exact rationals throughout: no float ever touches this. The objective row is carried INSIDE
// the tableau and pivoted with it, so reduced costs are READ rather than recomputed --
// recomputing them against a mutating basis is where the reference oracle's first attempt at
// this went wrong, silently returning a point that violated its own constraints.
//
// BLAND'S RULE, not the steepest edge: the lowest-index eligible column, and the lowest basis
// index among tied ratios. Cycling is then impossible, so termination is a fact rather than a
// hope. These programs have single-digit rows and columns, so trading speed for a termination
// proof is the right trade.
func simplex(rows [][]exact.Q, rhs []exact.Q, cost []exact.Q, columns int) Solution {
	m := len(rows)
	zero, one := exact.Zero(), exact.One()

	// Every right-hand side is made non-negative, so the artificial basis starts feasible.
	// A flipped row had its whole inequality multiplied by -1, surplus included, and its
	// Farkas multiplier carries that sign back at the end.
	flipped := make([]bool, m)
	a := make([][]exact.Q, m)
	b := make([]exact.Q, m)
	for j := 0; j < m; j++ {
		a[j] = make([]exact.Q, columns)
		if rhs[j].Sign() < 0 {
			flipped[j] = true
			for i := 0; i < columns; i++ {
				a[j][i] = rows[j][i].Neg()
			}
			b[j] = rhs[j].Neg()
		} else {
			copy(a[j], rows[j])
			b[j] = rhs[j]
		}
	}

	surplus, artificial := columns, columns+m
	width := columns + 2*m

	table := make([][]exact.Q, m)
	basis := make([]int, m)
	for j := 0; j < m; j++ {
		row := make([]exact.Q, width+1)
		for i := range row {
			row[i] = zero
		}
		copy(row, a[j])
		if flipped[j] {
			row[surplus+j] = one
		} else {
			row[surplus+j] = one.Neg()
		}
		row[artificial+j] = one
		row[width] = b[j]
		table[j] = row
		basis[j] = artificial + j
	}

	pivot := func(objective []exact.Q, pr, pc int) {
		factor := table[pr][pc]
		for k := 0; k <= width; k++ {
			value, ok := table[pr][k].Div(factor)
			if !ok {
				return // factor is non-zero by construction; a zero would be a bug, not an input
			}
			table[pr][k] = value
		}
		for r := 0; r < m; r++ {
			if r == pr || table[r][pc].Sign() == 0 {
				continue
			}
			scale := table[r][pc]
			for k := 0; k <= width; k++ {
				table[r][k] = table[r][k].Sub(scale.Mul(table[pr][k]))
			}
		}
		if objective[pc].Sign() != 0 {
			scale := objective[pc]
			for k := 0; k <= width; k++ {
				objective[k] = objective[k].Sub(scale.Mul(table[pr][k]))
			}
		}
		basis[pr] = pc
	}

	// run pivots to optimality over the first `allowed` columns. False means unbounded.
	run := func(objective []exact.Q, allowed int) bool {
		for {
			entering := -1
			for j := 0; j < allowed; j++ {
				if objective[j].Sign() < 0 {
					entering = j
					break
				}
			}
			if entering < 0 {
				return true
			}
			leaving, bestRatio, bestBasis := -1, exact.Zero(), 0
			for r := 0; r < m; r++ {
				if table[r][entering].Sign() <= 0 {
					continue
				}
				ratio, ok := table[r][width].Div(table[r][entering])
				if !ok {
					continue
				}
				if leaving < 0 || ratio.Less(bestRatio) ||
					(ratio.Equal(bestRatio) && basis[r] < bestBasis) {
					leaving, bestRatio, bestBasis = r, ratio, basis[r]
				}
			}
			if leaving < 0 {
				return false
			}
			pivot(objective, leaving, entering)
		}
	}

	// ---- phase one: minimise the sum of the artificials
	phase := make([]exact.Q, width+1)
	for k := range phase {
		phase[k] = zero
	}
	for j := 0; j < m; j++ {
		phase[artificial+j] = one
	}
	for r := 0; r < m; r++ {
		for k := 0; k <= width; k++ {
			phase[k] = phase[k].Sub(table[r][k])
		}
	}
	run(phase, artificial)

	if phase[width].Neg().Sign() > 0 {
		// INFEASIBLE. y_j is the simplex multiplier on row j. After phase one the objective
		// row holds each artificial's REDUCED cost, which is `1 - y_j` because the
		// artificial's own cost is 1.
		certificate := make([]exact.Q, m)
		for j := 0; j < m; j++ {
			value := one.Sub(phase[artificial+j])
			if flipped[j] {
				value = value.Neg()
			}
			certificate[j] = value
		}
		return Solution{Status: Infeasible, Certificate: certificate}
	}

	// ---- phase two: the real cost, with the artificials pinned out of play
	objective := make([]exact.Q, width+1)
	for k := range objective {
		objective[k] = zero
	}
	copy(objective, cost)
	for r := 0; r < m; r++ {
		if objective[basis[r]].Sign() == 0 {
			continue
		}
		scale := objective[basis[r]]
		for k := 0; k <= width; k++ {
			objective[k] = objective[k].Sub(scale.Mul(table[r][k]))
		}
	}
	if !run(objective, artificial) {
		return Solution{Status: Unbounded}
	}

	point := make([]exact.Q, columns)
	for i := range point {
		point[i] = zero
	}
	for r := 0; r < m; r++ {
		if basis[r] < columns {
			point[basis[r]] = table[r][width]
		}
	}
	return Solution{Status: Optimal, Point: point}
}
