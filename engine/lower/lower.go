// Package lower turns a proposal into a lowered proposal. Pure: a proposal, the
// registry entries it pins and the snapshot bytes it cites, in; primitives out.
//
// This is the one place that reads a registry entry, checks an instance against the
// catalogue the proposal cites, and prices a size against the book it cites. The
// kernel knows none of that, which is why it can be checked by arithmetic alone.
//
// Refusals are errors, never verdicts. A proposal that cannot be lowered has no
// result: calling it `fails` would claim the objective was evaluated and found
// wanting, when it was never evaluated at all.
package lower

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"hedgecheck/engine/canon"
	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
	"hedgecheck/engine/pwa"
)

// Refused is a proposal that cannot be lowered, with the code saying why.
type Refused struct {
	Code   string
	Detail string
}

func (r *Refused) Error() string { return r.Code + ": " + r.Detail }

func refuse(code, format string, args ...any) error {
	return &Refused{Code: code, Detail: fmt.Sprintf(format, args...)}
}

// Snapshot is a retained venue response, kept as exact bytes and read permissively.
//
// Venue JSON is not a contract document: it carries numbers where a contract carries
// strings. It is parsed with UseNumber so no value passes through a float, and every
// quantity is read from a string field.
type Snapshot struct {
	Digest string
	Raw    []byte
	value  any
}

// NewSnapshot hashes and parses retained bytes.
func NewSnapshot(raw []byte) (Snapshot, error) {
	sum := sha256.Sum256(raw)
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return Snapshot{}, refuse("SNAPSHOT_UNREADABLE", "%v", err)
	}
	return Snapshot{Digest: hex.EncodeToString(sum[:]), Raw: raw, value: value}, nil
}

// Snapshots is a set of retained responses, keyed by the digest a proposal cites.
type Snapshots map[string]Snapshot

// Add stores a snapshot under its own digest, so a citation can only find bytes that
// really hash to it.
func (s Snapshots) Add(raw []byte) (string, error) {
	snapshot, err := NewSnapshot(raw)
	if err != nil {
		return "", err
	}
	s[snapshot.Digest] = snapshot
	return snapshot.Digest, nil
}

// Bytes returns the exact retained bytes a digest was stored under. A citation that
// finds nothing is an error rather than empty bytes, so a missing snapshot cannot be
// read as an empty response.
func (s Snapshots) Bytes(digest string) ([]byte, error) {
	snapshot, ok := s[digest]
	if !ok {
		return nil, refuse("SNAPSHOT_NOT_SUPPLIED", "%s was not supplied", short(digest))
	}
	return snapshot.Raw, nil
}

func (s Snapshots) cited(digest, what string) (any, error) {
	snapshot, ok := s[digest]
	if !ok {
		return nil, refuse("SNAPSHOT_NOT_SUPPLIED", "%s cites %s, which was not supplied", what, short(digest))
	}
	return snapshot.value, nil
}

// Lower produces the lowered proposal and the semantics versions it used.
func Lower(proposal doc.Proposal, registry map[string]doc.Entry, snapshots Snapshots) (doc.IR, []string, error) {
	if proposal.SchemaVersion != "1" {
		return doc.IR{}, nil, refuse("UNSUPPORTED_SCHEMA", "proposal schema_version %q", proposal.SchemaVersion)
	}
	if !contains(proposal.Assumptions, "zero_base_fee") {
		return doc.IR{}, nil, refuse("ASSUMPTION_REQUIRED",
			"pricing at displayed asks requires the 'zero_base_fee' assumption")
	}

	baseline, err := readBaseline(proposal, snapshots)
	if err != nil {
		return doc.IR{}, nil, err
	}

	legs := []doc.Leg{}
	versions := []string{}
	reductions := []doc.Reduction{}
	for _, leg := range proposal.Legs {
		entry, version, err := resolve(leg, registry)
		if err != nil {
			return doc.IR{}, nil, err
		}
		versions = append(versions, version)

		// Reductions lower a leg's value to something provable, and each declares
		// whether it is tight. A loose bound can make a proposal need review; it can
		// never make one fail.
		expiry, _ := leg.Terms["expiry"].(string)
		if expiry != proposal.ObjectiveValuationTime {
			reductions = append(reductions, doc.Reduction{
				Leg: leg.ID, Rule: "horizon_mismatch", Tight: true,
				ReasonCode: "LEG_WORST_CASED_HORIZON",
			})
		}
		reviewed, err := entry.Reviewed()
		if err != nil {
			return doc.IR{}, nil, err
		}
		if !reviewed {
			reductions = append(reductions, doc.Reduction{
				Leg: leg.ID, Rule: "unreviewed_family", Tight: false,
				ReasonCode: "UNREVIEWED_FAMILY",
			})
		}

		if err := checkCoin(leg); err != nil {
			return doc.IR{}, nil, err
		}
		catalogue, err := snapshots.cited(leg.Instance.Catalogue, leg.ID+" catalogue")
		if err != nil {
			return doc.IR{}, nil, err
		}
		values, err := checkTerms(leg, catalogue)
		if err != nil {
			return doc.IR{}, nil, err
		}
		for _, required := range entry.AssumptionsRequired {
			if !contains(proposal.Assumptions, required) {
				return doc.IR{}, nil, refuse("ASSUMPTION_REQUIRED",
					"%s: %s requires the %q assumption", leg.ID, entry.Family, required)
			}
		}
		paysOn, err := paysOnFor(entry, leg, values)
		if err != nil {
			return doc.IR{}, nil, err
		}
		premium, err := price(leg, snapshots)
		if err != nil {
			return doc.IR{}, nil, err
		}
		size, err := exact.ParseQ(leg.Size.String())
		if err != nil {
			return doc.IR{}, nil, refuse("SIZE_NOT_WHOLE", "%s: %s", leg.ID, leg.Size)
		}
		legs = append(legs, doc.Leg{
			ID: leg.ID, Kind: "indicator", Size: size, PaysOn: paysOn,
			Premium: premium, ObservationTime: expiry, Semantics: version,
		})
	}

	ir := doc.IR{
		SchemaVersion:          "1",
		Units:                  proposal.Units,
		Domain:                 proposal.Domain,
		Baseline:               dict(proposal.Baseline, baseline),
		Exposure:               doc.Exposure{Kind: "linear", Quantity: proposal.Exposure.Quantity},
		Legs:                   legs,
		Objective:              proposal.Objective,
		ObjectiveValuationTime: proposal.ObjectiveValuationTime,
		OtherCosts:             proposal.OtherCosts,
		Assumptions:            proposal.Assumptions,
	}
	if len(reductions) > 0 {
		ir.Reductions = reductions
	}
	if proposal.Capture != nil {
		capture := *proposal.Capture
		ir.Capture = &capture
	}
	return ir, versions, nil
}

// dict keeps the baseline's provenance while replacing its price with the one read
// from the snapshot, so a checker re-reads the same bytes rather than trusting a
// number the lowering wrote down.
func dict(baseline doc.Baseline, price exact.Q) doc.Baseline {
	baseline.Price = price
	return baseline
}

func resolve(leg doc.ProposalLeg, registry map[string]doc.Entry) (doc.Entry, string, error) {
	entry, known := registry[leg.Family]
	if !known {
		return doc.Entry{}, "", refuse("UNKNOWN_FAMILY", "%s: the registry has no entry for %s", leg.ID, leg.Family)
	}
	version, err := entry.SemanticsVersion()
	if err != nil {
		return doc.Entry{}, "", err
	}
	if leg.SemanticsVersion != version {
		return doc.Entry{}, "", refuse("SEMANTICS_PIN_MISMATCH",
			"%s: pins %s, the registry entry is %s", leg.ID, short(leg.SemanticsVersion), short(version))
	}
	return entry, version, nil
}

// checkCoin holds the encoding: '#' + (10*outcome + side), yes=0, no=1. A coin that
// does not encode its own instance would price a leg on another contract's book.
func checkCoin(leg doc.ProposalLeg) error {
	side := 1
	if leg.Side == "yes" || leg.Side == "long" {
		side = 0
	}
	outcome, err := strconv.Atoi(leg.Instance.Outcome)
	if err != nil {
		return refuse("COIN_MISMATCH", "%s: outcome %q is not a number", leg.ID, leg.Instance.Outcome)
	}
	want := fmt.Sprintf("#%d", 10*outcome+side)
	if leg.Instance.Coin != want {
		return refuse("COIN_MISMATCH",
			"%s: coin %s does not encode outcome and side, expected %s", leg.ID, leg.Instance.Coin, want)
	}
	return nil
}

func readBaseline(proposal doc.Proposal, snapshots Snapshots) (exact.Q, error) {
	if proposal.Baseline.Kind != "analysis_time" {
		return proposal.Baseline.Price, nil
	}
	contexts, err := snapshots.cited(proposal.Baseline.Snapshot, "baseline")
	if err != nil {
		return exact.Q{}, err
	}
	outer, ok := contexts.([]any)
	if !ok || len(outer) != 2 {
		return exact.Q{}, refuse("BASELINE_MISMATCH", "the cited snapshot is not a contexts response")
	}
	meta, _ := outer[0].(map[string]any)
	states, _ := outer[1].([]any)
	universe, _ := meta["universe"].([]any)
	for index, asset := range universe {
		entry, _ := asset.(map[string]any)
		if name, _ := entry["name"].(string); name != proposal.Baseline.Coin {
			continue
		}
		if index >= len(states) {
			break
		}
		state, _ := states[index].(map[string]any)
		// Read the mark from its STRING field. A json.Number converted to a float would
		// lose the exactness every later comparison depends on.
		text, ok := state["markPx"].(string)
		if !ok {
			return exact.Q{}, refuse("BASELINE_MISMATCH", "markPx is not a string")
		}
		mark, err := exact.ParseQ(text)
		if err != nil {
			return exact.Q{}, refuse("BASELINE_MISMATCH", "markPx %q is not in the number grammar", text)
		}
		if !mark.Equal(proposal.Baseline.Price) {
			return exact.Q{}, refuse("BASELINE_MISMATCH",
				"baseline says %s, the cited snapshot says %s", proposal.Baseline.Price, mark)
		}
		return mark, nil
	}
	return exact.Q{}, refuse("BASELINE_MISMATCH", "%s is not in the cited contexts snapshot", proposal.Baseline.Coin)
}

func price(leg doc.ProposalLeg, snapshots Snapshots) (doc.Cost, error) {
	if leg.Acquisition.Kind != "book_walk" {
		return doc.Cost{}, refuse("UNSUPPORTED_ACQUISITION", "%s: %q", leg.ID, leg.Acquisition.Kind)
	}
	if leg.Acquisition.Path != "direct_book" {
		return doc.Cost{}, refuse("UNSUPPORTED_ACQUISITION",
			"%s: path %q is not lowered yet", leg.ID, leg.Acquisition.Path)
	}
	book, err := snapshots.cited(leg.Acquisition.Snapshot, leg.ID)
	if err != nil {
		return doc.Cost{}, err
	}
	if !leg.Size.IsInt() || leg.Size.Sign() <= 0 {
		return doc.Cost{}, refuse("SIZE_NOT_WHOLE",
			"%s: size %s is not a positive whole number of contracts", leg.ID, leg.Size)
	}
	levels, err := asks(book, leg.ID)
	if err != nil {
		return doc.Cost{}, err
	}
	total, covered := pwa.AskCost(levels, leg.Size)
	if !covered {
		return doc.Cost{}, refuse("INSUFFICIENT_DEPTH",
			"%s: displayed asks do not cover %s contracts", leg.ID, leg.Size)
	}
	out := doc.Cost{Kind: "walked", Total: total, Path: "direct_book", Snapshot: leg.Acquisition.Snapshot}
	for _, level := range levels {
		out.Levels = append(out.Levels, doc.Level{Price: level.Price, Size: level.Size})
	}
	return out, nil
}

// asks reads displayed asks from an l2Book response. A hash says nothing about what a
// response was, so the shape is checked before it is indexed.
func asks(book any, legID string) ([]pwa.Level, error) {
	typed, ok := book.(map[string]any)
	if !ok {
		return nil, refuse("SNAPSHOT_NOT_A_BOOK", "%s: the cited snapshot is not an l2Book response", legID)
	}
	if _, hasCoin := typed["coin"]; !hasCoin {
		return nil, refuse("SNAPSHOT_NOT_A_BOOK", "%s: the cited snapshot is not an l2Book response", legID)
	}
	sides, ok := typed["levels"].([]any)
	if !ok || len(sides) != 2 {
		return nil, refuse("SNAPSHOT_NOT_A_BOOK", "%s: the cited snapshot is not an l2Book response", legID)
	}
	rows, _ := sides[1].([]any)
	out := []pwa.Level{}
	for _, row := range rows {
		entry, _ := row.(map[string]any)
		priceText, priceOK := entry["px"].(string)
		sizeText, sizeOK := entry["sz"].(string)
		if !priceOK || !sizeOK {
			return nil, refuse("SNAPSHOT_NOT_A_BOOK", "%s: a level's px and sz are strings", legID)
		}
		price, err := exact.ParseQ(priceText)
		if err != nil {
			return nil, refuse("SNAPSHOT_NOT_A_BOOK", "%s: px %q is not in the number grammar", legID, priceText)
		}
		size, err := exact.ParseQ(sizeText)
		if err != nil {
			return nil, refuse("SNAPSHOT_NOT_A_BOOK", "%s: sz %q is not in the number grammar", legID, sizeText)
		}
		out = append(out, pwa.Level{Price: price, Size: size})
	}
	return out, nil
}

// ---------------------------------------------------------------- digests

// ProposalDigest, IRDigest and InputDigest are composed exactly as oracle/lower.py
// composes them: ARCHITECTURE section 2 states the intent, the oracle's code is the
// byte-level definition.
func ProposalDigest(proposal doc.Proposal) (string, error) { return doc.ProposalDigest(proposal) }

func IRDigest(ir doc.IR) (string, error) { return doc.IRDigest(ir) }

// InputDigest covers everything that determines a result except the engine.
func InputDigest(proposal doc.Proposal, ir doc.IR, versions []string) (string, error) {
	proposalDigest, err := ProposalDigest(proposal)
	if err != nil {
		return "", err
	}
	irDigest, err := IRDigest(ir)
	if err != nil {
		return "", err
	}
	return canon.Digest(map[string]any{
		"schema_version":     "1",
		"proposal_digest":    proposalDigest,
		"ir_digest":          irDigest,
		"semantics_versions": uniqueSorted(versions),
		"snapshots":          uniqueSorted(snapshotsCited(proposal)),
	})
}

func snapshotsCited(proposal doc.Proposal) []string {
	out := []string{}
	if proposal.Baseline.Snapshot != "" {
		out = append(out, proposal.Baseline.Snapshot)
	}
	for _, leg := range proposal.Legs {
		out = append(out, leg.Instance.Catalogue)
		if leg.Acquisition.Snapshot != "" {
			out = append(out, leg.Acquisition.Snapshot)
		}
	}
	return out
}

func uniqueSorted(values []string) []any {
	seen := map[string]bool{}
	for _, value := range values {
		seen[value] = true
	}
	out := make([]string, 0, len(seen))
	for value := range seen {
		out = append(out, value)
	}
	sort.Strings(out)
	list := make([]any, 0, len(out))
	for _, value := range out {
		list = append(list, value)
	}
	return list
}

func contains(values []string, needle string) bool {
	for _, value := range values {
		if value == needle {
			return true
		}
	}
	return false
}

func short(digest string) string {
	if len(digest) > 12 {
		return digest[:12]
	}
	return digest
}
