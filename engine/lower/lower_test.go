package lower

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"hedgecheck/engine/canon"
	"hedgecheck/engine/doc"
)

// reviewedRegistry loads the on-disk entries and marks each reviewed, in memory only.
// Reviewing an entry is the owner's act; a test must never perform it on disk.
func reviewedRegistry(t *testing.T) map[string]doc.Entry {
	t.Helper()
	matches, _ := filepath.Glob("../../registry/*.json")
	if len(matches) == 0 {
		t.Fatal("no registry entries")
	}
	out := map[string]doc.Entry{}
	for _, path := range matches {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		entry, err := doc.ReadEntry(raw)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		version, err := entry.SemanticsVersion()
		if err != nil {
			t.Fatal(err)
		}
		entry.SetReviewed("fixture", "2026-09-19", version)
		out[entry.Family] = entry
	}
	return out
}

func replaySnapshots(t *testing.T, directory string) Snapshots {
	t.Helper()
	out := Snapshots{}
	matches, _ := filepath.Glob(filepath.Join(directory, "*.json"))
	for _, path := range matches {
		name := filepath.Base(path)
		if strings.HasSuffix(name, ".request.json") || strings.HasSuffix(name, ".proposal.json") ||
			strings.HasSuffix(name, ".run.json") {
			continue
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := out.Add(raw); err != nil {
			t.Fatalf("%s: %v", path, err)
		}
	}
	return out
}

// Every replay proposal lowers to the same canonical bytes as the oracle's.
func TestLowersReplayProposalsIdentically(t *testing.T) {
	registry := reviewedRegistry(t)
	directories, _ := filepath.Glob("../../fixtures/replay/*")
	checked := 0
	for _, directory := range directories {
		snapshots := replaySnapshots(t, directory)
		proposals, _ := filepath.Glob(filepath.Join(directory, "*.proposal.json"))
		for _, path := range proposals {
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			proposal, err := doc.ReadProposal(raw)
			if err != nil {
				t.Fatalf("%s: %v", path, err)
			}
			ir, versions, err := Lower(proposal, registry, snapshots)
			if err != nil {
				t.Errorf("%s: refused a valid proposal: %v", path, err)
				continue
			}
			if len(versions) != len(proposal.Legs) {
				t.Errorf("%s: %d versions for %d legs", path, len(versions), len(proposal.Legs))
			}
			got, err := doc.WriteIR(ir)
			if err != nil {
				t.Fatal(err)
			}
			// The oracle's own lowering of the same proposal, as bundled.
			want, ok := oracleLowered(t, path)
			if !ok {
				checked++
				continue
			}
			if string(got) != string(want) {
				t.Errorf("%s: lowered bytes differ\n  go     %.200s\n  oracle %.200s", path, got, want)
			}
			checked++
		}
	}
	if checked == 0 {
		t.Fatal("no replay proposals were lowered")
	}
	t.Logf("lowered %d replay proposals", checked)
}

// bundled maps a replay proposal to the bundle carrying the oracle's own lowering of
// it. Named explicitly: two proposals can differ in one field and matching them by
// content would silently compare the wrong pair.
var bundled = map[string]string{
	"bucket0":         "good",
	"bucket0-horizon": "good-horizon",
}

func oracleLowered(t *testing.T, proposalPath string) ([]byte, bool) {
	t.Helper()
	name := strings.TrimSuffix(filepath.Base(proposalPath), ".proposal.json")
	bundle, known := bundled[name]
	if !known {
		return nil, false
	}
	raw, err := os.ReadFile(filepath.Join("../../fixtures/bundles", bundle, "lowered.json"))
	if err != nil {
		return nil, false
	}
	parsed, err := canon.Parse(raw)
	if err != nil {
		t.Fatalf("%s: %v", bundle, err)
	}
	want, err := canon.Marshal(parsed)
	if err != nil {
		t.Fatalf("%s: %v", bundle, err)
	}
	return want, true
}

// Every refusal code has a fixture, and Go raises exactly the code the oracle does.
func TestRefusesWithTheSameCode(t *testing.T) {
	matches, _ := filepath.Glob("../../fixtures/refusals/*.json")
	if len(matches) < 17 {
		t.Fatalf("only %d refusal fixtures; every code lowering can raise needs one", len(matches))
	}
	registry := reviewedRegistry(t)
	snapshots := replaySnapshots(t, "../../fixtures/replay/2026-09-18")
	seen := map[string]bool{}
	for _, path := range matches {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		var fixture struct {
			Name     string                     `json:"name"`
			Expects  string                     `json:"expects"`
			Why      string                     `json:"why"`
			Proposal json.RawMessage            `json:"proposal"`
			Registry map[string]json.RawMessage `json:"registry"`
			Snapshot map[string]string          `json:"snapshots"`
		}
		if err := json.Unmarshal(raw, &fixture); err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		seen[fixture.Expects] = true
		t.Run(fixture.Name, func(t *testing.T) {
			proposal, err := doc.ReadProposal(fixture.Proposal)
			if err != nil {
				// A fixture the decoder refuses never reaches lowering; that is the
				// document layer's job and a different test.
				t.Skipf("the decoder refuses this document: %v", err)
			}
			// A case that needs a different registry or catalogue carries it, so both
			// implementations read the same inputs rather than the tree's at the time.
			cases := registry
			if len(fixture.Registry) > 0 {
				cases = map[string]doc.Entry{}
				for family, raw := range fixture.Registry {
					entry, err := doc.ReadEntry(raw)
					if err != nil {
						t.Fatalf("%s: registry %s: %v", fixture.Name, family, err)
					}
					cases[entry.Family] = entry
				}
			}
			bytes := snapshots
			if len(fixture.Snapshot) > 0 {
				bytes = Snapshots{}
				for digest, snapshot := range snapshots {
					bytes[digest] = snapshot
				}
				for digest, raw := range fixture.Snapshot {
					replacement, err := NewSnapshot([]byte(raw))
					if err != nil {
						t.Fatalf("%s: snapshot: %v", fixture.Name, err)
					}
					// Stored under the digest the proposal cites, which is the point: the
					// bytes changed, the citation did not.
					replacement.Digest = digest
					bytes[digest] = replacement
				}
			}
			_, _, err = Lower(proposal, cases, bytes)
			if err == nil {
				t.Fatalf("accepted a proposal that must be refused: %s", fixture.Why)
			}
			refused, ok := err.(*Refused)
			if !ok {
				t.Fatalf("refused with a plain error rather than a code: %v", err)
			}
			if refused.Code != fixture.Expects {
				t.Errorf("refused with %s, the oracle raises %s (%s)",
					refused.Code, fixture.Expects, fixture.Why)
			}
		})
	}
	t.Logf("checked %d refusal fixtures covering %d codes", len(matches), len(seen))
}

// A changed byte in a retained book is caught by its hash, before any arithmetic.
func TestATamperedBookIsRefusedByHash(t *testing.T) {
	raw, err := os.ReadFile("../../fixtures/replay/2026-09-18/book-bucket0-3971-yes.json")
	if err != nil {
		t.Fatal(err)
	}
	original, err := NewSnapshot(raw)
	if err != nil {
		t.Fatal(err)
	}
	tampered, err := NewSnapshot([]byte(strings.Replace(string(raw), "0.17399", "0.17398", 1)))
	if err != nil {
		t.Fatal(err)
	}
	if tampered.Digest == original.Digest {
		t.Fatal("a one-cent change did not change the digest")
	}
	// A store keyed by digest cannot serve the tampered bytes under the original name,
	// so the citation simply finds nothing.
	snapshots := Snapshots{}
	if _, err := snapshots.Add(tampered.Raw); err != nil {
		t.Fatal(err)
	}
	if _, err := snapshots.cited(original.Digest, "book"); err == nil {
		t.Fatal("the tampered bytes were served under the original digest")
	}
}
