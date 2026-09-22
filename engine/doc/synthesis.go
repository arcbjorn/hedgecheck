package doc

import (
	"hedgecheck/engine/exact"
)

// BasePart is one term of what the holder already has: linear spot exposure, a position
// already taken, or cash. Its own shape rather than an IR leg's, because an IR leg's
// `kind` is part of the frozen IR contract and a holding is not an IR leg.
type BasePart struct {
	ID       string
	Kind     string
	Quantity exact.Q // linear
	Baseline exact.Q // linear
	Size     exact.Q // indicator
	PaysOn   PaysOn  // indicator
	Amount   exact.Q // cash
}

// Candidate instrument offered to the synthesis, one unit, with what one contract costs.
type SynthesisCandidate struct {
	ID     string
	PaysOn PaysOn
	Price  exact.Q
}

// SynthesisRequest is the question: everything a checker needs to rebuild the program.
type SynthesisRequest struct {
	SchemaVersion string
	Objective     Clause
	Domain        Domain
	Units         Units
	Base          []BasePart
	Candidates    []SynthesisCandidate
	Lot           exact.Q
	hasLot        bool
}

// SynthesisSize is one candidate's answer, named by candidate rather than by position.
type SynthesisSize struct {
	Candidate string
	Size      exact.Q
}

// CertificateWeight is one weight of a Farkas certificate, NAMING the constraint row it
// weights. A bare vector would be ordered by the rows, making row order an implicit
// contract between three implementations; naming the site lets each look it up among its
// own rows, so order stops mattering and an unknown site is a refusal rather than a silent
// misalignment against the wrong constraint.
type CertificateWeight struct {
	Price  exact.Q
	Side   string
	Weight exact.Q
}

// Synthesis is cheapest whole-contract sizes over several candidates meeting an objective,
// or a certificate that none exist. It carries the QUESTION as well as the answer, because
// a checker that re-added the numbers the solver emitted would be confirming arithmetic
// rather than verifying a claim. It carries NO solver state: a certificate that needed the
// search replayed would not be a certificate.
type Synthesis struct {
	SchemaVersion string
	Request       SynthesisRequest
	Status        string
	Sizes         []SynthesisSize
	Cost          exact.Q
	hasCost       bool
	Relaxed       []exact.Q
	Certificate   []CertificateWeight
	hasCert       bool
}

// ReadSynthesis decodes a synthesis answer from canonical bytes.
func ReadSynthesis(raw []byte) (Synthesis, error) {
	value, err := parse(raw)
	if err != nil {
		return Synthesis{}, err
	}
	r, err := object("", value)
	if err != nil {
		return Synthesis{}, err
	}
	out := Synthesis{}
	out.SchemaVersion = r.str("schema_version", nil, "")

	if request, ok := r.sub("request"); ok {
		out.Request.SchemaVersion = request.str("schema_version", nil, "")
		// The clause inline, as readObjective does for the IR's list of them: a synthesis
		// answers ONE objective, so there is no list to walk.
		if objective, ok := request.sub("objective"); ok {
			out.Request.Objective = Clause{
				ID:     objective.str("id", slugPattern, "a slug"),
				MinPnl: objective.number("min_pnl"),
			}
			if on, ok := objective.optionalSub("on"); ok && on != nil {
				interval := readInterval(on)
				out.Request.Objective.On = &interval
				objective.finish(on)
			}
			request.finish(objective)
		}
		out.Request.Domain = readDomain(request)
		out.Request.Units = readUnits(request)
		// `base` may be empty: synthesising from nothing is a legitimate question.
		base, _ := request.optionalList("base", 0)
		for index, item := range base {
			child, err := object(at2(request.path, "base", index), item)
			if err != nil {
				request.note(err)
				break
			}
			part := BasePart{
				ID:   child.str("id", legIDPattern, "a leg id"),
				Kind: child.enum("kind", "linear", "indicator", "cash"),
			}
			switch part.Kind {
			case "linear":
				part.Quantity = child.number("quantity")
				part.Baseline = child.number("baseline")
			case "indicator":
				part.Size = child.number("size")
				part.PaysOn = readPaysOn(child)
			case "cash":
				part.Amount = child.number("amount")
			}
			if err := child.done(); err != nil {
				request.note(err)
				break
			}
			out.Request.Base = append(out.Request.Base, part)
		}
		for index, item := range request.list("candidates", 1) {
			child, err := object(at2(request.path, "candidates", index), item)
			if err != nil {
				request.note(err)
				break
			}
			candidate := SynthesisCandidate{ID: child.str("id", legIDPattern, "a leg id")}
			candidate.PaysOn = readPaysOn(child)
			candidate.Price = child.number("price")
			if err := child.done(); err != nil {
				request.note(err)
				break
			}
			out.Request.Candidates = append(out.Request.Candidates, candidate)
		}
		if lot, present := request.optionalNumber("lot"); present {
			out.Request.Lot, out.Request.hasLot = lot, true
		}
		r.finish(request)
	}

	out.Status = r.enum("status", "feasible", "infeasible", "rounding_failed")
	if sizes, present := r.optionalList("sizes", 1); present {
		for index, item := range sizes {
			child, err := object(at2(r.path, "sizes", index), item)
			if err != nil {
				r.note(err)
				break
			}
			size := SynthesisSize{
				Candidate: child.str("candidate", legIDPattern, "a leg id"),
				Size:      child.number("size"),
			}
			if err := child.done(); err != nil {
				r.note(err)
				break
			}
			out.Sizes = append(out.Sizes, size)
		}
	}
	if cost, present := r.optionalNumber("cost"); present {
		out.Cost, out.hasCost = cost, true
	}
	if relaxed, present := r.optionalList("relaxed", 1); present {
		for index, item := range relaxed {
			text, ok := item.(string)
			if !ok {
				r.note(fail(at2(r.path, "relaxed", index), "a number"))
				break
			}
			parsed, err := exact.ParseQ(text)
			if err != nil {
				r.note(fail(at2(r.path, "relaxed", index), "a number"))
				break
			}
			out.Relaxed = append(out.Relaxed, parsed)
		}
	}
	if certificate, ok := r.optionalSub("certificate"); ok {
		out.hasCert = true
		certificate.enum("kind", "farkas")
		for index, item := range certificate.list("weights", 1) {
			child, err := object(at2(certificate.path, "weights", index), item)
			if err != nil {
				certificate.note(err)
				break
			}
			weight := CertificateWeight{
				Price:  child.number("price"),
				Side:   child.enum("side", "at", "above", "below"),
				Weight: child.number("weight"),
			}
			if err := child.done(); err != nil {
				certificate.note(err)
				break
			}
			out.Certificate = append(out.Certificate, weight)
		}
		r.finish(certificate)
	}
	return out, r.done()
}
