package evaluate

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"hedgecheck/engine/doc"
)

// The broad agreement fixture: whole results, on proposals neither author chose.
// Where the kernel cases test one query, these test every field of a result at once.
func TestAgreesWithTheOracleOnGeneratedProposals(t *testing.T) {
	matches, err := filepath.Glob("../../fixtures/generated/ir/*.ir.json")
	if err != nil || len(matches) == 0 {
		t.Fatalf("no generated IR cases found: %v", err)
	}
	if len(matches) < 300 {
		t.Fatalf("only %d cases; the corpus is meant to be broad", len(matches))
	}
	verdicts := map[string]int{}
	for _, path := range matches {
		name := strings.TrimSuffix(filepath.Base(path), ".ir.json")
		t.Run(name, func(t *testing.T) {
			rawIR, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			ir, err := doc.ReadIR(rawIR)
			if err != nil {
				t.Fatalf("refused a generated lowered proposal: %v", err)
			}
			result, err := Evaluate(ir)
			if err != nil {
				t.Fatalf("evaluate: %v", err)
			}
			got, err := doc.WriteResult(result)
			if err != nil {
				t.Fatal(err)
			}
			want, err := os.ReadFile(strings.TrimSuffix(path, ".ir.json") + ".result.json")
			if err != nil {
				t.Fatal(err)
			}
			gotText, wantText, same := equalResults(t, got, want)
			if !same {
				goSide, oracleSide := firstDiff(gotText, wantText)
				t.Errorf("differs from the oracle\n  go     %s\n  oracle %s", goSide, oracleSide)
			}
			verdicts[result.ModelResult]++
		})
	}
	t.Logf("verdicts across %d cases: %v", len(matches), verdicts)
}
