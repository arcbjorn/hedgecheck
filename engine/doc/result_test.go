package doc

import (
	"os"
	"path/filepath"
	"testing"

	"hedgecheck/engine/canon"
)

func TestResultRoundTripIsByteExact(t *testing.T) {
	for _, path := range []string{
		"../../fixtures/golden/1000-contracts.result.json",
		"../../fixtures/bundles/good/result.json",
		"../../fixtures/bundles/good-horizon/result.json",
	} {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		result, err := ReadResult(raw)
		if err != nil {
			t.Fatalf("%s: refused a valid result: %v", path, err)
		}
		out, err := WriteResult(result)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		parsed, _ := canon.Parse(raw)
		want, _ := canon.Marshal(parsed)
		if string(out) != string(want) {
			t.Errorf("%s: round trip differs\n  got  %.200s\n  want %.200s", filepath.Base(path), out, want)
		}
	}
}

func TestRefusesEveryRejectedResult(t *testing.T) {
	matches, _ := filepath.Glob("../../fixtures/rejected/result/*.json")
	if len(matches) == 0 {
		t.Fatal("no rejected result fixtures")
	}
	for _, path := range matches {
		raw, _ := os.ReadFile(path)
		if _, err := ReadResult(raw); err == nil {
			why, _ := os.ReadFile(path[:len(path)-5] + ".why")
			t.Errorf("%s ACCEPTED, should refuse: %s", filepath.Base(path), why)
		}
	}
	t.Logf("checked %d rejected result documents", len(matches))
}
