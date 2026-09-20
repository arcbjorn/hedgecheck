package doc

import (
	"hedgecheck/engine/canon"
)

// Review records who checked a reading of a family, and which reading they checked.
//
// Digest is the semantics_version that was reviewed. Without it, marking an entry
// reviewed would change its digest and break every proposal pinning it; with it,
// editing the semantics leaves a stale digest and the entry silently reverts to
// unreviewed. That rule is `Reviewed` below, and no schema keyword can state it.
type Review struct {
	State      string // "draft" or "reviewed"
	DraftedBy  string
	ReviewedBy string
	ReviewedOn string
	Digest     string
	hasBy      bool
	hasOn      bool
	hasDigest  bool
}

// Source is one retained document behind a reading, with the quotes it rests on.
type Source struct {
	Title, URL, Retrieved, SHA256, RetainedAt string
	Quotes                                    []string
}

// Term names one value a family's instances carry.
type Term struct{ Name, Type string }

// TermBound points at a term, optionally at one position of a list-valued one.
type TermBound struct {
	Term  string
	At    string
	HasAt bool
}

// PayoffBound is one end of where a payoff pays, in terms rather than prices.
type PayoffBound struct {
	Bound     TermBound
	Present   bool
	Inclusive bool
}

// Payoff maps a side, and an index where the family has one, to what it pays.
type Payoff struct {
	Side     string
	Index    string
	HasIndex bool
	Pays     []PayoffLeg
}

// PayoffLeg is one indicator of a payoff. A side may need more than one: NO on the
// middle bucket pays below the lower threshold and at or above the upper one.
type PayoffLeg struct {
	Primitive    string
	Lower, Upper PayoffBound
}

// Evidence labels one claim in an entry as verified, third-party or unverified.
type Evidence struct{ Claim, Label, Where string }

// Entry is one reviewed reading of one contract family, as data.
type Entry struct {
	SchemaVersion       string
	Family              string
	Version             string
	Status              string
	Settlement          string
	Review              Review
	Sources             []Source
	Terms               []Term
	Reference           string
	Observation         string
	Payoffs             []Payoff
	AssumptionsRequired []string
	Ambiguities         []string
	Evidence            []Evidence
}

// SemanticsVersion is the digest of the entry WITHOUT its review block.
//
// A proposal pins a reading, not a review state. Digesting the whole entry would
// couple the two, so reviewing an entry would move every pin that named it.
func (e Entry) SemanticsVersion() (string, error) {
	encoded := encodeEntry(e)
	delete(encoded, "review")
	return canon.Digest(encoded)
}

// Reviewed reports whether THIS reading has been reviewed. Both halves are required:
// the state says the owner reviewed something, and the digest says it was this.
func (e Entry) Reviewed() (bool, error) {
	if e.Review.State != "reviewed" || !e.Review.hasDigest {
		return false, nil
	}
	version, err := e.SemanticsVersion()
	if err != nil {
		return false, err
	}
	return e.Review.Digest == version, nil
}

// ReadEntry decodes a registry entry from canonical bytes.
func ReadEntry(raw []byte) (Entry, error) {
	value, err := parse(raw)
	if err != nil {
		return Entry{}, err
	}
	return decodeEntry("", value)
}

func decodeEntry(path string, value any) (Entry, error) {
	r, err := object(path, value)
	if err != nil {
		return Entry{}, err
	}
	out := Entry{}
	out.SchemaVersion = r.str("schema_version", nil, "")
	if out.SchemaVersion != "" && out.SchemaVersion != "1" {
		r.note(fail(r.at("schema_version"), "unsupported schema version %q", out.SchemaVersion))
	}
	out.Family = r.enum("family", "recurring.priceBinary", "recurring.priceBucket",
		"template.binaryPrice", "template.scalarPrice", "template.priceTouch")
	out.Version = r.str("version", nil, "")
	out.Status = r.enum("status", "computed", "bounded", "refused")
	out.Settlement = r.enum("settlement", "protocol", "deployer")
	out.Review = readReview(r)
	out.Sources = readSources(r)
	out.Terms = readTerms(r)
	out.Reference = r.str("reference", nil, "")
	out.Observation = r.str("observation", nil, "")
	out.Payoffs = readPayoffs(r)
	for index, item := range r.list("assumptions_required", 0) {
		text, ok := item.(string)
		if !ok || !slugPattern.MatchString(text) {
			r.note(fail(at2(r.path, "assumptions_required", index), "an assumption is a slug"))
			break
		}
		out.AssumptionsRequired = append(out.AssumptionsRequired, text)
	}
	for index, item := range r.list("ambiguities", 0) {
		text, ok := item.(string)
		if !ok {
			r.note(fail(at2(r.path, "ambiguities", index), "expected a string"))
			break
		}
		out.Ambiguities = append(out.Ambiguities, text)
	}
	out.Evidence = readEvidence(r)
	return out, r.done()
}

func readReview(r *reader) Review {
	child, ok := r.sub("review")
	if !ok {
		return Review{}
	}
	out := Review{
		State:     child.enum("state", "draft", "reviewed"),
		DraftedBy: child.enum("drafted_by", "model", "owner"),
	}
	out.ReviewedBy, out.hasBy = child.optionalStr("reviewed_by", nil, "")
	out.ReviewedOn, out.hasOn = child.optionalStr("reviewed_on", datePattern, "a date")
	out.Digest, out.hasDigest = child.optionalStr("digest", digestPattern, "a SHA-256")
	// The schema's dependentRequired, restated here so the decoder is the whole rule.
	if out.hasDigest && (!out.hasBy || !out.hasOn) {
		child.note(fail(child.at("digest"), "a review digest names its reviewer and date"))
	}
	r.finish(child)
	return out
}

func readSources(r *reader) []Source {
	out := []Source{}
	for index, item := range r.list("sources", 1) {
		child, err := object(at2(r.path, "sources", index), item)
		if err != nil {
			r.note(err)
			break
		}
		source := Source{
			Title:      child.str("title", nil, ""),
			URL:        child.str("url", nil, ""),
			Retrieved:  child.str("retrieved", datePattern, "a date"),
			SHA256:     child.str("sha256", digestPattern, "a SHA-256"),
			RetainedAt: child.str("retained_at", nil, ""),
		}
		for quoteIndex, quote := range child.list("quotes", 1) {
			text, ok := quote.(string)
			if !ok {
				child.note(fail(at2(child.path, "quotes", quoteIndex), "expected a string"))
				break
			}
			source.Quotes = append(source.Quotes, text)
		}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, source)
	}
	return out
}

func readTerms(r *reader) []Term {
	out := []Term{}
	for index, item := range r.list("terms", 0) {
		child, err := object(at2(r.path, "terms", index), item)
		if err != nil {
			r.note(err)
			break
		}
		term := Term{
			Name: child.str("name", slugPattern, "a slug"),
			Type: child.enum("type", "number", "numbers", "time", "text", "index"),
		}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, term)
	}
	return out
}

func readPayoffs(r *reader) []Payoff {
	out := []Payoff{}
	for index, item := range r.list("payoffs", 1) {
		child, err := object(at2(r.path, "payoffs", index), item)
		if err != nil {
			r.note(err)
			break
		}
		payoff := Payoff{}
		if selector, ok := child.sub("select"); ok {
			payoff.Side = selector.enum("side", "yes", "no", "long", "short")
			payoff.Index, payoff.HasIndex = selector.optionalStr("index", nil, "")
			child.finish(selector)
		}
		for legIndex, legItem := range child.list("pays", 1) {
			leg, err := decodePayoffLeg(at2(child.path, "pays", legIndex), legItem)
			if err != nil {
				child.note(err)
				break
			}
			payoff.Pays = append(payoff.Pays, leg)
		}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, payoff)
	}
	return out
}

func decodePayoffLeg(path string, value any) (PayoffLeg, error) {
	r, err := object(path, value)
	if err != nil {
		return PayoffLeg{}, err
	}
	out := PayoffLeg{Primitive: r.enum("primitive", "indicator")}
	child, ok := r.sub("pays_on")
	if !ok {
		return out, r.done()
	}
	lower, hasLower := readTermBound(child, "lower")
	lowerIncl, hasLowerIncl := child.optionalBool("lower_inclusive")
	upper, hasUpper := readTermBound(child, "upper")
	upperIncl, hasUpperIncl := child.optionalBool("upper_inclusive")
	if hasLower != hasLowerIncl || hasUpper != hasUpperIncl {
		child.note(fail(child.path, "a bound and its ownership travel together"))
	}
	if !hasLower && !hasUpper {
		child.note(fail(child.path, "an indicator pays somewhere in particular"))
	}
	out.Lower = PayoffBound{Bound: lower, Present: hasLower, Inclusive: lowerIncl}
	out.Upper = PayoffBound{Bound: upper, Present: hasUpper, Inclusive: upperIncl}
	r.finish(child)
	return out, r.done()
}

func readTermBound(r *reader, key string) (TermBound, bool) {
	child, present := r.optionalSub(key)
	if !present || child == nil {
		return TermBound{}, false
	}
	out := TermBound{Term: child.str("term", slugPattern, "a slug")}
	out.At, out.HasAt = child.optionalStr("at", nil, "")
	r.finish(child)
	return out, true
}

func readEvidence(r *reader) []Evidence {
	out := []Evidence{}
	for index, item := range r.list("evidence", 1) {
		child, err := object(at2(r.path, "evidence", index), item)
		if err != nil {
			r.note(err)
			break
		}
		evidence := Evidence{
			Claim: child.str("claim", nil, ""),
			Label: child.enum("label", "V", "T", "U"),
			Where: child.str("where", nil, ""),
		}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, evidence)
	}
	return out
}

// WriteEntry encodes a registry entry as canonical bytes.
func WriteEntry(entry Entry) ([]byte, error) { return canon.Marshal(encodeEntry(entry)) }

func encodeEntry(entry Entry) map[string]any {
	out := map[string]any{
		"schema_version":       entry.SchemaVersion,
		"family":               entry.Family,
		"version":              entry.Version,
		"status":               entry.Status,
		"settlement":           entry.Settlement,
		"review":               encodeReview(entry.Review),
		"sources":              encodeSources(entry.Sources),
		"terms":                encodeTerms(entry.Terms),
		"reference":            entry.Reference,
		"observation":          entry.Observation,
		"payoffs":              encodePayoffs(entry.Payoffs),
		"assumptions_required": textList(entry.AssumptionsRequired),
		"ambiguities":          textList(entry.Ambiguities),
		"evidence":             encodeEvidence(entry.Evidence),
	}
	return out
}

func encodeReview(review Review) map[string]any {
	out := map[string]any{"state": review.State, "drafted_by": review.DraftedBy}
	setIf(out, review.hasBy, "reviewed_by", review.ReviewedBy)
	setIf(out, review.hasOn, "reviewed_on", review.ReviewedOn)
	setIf(out, review.hasDigest, "digest", review.Digest)
	return out
}

func encodeSources(sources []Source) []any {
	out := make([]any, 0, len(sources))
	for _, source := range sources {
		out = append(out, map[string]any{
			"title": source.Title, "url": source.URL, "retrieved": source.Retrieved,
			"sha256": source.SHA256, "retained_at": source.RetainedAt,
			"quotes": textList(source.Quotes),
		})
	}
	return out
}

func encodeTerms(terms []Term) []any {
	out := make([]any, 0, len(terms))
	for _, term := range terms {
		out = append(out, map[string]any{"name": term.Name, "type": term.Type})
	}
	return out
}

func encodePayoffs(payoffs []Payoff) []any {
	out := make([]any, 0, len(payoffs))
	for _, payoff := range payoffs {
		selector := map[string]any{"side": payoff.Side}
		setIf(selector, payoff.HasIndex, "index", payoff.Index)
		pays := make([]any, 0, len(payoff.Pays))
		for _, leg := range payoff.Pays {
			paysOn := map[string]any{}
			if leg.Lower.Present {
				paysOn["lower"] = encodeTermBound(leg.Lower.Bound)
				paysOn["lower_inclusive"] = leg.Lower.Inclusive
			}
			if leg.Upper.Present {
				paysOn["upper"] = encodeTermBound(leg.Upper.Bound)
				paysOn["upper_inclusive"] = leg.Upper.Inclusive
			}
			pays = append(pays, map[string]any{"primitive": leg.Primitive, "pays_on": paysOn})
		}
		out = append(out, map[string]any{"select": selector, "pays": pays})
	}
	return out
}

func encodeTermBound(bound TermBound) map[string]any {
	out := map[string]any{"term": bound.Term}
	setIf(out, bound.HasAt, "at", bound.At)
	return out
}

func encodeEvidence(items []Evidence) []any {
	out := make([]any, 0, len(items))
	for _, item := range items {
		out = append(out, map[string]any{"claim": item.Claim, "label": item.Label, "where": item.Where})
	}
	return out
}
