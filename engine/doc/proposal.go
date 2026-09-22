package doc

import (
	"hedgecheck/engine/canon"
	"hedgecheck/engine/exact"
)

// Instance names the live contract a leg is written against.
type Instance struct{ Outcome, Coin, Catalogue string }

// Acquisition says how a leg would be bought, and from which retained book.
type Acquisition struct {
	Kind     string
	Path     string
	Snapshot string
	Price    exact.Q
	hasPrice bool
}

// ProposalLeg is a leg in the terms a person writes: a family, an instance and the
// reading of that family it was written against.
type ProposalLeg struct {
	ID               string
	Family           string
	SemanticsVersion string
	Side             string
	Terms            map[string]any
	Instance         Instance
	Size             exact.Q
	Acquisition      Acquisition
}

// Proposal is what someone asks about: holdings, legs by family and instance, an
// objective, and the assumptions the answer rests on.
type Proposal struct {
	SchemaVersion          string
	Units                  Units
	Domain                 Domain
	Baseline               Baseline
	Exposure               ProposalExposure
	Legs                   []ProposalLeg
	Objective              []Clause
	ObjectiveValuationTime string
	ObjectiveReference     string
	hasObjectiveReference  bool
	// BasisBounds are the user's declared bounds between two price series. Never
	// defaulted: a bound nobody declared is not a bound, and PLAN section 2 worst-cases
	// an unbridged group to zero rather than guessing one.
	BasisBounds []BasisBound
	OtherCosts  exact.Q
	Assumptions []string
	Capture     *Capture
}

// ProposalExposure carries the reference the holding is priced against, which the
// lowered form has already resolved away.
type ProposalExposure struct {
	Kind       string
	Underlying string
	Quantity   exact.Q
	Reference  string
}

// ReadProposal decodes a proposal from canonical bytes.
func ReadProposal(raw []byte) (Proposal, error) {
	value, err := parse(raw)
	if err != nil {
		return Proposal{}, err
	}
	r, err := object("", value)
	if err != nil {
		return Proposal{}, err
	}
	out := Proposal{}
	out.SchemaVersion = r.str("schema_version", nil, "")
	if out.SchemaVersion != "" && out.SchemaVersion != "1" {
		r.note(fail(r.at("schema_version"), "unsupported schema version %q", out.SchemaVersion))
	}
	out.Units = readUnits(r)
	out.Domain = readDomain(r)
	out.Baseline = readBaseline(r)
	out.Exposure = readProposalExposure(r)
	for index, item := range r.list("legs", 1) {
		leg, err := decodeProposalLeg(at2(r.path, "legs", index), item)
		if err != nil {
			r.note(err)
			break
		}
		out.Legs = append(out.Legs, leg)
	}
	out.Objective = readObjective(r)
	out.ObjectiveValuationTime = r.str("objective_valuation_time", timePattern, "a UTC instant ending in Z")
	out.ObjectiveReference, out.hasObjectiveReference = r.optionalStr("objective_reference", refPattern, "a reference id")
	out.BasisBounds = readBasisBounds(r)
	out.OtherCosts = r.number("other_costs")
	out.Assumptions = readSlugs(r, "assumptions")
	out.Capture = readCapture(r)
	return out, r.done()
}

func readProposalExposure(r *reader) ProposalExposure {
	child, ok := r.sub("exposure")
	if !ok {
		return ProposalExposure{}
	}
	out := ProposalExposure{
		Kind:       child.str("kind", nil, ""),
		Underlying: child.str("underlying", nil, ""),
		Quantity:   child.number("quantity"),
		Reference:  child.str("reference", refPattern, "a reference id"),
	}
	if out.Quantity.Sign() < 0 {
		child.note(fail(child.at("quantity"), "a quantity is not negative"))
	}
	r.finish(child)
	return out
}

func decodeProposalLeg(path string, value any) (ProposalLeg, error) {
	r, err := object(path, value)
	if err != nil {
		return ProposalLeg{}, err
	}
	out := ProposalLeg{}
	out.ID = r.str("id", legIDPattern, "a leg id")
	out.Family = r.enum("family", "recurring.priceBinary", "recurring.priceBucket",
		"template.binaryPrice", "template.scalarPrice", "template.priceTouch")
	out.SemanticsVersion = r.str("semantics_version", digestPattern, "a SHA-256")
	out.Side = r.enum("side", "yes", "no", "long", "short")
	// Terms are family-specific, so they are carried as read and checked by lowering
	// against the catalogue. The schema constrains their shape, not their meaning.
	if terms, ok := r.take("terms"); ok {
		typed, ok := terms.(map[string]any)
		if !ok {
			r.note(fail(r.at("terms"), "expected an object"))
		} else {
			out.Terms = typed
		}
	} else {
		r.note(fail(r.at("terms"), "missing"))
	}
	if instance, ok := r.sub("instance"); ok {
		out.Instance = Instance{
			Outcome:   instance.str("outcome", nil, ""),
			Coin:      instance.str("coin", nil, ""),
			Catalogue: instance.str("catalogue", digestPattern, "a SHA-256"),
		}
		r.finish(instance)
	}
	out.Size = r.number("size")
	if acquisition, ok := r.sub("acquisition"); ok {
		out.Acquisition = Acquisition{Kind: acquisition.enum("kind", "book_walk", "fixed")}
		switch out.Acquisition.Kind {
		case "book_walk":
			out.Acquisition.Path = acquisition.enum("path", "direct_book")
			out.Acquisition.Snapshot = acquisition.str("snapshot", digestPattern, "a SHA-256")
		case "fixed":
			out.Acquisition.Price = acquisition.number("price")
			out.Acquisition.hasPrice = true
		}
		r.finish(acquisition)
	}
	return out, r.done()
}

// WriteProposal encodes a proposal as canonical bytes.
func WriteProposal(proposal Proposal) ([]byte, error) {
	return canon.Marshal(encodeProposal(proposal))
}

func encodeProposal(proposal Proposal) map[string]any {
	out := map[string]any{
		"schema_version": proposal.SchemaVersion,
		"units": map[string]any{
			"money": proposal.Units.Money, "price": proposal.Units.Price,
			"exposure": proposal.Units.Exposure, "size": proposal.Units.Size,
		},
		"domain":   map[string]any{"lower": proposal.Domain.Lower.String(), "upper": proposal.Domain.Upper.String()},
		"baseline": encodeBaseline(proposal.Baseline),
		"exposure": map[string]any{
			"kind": proposal.Exposure.Kind, "underlying": proposal.Exposure.Underlying,
			"quantity": proposal.Exposure.Quantity.String(), "reference": proposal.Exposure.Reference,
		},
		"legs":                     encodeProposalLegs(proposal.Legs),
		"objective":                encodeObjective(proposal.Objective),
		"objective_valuation_time": proposal.ObjectiveValuationTime,
		"other_costs":              proposal.OtherCosts.String(),
		"assumptions":              textList(proposal.Assumptions),
	}
	setIf(out, proposal.hasObjectiveReference, "objective_reference", proposal.ObjectiveReference)
	if len(proposal.BasisBounds) > 0 {
		bounds := make([]any, 0, len(proposal.BasisBounds))
		for _, declared := range proposal.BasisBounds {
			bounds = append(bounds, map[string]any{
				"between": []any{declared.Between[0], declared.Between[1]},
				"bound":   declared.Bound.String(),
			})
		}
		out["basis_bounds"] = bounds
	}
	if proposal.Capture != nil {
		out["capture"] = map[string]any{
			"skew_ms": proposal.Capture.SkewMs, "max_skew_ms": proposal.Capture.MaxSkewMs,
			"measured_by": proposal.Capture.MeasuredBy,
		}
	}
	return out
}

func encodeProposalLegs(legs []ProposalLeg) []any {
	out := make([]any, 0, len(legs))
	for _, leg := range legs {
		acquisition := map[string]any{"kind": leg.Acquisition.Kind}
		switch leg.Acquisition.Kind {
		case "book_walk":
			acquisition["path"] = leg.Acquisition.Path
			acquisition["snapshot"] = leg.Acquisition.Snapshot
		case "fixed":
			acquisition["price"] = leg.Acquisition.Price.String()
		}
		out = append(out, map[string]any{
			"id": leg.ID, "family": leg.Family, "semantics_version": leg.SemanticsVersion,
			"side": leg.Side, "terms": leg.Terms,
			"instance": map[string]any{
				"outcome": leg.Instance.Outcome, "coin": leg.Instance.Coin,
				"catalogue": leg.Instance.Catalogue,
			},
			"size": leg.Size.String(), "acquisition": acquisition,
		})
	}
	return out
}

// BasisBound is one declared bound between two price series.
type BasisBound struct {
	Between [2]string
	Bound   exact.Q
}

func readBasisBounds(r *reader) []BasisBound {
	items, present := r.optionalList("basis_bounds", 0)
	if !present {
		return nil
	}
	out := []BasisBound{}
	for index, item := range items {
		child, err := object(at2(r.path, "basis_bounds", index), item)
		if err != nil {
			r.note(err)
			break
		}
		pair, _ := child.optionalList("between", 2)
		bound := BasisBound{Bound: child.number("bound")}
		if len(pair) != 2 {
			child.note(fail(child.at("between"), "two reference ids"))
		} else {
			for at, side := range pair {
				text, ok := side.(string)
				if !ok || !refPattern.MatchString(text) {
					child.note(fail(at2(child.path, "between", at), "a reference id"))
					break
				}
				bound.Between[at] = text
			}
		}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, bound)
	}
	return out
}
