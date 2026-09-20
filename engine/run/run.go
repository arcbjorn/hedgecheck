// Package run turns a capture set into proposals, results and a comparison. Pure:
// bytes and options in, documents out. Nothing here fetches, and nothing here waits.
//
// The same function serves a live run and a replay, which is what makes the two
// byte-identical. A replay that went down a different path would prove nothing about
// the run it claims to reproduce.
package run

import (
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"hedgecheck/engine/discover"
	"hedgecheck/engine/doc"
	"hedgecheck/engine/evaluate"
	"hedgecheck/engine/exact"
	"hedgecheck/engine/lower"
	"hedgecheck/engine/pwa"
)

// MaxSkewMs bounds how far apart the snapshots in one result may have been captured.
//
// Proposed from 31 measurements on 19-20 September: book venue time minus local
// retrieval ran from -796 ms to -291 ms. This is roughly six times the observed worst.
// It is a bound on an ASSERTION, not a derivation: the contexts response carries no
// venue timestamp, so nobody can re-derive the spread from the bytes (EVIDENCE §4).
const MaxSkewMs = 5000

// Options are the question a run answers. Baseline and valuation time have no
// defaults: each decides what the answer means.
type Options struct {
	Underlying    string
	Quantity      exact.Q
	Cap           exact.Q
	Floor         exact.Q
	Ceiling       exact.Q
	BaselineKind  string // "analysis_time" or "explicit"
	BaselinePrice exact.Q
	ValuationTime string // an instant, or "" to use the contract's own
	Capture       *doc.Capture
}

// Capture is one coherent set of retained responses.
type Capture struct {
	CatalogueDigest string
	ContextsDigest  string
	BookDigests     map[string]string
	Snapshots       lower.Snapshots
}

// Row is one candidate instrument, answered.
type Row struct {
	ID          string
	Size        exact.Q
	Sized       bool
	Proposal    doc.Proposal
	IR          doc.IR
	Result      doc.Result
	InputDigest string
	Window      pwa.SizeWindow
}

// Answer is everything a run produces.
type Answer struct {
	Expiry          string
	ObservationTime string
	ValuationTime   string
	Baseline        exact.Q
	Rows            []Row
	Reduction       Reduction
	Comparison      *doc.Comparison
}

// Reduction is the no-premium alternative: sell down to what meets the cap.
type Reduction struct {
	Keep, Sell, WorstCase exact.Q
}

// Run answers a capture. Registry entries are passed in, so the caller decides
// whether to use the tree's or a reviewed copy; reviewing is never done here.
func Run(capture Capture, options Options, registry map[string]doc.Entry) (Answer, error) {
	catalogueRaw, err := capture.Snapshots.Bytes(capture.CatalogueDigest)
	if err != nil {
		return Answer{}, err
	}
	catalogue, err := parseVenue(catalogueRaw)
	if err != nil {
		return Answer{}, err
	}
	expiry, candidates, err := discover.Candidates(catalogue, options.Underlying, "")
	if err != nil {
		return Answer{}, err
	}
	observation, err := discover.ExpiryToISO(expiry)
	if err != nil {
		return Answer{}, err
	}
	valuation := options.ValuationTime
	if valuation == "" {
		valuation = observation
	}

	baseline := options.BaselinePrice
	if options.BaselineKind == "analysis_time" {
		contextsRaw, err := capture.Snapshots.Bytes(capture.ContextsDigest)
		if err != nil {
			return Answer{}, err
		}
		baseline, err = markPrice(contextsRaw, options.Underlying)
		if err != nil {
			return Answer{}, err
		}
	}

	answer := Answer{
		Expiry: expiry, ObservationTime: observation,
		ValuationTime: valuation, Baseline: baseline,
	}
	for _, candidate := range candidates {
		bookDigest, known := capture.BookDigests[candidate.ID]
		if !known {
			return Answer{}, fmt.Errorf("run: no book captured for %s", candidate.ID)
		}
		bookRaw, err := capture.Snapshots.Bytes(bookDigest)
		if err != nil {
			return Answer{}, err
		}
		row := Row{ID: candidate.ID}
		size, window, err := smallestPassingSize(candidate, bookRaw, options, baseline)
		if err != nil {
			return Answer{}, err
		}
		row.Window = window
		if !window.HasWhole {
			answer.Rows = append(answer.Rows, row)
			continue
		}
		row.Size, row.Sized = size, true

		entry, known := registry[candidate.Family]
		if !known {
			return Answer{}, fmt.Errorf("run: the registry has no entry for %s", candidate.Family)
		}
		version, err := entry.SemanticsVersion()
		if err != nil {
			return Answer{}, err
		}
		row.Proposal = buildProposal(candidate, size, capture, options, baseline, valuation, version, bookDigest)
		ir, versions, err := lower.Lower(row.Proposal, registry, capture.Snapshots)
		if err != nil {
			return Answer{}, err
		}
		row.IR = ir
		result, err := evaluate.Evaluate(ir)
		if err != nil {
			return Answer{}, err
		}
		row.Result = result
		digest, err := lower.InputDigest(row.Proposal, ir, versions)
		if err != nil {
			return Answer{}, err
		}
		row.InputDigest = digest
		answer.Rows = append(answer.Rows, row)
	}

	keep := smallestReduction(options.Quantity, baseline, options.Cap.Neg(), options.Floor)
	answer.Reduction = Reduction{
		Keep: keep, Sell: options.Quantity.Sub(keep),
		WorstCase: keep.Mul(options.Floor.Sub(baseline)),
	}

	// A comparison needs at least two evaluated candidates answering the same question.
	candidatesForComparison := []evaluate.Candidate{}
	for _, row := range answer.Rows {
		if row.Sized {
			candidatesForComparison = append(candidatesForComparison,
				evaluate.Candidate{Label: slug(row.ID), IR: row.IR, Result: row.Result})
		}
	}
	if len(candidatesForComparison) >= 2 {
		comparison, err := evaluate.Compare(candidatesForComparison)
		if err != nil {
			return Answer{}, err
		}
		answer.Comparison = &comparison
	}
	return answer, nil
}

// smallestPassingSize is the fewest whole contracts of this candidate that meet the
// cap on the book that was captured.
func smallestPassingSize(candidate discover.Candidate, bookRaw []byte, options Options,
	baseline exact.Q) (exact.Q, pwa.SizeWindow, error) {
	strike, err := strikeOf(candidate)
	if err != nil {
		return exact.Q{}, pwa.SizeWindow{}, err
	}
	levels, err := asksOf(bookRaw)
	if err != nil {
		return exact.Q{}, pwa.SizeWindow{}, err
	}
	base := pwa.Linear(options.Quantity, baseline)
	unit, err := pwa.Indicator(exact.One(), pwa.NegInf(), pwa.Finite(strike, false))
	if err != nil {
		return exact.Q{}, pwa.SizeWindow{}, err
	}
	window, err := pwa.SizeWindowFor(base, unit, levels, options.Cap.Neg(),
		options.Floor, options.Ceiling, exact.One())
	if err != nil {
		return exact.Q{}, pwa.SizeWindow{}, err
	}
	return window.Smallest, window, nil
}

func strikeOf(candidate discover.Candidate) (exact.Q, error) {
	if candidate.StrikeTerm == "target_price" {
		text, _ := candidate.Terms["target_price"].(string)
		return exact.ParseQ(text)
	}
	list, _ := candidate.Terms["thresholds"].([]any)
	if len(list) == 0 {
		return exact.Q{}, fmt.Errorf("run: %s names no thresholds", candidate.ID)
	}
	text, _ := list[0].(string)
	return exact.ParseQ(text)
}

func buildProposal(candidate discover.Candidate, size exact.Q, capture Capture, options Options,
	baseline exact.Q, valuation, version, bookDigest string) doc.Proposal {
	baselineBlock := doc.Baseline{Kind: options.BaselineKind, Price: baseline}
	if options.BaselineKind == "analysis_time" {
		baselineBlock.Snapshot = capture.ContextsDigest
		baselineBlock.Coin = options.Underlying
	} else {
		baselineBlock.Label = "operator-supplied"
	}
	proposal := doc.Proposal{
		SchemaVersion: "1",
		Units:         doc.Units{Money: "USDC", Price: "USDC per BTC", Exposure: "BTC", Size: "contracts"},
		Domain:        doc.Domain{Lower: options.Floor, Upper: options.Ceiling},
		Baseline:      baselineBlock,
		Exposure: doc.ProposalExposure{
			Kind: "linear_spot", Underlying: options.Underlying,
			Quantity: options.Quantity, Reference: "hl:perp:BTC:mark-interp",
		},
		Legs: []doc.ProposalLeg{{
			ID: candidate.ID, Family: candidate.Family, SemanticsVersion: version,
			Side: candidate.Side, Terms: candidate.Terms,
			Instance: doc.Instance{
				Outcome: candidate.Outcome, Coin: candidate.Coin,
				Catalogue: capture.CatalogueDigest,
			},
			Size: size,
			Acquisition: doc.Acquisition{
				Kind: "book_walk", Path: "direct_book", Snapshot: bookDigest,
			},
		}},
		Objective:              []doc.Clause{{ID: "loss_cap", MinPnl: options.Cap.Neg()}},
		ObjectiveValuationTime: valuation,
		OtherCosts:             exact.Zero(),
		Assumptions:            []string{"common_reference", "zero_base_fee"},
	}
	proposal.SetObjectiveReference("hl:perp:BTC:mark-interp")
	if options.Capture != nil {
		// Copied, so two proposals from one run cannot alias a single assertion.
		assertion := *options.Capture
		proposal.Capture = &assertion
	}
	return proposal
}

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

// ---------------------------------------------------------------- venue reading

// ParseVenue reads venue JSON with UseNumber, so a quantity never passes through a
// float. Venue JSON is not a contract document: it is read leniently here and every
// quantity is taken from a string field.
func ParseVenue(raw []byte) (any, error) { return parseVenue(raw) }

func parseVenue(raw []byte) (any, error) {
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return nil, err
	}
	return value, nil
}

// markPrice reads a perp's mark from the contexts response, from its STRING field.
// A json.Number converted to a float would lose the exactness everything later needs.
func markPrice(raw []byte, coin string) (exact.Q, error) {
	value, err := parseVenue(raw)
	if err != nil {
		return exact.Q{}, err
	}
	outer, ok := value.([]any)
	if !ok || len(outer) != 2 {
		return exact.Q{}, fmt.Errorf("run: not a contexts response")
	}
	meta, _ := outer[0].(map[string]any)
	states, _ := outer[1].([]any)
	universe, _ := meta["universe"].([]any)
	for index, asset := range universe {
		entry, _ := asset.(map[string]any)
		if name, _ := entry["name"].(string); name != coin {
			continue
		}
		if index >= len(states) {
			break
		}
		state, _ := states[index].(map[string]any)
		text, ok := state["markPx"].(string)
		if !ok {
			return exact.Q{}, fmt.Errorf("run: markPx is not a string")
		}
		return exact.ParseQ(text)
	}
	return exact.Q{}, fmt.Errorf("run: %s is not in the contexts snapshot", coin)
}

func asksOf(raw []byte) ([]pwa.Level, error) {
	value, err := parseVenue(raw)
	if err != nil {
		return nil, err
	}
	book, _ := value.(map[string]any)
	sides, ok := book["levels"].([]any)
	if !ok || len(sides) != 2 {
		return nil, fmt.Errorf("run: not an l2Book response")
	}
	rows, _ := sides[1].([]any)
	out := []pwa.Level{}
	for _, row := range rows {
		entry, _ := row.(map[string]any)
		priceText, _ := entry["px"].(string)
		sizeText, _ := entry["sz"].(string)
		price, err := exact.ParseQ(priceText)
		if err != nil {
			return nil, fmt.Errorf("run: px %q is not in the number grammar", priceText)
		}
		size, err := exact.ParseQ(sizeText)
		if err != nil {
			return nil, fmt.Errorf("run: sz %q is not in the number grammar", sizeText)
		}
		out = append(out, pwa.Level{Price: price, Size: size})
	}
	return out, nil
}

// slug turns a leg id into a label a comparison can carry.
func slug(id string) string {
	out := strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			return r
		}
		return '_'
	}, id)
	if out == "" || out[0] < 'a' || out[0] > 'z' {
		out = "c" + out
	}
	return out
}

// BookTime reads an l2Book's venue timestamp, in milliseconds.
//
// Pure: it reads a number out of retained bytes and does no timekeeping, so it lives
// here rather than in the adapter and a replay can call it without touching the
// network package. Its counterpart, the LOCAL retrieval time, is an RFC 3339 instant
// that needs a clock library to parse, so that one stays in the adapter and is handed
// to Measure as a function.
func BookTime(raw []byte) (int64, bool) {
	value, err := parseVenue(raw)
	if err != nil {
		return 0, false
	}
	book, ok := value.(map[string]any)
	if !ok {
		return 0, false
	}
	number, ok := book["time"].(json.Number)
	if !ok {
		return 0, false
	}
	milliseconds, err := number.Int64()
	if err != nil {
		return 0, false
	}
	return milliseconds, true
}

// Skew is the worst |book venue time - local retrieval| across a capture, and the
// bound it was refused above.
type Skew struct {
	WorstMs int64
	Details map[string]int64
}

// Measure computes the capture skew from books and their request records. Sorted, so
// the reported detail order does not depend on map iteration.
func Measure(books map[string][]byte, records map[string][]byte,
	venueTime func([]byte) (int64, bool), retrieved func([]byte) (int64, bool)) (Skew, error) {
	out := Skew{Details: map[string]int64{}}
	names := make([]string, 0, len(books))
	for name := range books {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		venue, ok := venueTime(books[name])
		if !ok {
			return Skew{}, fmt.Errorf("run: %s has no venue timestamp", name)
		}
		local, ok := retrieved(records[name])
		if !ok {
			return Skew{}, fmt.Errorf("run: %s has no retrieval time", name)
		}
		skew := venue - local
		out.Details[name] = skew
		if abs(skew) > abs(out.WorstMs) {
			out.WorstMs = skew
		}
	}
	return out, nil
}

func abs(value int64) int64 {
	if value < 0 {
		return -value
	}
	return value
}

// FormatMs renders a whole number of milliseconds as the documents carry it.
func FormatMs(value int64) string { return strconv.FormatInt(value, 10) }

// TooSkewed reports a capture whose snapshots were taken too far apart to be treated
// as one moment.
type TooSkewed struct{ WorstMs, MaxMs int64 }

func (e *TooSkewed) Error() string {
	return fmt.Sprintf("worst book-to-local skew %d ms exceeds the %d ms bound",
		e.WorstMs, e.MaxMs)
}

// Assert turns a measured skew into the assertion a result carries, refusing a
// capture that is too spread out to be one moment.
//
// Two questions are asked of one number and only one is about magnitude. Whether the
// capture is trustworthy is about distance from zero, so the bound compares the
// absolute value. What the document RECORDS keeps its sign, because the sign is the
// content: it says which clock was ahead. The assertion is carried inside the result,
// so it feeds the input digest -- dropping the sign would change the digest and lose
// the only readable fact in the claim.
func (s Skew) Assert(measuredBy string) (*doc.Capture, error) {
	if abs(s.WorstMs) > MaxSkewMs {
		return nil, &TooSkewed{WorstMs: s.WorstMs, MaxMs: MaxSkewMs}
	}
	return doc.NewCapture(FormatMs(s.WorstMs), FormatMs(MaxSkewMs), measuredBy), nil
}
