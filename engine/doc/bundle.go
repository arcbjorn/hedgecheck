package doc

import (
	"hedgecheck/engine/canon"
	"hedgecheck/engine/exact"
)

// Candidate is one proposal in a comparison, cited by the digest of its lowered form
// rather than by restating its numbers.
type Candidate struct {
	Label       string
	IRDigest    string
	ModelResult string
	Cost        exact.Q
}

// Shared are the terms every candidate must agree on for a ranking to mean anything.
type Shared struct {
	Domain                 Domain
	Baseline               Baseline
	Objective              []Clause
	ObjectiveValuationTime string
}

// Comparison ranks independently evaluated proposals. It restates none of their
// numbers, so each result stays about one proposal and stays checkable on its own.
type Comparison struct {
	SchemaVersion string
	Shared        Shared
	Candidates    []Candidate
	RankedBy      string
	Ranking       []string
	hasRanking    bool
	EngineVersion string
}

// ReadComparison decodes a comparison from canonical bytes.
func ReadComparison(raw []byte) (Comparison, error) {
	value, err := parse(raw)
	if err != nil {
		return Comparison{}, err
	}
	r, err := object("", value)
	if err != nil {
		return Comparison{}, err
	}
	out := Comparison{}
	out.SchemaVersion = r.str("schema_version", nil, "")
	if shared, ok := r.sub("shared"); ok {
		out.Shared.Domain = readDomain(shared)
		out.Shared.Baseline = readBaseline(shared)
		out.Shared.Objective = readObjective(shared)
		out.Shared.ObjectiveValuationTime = shared.str("objective_valuation_time", timePattern, "a UTC instant ending in Z")
		r.finish(shared)
	}
	for index, item := range r.list("candidates", 2) {
		child, err := object(at2(r.path, "candidates", index), item)
		if err != nil {
			r.note(err)
			break
		}
		candidate := Candidate{
			Label:       child.str("label", slugPattern, "a slug"),
			IRDigest:    child.str("ir_digest", digestPattern, "a SHA-256"),
			ModelResult: child.enum("model_result", "passes", "fails", "needs_review"),
			Cost:        child.number("cost"),
		}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out.Candidates = append(out.Candidates, candidate)
	}
	out.RankedBy = r.enum("ranked_by", "cost_of_smallest_passing_size")
	if ranking, present := r.optionalList("ranking", 0); present {
		out.hasRanking = true
		for index, item := range ranking {
			text, ok := item.(string)
			if !ok || !slugPattern.MatchString(text) {
				r.note(fail(at2(r.path, "ranking", index), "a slug"))
				break
			}
			out.Ranking = append(out.Ranking, text)
		}
	}
	out.EngineVersion = r.str("engine_version", nil, "")
	return out, r.done()
}

// WriteComparison encodes a comparison as canonical bytes.
func WriteComparison(comparison Comparison) ([]byte, error) {
	out := map[string]any{
		"schema_version": comparison.SchemaVersion,
		"shared": map[string]any{
			"domain": map[string]any{
				"lower": comparison.Shared.Domain.Lower.String(),
				"upper": comparison.Shared.Domain.Upper.String(),
			},
			"baseline":                 encodeBaseline(comparison.Shared.Baseline),
			"objective":                encodeObjective(comparison.Shared.Objective),
			"objective_valuation_time": comparison.Shared.ObjectiveValuationTime,
		},
		"ranked_by":      comparison.RankedBy,
		"engine_version": comparison.EngineVersion,
	}
	candidates := make([]any, 0, len(comparison.Candidates))
	for _, candidate := range comparison.Candidates {
		candidates = append(candidates, map[string]any{
			"label": candidate.Label, "ir_digest": candidate.IRDigest,
			"model_result": candidate.ModelResult, "cost": candidate.Cost.String(),
		})
	}
	out["candidates"] = candidates
	setIf(out, comparison.hasRanking, "ranking", textList(comparison.Ranking))
	return canon.Marshal(out)
}

// ---------------------------------------------------------------- bundle manifest

// NamedFile is one file a bundle carries, under the name that identifies it.
type NamedFile struct{ Key, Path string }

// Manifest lists everything a checker needs to accept or refuse one result, and the
// class the bundle must be refused with when it is a corrupted fixture.
type Manifest struct {
	SchemaVersion string
	Name          string
	Expects       string
	Corruption    *Corruption
	Proposal      string
	Lowered       string
	Result        string
	Registry      []NamedFile
	Snapshots     []NamedFile
}

// Corruption documents the single change that made a bundle corrupt.
type Corruption struct{ Of, Change, Target string }

// RefusalClasses is the closed list a checker may refuse with. Closed on purpose: two
// checkers that refuse the same bundle must say the same thing, or a disagreement is
// a wording question rather than a real one.
var RefusalClasses = []string{
	"SNAPSHOT_BYTES", "SNAPSHOT_NOT_CITED", "SEMANTICS_PIN", "TERMS_MISMATCH",
	"COST_MISMATCH", "PROFILE_COVERAGE", "PROFILE_VALUE", "ENDPOINT_OWNERSHIP",
	"OBJECTIVE_MISMATCH", "VERDICT_MISMATCH", "INTERVAL_MISMATCH", "WITNESS_INADMISSIBLE",
	"REDUCTION_UNDECLARED", "REDUCTION_UNSOUND", "SIZE_WINDOW", "CERTIFICATE_WEIGHTS",
	"ENVELOPE_MISMATCH", "ENGINE_DISAGREES",
}

// ReadManifest decodes a bundle manifest from canonical bytes.
func ReadManifest(raw []byte) (Manifest, error) {
	value, err := parse(raw)
	if err != nil {
		return Manifest{}, err
	}
	r, err := object("", value)
	if err != nil {
		return Manifest{}, err
	}
	out := Manifest{}
	out.SchemaVersion = r.str("schema_version", nil, "")
	out.Name = r.str("name", nil, "")
	out.Expects = r.enum("expects", append([]string{"accept"}, RefusalClasses...)...)
	if corruption, present := r.optionalSub("corruption"); present && corruption != nil {
		out.Corruption = &Corruption{
			Of:     corruption.str("of", nil, ""),
			Change: corruption.str("change", nil, ""),
			Target: corruption.str("target", nil, ""),
		}
		r.finish(corruption)
	}
	if files, ok := r.sub("files"); ok {
		out.Proposal = files.str("proposal", nil, "")
		out.Lowered = files.str("lowered", nil, "")
		out.Result = files.str("result", nil, "")
		out.Registry = readNamedFiles(files, "registry", "family")
		out.Snapshots = readNamedFiles(files, "snapshots", "sha256")
		r.finish(files)
	}
	return out, r.done()
}

func readNamedFiles(r *reader, key, nameKey string) []NamedFile {
	out := []NamedFile{}
	for index, item := range r.list(key, 1) {
		child, err := object(at2(r.path, key, index), item)
		if err != nil {
			r.note(err)
			break
		}
		name := ""
		if nameKey == "sha256" {
			name = child.str(nameKey, digestPattern, "a SHA-256")
		} else {
			name = child.str(nameKey, nil, "")
		}
		file := NamedFile{Key: name, Path: child.str("path", nil, "")}
		if err := child.done(); err != nil {
			r.note(err)
			break
		}
		out = append(out, file)
	}
	return out
}

// WriteManifest encodes a bundle manifest as canonical bytes.
func WriteManifest(manifest Manifest) ([]byte, error) {
	registry := make([]any, 0, len(manifest.Registry))
	for _, file := range manifest.Registry {
		registry = append(registry, map[string]any{"family": file.Key, "path": file.Path})
	}
	snapshots := make([]any, 0, len(manifest.Snapshots))
	for _, file := range manifest.Snapshots {
		snapshots = append(snapshots, map[string]any{"sha256": file.Key, "path": file.Path})
	}
	out := map[string]any{
		"schema_version": manifest.SchemaVersion,
		"name":           manifest.Name,
		"expects":        manifest.Expects,
		"files": map[string]any{
			"proposal": manifest.Proposal, "lowered": manifest.Lowered, "result": manifest.Result,
			"registry": registry, "snapshots": snapshots,
		},
	}
	if manifest.Corruption != nil {
		out["corruption"] = map[string]any{
			"of": manifest.Corruption.Of, "change": manifest.Corruption.Change,
			"target": manifest.Corruption.Target,
		}
	}
	return canon.Marshal(out)
}

// ---------------------------------------------------------------- refusal

// Refusal is a checker's answer: accepted, or refused with one class and a detail.
type Refusal struct {
	Accepted bool
	Class    string
	Detail   string
	At       string
	hasAt    bool
	hasWhy   bool
}

// ReadRefusal decodes a refusal from canonical bytes.
func ReadRefusal(raw []byte) (Refusal, error) {
	value, err := parse(raw)
	if err != nil {
		return Refusal{}, err
	}
	r, err := object("", value)
	if err != nil {
		return Refusal{}, err
	}
	out := Refusal{Accepted: r.boolean("accepted")}
	if refusal, present := r.optionalSub("refusal"); present && refusal != nil {
		out.hasWhy = true
		out.Class = refusal.enum("class", RefusalClasses...)
		out.Detail = refusal.str("detail", nil, "")
		out.At, out.hasAt = refusal.optionalStr("at", nil, "")
		r.finish(refusal)
	}
	if out.Accepted && out.hasWhy {
		r.note(fail("", "an accepted bundle carries no refusal"))
	}
	if !out.Accepted && !out.hasWhy {
		r.note(fail("", "a refused bundle says why"))
	}
	return out, r.done()
}

// WriteRefusal encodes a refusal as canonical bytes.
func WriteRefusal(refusal Refusal) ([]byte, error) {
	out := map[string]any{"accepted": refusal.Accepted}
	if refusal.hasWhy {
		inner := map[string]any{"class": refusal.Class, "detail": refusal.Detail}
		setIf(inner, refusal.hasAt, "at", refusal.At)
		out["refusal"] = inner
	}
	return canon.Marshal(out)
}
