package doc

import (
	"hedgecheck/engine/exact"
)

// Units names what every quantity in a document is measured in. There is no default:
// a number without its unit is not a quantity.
type Units struct {
	Money, Price, Exposure, Size string
}

// Domain is the closed price range a verdict covers. Both ends belong to it.
type Domain struct{ Lower, Upper exact.Q }

// Bound is one end of an interval, always stating who owns it.
type Bound struct {
	Value     exact.Q
	Present   bool
	Inclusive bool
}

// PaysOn is where an indicator pays. A missing bound is unbounded; a present one
// always says whether its own price is included.
type PaysOn struct{ Lower, Upper Bound }

// Baseline is what the exposure is valued from. Required, never defaulted, because
// the strike and the analysis-time mark give materially different answers.
type Baseline struct {
	Kind     string // "explicit" or "analysis_time"
	Price    exact.Q
	Label    string // explicit only
	Snapshot string // analysis_time only
	Coin     string // analysis_time only
}

// Cost is what a leg cost: a hypothetical per-unit price, or the exact total paid by
// walking a book, carrying the levels it walked.
type Cost struct {
	Kind     string // "fixed" or "walked"
	Price    exact.Q
	Total    exact.Q
	Path     string
	Snapshot string
	Levels   []Level
}

// Level is one rung of displayed depth.
type Level struct{ Price, Size exact.Q }

// Clause is one term of the objective: P&L at least MinPnl, on the whole domain or on
// one interval of it.
type Clause struct {
	ID     string
	MinPnl exact.Q
	On     *Interval
}

// Interval is a price range with explicit ownership of each end.
type Interval struct {
	Lower, Upper         exact.Q
	LowerIncl, UpperIncl bool
}

// Reduction records a lowering rule that lowered a leg's value, and whether the bound
// is tight. A loose bound can make a proposal need review; it can never fail one.
type Reduction struct {
	Leg        string
	Rule       string
	Tight      bool
	ReasonCode string
}

// Capture is how the evidence was gathered, as asserted by whatever gathered it. It
// cannot be re-derived: the contexts response carries no venue timestamp.
type Capture struct {
	SkewMs     string
	MaxSkewMs  string
	MeasuredBy string
}

// Leg is one lowered primitive: an indicator over an interval, or a ramp.
type Leg struct {
	ID              string
	Kind            string // "indicator" or "ramp"
	Size            exact.Q
	PaysOn          PaysOn  // indicator
	Direction       string  // ramp: "long" or "short"
	Low, High       exact.Q // ramp
	Premium         Cost
	ObservationTime string
	Semantics       string
}

// Exposure is the linear holding being hedged.
type Exposure struct {
	Kind     string
	Quantity exact.Q
}

// IR is a lowered proposal: primitives the kernel can evaluate, with nothing left to
// interpret.
type IR struct {
	SchemaVersion          string
	Units                  Units
	Domain                 Domain
	Baseline               Baseline
	Exposure               Exposure
	Legs                   []Leg
	Objective              []Clause
	ObjectiveValuationTime string
	OtherCosts             exact.Q
	Assumptions            []string
	Reductions             []Reduction
	Capture                *Capture
}

// ReadIR decodes a lowered proposal from canonical bytes.
func ReadIR(raw []byte) (IR, error) {
	value, err := parse(raw)
	if err != nil {
		return IR{}, err
	}
	return decodeIR("", value)
}

func decodeIR(path string, value any) (IR, error) {
	r, err := object(path, value)
	if err != nil {
		return IR{}, err
	}
	out := IR{}
	out.SchemaVersion = r.str("schema_version", nil, "")
	if out.SchemaVersion != "" && out.SchemaVersion != "1" {
		r.note(fail(r.at("schema_version"), "unsupported schema version %q", out.SchemaVersion))
	}
	out.Units = readUnits(r)
	out.Domain = readDomain(r)
	out.Baseline = readBaseline(r)
	out.Exposure = readExposure(r)

	for index, item := range r.list("legs", 1) {
		leg, err := decodeLeg(at2(r.path, "legs", index), item)
		if err != nil {
			r.note(err)
			break
		}
		out.Legs = append(out.Legs, leg)
	}
	out.Objective = readObjective(r)
	out.ObjectiveValuationTime = r.str("objective_valuation_time", timePattern, "a UTC instant ending in Z")
	out.OtherCosts = r.number("other_costs")
	for index, item := range r.list("assumptions", 0) {
		text, ok := item.(string)
		if !ok || !slugPattern.MatchString(text) {
			r.note(fail(at2(r.path, "assumptions", index), "an assumption is a slug"))
			break
		}
		out.Assumptions = append(out.Assumptions, text)
	}
	out.Reductions = readReductions(r)
	out.Capture = readCapture(r)
	return out, r.done()
}

func readUnits(r *reader) Units {
	child, ok := r.sub("units")
	if !ok {
		return Units{}
	}
	out := Units{
		Money:    child.str("money", nil, ""),
		Price:    child.str("price", nil, ""),
		Exposure: child.str("exposure", nil, ""),
		Size:     child.str("size", nil, ""),
	}
	r.finish(child)
	return out
}

func readDomain(r *reader) Domain {
	child, ok := r.sub("domain")
	if !ok {
		return Domain{}
	}
	out := Domain{Lower: child.number("lower"), Upper: child.number("upper")}
	r.finish(child)
	return out
}

func readBaseline(r *reader) Baseline {
	child, ok := r.sub("baseline")
	if !ok {
		return Baseline{}
	}
	out := Baseline{Kind: child.enum("kind", "explicit", "analysis_time"), Price: child.number("price")}
	switch out.Kind {
	case "explicit":
		out.Label = child.str("label", nil, "")
	case "analysis_time":
		source, ok := child.sub("source")
		if ok {
			out.Snapshot = source.str("snapshot", digestPattern, "a SHA-256")
			out.Coin = source.str("coin", nil, "")
			child.finish(source)
		}
	}
	r.finish(child)
	return out
}

func readExposure(r *reader) Exposure {
	child, ok := r.sub("exposure")
	if !ok {
		return Exposure{}
	}
	out := Exposure{Kind: child.str("kind", nil, ""), Quantity: child.number("quantity")}
	if out.Quantity.Sign() < 0 {
		child.note(fail(child.at("quantity"), "a quantity is not negative"))
	}
	r.finish(child)
	return out
}

func decodeLeg(path string, value any) (Leg, error) {
	r, err := object(path, value)
	if err != nil {
		return Leg{}, err
	}
	out := Leg{}
	out.ID = r.str("id", legIDPattern, "a leg id")
	out.Kind = r.enum("kind", "indicator", "ramp")
	out.Size = r.number("size")
	switch out.Kind {
	case "indicator":
		out.PaysOn = readPaysOn(r)
	case "ramp":
		out.Direction = r.enum("direction", "long", "short")
		out.Low = r.number("low")
		out.High = r.number("high")
		if out.High.LessEqual(out.Low) {
			r.note(fail(r.at("high"), "a ramp needs high above low"))
		}
	}
	out.Premium = readCost(r, "premium")
	out.ObservationTime = r.str("observation_time", timePattern, "a UTC instant ending in Z")
	out.Semantics = r.str("semantics", nil, "")
	return out, r.done()
}

// readPaysOn enforces the rule no schema keyword states well: a bound and its
// ownership flag travel together, and an indicator pays somewhere.
func readPaysOn(r *reader) PaysOn {
	child, ok := r.sub("pays_on")
	if !ok {
		return PaysOn{}
	}
	out := PaysOn{}
	lower, hasLower := child.optionalNumber("lower")
	lowerIncl, hasLowerIncl := child.optionalBool("lower_inclusive")
	upper, hasUpper := child.optionalNumber("upper")
	upperIncl, hasUpperIncl := child.optionalBool("upper_inclusive")
	if hasLower != hasLowerIncl {
		child.note(fail(child.at("lower"), "a bound and its ownership travel together"))
	}
	if hasUpper != hasUpperIncl {
		child.note(fail(child.at("upper"), "a bound and its ownership travel together"))
	}
	if !hasLower && !hasUpper {
		child.note(fail(child.path, "an indicator pays somewhere in particular"))
	}
	if hasLower && hasUpper && upper.Less(lower) {
		child.note(fail(child.path, "the interval runs backwards"))
	}
	out.Lower = Bound{Value: lower, Present: hasLower, Inclusive: lowerIncl}
	out.Upper = Bound{Value: upper, Present: hasUpper, Inclusive: upperIncl}
	r.finish(child)
	return out
}

func readCost(r *reader, key string) Cost {
	child, ok := r.sub(key)
	if !ok {
		return Cost{}
	}
	out := Cost{Kind: child.enum("kind", "fixed", "walked")}
	switch out.Kind {
	case "fixed":
		out.Price = child.number("price")
	case "walked":
		out.Total = child.number("total")
		out.Path = child.enum("path", "direct_book")
		out.Snapshot = child.str("snapshot", digestPattern, "a SHA-256")
		for index, item := range child.list("levels", 1) {
			pair, ok := item.([]any)
			if !ok || len(pair) != 2 {
				child.note(fail(at2(child.path, "levels", index), "a level is [price, size]"))
				break
			}
			price, priceOK := pair[0].(string)
			size, sizeOK := pair[1].(string)
			if !priceOK || !sizeOK {
				child.note(fail(at2(child.path, "levels", index), "a level's numbers are strings"))
				break
			}
			p, errP := exact.ParseQ(price)
			s, errS := exact.ParseQ(size)
			if errP != nil || errS != nil {
				child.note(fail(at2(child.path, "levels", index), "a level's numbers follow the grammar"))
				break
			}
			out.Levels = append(out.Levels, Level{Price: p, Size: s})
		}
	}
	r.finish(child)
	return out
}

func readObjective(r *reader) []Clause {
	out := []Clause{}
	for index, item := range r.list("objective", 1) {
		child, err := object(at2(r.path, "objective", index), item)
		if err != nil {
			r.note(err)
			break
		}
		clause := Clause{ID: child.str("id", slugPattern, "a slug"), MinPnl: child.number("min_pnl")}
		if on, ok := child.optionalSub("on"); ok && on != nil {
			interval := readInterval(on)
			clause.On = &interval
			child.finish(on)
		}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, clause)
	}
	return out
}

func readInterval(child *reader) Interval {
	return Interval{
		Lower:     child.number("lower"),
		LowerIncl: child.boolean("lower_inclusive"),
		Upper:     child.number("upper"),
		UpperIncl: child.boolean("upper_inclusive"),
	}
}

func readReductions(r *reader) []Reduction {
	items, present := r.optionalList("reductions", 0)
	if !present {
		return nil
	}
	out := []Reduction{}
	for index, item := range items {
		child, err := object(at2(r.path, "reductions", index), item)
		if err != nil {
			r.note(err)
			break
		}
		reduction := Reduction{
			Leg:        child.str("leg", legIDPattern, "a leg id"),
			Rule:       child.str("rule", slugPattern, "a slug"),
			Tight:      child.boolean("tight"),
			ReasonCode: child.str("reason_code", codePattern, "an upper-case reason code"),
		}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, reduction)
	}
	return out
}

func readCapture(r *reader) *Capture {
	child, present := r.optionalSub("capture")
	if !present || child == nil {
		return nil
	}
	out := Capture{
		SkewMs:     child.str("skew_ms", intPattern, "a whole number of milliseconds"),
		MaxSkewMs:  child.str("max_skew_ms", intPattern, "a whole number of milliseconds"),
		MeasuredBy: child.str("measured_by", nil, ""),
	}
	r.finish(child)
	return &out
}
