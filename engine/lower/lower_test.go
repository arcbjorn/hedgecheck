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
// referenceMap loads the reviewed mapping the refusal fixtures need.
//
// Without it a templated leg is refused for having NO mapping, which happens to be the
// same code -- so the `ambiguous` branch, the one that matters, went untested. The map is
// data, so the test reads it rather than restating it.
func referenceMap(t *testing.T) References {
	t.Helper()
	raw, err := os.ReadFile("../../references/reference-map.json")
	if err != nil {
		t.Skipf("no reference map: %v", err)
	}
	var document struct {
		Mappings []struct {
			Venue            string `json:"venue"`
			PriceDescription string `json:"price_description"`
			Seconds          string `json:"seconds"`
			State            string `json:"state"`
			Reference        string `json:"reference"`
			Why              string `json:"why"`
		} `json:"mappings"`
	}
	if err := json.Unmarshal(raw, &document); err != nil {
		t.Fatal(err)
	}
	out := References{}
	for _, m := range document.Mappings {
		out[ReferenceKey(m.Venue, m.PriceDescription, m.Seconds)] = doc.ReferenceMapping{
			Venue: m.Venue, PriceDescription: m.PriceDescription, Seconds: m.Seconds,
			State: m.State, Reference: m.Reference, Why: m.Why,
		}
	}
	if len(out) == 0 {
		t.Fatal("the reference map is empty")
	}
	return out
}

func TestRefusesWithTheSameCode(t *testing.T) {
	// The fixtures are DERIVED and are not in git: `make generated` writes them, or
	// `python3 tools/make_refusals.py`. Zero of them is a missing corpus, not a passing
	// test, so this fails loudly rather than verifying nothing.
	matches, _ := filepath.Glob("../../fixtures/refusals/*.json")
	if len(matches) < 17 {
		t.Fatalf("only %d refusal fixtures; every code lowering can raise needs one. "+
			"They are generated, not committed: run `make generated`", len(matches))
	}
	registry := reviewedRegistry(t)
	snapshots := replaySnapshots(t, "../../fixtures/replay/2026-09-18")
	references := referenceMap(t)
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
			_, _, err = Lower(proposal, cases, bytes, references)
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

// A DEPLOYER LEG IS REDUCED, BECAUSE ITS PAYOUT IS SUBMITTED RATHER THAN COMPUTED.
//
// EVIDENCE section 1, verified: `settleOutcome` carries a `settleFraction` the deployer
// chooses, and nothing in the protocol derives it from a price. So the template says
// what the deployer said they would do, not what they must -- and lowering must not
// value such a leg as written.
//
// This guards GO's own rule. The bundle fixtures are generated by Python and checked by
// Python and TypeScript, so disabling this branch left `make check` entirely green: a
// fix with no guard, which is the pattern this project keeps meeting.
func TestADeployerLegIsReduced(t *testing.T) {
	registry := reviewedRegistry(t)
	snapshots := replaySnapshots(t, "../../fixtures/replay/2026-09-18")
	raw, err := os.ReadFile("../../fixtures/replay/2026-09-18/bucket0.proposal.json")
	if err != nil {
		t.Fatal(err)
	}
	proposal, err := doc.ReadProposal(raw)
	if err != nil {
		t.Fatal(err)
	}

	for _, settlement := range []string{"protocol", "deployer"} {
		entries := map[string]doc.Entry{}
		for family, entry := range registry {
			entry.Settlement = settlement
			// Repin: settlement is part of the semantics, so changing it moves the
			// digest, and a stale pin would refuse before the rule is ever reached.
			version, err := entry.SemanticsVersion()
			if err != nil {
				t.Fatal(err)
			}
			entry.SetReviewed("fixture", "2026-09-19", version)
			entries[family] = entry
		}
		repinned := proposal
		repinned.Legs = append([]doc.ProposalLeg(nil), proposal.Legs...)
		for index := range repinned.Legs {
			version, err := entries[repinned.Legs[index].Family].SemanticsVersion()
			if err != nil {
				t.Fatal(err)
			}
			repinned.Legs[index].SemanticsVersion = version
		}

		ir, _, err := Lower(repinned, entries, snapshots)
		if err != nil {
			t.Fatalf("%s: %v", settlement, err)
		}
		rules := map[string]bool{}
		for _, reduction := range ir.Reductions {
			rules[reduction.Rule] = true
			if reduction.Rule == "deployer_settled" {
				// LOOSE, always: a leg nobody is bound to pay must never make a
				// proposal fail, only need review.
				if reduction.Tight {
					t.Errorf("deployer_settled is tight; a loose bound is what stops it condemning a hedge")
				}
				if reduction.ReasonCode != "DEPLOYER_SETTLED" {
					t.Errorf("reason code %q, want DEPLOYER_SETTLED", reduction.ReasonCode)
				}
			}
		}
		switch settlement {
		case "protocol":
			if rules["deployer_settled"] {
				t.Error("a protocol-settled family was reduced as deployer-settled")
			}
		case "deployer":
			if !rules["deployer_settled"] {
				t.Error("a deployer-settled family was valued as written; its payout is submitted, not computed")
			}
		}
	}
}

// EVERY GOOD BUNDLE'S PROPOSAL, LOWERED BY THIS ENGINE.
//
// The replay test above lowers proposals whose every reference agrees, so it cannot see a
// band reduction. A bundle carries its own proposal, its own registry copies and the IR
// Python lowered them to, so this holds Go to that IR byte for byte -- including the two
// bundles with a leg on a foreign price series, which is where the two lowerings had
// nothing in common before.
func TestLowersEveryBundleProposalIdentically(t *testing.T) {
	bundles, err := filepath.Glob("../../fixtures/bundles/good*")
	if err != nil || len(bundles) == 0 {
		t.Fatalf("no good bundles: %v", err)
	}
	checked := 0
	for _, directory := range bundles {
		name := filepath.Base(directory)
		raw, err := os.ReadFile(filepath.Join(directory, "proposal.json"))
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		proposal, err := doc.ReadProposal(raw)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}

		// The bundle's OWN registry copies, not the repository's: a bundle records the
		// reading it was built against, and that is the whole point of carrying them.
		entries := map[string]doc.Entry{}
		copies, _ := filepath.Glob(filepath.Join(directory, "registry-*.json"))
		for _, path := range copies {
			entryRaw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			entry, err := doc.ReadEntry(entryRaw)
			if err != nil {
				t.Fatalf("%s: %v", path, err)
			}
			entries[entry.Family] = entry
		}
		snapshots := Snapshots{}
		shots, _ := filepath.Glob(filepath.Join(directory, "snapshot-*.json"))
		for _, path := range shots {
			shot, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := snapshots.Add(shot); err != nil {
				t.Fatalf("%s: %v", path, err)
			}
		}

		ir, _, err := Lower(proposal, entries, snapshots)
		if err != nil {
			t.Errorf("%s: refused a valid proposal: %v", name, err)
			continue
		}
		got, err := doc.WriteIR(ir)
		if err != nil {
			t.Fatal(err)
		}
		want, err := os.ReadFile(filepath.Join(directory, "lowered.json"))
		if err != nil {
			t.Fatal(err)
		}
		if string(got) != strings.TrimRight(string(want), "\n") {
			t.Errorf("%s: lowered differs from the oracle's\n  go     %.180s\n  oracle %.180s",
				name, got, want)
		}
		checked++
	}
	if checked < 5 {
		t.Fatalf("only %d bundles lowered", checked)
	}
}
