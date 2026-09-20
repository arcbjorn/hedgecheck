package doc

import (
	"hedgecheck/engine/canon"
	"hedgecheck/engine/exact"
)

// Constructors and setters for documents an engine builds rather than reads.
//
// The presence flags are unexported on purpose: whether an optional field was present
// is the decoder's finding, not something a caller should be able to set by accident.
// A builder states its intent through these, so "set it" and "leave it out" are both
// deliberate.

// NewWitness builds a witness with no adverse state, for a payoff where nothing was
// bounded and a price alone is therefore a counterexample.
func NewWitness(price, pnl exact.Q) Witness {
	return Witness{Price: price, Pnl: pnl}
}

// SetAdverseStates records why the witness is admissible once legs were bounded.
func (w *Witness) SetAdverseStates(states []AdverseState) {
	w.AdverseStates = states
	w.hasAdverse = true
}

// SetResponsible names the loose legs an undecided interval rests on.
func (f *FailingInterval) SetResponsible(legs []string) {
	f.ResponsibleLegs = legs
	f.hasResponsible = true
}

// NewWorstCase records the worst P&L, where, and whether it is attained.
func NewWorstCase(pnl, price exact.Q, attained bool) WorstCase {
	return WorstCase{Pnl: pnl, Price: price, Attained: attained, hasAttained: true}
}

// NewWorstCaseNoAttained is the comparison form, which states no attainment.
func NewWorstCaseNoAttained(pnl, price exact.Q) WorstCase {
	return WorstCase{Pnl: pnl, Price: price}
}

// SetBounds records a size window's exact real bounds.
func (s *SizeWindow) SetBounds(lower, upper exact.Q) {
	s.LowerBound, s.UpperBound, s.hasBounds = lower, upper, true
}

// SetWhole records the whole-contract window inside those bounds.
func (s *SizeWindow) SetWhole(smallest, largest exact.Q) {
	s.Smallest, s.Largest, s.hasWhole = smallest, largest, true
}

// SetUndecided records intervals whose violation rests only on a loose bound.
func (r *Result) SetUndecided(intervals []FailingInterval) {
	r.UndecidedIntervals, r.hasUndecided = intervals, true
}

// SetUpperProfile records the best the proposal could be.
func (r *Result) SetUpperProfile(pieces []Piece) {
	r.UpperProfile, r.hasUpperProfile = pieces, true
}

// SetSizeWindows records the sizes that would have met the objective.
func (r *Result) SetSizeWindows(windows []SizeWindow) {
	r.SizeWindows, r.hasSizeWindows = windows, true
}

// SetReductions copies the lowering rules that lowered a leg's value.
func (r *Result) SetReductions(reductions []Reduction) {
	r.Reductions, r.hasReductions = reductions, true
}

// SetSnapshots records the evidence the result rests on.
func (r *Result) SetSnapshots(snapshots []string) {
	r.Snapshots, r.hasSnapshots = snapshots, true
}

// SetDigests records the three digests that identify what was asked and answered.
func (r *Result) SetDigests(proposal, input string) {
	r.ProposalDigest, r.hasProposalDigest = proposal, proposal != ""
	r.InputDigest, r.hasInputDigest = input, input != ""
}

// SetSemanticsVersions records the readings the answer used.
func (r *Result) SetSemanticsVersions(versions []string) {
	r.SemanticsVersion, r.hasSemanticsVersion = versions, true
}

// IRDigest is the digest of a lowered proposal, over its canonical encoding. It is
// what a result is cited by, so it must be computed from the document rather than
// carried alongside it.
func IRDigest(ir IR) (string, error) {
	return canon.Digest(encodeIR(ir))
}

// ProposalDigest is the digest of a proposal's canonical encoding.
func ProposalDigest(proposal Proposal) (string, error) {
	return canon.Digest(encodeProposal(proposal))
}

// NewCapture states how the evidence was gathered. It is an assertion: no checker can
// re-derive it, because the contexts response carries no venue timestamp.
func NewCapture(skewMs, maxSkewMs, measuredBy string) *Capture {
	return &Capture{SkewMs: skewMs, MaxSkewMs: maxSkewMs, MeasuredBy: measuredBy}
}

// SetRanking records the passing candidates, cheapest first.
func (c *Comparison) SetRanking(labels []string) {
	c.Ranking, c.hasRanking = labels, true
}

// SharedCanonical renders a comparison's shared terms canonically, so two candidates
// agreeing on "the same question" is a byte comparison rather than a field-by-field
// one that a later field could slip past.
func SharedCanonical(shared Shared) ([]byte, error) {
	return canon.Marshal(map[string]any{
		"domain": map[string]any{
			"lower": shared.Domain.Lower.String(),
			"upper": shared.Domain.Upper.String(),
		},
		"baseline":                 encodeBaseline(shared.Baseline),
		"objective":                encodeObjective(shared.Objective),
		"objective_valuation_time": shared.ObjectiveValuationTime,
	})
}

// SetReviewed marks an entry reviewed against a semantics version. Callers pass the
// version they computed, so marking cannot silently review something else.
func (e *Entry) SetReviewed(by, on, digest string) {
	e.Review.State = "reviewed"
	e.Review.ReviewedBy, e.Review.hasBy = by, true
	e.Review.ReviewedOn, e.Review.hasOn = on, true
	e.Review.Digest, e.Review.hasDigest = digest, true
}
