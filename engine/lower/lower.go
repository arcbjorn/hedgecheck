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
	"regexp"
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

// assumptions is the closed vocabulary, mirroring oracle/lower.py's ASSUMPTIONS. Each value
// says what declaring it asserts, because a name a reader cannot interpret is no better than
// an invented one. `common_reference` is a NOTE and not a gate: it does not switch the basis
// rule off, because that reduction rests on the RESOLVED references rather than on an
// assertion about them.
var assumptions = map[string]string{
	"zero_base_fee":               "the venue charges no base fee on an outcome trade",
	"deployer_settles_as_written": "the deployer settles as the template is written",
	"common_reference":            "the holder believes every leg is observed on the objective's series",
}

// loweredExposure carries the exposure's KIND rather than discarding it. Lowering used to
// write `{"kind": "linear", ...}` whatever the proposal said, so an isolated perp arrived at
// the evaluator indistinguishable from spot -- and a checker cannot re-derive a reduction from
// an IR that does not say what is exposed.
func loweredExposure(exposure doc.ProposalExposure) doc.Exposure {
	if exposure.Kind != "isolated_perp" {
		return doc.Exposure{Kind: "linear", Quantity: exposure.Quantity}
	}
	out := doc.Exposure{Kind: "isolated_perp", Quantity: exposure.Quantity}
	out.SetLiquidation(exposure.LiquidationPrice, exposure.IsolatedMargin)
	return out
}

// pathDomain is every price the path can take: the hull of the terminal domain and where the
// price starts. PLAN section 2 -- "every price between now and the valuation time, so it
// contains the current price and the terminal domain". A baseline OUTSIDE the terminal domain
// widens it, which is right: the path starts there whatever the terminal range says.
func pathDomain(domain doc.Domain, baseline exact.Q) (exact.Q, exact.Q) {
	return exact.Min(domain.Lower, baseline), exact.Max(domain.Upper, baseline)
}

// liquidationReduction reduces an exposure that can be liquidated inside the path domain.
//
// THE HEDGE CANNOT BE LIQUIDATED; THE EXPOSURE CAN. Retained evidence at 085ccfb states that
// outcomes "do not involve leverage or liquidations", so an outcome leg is safe and an
// isolated perp is not.
//
// PLAN section 2's rule: with the liquidation price inside the path domain, the leg is worth
// MINUS ITS ISOLATED MARGIN at every terminal price -- not sometimes, because liquidation at
// any moment closes the position permanently and a later recovery does not bring it back.
//
// TIGHT, unlike a loose bound: the adverse state is ADMISSIBLE, not merely unproven, so a
// verdict may rest on it alone and it CAN fail a proposal. That is the difference from
// `price_touch`, whose bound understates a payoff and may therefore only ask for review.
func liquidationReduction(proposal doc.Proposal, baseline exact.Q) (doc.Reduction, bool, error) {
	if proposal.Exposure.Kind != "isolated_perp" {
		return doc.Reduction{}, false, nil
	}
	low, high := pathDomain(proposal.Domain, baseline)
	price := proposal.Exposure.LiquidationPrice
	if price.Less(low) || high.Less(price) {
		// The path cannot reach it within the declared domain, so there is nothing to reduce.
		return doc.Reduction{}, false, nil
	}
	if proposal.Exposure.IsolatedMargin.Sign() < 0 {
		return doc.Reduction{}, false, refuse("EXPOSURE_UNSOUND", "an isolated margin cannot be negative")
	}
	return doc.Reduction{Leg: "exposure", Rule: "liquidated_in_path", Tight: true,
		ReasonCode: "LIQUIDATED_IN_PATH"}, true, nil
}

// References maps a venue's exact price description to what it denotes. The key is
// (venue, price_description, seconds), spacing included.
type References map[[3]string]doc.ReferenceMapping

// ReferenceKey builds the lookup key for one description.
func ReferenceKey(venue, description, seconds string) [3]string {
	return [3]string{venue, description, seconds}
}

// Lower produces the lowered proposal and the semantics versions it used.
//
// `references` is variadic so every existing caller keeps working: a proposal whose legs
// are all canonical families never consults it, because no `recurring` outcome carries a
// price description.
func Lower(proposal doc.Proposal, registry map[string]doc.Entry, snapshots Snapshots, references ...References) (doc.IR, []string, error) {
	var refs References
	if len(references) > 0 {
		refs = references[0]
	}
	if proposal.SchemaVersion != "1" {
		return doc.IR{}, nil, refuse("UNSUPPORTED_SCHEMA", "proposal schema_version %q", proposal.SchemaVersion)
	}
	// THE ASSUMPTION VOCABULARY IS CLOSED, and mirrors oracle/lower.py's `ASSUMPTIONS`.
	//
	// An assumption is carried into the result and shown to a reader, who relies on what it
	// MEANS. An invented slug means nothing, so it is refused rather than displayed beside the
	// real ones with equal standing -- which is what happened until 22 Sep, on both sides: the
	// schema types `assumptions` as any slug, so a proposal declaring `nothing_can_go_wrong`
	// validated, lowered and appeared in the result's own list. It also catches the likelier
	// fault, a near-miss typo: `zero_base_fees` is refused where it used to pass silently and
	// then fail the `zero_base_fee` requirement with a confusing message.
	for _, declared := range proposal.Assumptions {
		if _, known := assumptions[declared]; !known {
			return doc.IR{}, nil, refuse("ASSUMPTION_UNKNOWN",
				"%q is not an assumption this system defines, so it means nothing to a reader",
				declared)
		}
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
	// Each leg's resolved price series, for the basis-band grouping after the loop.
	legReferences := map[string]string{}
	versions := []string{}
	reductions := []doc.Reduction{}
	// THE EXPOSURE'S OWN REDUCTION, before any leg's. An isolated perp liquidated inside the
	// path domain is worth minus its margin at every terminal price, and no hedge can undo
	// that -- so a reader should see it first among the rules the verdict rests on.
	if liquidation, reduced, err := liquidationReduction(proposal, baseline); err != nil {
		return doc.IR{}, nil, err
	} else if reduced {
		reductions = append(reductions, liquidation)
	}
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
		// A DEPLOYER LEG PAYS WHAT THE DEPLOYER SUBMITS.
		//
		// EVIDENCE section 1, verified: `settleOutcome` carries a `settleFraction` the
		// deployer chooses -- "Standalone outcomes may settle to any fraction" -- and
		// nothing in the protocol derives it from a price. So the template describes
		// what the deployer SAID they would do, not what they must do, and evaluating
		// such a leg as written is an assumption rather than a fact.
		//
		// LOOSE, like unreviewed_family: the leg is worst-cased to zero on the lower
		// profile, so a deployer leg can make a proposal need review and can never make
		// one fail. A tight rule here would let this system condemn a hedge on the
		// strength of a payoff nobody is bound to.
		if entry.Settlement == "deployer" {
			reductions = append(reductions, doc.Reduction{
				Leg: leg.ID, Rule: "deployer_settled", Tight: false,
				ReasonCode: "DEPLOYER_SETTLED",
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
		// A DEPLOYER-TEMPLATED instance names its own series, so the catalogue governs and
		// the entry's template is only for families whose reference is fixed.
		reference, err := catalogueReference(leg, catalogue, refs)
		if err != nil {
			return doc.IR{}, nil, err
		}
		if reference == "" {
			reference, err = legReference(leg, entry)
			if err != nil {
				return doc.IR{}, nil, err
			}
		}
		legReferences[leg.ID] = reference
	}

	// ---- the basis band: legs observed on a reference the objective is not stated on
	//
	// GROUPED, never leg by leg. PLAN section 2 states the rule as the infimum of the
	// GROUP's SUMMED payoff, and the infimum of a sum is not the sum of infima: two legs
	// whose payoffs cancel have a flat sum that no basis move can hurt, while each alone is
	// stepped. Reducing them separately invents a loss on a perfectly hedged position.
	if proposal.ObjectiveReference != "" {
		declared := map[string]exact.Q{}
		for _, bound := range proposal.BasisBounds {
			declared[referenceKey(bound.Between[0], bound.Between[1])] = bound.Bound
		}
		groups := map[string][]string{}
		for _, leg := range proposal.Legs {
			if legReferences[leg.ID] != proposal.ObjectiveReference {
				groups[legReferences[leg.ID]] = append(groups[legReferences[leg.ID]], leg.ID)
			}
		}
		foreign := make([]string, 0, len(groups))
		for reference := range groups {
			foreign = append(foreign, reference)
		}
		sort.Strings(foreign)
		for _, reference := range foreign {
			members := groups[reference]
			sort.Strings(members)
			reduction := doc.Reduction{Leg: members[0], Tight: false}
			if len(members) > 1 {
				reduction.With = members[1:]
			}
			bound, known := declared[referenceKey(proposal.ObjectiveReference, reference)]
			if known {
				reduction.Rule, reduction.ReasonCode = "basis_band", "BASIS_BAND"
				reduction.SetBound(bound)
			} else {
				// PLAN section 2: "No bound declared: zero". The reference is KNOWN -- it
				// just cannot be related to the objective's -- so this is a reduction and
				// not a refusal. Loose: the group is probably worth more than zero.
				reduction.Rule, reduction.ReasonCode = "basis_unbridged", "BASIS_UNBRIDGED"
			}
			reductions = append(reductions, reduction)
		}
	}

	ir := doc.IR{
		SchemaVersion:          "1",
		Units:                  proposal.Units,
		Domain:                 proposal.Domain,
		Baseline:               dict(proposal.Baseline, baseline),
		Exposure:               loweredExposure(proposal.Exposure),
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
	// A bounded family's payoff is NOT a function of the terminal price. `priceTouch` is
	// the case: whether the price ever touched a level is path-dependent, and this
	// kernel evaluates terminal prices. PLAN section 2 states the bound -- the inclusive
	// terminal digital at the target, and only when the touch window covers the
	// valuation time -- but no such family exists yet, so there is no rule to apply.
	// Refusing is the safe direction: evaluating one with the terminal machinery would
	// over-credit it at prices it may never have touched.
	if entry.Status == "bounded" {
		return doc.Entry{}, "", refuse("UNSUPPORTED_FAMILY",
			"%s: %s is bounded, not computed, and lowering has no bound for it yet", leg.ID, entry.Family)
	}
	// The registry says this family is not understood (PLAN section 6: "Everything else
	// -- Refused"). A REFUSAL, not a reduction: a reduction still yields a verdict, and
	// there is no verdict to give about a payoff nobody has read. Worst-casing it to zero
	// would answer a question this project has declared unanswerable.
	if entry.Status == "refused" {
		return doc.Entry{}, "", refuse("UNSUPPORTED_FAMILY",
			"%s: the registry refuses %s: its reading is not established", leg.ID, entry.Family)
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

// legReference is the price series a leg is observed on, resolved from its entry.
//
// An entry carries a TEMPLATE -- `hl:perp:{underlying}:mark-interp` -- because one reading
// covers every instance of a family. Each `{name}` is the leg's own term of that name, so
// the reference is a fact about the leg and is never restated in the proposal.
//
// A template naming a term the leg does not carry is a MALFORMED ENTRY, not a leg on a
// foreign reference: there is no series to name at all.
func legReference(leg doc.ProposalLeg, entry doc.Entry) (string, error) {
	var failure error
	out := placeholderPattern.ReplaceAllStringFunc(entry.Reference, func(match string) string {
		name := match[1 : len(match)-1]
		value, ok := leg.Terms[name].(string)
		if !ok {
			failure = refuse("UNSUPPORTED_FAMILY",
				"%s: the entry's reference names {%s}, which the leg's terms do not carry as a single value",
				leg.ID, name)
			return match
		}
		return value
	})
	if failure != nil {
		return "", failure
	}
	return out, nil
}

// referenceKey names an unordered pair of references, so a declared bound is found
// whichever way round the proposal wrote it.
func referenceKey(a, b string) string {
	if a > b {
		a, b = b, a
	}
	return a + "\x00" + b
}

var placeholderPattern = regexp.MustCompile(`\{[a-z_]+\}`)

// catalogueReference is the reference a DEPLOYER-TEMPLATED instance is observed on, or "".
//
// No `recurring` outcome on the 18 September catalogue carries a price description (0 of
// 32) and all 78 that do are `template:*`, so this governs the templated families only.
//
// AN UNMAPPABLE DESCRIPTION IS REFUSED, never resolved. Returning "" would fall back to the
// entry's own reference, so a leg nobody can map would be treated as sharing the objective's
// series -- the silent resolution PLAN section 6 forbids by name.
func catalogueReference(leg doc.ProposalLeg, catalogue any, refs References) (string, error) {
	item, err := findOutcome(catalogue, leg.Instance.Outcome)
	if err != nil {
		return "", err
	}
	described, err := termsOf(text(item["description"]))
	if err != nil {
		return "", err
	}
	description, ok := described["priceDescription"]
	if !ok {
		return "", nil
	}
	key := ReferenceKey(text(item["venue"]), description, described["seconds"])
	mapping, known := refs[key]
	if !known {
		return "", refuse("AMBIGUOUS_RULES",
			"%s: no reviewed mapping for %q at %ss on %q",
			leg.ID, description, described["seconds"], text(item["venue"]))
	}
	if mapping.State == "ambiguous" {
		return "", refuse("AMBIGUOUS_RULES", "%s: %s", leg.ID, mapping.Why)
	}
	return mapping.Reference, nil
}
