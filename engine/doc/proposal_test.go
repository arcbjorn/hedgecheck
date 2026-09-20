package doc

import (
	"os"
	"path/filepath"
	"testing"

	"hedgecheck/engine/canon"
)

func TestProposalRoundTripIsByteExact(t *testing.T) {
	matches, _ := filepath.Glob("../../fixtures/replay/*/*.proposal.json")
	extra, _ := filepath.Glob("../../fixtures/bundles/*/proposal.json")
	matches = append(matches, extra...)
	if len(matches) == 0 {
		t.Fatal("no proposals found")
	}
	for _, path := range matches {
		raw, _ := os.ReadFile(path)
		proposal, err := ReadProposal(raw)
		if err != nil {
			t.Errorf("%s: refused a valid proposal: %v", path, err)
			continue
		}
		out, err := WriteProposal(proposal)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		parsed, _ := canon.Parse(raw)
		want, _ := canon.Marshal(parsed)
		if string(out) != string(want) {
			t.Errorf("%s: round trip differs\n  got  %.180s\n  want %.180s", path, out, want)
		}
	}
	t.Logf("round-tripped %d proposals", len(matches))
}

func TestRefusesEveryRejectedProposal(t *testing.T) {
	matches, _ := filepath.Glob("../../fixtures/rejected/proposal/*.json")
	for _, path := range matches {
		raw, _ := os.ReadFile(path)
		if _, err := ReadProposal(raw); err == nil {
			why, _ := os.ReadFile(path[:len(path)-5] + ".why")
			t.Errorf("%s ACCEPTED, should refuse: %s", filepath.Base(path), why)
		}
	}
	t.Logf("checked %d rejected proposals", len(matches))
}
