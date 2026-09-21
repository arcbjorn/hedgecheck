package doc

import (
	"hedgecheck/engine/canon"
	"hedgecheck/engine/exact"
)

// AdverseState says why a witness is admissible once a leg has been bounded: which
// leg, which rule bounded it, and the state that rule assumes. A price alone stops
// being a counterexample the moment anything was worst-cased.
type AdverseState struct{ Leg, Rule, State string }

// Witness is a price the objective is violated at, with the value there.
type Witness struct {
	Price, Pnl    exact.Q
	AdverseStates []AdverseState
	hasAdverse    bool
}

// FailingInterval is a run of prices that violate one clause, with a witness inside.
type FailingInterval struct {
	Interval
	Clause          string
	Witness         Witness
	ResponsibleLegs []string
	hasResponsible  bool
}

// Piece is one affine segment of a payoff profile.
type Piece struct {
	Interval
	Slope, Intercept exact.Q
}

// WorstCase is the lowest P&L on the domain and where it happens.
type WorstCase struct {
	Pnl, Price  exact.Q
	Attained    bool
	hasAttained bool
}

// Cost is what the verdict cost: the premium, other costs, the P&L if nothing moves,
// and where the profile crosses zero.
type CostSummary struct {
	Premium, OtherCosts, PnlAtBaseline exact.Q
	Breakevens                         []exact.Q
}

// Site is a price and the side of it that a size constraint binds at.
type Site struct {
	Price exact.Q
	Side  string
}

// Certificate proves no size works, by weights that cancel the size term.
type Certificate struct {
	Kind    string
	Weights []exact.Q
}

// SizeWindow is the set of sizes of one leg that meet every clause.
type SizeWindow struct {
	Leg                    string
	Status                 string
	LowerBound, UpperBound exact.Q
	hasBounds              bool
	Smallest, Largest      exact.Q
	hasWhole               bool
	Binding                []Site
	Certificate            *Certificate
}

// NoHedge is the same objective with no hedge at all.
type NoHedge struct {
	WorstCase        WorstCase
	FailingIntervals []Interval
	ProposalBetter   []Interval
	ProposalWorse    []Interval
}

// SmallestReduction is the no-premium alternative: sell down to what meets the cap.
type SmallestReduction struct {
	KeepQuantity, SellQuantity, SellAt exact.Q
	WorstCase                          WorstCase
	ProposalBetter                     []Interval
	ProposalWorse                      []Interval
}

// Comparisons are the alternatives every result carries, never the verdict alone.
type Comparisons struct {
	NoHedge           NoHedge
	SmallestReduction SmallestReduction
}

// OrderEnvelope is the order a depth-priced cost bound assumes.
//
// The bound is about ONE order. A walk of 924 contracts down the asks says what those
// 924 cost at the prices the book displayed, and nothing whatever about 925, about a
// limit below the last level it touched, or about an order left resting until the book
// has moved. The envelope writes that order down so a gate places it rather than
// guessing at it, and carries the InputDigest of the result it belongs to so it cannot
// be carried to a different answer.
type OrderEnvelope struct {
	Coin        string
	Side        string // always "buy"
	Size        exact.Q
	LimitPrice  exact.Q
	TimeInForce string // always "Ioc"
	MaxCost     exact.Q
	InputDigest string
}

// Result is one complete answer: the verdict, what it cost, and what else was possible.
type Result struct {
	SchemaVersion          string
	Units                  Units
	ModelResult            string
	ExecutionReadiness     string
	EvaluationScope        string
	Baseline               Baseline
	ObjectiveValuationTime string
	LegObservationTimes    []string
	WorstCase              WorstCase
	FailingIntervals       []FailingInterval
	UndecidedIntervals     []FailingInterval
	hasUndecided           bool
	Profile                []Piece
	UpperProfile           []Piece
	hasUpperProfile        bool
	Cost                   CostSummary
	Comparisons            Comparisons
	SizeWindows            []SizeWindow
	hasSizeWindows         bool
	Reductions             []Reduction
	hasReductions          bool
	ReasonCodes            []string
	Assumptions            []string
	ChecksNotPerformed     []string
	EngineVersion          string
	IRDigest               string
	ProposalDigest         string
	hasProposalDigest      bool
	InputDigest            string
	hasInputDigest         bool
	SemanticsVersion       []string
	hasSemanticsVersion    bool
	Snapshots              []string
	hasSnapshots           bool
	Capture                *Capture
	OrderEnvelope          *OrderEnvelope
}

// ReadResult decodes a result from canonical bytes.
func ReadResult(raw []byte) (Result, error) {
	value, err := parse(raw)
	if err != nil {
		return Result{}, err
	}
	return decodeResult("", value)
}

func decodeResult(path string, value any) (Result, error) {
	r, err := object(path, value)
	if err != nil {
		return Result{}, err
	}
	out := Result{}
	out.SchemaVersion = r.str("schema_version", nil, "")
	if out.SchemaVersion != "" && out.SchemaVersion != "1" {
		r.note(fail(r.at("schema_version"), "unsupported schema version %q", out.SchemaVersion))
	}
	out.Units = readUnits(r)
	out.ModelResult = r.enum("model_result", "passes", "fails", "needs_review")
	out.ExecutionReadiness = r.str("execution_readiness", nil, "")
	out.EvaluationScope = r.str("evaluation_scope", nil, "")
	out.Baseline = readBaseline(r)
	out.ObjectiveValuationTime = r.str("objective_valuation_time", timePattern, "a UTC instant ending in Z")
	out.LegObservationTimes = readTimes(r, "leg_observation_times")
	out.WorstCase = readWorstCase(r, "worst_case")
	out.FailingIntervals = readFailingIntervals(r, "failing_intervals", true)
	out.UndecidedIntervals, out.hasUndecided = readOptionalFailing(r, "undecided_intervals")
	out.Profile = readPieces(r, "profile", true)
	upper, hasUpper := readOptionalPieces(r, "upper_profile")
	out.UpperProfile, out.hasUpperProfile = upper, hasUpper
	out.Cost = readCostSummary(r)
	out.Comparisons = readComparisons(r)
	out.SizeWindows, out.hasSizeWindows = readSizeWindows(r)
	out.Reductions = readReductions(r)
	out.hasReductions = out.Reductions != nil
	out.ReasonCodes = readCodes(r, "reason_codes")
	out.Assumptions = readSlugs(r, "assumptions")
	out.ChecksNotPerformed = readCodes(r, "checks_not_performed")
	out.EngineVersion = r.str("engine_version", nil, "")
	out.IRDigest = r.str("ir_digest", digestPattern, "a SHA-256")
	out.ProposalDigest, out.hasProposalDigest = r.optionalStr("proposal_digest", digestPattern, "a SHA-256")
	out.InputDigest, out.hasInputDigest = r.optionalStr("input_digest", digestPattern, "a SHA-256")
	out.SemanticsVersion, out.hasSemanticsVersion = readOptionalDigests(r, "semantics_version")
	out.Snapshots, out.hasSnapshots = readOptionalDigests(r, "snapshots")
	out.Capture = readCapture(r)
	out.OrderEnvelope = readOrderEnvelope(r)
	return out, r.done()
}

func readOrderEnvelope(r *reader) *OrderEnvelope {
	child, present := r.optionalSub("order_envelope")
	if !present || child == nil {
		return nil
	}
	out := OrderEnvelope{
		Coin:        child.str("coin", coinPattern, "the venue's own instrument id"),
		Side:        child.enum("side", "buy"),
		Size:        child.number("size"),
		LimitPrice:  child.number("limit_price"),
		TimeInForce: child.enum("time_in_force", "Ioc"),
		MaxCost:     child.number("max_cost"),
		InputDigest: child.str("input_digest", digestPattern, "a SHA-256"),
	}
	r.finish(child)
	return &out
}

func readTimes(r *reader, key string) []string {
	out := []string{}
	for index, item := range r.list(key, 0) {
		text, ok := item.(string)
		if !ok || !timePattern.MatchString(text) {
			r.note(fail(at2(r.path, key, index), "a UTC instant ending in Z"))
			break
		}
		out = append(out, text)
	}
	return out
}

func readCodes(r *reader, key string) []string {
	out := []string{}
	for index, item := range r.list(key, 0) {
		text, ok := item.(string)
		if !ok || !codePattern.MatchString(text) {
			r.note(fail(at2(r.path, key, index), "an upper-case code"))
			break
		}
		out = append(out, text)
	}
	return out
}

func readSlugs(r *reader, key string) []string {
	out := []string{}
	for index, item := range r.list(key, 0) {
		text, ok := item.(string)
		if !ok || !slugPattern.MatchString(text) {
			r.note(fail(at2(r.path, key, index), "a slug"))
			break
		}
		out = append(out, text)
	}
	return out
}

func readOptionalDigests(r *reader, key string) ([]string, bool) {
	items, present := r.optionalList(key, 0)
	if !present {
		return nil, false
	}
	out := []string{}
	for index, item := range items {
		text, ok := item.(string)
		if !ok || !digestPattern.MatchString(text) {
			r.note(fail(at2(r.path, key, index), "a SHA-256"))
			break
		}
		out = append(out, text)
	}
	return out, true
}

func readWorstCase(r *reader, key string) WorstCase {
	child, ok := r.sub(key)
	if !ok {
		return WorstCase{}
	}
	out := WorstCase{Pnl: child.number("pnl"), Price: child.number("price")}
	out.Attained, out.hasAttained = child.optionalBool("attained")
	r.finish(child)
	return out
}

func readIntervalList(r *reader, key string) []Interval {
	out := []Interval{}
	for index, item := range r.list(key, 0) {
		child, err := object(at2(r.path, key, index), item)
		if err != nil {
			r.note(err)
			break
		}
		interval := readInterval(child)
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, interval)
	}
	return out
}

func readFailingIntervals(r *reader, key string, required bool) []FailingInterval {
	var items []any
	if required {
		items = r.list(key, 0)
	} else {
		items, _ = r.optionalList(key, 0)
	}
	out := []FailingInterval{}
	for index, item := range items {
		child, err := object(at2(r.path, key, index), item)
		if err != nil {
			r.note(err)
			break
		}
		entry := FailingInterval{Interval: readInterval(child)}
		entry.Clause = child.str("clause", slugPattern, "a slug")
		if witness, ok := child.sub("witness"); ok {
			entry.Witness = readWitness(witness)
			child.finish(witness)
		}
		if legs, present := child.optionalList("responsible_legs", 0); present {
			entry.hasResponsible = true
			for legIndex, leg := range legs {
				text, ok := leg.(string)
				if !ok || !legIDPattern.MatchString(text) {
					child.note(fail(at2(child.path, "responsible_legs", legIndex), "a leg id"))
					break
				}
				entry.ResponsibleLegs = append(entry.ResponsibleLegs, text)
			}
		}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, entry)
	}
	return out
}

func readOptionalFailing(r *reader, key string) ([]FailingInterval, bool) {
	if _, present := r.fields[key]; !present {
		return nil, false
	}
	return readFailingIntervals(r, key, false), true
}

func readWitness(child *reader) Witness {
	out := Witness{Price: child.number("price"), Pnl: child.number("pnl")}
	states, present := child.optionalList("adverse_states", 0)
	if !present {
		return out
	}
	out.hasAdverse = true
	for index, item := range states {
		state, err := object(at2(child.path, "adverse_states", index), item)
		if err != nil {
			child.note(err)
			break
		}
		out.AdverseStates = append(out.AdverseStates, AdverseState{
			Leg:   state.str("leg", legIDPattern, "a leg id"),
			Rule:  state.str("rule", slugPattern, "a slug"),
			State: state.str("state", nil, ""),
		})
		if err := state.done(); err != nil {
			child.note(err)
			break
		}
	}
	return out
}

func readPieces(r *reader, key string, required bool) []Piece {
	var items []any
	if required {
		items = r.list(key, 1)
	} else {
		items, _ = r.optionalList(key, 1)
	}
	out := []Piece{}
	for index, item := range items {
		child, err := object(at2(r.path, key, index), item)
		if err != nil {
			r.note(err)
			break
		}
		piece := Piece{Interval: readInterval(child), Slope: child.number("slope"), Intercept: child.number("intercept")}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, piece)
	}
	return out
}

func readOptionalPieces(r *reader, key string) ([]Piece, bool) {
	if _, present := r.fields[key]; !present {
		return nil, false
	}
	return readPieces(r, key, false), true
}

func readCostSummary(r *reader) CostSummary {
	child, ok := r.sub("cost")
	if !ok {
		return CostSummary{}
	}
	out := CostSummary{
		Premium:       child.number("premium"),
		OtherCosts:    child.number("other_costs"),
		PnlAtBaseline: child.number("pnl_at_baseline"),
		Breakevens:    []exact.Q{},
	}
	for index, item := range child.list("breakevens", 0) {
		text, ok := item.(string)
		if !ok {
			child.note(fail(at2(child.path, "breakevens", index), "a number travels as a string"))
			break
		}
		number, err := exact.ParseQ(text)
		if err != nil {
			child.note(fail(at2(child.path, "breakevens", index), "not in the number grammar"))
			break
		}
		out.Breakevens = append(out.Breakevens, number)
	}
	r.finish(child)
	return out
}

func readComparisons(r *reader) Comparisons {
	child, ok := r.sub("comparisons")
	if !ok {
		return Comparisons{}
	}
	out := Comparisons{}
	if noHedge, ok := child.sub("no_hedge"); ok {
		out.NoHedge = NoHedge{
			WorstCase:        readWorstCase(noHedge, "worst_case"),
			FailingIntervals: readIntervalList(noHedge, "failing_intervals"),
			ProposalBetter:   readIntervalList(noHedge, "proposal_better"),
			ProposalWorse:    readIntervalList(noHedge, "proposal_worse"),
		}
		child.finish(noHedge)
	}
	if reduction, ok := child.sub("smallest_reduction"); ok {
		out.SmallestReduction = SmallestReduction{
			KeepQuantity:   reduction.number("keep_quantity"),
			SellQuantity:   reduction.number("sell_quantity"),
			SellAt:         reduction.number("sell_at"),
			WorstCase:      readWorstCase(reduction, "worst_case"),
			ProposalBetter: readIntervalList(reduction, "proposal_better"),
			ProposalWorse:  readIntervalList(reduction, "proposal_worse"),
		}
		child.finish(reduction)
	}
	r.finish(child)
	return out
}

func readSizeWindows(r *reader) ([]SizeWindow, bool) {
	items, present := r.optionalList("size_windows", 0)
	if !present {
		return nil, false
	}
	out := []SizeWindow{}
	for index, item := range items {
		child, err := object(at2(r.path, "size_windows", index), item)
		if err != nil {
			r.note(err)
			break
		}
		window := SizeWindow{
			Leg:    child.str("leg", legIDPattern, "a leg id"),
			Status: child.enum("status", "nonempty", "empty"),
		}
		lower, hasLower := child.optionalNumber("lower_bound")
		upper, hasUpper := child.optionalNumber("upper_bound")
		if hasLower != hasUpper {
			child.note(fail(child.path, "a bound without its partner"))
		}
		window.LowerBound, window.UpperBound, window.hasBounds = lower, upper, hasLower
		smallest, hasSmallest := child.optionalNumber("smallest")
		largest, hasLargest := child.optionalNumber("largest")
		if hasSmallest != hasLargest {
			child.note(fail(child.path, "a smallest size without a largest"))
		}
		window.Smallest, window.Largest, window.hasWhole = smallest, largest, hasSmallest
		for siteIndex, siteItem := range child.list("binding", 0) {
			site, err := object(at2(child.path, "binding", siteIndex), siteItem)
			if err != nil {
				child.note(err)
				break
			}
			window.Binding = append(window.Binding, Site{
				Price: site.number("price"),
				Side:  site.enum("side", "at", "above", "below"),
			})
			if err := site.done(); err != nil {
				child.note(err)
				break
			}
		}
		if certificate, present := child.optionalSub("certificate"); present && certificate != nil {
			cert := Certificate{Kind: certificate.enum("kind", "farkas")}
			for weightIndex, weightItem := range certificate.list("weights", 2) {
				text, ok := weightItem.(string)
				if !ok {
					certificate.note(fail(at2(certificate.path, "weights", weightIndex), "a number travels as a string"))
					break
				}
				number, err := exact.ParseQ(text)
				if err != nil {
					certificate.note(fail(at2(certificate.path, "weights", weightIndex), "not in the number grammar"))
					break
				}
				cert.Weights = append(cert.Weights, number)
			}
			window.Certificate = &cert
			child.finish(certificate)
		}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, window)
	}
	return out, true
}

// WriteResult encodes a result as canonical bytes.
func WriteResult(result Result) ([]byte, error) { return canon.Marshal(encodeResult(result)) }

func encodeResult(result Result) map[string]any {
	out := map[string]any{
		"schema_version": result.SchemaVersion,
		"units": map[string]any{
			"money": result.Units.Money, "price": result.Units.Price,
			"exposure": result.Units.Exposure, "size": result.Units.Size,
		},
		"model_result":             result.ModelResult,
		"execution_readiness":      result.ExecutionReadiness,
		"evaluation_scope":         result.EvaluationScope,
		"baseline":                 encodeBaseline(result.Baseline),
		"objective_valuation_time": result.ObjectiveValuationTime,
		"leg_observation_times":    textList(result.LegObservationTimes),
		"worst_case":               encodeWorstCase(result.WorstCase),
		"failing_intervals":        encodeFailing(result.FailingIntervals),
		"profile":                  encodePieces(result.Profile),
		"cost":                     encodeCostSummary(result.Cost),
		"comparisons":              encodeComparisons(result.Comparisons),
		"reason_codes":             textList(result.ReasonCodes),
		"assumptions":              textList(result.Assumptions),
		"checks_not_performed":     textList(result.ChecksNotPerformed),
		"engine_version":           result.EngineVersion,
		"ir_digest":                result.IRDigest,
	}
	setIf(out, result.hasUndecided, "undecided_intervals", encodeFailing(result.UndecidedIntervals))
	setIf(out, result.hasUpperProfile, "upper_profile", encodePieces(result.UpperProfile))
	setIf(out, result.hasSizeWindows, "size_windows", encodeSizeWindows(result.SizeWindows))
	setIf(out, result.hasReductions, "reductions", encodeReductions(result.Reductions))
	setIf(out, result.hasProposalDigest, "proposal_digest", result.ProposalDigest)
	setIf(out, result.hasInputDigest, "input_digest", result.InputDigest)
	setIf(out, result.hasSemanticsVersion, "semantics_version", textList(result.SemanticsVersion))
	setIf(out, result.hasSnapshots, "snapshots", textList(result.Snapshots))
	if result.Capture != nil {
		out["capture"] = map[string]any{
			"skew_ms": result.Capture.SkewMs, "max_skew_ms": result.Capture.MaxSkewMs,
			"measured_by": result.Capture.MeasuredBy,
		}
	}
	if envelope := result.OrderEnvelope; envelope != nil {
		out["order_envelope"] = map[string]any{
			"coin": envelope.Coin, "side": envelope.Side, "size": envelope.Size.String(),
			"limit_price": envelope.LimitPrice.String(), "time_in_force": envelope.TimeInForce,
			"max_cost": envelope.MaxCost.String(), "input_digest": envelope.InputDigest,
		}
	}
	return out
}

func encodeWorstCase(worst WorstCase) map[string]any {
	out := map[string]any{"pnl": worst.Pnl.String(), "price": worst.Price.String()}
	setIf(out, worst.hasAttained, "attained", worst.Attained)
	return out
}

func encodeFailing(intervals []FailingInterval) []any {
	out := make([]any, 0, len(intervals))
	for _, interval := range intervals {
		item := encodeInterval(interval.Interval)
		item["clause"] = interval.Clause
		witness := map[string]any{"price": interval.Witness.Price.String(), "pnl": interval.Witness.Pnl.String()}
		if interval.Witness.hasAdverse {
			states := make([]any, 0, len(interval.Witness.AdverseStates))
			for _, state := range interval.Witness.AdverseStates {
				states = append(states, map[string]any{"leg": state.Leg, "rule": state.Rule, "state": state.State})
			}
			witness["adverse_states"] = states
		}
		item["witness"] = witness
		setIf(item, interval.hasResponsible, "responsible_legs", textList(interval.ResponsibleLegs))
		out = append(out, item)
	}
	return out
}

func encodePieces(pieces []Piece) []any {
	out := make([]any, 0, len(pieces))
	for _, piece := range pieces {
		item := encodeInterval(piece.Interval)
		item["slope"] = piece.Slope.String()
		item["intercept"] = piece.Intercept.String()
		out = append(out, item)
	}
	return out
}

func encodeIntervals(intervals []Interval) []any {
	out := make([]any, 0, len(intervals))
	for _, interval := range intervals {
		out = append(out, encodeInterval(interval))
	}
	return out
}

func encodeCostSummary(cost CostSummary) map[string]any {
	breakevens := make([]any, 0, len(cost.Breakevens))
	for _, value := range cost.Breakevens {
		breakevens = append(breakevens, value.String())
	}
	return map[string]any{
		"premium": cost.Premium.String(), "other_costs": cost.OtherCosts.String(),
		"pnl_at_baseline": cost.PnlAtBaseline.String(), "breakevens": breakevens,
	}
}

func encodeComparisons(comparisons Comparisons) map[string]any {
	return map[string]any{
		"no_hedge": map[string]any{
			"worst_case":        encodeWorstCase(comparisons.NoHedge.WorstCase),
			"failing_intervals": encodeIntervals(comparisons.NoHedge.FailingIntervals),
			"proposal_better":   encodeIntervals(comparisons.NoHedge.ProposalBetter),
			"proposal_worse":    encodeIntervals(comparisons.NoHedge.ProposalWorse),
		},
		"smallest_reduction": map[string]any{
			"keep_quantity":   comparisons.SmallestReduction.KeepQuantity.String(),
			"sell_quantity":   comparisons.SmallestReduction.SellQuantity.String(),
			"sell_at":         comparisons.SmallestReduction.SellAt.String(),
			"worst_case":      encodeWorstCase(comparisons.SmallestReduction.WorstCase),
			"proposal_better": encodeIntervals(comparisons.SmallestReduction.ProposalBetter),
			"proposal_worse":  encodeIntervals(comparisons.SmallestReduction.ProposalWorse),
		},
	}
}

func encodeSizeWindows(windows []SizeWindow) []any {
	out := make([]any, 0, len(windows))
	for _, window := range windows {
		binding := make([]any, 0, len(window.Binding))
		for _, site := range window.Binding {
			binding = append(binding, map[string]any{"price": site.Price.String(), "side": site.Side})
		}
		item := map[string]any{"leg": window.Leg, "status": window.Status, "binding": binding}
		setIf(item, window.hasBounds, "lower_bound", window.LowerBound.String())
		setIf(item, window.hasBounds, "upper_bound", window.UpperBound.String())
		setIf(item, window.hasWhole, "smallest", window.Smallest.String())
		setIf(item, window.hasWhole, "largest", window.Largest.String())
		if window.Certificate != nil {
			weights := make([]any, 0, len(window.Certificate.Weights))
			for _, weight := range window.Certificate.Weights {
				weights = append(weights, weight.String())
			}
			item["certificate"] = map[string]any{"kind": window.Certificate.Kind, "weights": weights}
		}
		out = append(out, item)
	}
	return out
}
