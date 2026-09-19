package doc

import (
	"os"
	"path/filepath"
	"testing"
)

func TestReadsRealLoweredProposals(t *testing.T) {
	for _, path := range []string{
		"../../fixtures/golden/1000-contracts.ir.json",
		"../../fixtures/bundles/good/lowered.json",
		"../../fixtures/bundles/good-horizon/lowered.json",
	} {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		ir, err := ReadIR(raw)
		if err != nil {
			t.Errorf("%s: refused a valid document: %v", path, err)
			continue
		}
		t.Logf("%s: %d legs, %d clauses, %d reductions, capture=%v",
			filepath.Base(path), len(ir.Legs), len(ir.Objective), len(ir.Reductions), ir.Capture != nil)
	}
}

func TestRefusesEveryRejectedIR(t *testing.T) {
	matches, _ := filepath.Glob("../../fixtures/rejected/ir/*.json")
	if len(matches) == 0 {
		t.Fatal("no rejected ir fixtures found")
	}
	for _, path := range matches {
		raw, _ := os.ReadFile(path)
		if _, err := ReadIR(raw); err == nil {
			why, _ := os.ReadFile(path[:len(path)-5] + ".why")
			t.Errorf("%s ACCEPTED, should refuse: %s", filepath.Base(path), why)
		}
	}
	t.Logf("checked %d rejected ir documents", len(matches))
}
