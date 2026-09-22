// Package evaluate turns a lowered proposal into a result. Pure: documents in,
// documents out, nothing fetched and nothing timed.
//
// A verdict alone is not an answer. Every result carries what the verdict cost, the
// sizes that would have met the objective, and the alternatives — because "passes" on
// a hedge that costs four times what selling down would is not the same answer as
// "passes", and a reader who sees only the first word cannot tell them apart.
package evaluate

import (
	"sort"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
	"hedgecheck/engine/pwa"
)

// Version identifies the engine in every result it produces. Two results are equal
// when their canonical bytes match after removing this one key.
const Version = "go-engine-1"

// Evaluate answers one lowered proposal.
func Evaluate(ir doc.IR) (doc.Result, error) {
	lower, upper := ir.Domain.Lower, ir.Domain.Upper
	baseline := ir.Baseline.Price
	quantity := ir.Exposure.Quantity

	exposure := pwa.Linear(quantity, baseline)
	premium := exact.Zero()
	for _, leg := range ir.Legs {
		premium = premium.Add(legCost(leg))
	}
	other := ir.OtherCosts

	// A reduced leg is valued at zero in the lower profile. Its premium still counts:
	// it was paid whatever the leg turns out to be worth.
	//
	// A TOUCH-BOUNDED LEG IS KEPT, NOT ZEROED, for the same reason a banded group is: its
	// `pays_on` already IS the bound, the inclusive terminal digital at the target on the
	// side the reference must travel. Zeroing it would discard the bound and make a sound
	// lower bound worth exactly as much as none.
	//
	// A ZEROING RULE WINS over the bound, though. `deployer_settled` says the leg may pay
	// nothing at any price, and every live touch instance is deployer-settled. The lower of
	// the two is the one a verdict may rest on: crediting the bound over a zeroing rule
	// would raise the lower profile on a leg that may pay nothing, which is the one
	// direction that can turn a failing proposal into a passing one.
	zeroed := map[string]bool{}
	loose := map[string]bool{}
	bounded := map[string]bool{}
	zeroing := map[string]bool{}
	for _, reduction := range ir.Reductions {
		if reduction.Rule == "price_touch" {
			bounded[reduction.Leg] = true
		} else {
			zeroing[reduction.Leg] = true
		}
		if !reduction.Tight {
			loose[reduction.Leg] = true
		}
	}
	for leg := range zeroing {
		delete(bounded, leg)
	}
	for _, reduction := range ir.Reductions {
		if !bounded[reduction.Leg] {
			zeroed[reduction.Leg] = true
		}
	}

	parts := []pwa.Fn{exposure, pwa.Cash(premium.Add(other).Neg())}

	// A BAND REDUCTION IS BANDED, NOT ZEROED.
	//
	// Every other reduction worst-cases its leg to zero. A declared basis bound says more:
	// the group is observed on another series that cannot move more than `b` away, so it is
	// worth the infimum of its SUMMED payoff over [S-b, S+b]. Zeroing it would discard the
	// bound and make a declared bound worth exactly as much as none.
	//
	// GROUPED. The infimum of a sum is not the sum of infima: two legs whose payoffs cancel
	// have a flat sum no basis move can hurt, while each alone is stepped.
	banded := map[string]bool{}
	var bandParts, unbandedParts []pwa.Fn
	for _, reduction := range ir.Reductions {
		if reduction.Rule != "basis_band" || !reduction.HasBound() {
			continue
		}
		members := map[string]bool{reduction.Leg: true}
		for _, other := range reduction.With {
			members[other] = true
		}
		var group []pwa.Fn
		for _, leg := range ir.Legs {
			if !members[leg.ID] {
				continue
			}
			banded[leg.ID] = true
			fn, err := legFn(leg)
			if err != nil {
				return doc.Result{}, err
			}
			group = append(group, fn)
		}
		eroded, err := pwa.Sum(group...).BandInfimum(reduction.Bound)
		if err != nil {
			return doc.Result{}, err
		}
		bandParts = append(bandParts, eroded)
		// The best a banded group can be worth is its UNBANDED payoff, not its size, so the
		// upper profile takes the pieces themselves.
		unbandedParts = append(unbandedParts, group...)
	}
	parts = append(parts, bandParts...)

	ceiling := exact.Zero()
	for _, leg := range ir.Legs {
		if banded[leg.ID] {
			continue
		}
		if zeroed[leg.ID] {
			// A long fully collateralized token is worth at most its size, so the upper
			// profile credits a reduced leg with exactly that.
			ceiling = ceiling.Add(leg.Size)
			continue
		}
		fn, err := legFn(leg)
		if err != nil {
			return doc.Result{}, err
		}
		parts = append(parts, fn)
	}
	pnl := pwa.Sum(parts...)
	upperPnl := pnl
	if ceiling.Sign() != 0 {
		upperPnl = pnl.Add(pwa.Cash(ceiling))
	}
	if len(unbandedParts) > 0 {
		// Add the unbanded payoff and remove the banded one, so the upper profile is the
		// group at its best rather than at its worst.
		upperParts := append([]pwa.Fn{upperPnl}, unbandedParts...)
		for _, part := range bandParts {
			upperParts = append(upperParts, part.Neg())
		}
		upperPnl = pwa.Sum(upperParts...)
	}
	// A TOUCH-BOUNDED leg's upper bound is its FULL SIZE, not the bound. The bound pays
	// only where the terminal price proves a touch; the leg pays on every path that ever
	// reached the target, retraces included. So below the target the true payoff may still
	// be the whole size, and an upper profile agreeing with the bound there would claim to
	// know the path. The correction is size less the bound, non-negative everywhere.
	for _, leg := range ir.Legs {
		if !bounded[leg.ID] {
			continue
		}
		fn, err := legFn(leg)
		if err != nil {
			return doc.Result{}, err
		}
		upperPnl = pwa.Sum(upperPnl, pwa.Cash(leg.Size), fn.Neg())
	}

	failing, undecided, codes := []doc.FailingInterval{}, []doc.FailingInterval{}, []string{}
	for _, clause := range ir.Objective {
		clauseLower, clauseUpper := lower, upper
		if clause.On != nil {
			clauseLower, clauseUpper = clause.On.Lower, clause.On.Upper
		}
		for _, interval := range pnl.Below(clause.MinPnl, clauseLower, clauseUpper) {
			entryFor := func(part pwa.Interval) doc.FailingInterval {
				price, value := pnl.Witness(part)
				return doc.FailingInterval{
					Interval: doc.Interval{
						Lower: part.Lo, LowerIncl: part.LoInclusive,
						Upper: part.Hi, UpperIncl: part.HiInclusive,
					},
					Clause:  clause.ID,
					Witness: doc.NewWitness(price, value),
				}
			}
			// The upper profile is the best the proposal could be. Where it also violates
			// the clause, the failure is real whatever the loose legs are worth. Where it
			// does not, the violation rests only on a loose bound, which proves nothing:
			// that is needs_review, never fails.
			var established []pwa.Interval
			if len(loose) > 0 {
				established = upperPnl.Below(clause.MinPnl, interval.Lo, interval.Hi)
				if len(established) == 0 {
					entry := entryFor(interval)
					entry.SetResponsible(sortedKeys(loose))
					undecided = append(undecided, entry)
					continue
				}
			} else {
				established = []pwa.Interval{interval}
			}
			// A FAILURE IS REPORTED ONLY WHERE IT IS ESTABLISHED, witness included. The
			// lower profile can violate across a wider span than the upper one, and that
			// surplus rests on the loose bound alone; a witness drawn from the whole lower
			// interval can land there, naming a price whose best case MEETS the clause.
			for _, part := range established {
				entry := entryFor(part)
				if len(zeroed) > 0 {
					entry.Witness.SetAdverseStates(adverseStates(ir.Reductions))
				}
				failing = append(failing, entry)
			}
		}
	}
	if len(failing) > 0 {
		codes = append(codes, "LOSS_BOUND_EXCEEDED")
	}
	for _, reduction := range ir.Reductions {
		if !contains(codes, reduction.ReasonCode) {
			codes = append(codes, reduction.ReasonCode)
		}
	}
	// Sorted, not joined: see ARCHITECTURE section 4. The verdict code and the
	// reduction codes come from two loops, so their meeting order means nothing.
	sort.Strings(codes)

	verdict := "passes"
	switch {
	case len(failing) > 0:
		verdict = "fails"
	case len(undecided) > 0:
		verdict = "needs_review"
	}

	worstValue, worstAttained, worstAt := pnl.Infimum(lower, upper)
	bareValue, _, bareAt := exposure.Infimum(lower, upper)
	cap := ir.Objective[0].MinPnl
	for _, clause := range ir.Objective {
		cap = exact.Min(cap, clause.MinPnl)
	}

	// The smallest exposure reduction meeting the same clauses, with no premium.
	keep := smallestReduction(quantity, baseline, cap, lower)
	reduced := pwa.Linear(keep, baseline)
	reducedValue, _, reducedAt := reduced.Infimum(lower, upper)

	result := doc.Result{
		SchemaVersion:          "1",
		Units:                  ir.Units,
		ModelResult:            verdict,
		ExecutionReadiness:     "not_evaluated",
		EvaluationScope:        "exhaustive_supported_terminal_model",
		Baseline:               ir.Baseline,
		ObjectiveValuationTime: ir.ObjectiveValuationTime,
		LegObservationTimes:    observationTimes(ir.Legs),
		WorstCase:              doc.NewWorstCase(worstValue, worstAt, worstAttained),
		FailingIntervals:       failing,
		Profile:                pieces(pnl.Profile(lower, upper)),
		Cost: doc.CostSummary{
			Premium: premium, OtherCosts: other,
			PnlAtBaseline: pnl.At(baseline),
			Breakevens:    breakevens(pnl, lower, upper),
		},
		Comparisons: doc.Comparisons{
			NoHedge: doc.NoHedge{
				WorstCase:        doc.NewWorstCaseNoAttained(bareValue, bareAt),
				FailingIntervals: intervals(exposure.Below(cap, lower, upper)),
				ProposalBetter:   intervals(exposure.Sub(pnl).Below(exact.Zero(), lower, upper)),
				ProposalWorse:    intervals(pnl.Sub(exposure).Below(exact.Zero(), lower, upper)),
			},
			SmallestReduction: doc.SmallestReduction{
				KeepQuantity: keep, SellQuantity: quantity.Sub(keep), SellAt: baseline,
				WorstCase:      doc.NewWorstCaseNoAttained(reducedValue, reducedAt),
				ProposalBetter: intervals(reduced.Sub(pnl).Below(exact.Zero(), lower, upper)),
				ProposalWorse:  intervals(pnl.Sub(reduced).Below(exact.Zero(), lower, upper)),
			},
		},
		ReasonCodes:        codes,
		Assumptions:        ir.Assumptions,
		ChecksNotPerformed: []string{"LIVE_EXECUTION", "PATH_RISK"},
		EngineVersion:      Version,
	}
	if len(undecided) > 0 {
		result.SetUndecided(undecided)
	}
	if len(ir.Reductions) > 0 {
		result.SetReductions(ir.Reductions)
		result.SetUpperProfile(pieces(upperPnl.Profile(lower, upper)))
	}
	// A BANDED leg is still sized. Only a leg valued at ZERO is skipped: a band leaves a
	// real payoff to size against, and the reference oracle sizes one too. `zeroed` here
	// includes every reduction, so the banded ones are taken back out -- matching how the
	// lower profile above treats them.
	sizable := map[string]bool{}
	for id := range zeroed {
		if !banded[id] {
			sizable[id] = true
		}
	}
	windows, err := sizeWindows(ir, sizable, baseline, cap, lower, upper)
	if err != nil {
		return doc.Result{}, err
	}
	if len(windows) > 0 {
		result.SetSizeWindows(windows)
	}
	result.SetSnapshots(snapshotsOf(ir))
	if ir.Capture != nil {
		capture := *ir.Capture
		result.Capture = &capture
	}
	digest, err := doc.IRDigest(ir)
	if err != nil {
		return doc.Result{}, err
	}
	result.IRDigest = digest
	return result, nil
}

// smallestReduction is the largest holding that still meets the cap, so the smallest
// sale that does: keep = -cap / (baseline - lower), capped at what is held.
func smallestReduction(quantity, baseline, cap, lower exact.Q) exact.Q {
	span := baseline.Sub(lower)
	if span.Sign() == 0 {
		return quantity
	}
	keep, ok := cap.Neg().Div(span)
	if !ok {
		return quantity
	}
	return exact.Min(keep, quantity)
}

func legCost(leg doc.Leg) exact.Q {
	if leg.Premium.Kind == "walked" {
		return leg.Premium.Total
	}
	return leg.Size.Mul(leg.Premium.Price)
}

func legFn(leg doc.Leg) (pwa.Fn, error) {
	switch leg.Kind {
	case "indicator":
		lo, hi := pwa.NegInf(), pwa.PosInf()
		if leg.PaysOn.Lower.Present {
			lo = pwa.Finite(leg.PaysOn.Lower.Value, leg.PaysOn.Lower.Inclusive)
		}
		if leg.PaysOn.Upper.Present {
			hi = pwa.Finite(leg.PaysOn.Upper.Value, leg.PaysOn.Upper.Inclusive)
		}
		return pwa.Indicator(leg.Size, lo, hi)
	case "ramp":
		if leg.Direction == "short" {
			return pwa.RampShort(leg.Size, leg.Low, leg.High)
		}
		return pwa.RampLong(leg.Size, leg.Low, leg.High)
	}
	return pwa.Fn{}, &doc.Error{Path: leg.ID, Why: "unsupported leg kind " + leg.Kind}
}

func sizeWindows(ir doc.IR, zeroed map[string]bool, baseline, cap, lower, upper exact.Q) ([]doc.SizeWindow, error) {
	out := []doc.SizeWindow{}
	for _, leg := range ir.Legs {
		if zeroed[leg.ID] || leg.Premium.Kind != "walked" || len(leg.Premium.Levels) == 0 {
			continue
		}
		// This leg is the one being sized, so everything else is the base.
		parts := []pwa.Fn{pwa.Linear(ir.Exposure.Quantity, baseline)}
		otherCost := exact.Zero()
		for _, sibling := range ir.Legs {
			if sibling.ID == leg.ID {
				continue
			}
			otherCost = otherCost.Add(legCost(sibling))
			if zeroed[sibling.ID] {
				continue
			}
			fn, err := legFn(sibling)
			if err != nil {
				return nil, err
			}
			parts = append(parts, fn)
		}
		parts = append(parts, pwa.Cash(otherCost.Add(ir.OtherCosts).Neg()))
		base := pwa.Sum(parts...)

		unit := leg
		unit.Size = exact.One()
		unitFn, err := legFn(unit)
		if err != nil {
			return nil, err
		}
		levels := make([]pwa.Level, 0, len(leg.Premium.Levels))
		for _, level := range leg.Premium.Levels {
			levels = append(levels, pwa.Level{Price: level.Price, Size: level.Size})
		}
		window, err := pwa.SizeWindowFor(base, unitFn, levels, cap, lower, upper, exact.One())
		if err != nil {
			return nil, err
		}
		entry := doc.SizeWindow{Leg: leg.ID, Status: "nonempty"}
		if window.Empty {
			entry.Status = "empty"
		}
		for _, site := range window.Binding {
			entry.Binding = append(entry.Binding, doc.Site{Price: site.Price, Side: site.Side})
		}
		if entry.Binding == nil {
			entry.Binding = []doc.Site{}
		}
		if !window.NoBounds {
			entry.SetBounds(window.LowerBound, window.UpperBound)
		}
		if window.HasWhole {
			entry.SetWhole(window.Smallest, window.Largest)
		} else if len(levels) == 1 {
			// One flat price: the infeasibility has a two-line certificate. Weighting the
			// strike and floor constraints by (1-p, p) cancels the size and leaves a
			// statement that is false whatever the size is.
			price := levels[0].Price
			entry.Certificate = &doc.Certificate{
				Kind:    "farkas",
				Weights: []exact.Q{exact.One().Sub(price), price},
			}
		}
		out = append(out, entry)
	}
	return out, nil
}

func breakevens(fn pwa.Fn, lower, upper exact.Q) []exact.Q {
	out := []exact.Q{}
	for _, piece := range fn.Profile(lower, upper) {
		if piece.Slope.Sign() == 0 {
			continue
		}
		root, ok := piece.Intercept.Neg().Div(piece.Slope)
		if !ok {
			continue
		}
		inside := piece.Lo.Value.Less(root) && root.Less(piece.Hi.Value)
		inside = inside || (root.Equal(piece.Lo.Value) && piece.Lo.Closed)
		inside = inside || (root.Equal(piece.Hi.Value) && piece.Hi.Closed)
		if inside {
			out = append(out, root)
		}
	}
	return out
}

func pieces(from []pwa.Piece) []doc.Piece {
	out := make([]doc.Piece, 0, len(from))
	for _, piece := range from {
		out = append(out, doc.Piece{
			Interval: doc.Interval{
				Lower: piece.Lo.Value, LowerIncl: piece.Lo.Closed,
				Upper: piece.Hi.Value, UpperIncl: piece.Hi.Closed,
			},
			Slope: piece.Slope, Intercept: piece.Intercept,
		})
	}
	return out
}

func intervals(from []pwa.Interval) []doc.Interval {
	out := make([]doc.Interval, 0, len(from))
	for _, interval := range from {
		out = append(out, doc.Interval{
			Lower: interval.Lo, LowerIncl: interval.LoInclusive,
			Upper: interval.Hi, UpperIncl: interval.HiInclusive,
		})
	}
	return out
}

func observationTimes(legs []doc.Leg) []string {
	out := make([]string, 0, len(legs))
	for _, leg := range legs {
		out = append(out, leg.ObservationTime)
	}
	return out
}

// adverseStates says why a witness is admissible once a leg has been bounded. The
// wording is part of the contract: two implementations must produce the same string.
var adverseWording = map[string]string{
	"price_touch":       "the leg pays only where the terminal price proves a touch",
	"horizon_mismatch":  "the leg's own observation pays zero",
	"unreviewed_family": "nothing is established about what the leg pays",
	"deployer_settled":  "the deployer chooses what the leg pays",
}

func adverseStates(reductions []doc.Reduction) []doc.AdverseState {
	out := make([]doc.AdverseState, 0, len(reductions))
	for _, reduction := range reductions {
		state, known := adverseWording[reduction.Rule]
		if !known {
			state = "the leg is valued at zero"
		}
		out = append(out, doc.AdverseState{Leg: reduction.Leg, Rule: reduction.Rule, State: state})
	}
	return out
}

func snapshotsOf(ir doc.IR) []string {
	seen := map[string]bool{}
	if ir.Baseline.Kind == "analysis_time" && ir.Baseline.Snapshot != "" {
		seen[ir.Baseline.Snapshot] = true
	}
	for _, leg := range ir.Legs {
		if leg.Premium.Kind == "walked" && leg.Premium.Snapshot != "" {
			seen[leg.Premium.Snapshot] = true
		}
	}
	return sortedKeys(seen)
}

func sortedKeys(set map[string]bool) []string {
	out := make([]string, 0, len(set))
	for key := range set {
		out = append(out, key)
	}
	sort.Strings(out)
	return out
}

func contains(values []string, needle string) bool {
	for _, value := range values {
		if value == needle {
			return true
		}
	}
	return false
}
