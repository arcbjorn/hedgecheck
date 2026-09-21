package doc

import (
	"encoding/json"
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

// A REFERENCE IS NEVER FREE TEXT, INCLUDING IN A REGISTRY ENTRY.
//
// PLAN section 6: reference ids are `source:series:statistic[:window]`, "never free
// text". The proposal's references were read with `refPattern`; the ENTRY's was read
// with no pattern at all, so "free text here", "" and "hl:perp" were all accepted. A
// reference decides which price series a payoff is observed on, so an unconstrained one
// is a leg valued against a series nobody can name.
//
// The entry carries a TEMPLATE -- `hl:perp:{underlying}:mark-interp` -- so the pattern
// admits a whole segment being a {placeholder}, and nothing looser. Tightening it to
// the plain `refPattern` refused every real entry, which is how that was found.
func TestAnEntryReferenceIsNotFreeText(t *testing.T) {
	raw, err := os.ReadFile("../../registry/recurring.priceBucket.json")
	if err != nil {
		t.Skip(err)
	}
	var entry map[string]any
	if err := json.Unmarshal(raw, &entry); err != nil {
		t.Fatal(err)
	}

	for _, good := range []string{
		"hl:perp:{underlying}:mark-interp",
		"hl:perp:BTC:mark-interp",
		"pyth:BTC/USD:price-twap:90s",
		"synthetic",
	} {
		entry["reference"] = good
		edited, _ := json.Marshal(entry)
		if _, err := ReadEntry(edited); err != nil {
			t.Errorf("reference %q was refused: %v", good, err)
		}
	}
	for _, bad := range []string{
		"free text here", "", "NOT A REF", "hl:perp",
		"hl:perp:{Underlying}:mark-interp", // a placeholder is lower-case
		"hl perp BTC mark",
	} {
		entry["reference"] = bad
		edited, _ := json.Marshal(entry)
		if _, err := ReadEntry(edited); err == nil {
			t.Errorf("reference %q was accepted; a reference is never free text", bad)
		}
	}
}
