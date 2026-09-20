package evaluate

import (
	"fmt"
	"sort"

	"hedgecheck/engine/doc"
)

// Candidate is one proposal that was evaluated on its own, ready to be ranked.
type Candidate struct {
	Label  string
	IR     doc.IR
	Result doc.Result
}

// Compare ranks independently evaluated proposals.
//
// Nothing here re-evaluates anything. The comparison cites each result by its
// `ir_digest` and restates none of its numbers, so a result stays about one proposal
// and stays checkable on its own: a checker verifies the results first, then
// re-derives this ranking from them.
//
// Proposals that do not share an objective, domain, baseline and valuation time are
// answers to different questions, so ranking them is an error rather than a number.
func Compare(candidates []Candidate) (doc.Comparison, error) {
	if len(candidates) < 2 {
		return doc.Comparison{}, fmt.Errorf("evaluate: a comparison needs at least two candidates")
	}
	first := candidates[0].IR
	shared := doc.Shared{
		Domain:                 first.Domain,
		Baseline:               first.Baseline,
		Objective:              first.Objective,
		ObjectiveValuationTime: first.ObjectiveValuationTime,
	}
	reference, err := sharedBytes(shared)
	if err != nil {
		return doc.Comparison{}, err
	}
	for _, candidate := range candidates {
		theirs, err := sharedBytes(doc.Shared{
			Domain:                 candidate.IR.Domain,
			Baseline:               candidate.IR.Baseline,
			Objective:              candidate.IR.Objective,
			ObjectiveValuationTime: candidate.IR.ObjectiveValuationTime,
		})
		if err != nil {
			return doc.Comparison{}, err
		}
		if theirs != reference {
			return doc.Comparison{}, fmt.Errorf(
				"evaluate: %s does not share the objective, domain, baseline and valuation time",
				candidate.Label)
		}
	}

	out := doc.Comparison{
		SchemaVersion: "1",
		Shared:        shared,
		RankedBy:      "cost_of_smallest_passing_size",
		EngineVersion: Version,
	}
	passing := []doc.Candidate{}
	for _, candidate := range candidates {
		entry := doc.Candidate{
			Label:       candidate.Label,
			IRDigest:    candidate.Result.IRDigest,
			ModelResult: candidate.Result.ModelResult,
			Cost:        candidate.Result.Cost.Premium,
		}
		out.Candidates = append(out.Candidates, entry)
		// Only a passing candidate is ranked: a cost that bought an unestablished
		// result has no place in an ordering by cost.
		if entry.ModelResult == "passes" {
			passing = append(passing, entry)
		}
	}
	if len(passing) > 0 {
		// Stable, so equal costs keep the caller's order rather than an arbitrary one.
		sort.SliceStable(passing, func(i, j int) bool {
			return passing[i].Cost.Less(passing[j].Cost)
		})
		labels := make([]string, 0, len(passing))
		for _, entry := range passing {
			labels = append(labels, entry.Label)
		}
		out.SetRanking(labels)
	}
	return out, nil
}

// sharedBytes renders the shared terms canonically, so "the same question" is a byte
// comparison rather than a field-by-field one that could miss a field added later.
func sharedBytes(shared doc.Shared) (string, error) {
	raw, err := doc.SharedCanonical(shared)
	if err != nil {
		return "", err
	}
	return string(raw), nil
}
