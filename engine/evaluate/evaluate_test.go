package evaluate

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"hedgecheck/engine/canon"
	"hedgecheck/engine/doc"
)

// Two results are equal when their canonical bytes match after removing the single
// key engine_version. No other field may differ.
func equalResults(t *testing.T, got, want []byte) (string, string, bool) {
	t.Helper()
	strip := func(raw []byte) string {
		var value map[string]any
		if err := json.Unmarshal(raw, &value); err != nil {
			t.Fatalf("parse: %v", err)
		}
		delete(value, "engine_version")
		out, err := canon.Marshal(value)
		if err != nil {
			t.Fatalf("marshal: %v", err)
		}
		return string(out)
	}
	a, b := strip(got), strip(want)
	return a, b, a == b
}

func TestReproducesPinnedResults(t *testing.T) {
	pairs := []struct{ ir, result string }{
		{"../../fixtures/golden/1000-contracts.ir.json", "../../fixtures/golden/1000-contracts.result.json"},
		{"../../fixtures/bundles/good/lowered.json", "../../fixtures/bundles/good/result.json"},
		{"../../fixtures/bundles/good-horizon/lowered.json", "../../fixtures/bundles/good-horizon/result.json"},
	}
	for _, pair := range pairs {
		rawIR, err := os.ReadFile(pair.ir)
		if err != nil {
			t.Fatalf("%s: %v", pair.ir, err)
		}
		ir, err := doc.ReadIR(rawIR)
		if err != nil {
			t.Fatalf("%s: %v", pair.ir, err)
		}
		result, err := Evaluate(ir)
		if err != nil {
			t.Fatalf("%s: %v", pair.ir, err)
		}
		got, err := doc.WriteResult(result)
		if err != nil {
			t.Fatalf("%s: %v", pair.ir, err)
		}
		want, err := os.ReadFile(pair.result)
		if err != nil {
			t.Fatalf("%s: %v", pair.result, err)
		}
		gotText, wantText, same := equalResults(t, got, want)
		if !same {
			goSide, oracleSide := firstDiff(gotText, wantText)
			t.Errorf("%s: differs from the oracle\n  go     %s\n  oracle %s",
				filepath.Base(pair.ir), goSide, oracleSide)
		}
	}
}

// firstDiff points at the first byte that differs, with context, so a 4 KB result
// does not have to be read in full.
func firstDiff(a, b string) (string, string) {
	limit := len(a)
	if len(b) < limit {
		limit = len(b)
	}
	for i := 0; i < limit; i++ {
		if a[i] != b[i] {
			start := i - 60
			if start < 0 {
				start = 0
			}
			end := i + 120
			if end > limit {
				end = limit
			}
			return "..." + a[start:end], "..." + b[start:end]
		}
	}
	return a[:min(200, len(a))], b[:min(200, len(b))]
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// Evaluating twice gives identical bytes. Map iteration order in Go is randomised per
// run, so anything that leaked a map into output would show up here.
func TestEvaluationIsDeterministic(t *testing.T) {
	raw, _ := os.ReadFile("../../fixtures/bundles/good-horizon/lowered.json")
	ir, err := doc.ReadIR(raw)
	if err != nil {
		t.Fatal(err)
	}
	var first []byte
	for attempt := 0; attempt < 20; attempt++ {
		result, err := Evaluate(ir)
		if err != nil {
			t.Fatal(err)
		}
		out, err := doc.WriteResult(result)
		if err != nil {
			t.Fatal(err)
		}
		if first == nil {
			first = out
			continue
		}
		if string(out) != string(first) {
			t.Fatalf("attempt %d differs from the first", attempt)
		}
	}
}

// A loose bound can never produce `fails`. This takes the tight horizon fixture, which
// really does fail, and makes its reduction loose; the failure must stop being one.
func TestALooseBoundCannotFail(t *testing.T) {
	raw, _ := os.ReadFile("../../fixtures/bundles/good-horizon/lowered.json")
	ir, err := doc.ReadIR(raw)
	if err != nil {
		t.Fatal(err)
	}
	tight, err := Evaluate(ir)
	if err != nil {
		t.Fatal(err)
	}
	if tight.ModelResult != "fails" || len(tight.FailingIntervals) == 0 {
		t.Fatalf("the fixture is meant to fail on a tight bound, got %s", tight.ModelResult)
	}
	for index := range ir.Reductions {
		ir.Reductions[index].Tight = false
	}
	loose, err := Evaluate(ir)
	if err != nil {
		t.Fatal(err)
	}
	if loose.ModelResult == "fails" {
		t.Fatal("a loose bound produced `fails`")
	}
	if loose.ModelResult != "needs_review" {
		t.Fatalf("expected needs_review, got %s", loose.ModelResult)
	}
	if len(loose.FailingIntervals) != 0 {
		t.Fatalf("a loose bound proved %d failing intervals", len(loose.FailingIntervals))
	}
	if len(loose.UndecidedIntervals) == 0 {
		t.Fatal("the violation did not move to undecided intervals")
	}
}

// The failing set is strictly below the cap: P&L exactly at the cap MEETS it.
//
// No pinned result touches the boundary, so without this the strictness is guarded
// only in the kernel's own cases. The golden table states it: 82,000 and 92,000 give
// exactly -1000 and are not failures.
func TestTheCapItselfIsNotAFailure(t *testing.T) {
	raw, _ := os.ReadFile("../../fixtures/golden/1000-contracts.ir.json")
	ir, err := doc.ReadIR(raw)
	if err != nil {
		t.Fatal(err)
	}
	result, err := Evaluate(ir)
	if err != nil {
		t.Fatal(err)
	}
	// [60000, 82000) and [90000, 92000): both upper ends are exactly -1000 and excluded.
	if len(result.FailingIntervals) != 2 {
		t.Fatalf("expected 2 failing intervals, got %d", len(result.FailingIntervals))
	}
	for _, interval := range result.FailingIntervals {
		if interval.UpperIncl {
			t.Errorf("interval ending at %s owns its upper end; the cap itself is not a failure",
				interval.Upper)
		}
	}
	if result.FailingIntervals[0].Upper.String() != "82000" ||
		result.FailingIntervals[1].Upper.String() != "92000" {
		t.Fatalf("boundaries moved: %s and %s",
			result.FailingIntervals[0].Upper, result.FailingIntervals[1].Upper)
	}
}

// THE ADVERSE WORDING IS A CONTRACT BETWEEN TWO IMPLEMENTATIONS.
//
// `adverseWording` carries the comment "two implementations must produce the same
// string", and until this test that agreement was incidental: it held only for rules
// that appear in a FAILING fixture, because the string reaches a result through a
// witness, and a witness only attaches to a failing interval.
//
// So a LOOSE rule's wording -- `unreviewed_family`, `deployer_settled` -- could drift
// between Go and Python with every check green. Verified by mutation before this test
// existed: changing Go's `deployer_settled` string left `make check` entirely green,
// while the same edit to `horizon_mismatch` was caught, because `good-horizon` fails
// and carries that witness.
//
// The maps are compared directly, so a rule needs no failing fixture to be pinned.
func TestAdverseWordingMatchesTheOracle(t *testing.T) {
	raw, err := os.ReadFile("../../oracle/oracle.py")
	if err != nil {
		t.Skip(err)
	}
	block := regexp.MustCompile(`(?s)ADVERSE_STATES\s*=\s*\{(.*?)\}`).FindSubmatch(raw)
	if block == nil {
		t.Fatal("oracle.py states no ADVERSE_STATES map")
	}
	entry := regexp.MustCompile(`"([a-z_]+)":\s*"((?:[^"\\]|\\.)*)"`)
	theirs := map[string]string{}
	for _, match := range entry.FindAllSubmatch(block[1], -1) {
		theirs[string(match[1])] = strings.ReplaceAll(string(match[2]), `\'`, `'`)
	}
	if len(theirs) == 0 {
		t.Fatal("no entries parsed from ADVERSE_STATES; the test is not reading what it thinks")
	}

	for rule, ours := range adverseWording {
		their, known := theirs[rule]
		if !known {
			t.Errorf("Go states %q for %s; the oracle states no wording at all", ours, rule)
			continue
		}
		if their != ours {
			t.Errorf("%s: Go says %q, the oracle says %q", rule, ours, their)
		}
	}
	for rule := range theirs {
		if _, known := adverseWording[rule]; !known {
			t.Errorf("the oracle states a wording for %s; Go states none", rule)
		}
	}
	// The rules this test is meant to cover, named so a silent shrink is caught.
	for _, rule := range []string{"horizon_mismatch", "unreviewed_family", "deployer_settled"} {
		if _, known := adverseWording[rule]; !known {
			t.Errorf("%s lost its adverse wording", rule)
		}
	}
}
