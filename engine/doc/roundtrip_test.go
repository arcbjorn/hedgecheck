package doc

import (
	"os"
	"path/filepath"
	"testing"

	"hedgecheck/engine/canon"
)

// The rule an encoder lives or dies by: decode then encode reproduces the document's
// CANONICAL bytes exactly. An optional field that was absent must stay absent,
// because a document's digest is what a result is cited by.
//
// Compared against the canonical form of the input rather than the file as stored:
// some fixtures are hand-formatted for a reader (the golden lowered proposal is), and
// re-indenting them is not the encoder's job. Where a fixture is already canonical --
// every bundle document is -- that is the same as comparing the file byte for byte.
func TestIRRoundTripIsByteExact(t *testing.T) {
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
			t.Fatalf("%s: %v", path, err)
		}
		out, err := WriteIR(ir)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		// The canonical form of what was read, via the same encoder canon provides.
		parsed, err := canon.Parse(raw)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		want, err := canon.Marshal(parsed)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		if string(out) != string(want) {
			t.Errorf("%s: round trip differs\n  got  %s\n  want %s",
				filepath.Base(path), truncate(string(out)), truncate(string(want)))
		}
	}
}

func truncate(s string) string {
	if len(s) > 220 {
		return s[:220] + "..."
	}
	return s
}
