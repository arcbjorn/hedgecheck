package doc

import (
	"os"
	"path/filepath"
	"testing"

	"hedgecheck/engine/canon"
)

func TestRegistryEntryRoundTripAndSemantics(t *testing.T) {
	matches, _ := filepath.Glob("../../registry/*.json")
	if len(matches) == 0 {
		t.Fatal("no registry entries found")
	}
	for _, path := range matches {
		raw, _ := os.ReadFile(path)
		entry, err := ReadEntry(raw)
		if err != nil {
			t.Fatalf("%s: refused a valid entry: %v", path, err)
		}
		out, err := WriteEntry(entry)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		parsed, _ := canon.Parse(raw)
		want, _ := canon.Marshal(parsed)
		if string(out) != string(want) {
			t.Errorf("%s: round trip differs", filepath.Base(path))
		}
		version, err := entry.SemanticsVersion()
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		reviewed, _ := entry.Reviewed()
		t.Logf("%s: semantics %s reviewed=%v", filepath.Base(path), version[:12], reviewed)
	}
}

func TestRefusesEveryRejectedEntry(t *testing.T) {
	matches, _ := filepath.Glob("../../fixtures/rejected/registry-entry/*.json")
	if len(matches) == 0 {
		t.Fatal("no rejected registry fixtures")
	}
	for _, path := range matches {
		raw, _ := os.ReadFile(path)
		if _, err := ReadEntry(raw); err == nil {
			why, _ := os.ReadFile(path[:len(path)-5] + ".why")
			t.Errorf("%s ACCEPTED, should refuse: %s", filepath.Base(path), why)
		}
	}
	t.Logf("checked %d rejected registry documents", len(matches))
}
