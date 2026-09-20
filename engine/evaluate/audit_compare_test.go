package evaluate

import (
	"strings"
	"testing"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
)

func aq(t *testing.T, text string) exact.Q {
	t.Helper()
	value, err := exact.ParseQ(text)
	if err != nil {
		t.Fatal(err)
	}
	return value
}

func candidateFor(t *testing.T, label, verdict, cost string) Candidate {
	t.Helper()
	ir := doc.IR{
		SchemaVersion: "1",
		Domain:        doc.Domain{Lower: aq(t, "60000"), Upper: aq(t, "110000")},
		Baseline:      doc.Baseline{Kind: "explicit", Price: aq(t, "80000"), Label: "operator-supplied"},
		Objective: []doc.Clause{
			{ID: "loss_cap", MinPnl: aq(t, "-1000")},
		},
		ObjectiveValuationTime: "2026-09-21T06:00:00Z",
	}
	return Candidate{
		Label: label, IR: ir,
		Result: doc.Result{
			ModelResult: verdict, IRDigest: strings.Repeat("a", 64),
			Cost: doc.CostSummary{Premium: aq(t, cost)},
		},
	}
}

// A comparison of proposals that answer DIFFERENT questions is an error, not a
// ranking. Every field of the shared terms is driven, because the check is a byte
// comparison and a field added later must be covered by it automatically.
func TestAuditCompareRefusesDifferentQuestions(t *testing.T) {
	differences := []struct {
		what   string
		change func(*doc.IR)
	}{
		{"the domain's floor", func(ir *doc.IR) { ir.Domain.Lower = aq(t, "50000") }},
		{"the domain's ceiling", func(ir *doc.IR) { ir.Domain.Upper = aq(t, "120000") }},
		{"the baseline price", func(ir *doc.IR) { ir.Baseline.Price = aq(t, "80001") }},
		{"the baseline kind", func(ir *doc.IR) {
			ir.Baseline.Kind = "analysis_time"
			ir.Baseline.Label = ""
			ir.Baseline.Snapshot = strings.Repeat("b", 64)
			ir.Baseline.Coin = "BTC"
		}},
		{"the cap", func(ir *doc.IR) { ir.Objective[0].MinPnl = aq(t, "-2000") }},
		{"the clause id", func(ir *doc.IR) { ir.Objective[0].ID = "other_cap" }},
		{"an extra clause", func(ir *doc.IR) {
			ir.Objective = append(ir.Objective, doc.Clause{ID: "second", MinPnl: aq(t, "-5000")})
		}},
		{"the valuation time", func(ir *doc.IR) { ir.ObjectiveValuationTime = "2026-09-22T06:00:00Z" }},
	}
	for _, difference := range differences {
		first := candidateFor(t, "a", "passes", "100")
		second := candidateFor(t, "b", "passes", "200")
		second.IR.Objective = append([]doc.Clause(nil), second.IR.Objective...)
		difference.change(&second.IR)

		_, err := Compare([]Candidate{first, second})
		if err == nil {
			t.Errorf("candidates differing in %s were ranked against each other", difference.what)
			continue
		}
		if !strings.Contains(err.Error(), "does not share") {
			t.Errorf("%s: the error does not say they answer different questions: %v",
				difference.what, err)
		}
	}
}

// Only PASSING candidates are ranked: a cost that bought an unestablished result has
// no place in an ordering by cost.
func TestAuditCompareRanksOnlyPassingCandidates(t *testing.T) {
	cheapFailing := candidateFor(t, "cheap_but_failing", "fails", "10")
	cheapUnestablished := candidateFor(t, "cheap_but_unreviewed", "needs_review", "20")
	dearPassing := candidateFor(t, "dear_but_passing", "passes", "900")

	comparison, err := Compare([]Candidate{cheapFailing, cheapUnestablished, dearPassing})
	if err != nil {
		t.Fatal(err)
	}
	if len(comparison.Candidates) != 3 {
		t.Errorf("the comparison lists %d candidates, want all 3", len(comparison.Candidates))
	}
	if len(comparison.Ranking) != 1 || comparison.Ranking[0] != "dear_but_passing" {
		t.Errorf("ranking is %v, want only the passing candidate", comparison.Ranking)
	}
}

// With nothing passing, there is no ranking at all rather than an ordering of
// results that were never established.
func TestAuditCompareRanksNothingWhenNothingPasses(t *testing.T) {
	comparison, err := Compare([]Candidate{
		candidateFor(t, "a", "needs_review", "10"),
		candidateFor(t, "b", "fails", "20"),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(comparison.Ranking) != 0 {
		t.Errorf("ranking is %v, want nothing ranked", comparison.Ranking)
	}
}

// The ranking is by exact cost, cheapest first, and ties keep their input order.
func TestAuditCompareOrdersByExactCost(t *testing.T) {
	comparison, err := Compare([]Candidate{
		candidateFor(t, "dear", "passes", "100.002"),
		candidateFor(t, "cheap", "passes", "100.001"),
		candidateFor(t, "tie_first", "passes", "100.001"),
	})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"cheap", "tie_first", "dear"}
	if len(comparison.Ranking) != len(want) {
		t.Fatalf("ranking is %v, want %v", comparison.Ranking, want)
	}
	for index := range want {
		if comparison.Ranking[index] != want[index] {
			t.Errorf("ranking is %v, want %v", comparison.Ranking, want)
			break
		}
	}
}

// A comparison of one is not a comparison.
func TestAuditCompareNeedsTwo(t *testing.T) {
	for _, count := range []int{0, 1} {
		candidates := []Candidate{}
		for index := 0; index < count; index++ {
			candidates = append(candidates, candidateFor(t, "a", "passes", "1"))
		}
		if _, err := Compare(candidates); err == nil {
			t.Errorf("%d candidates were compared", count)
		}
	}
}

// The comparison restates NO numbers of its own beyond the cost it ranks by: it
// cites each result by ir_digest so a checker verifies the results first and
// re-derives the ranking from them.
func TestAuditComparisonRestatesNoResultNumbers(t *testing.T) {
	first := candidateFor(t, "a", "passes", "100")
	second := candidateFor(t, "b", "passes", "200")
	first.Result.WorstCase = doc.NewWorstCase(aq(t, "-123.45"), aq(t, "60000"), true)
	second.Result.WorstCase = doc.NewWorstCase(aq(t, "-678.90"), aq(t, "60000"), true)

	comparison, err := Compare([]Candidate{first, second})
	if err != nil {
		t.Fatal(err)
	}
	encoded, err := doc.WriteComparison(comparison)
	if err != nil {
		t.Fatal(err)
	}
	for _, restated := range []string{"-123.45", "-678.90"} {
		if strings.Contains(string(encoded), restated) {
			t.Errorf("the comparison restates the worst case %s from a result", restated)
		}
	}
	for _, candidate := range comparison.Candidates {
		if candidate.IRDigest == "" {
			t.Errorf("%s is not cited by ir_digest", candidate.Label)
		}
	}
}
