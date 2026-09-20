package doc

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"hedgecheck/engine/canon"
)

// Every contract document in the tree round-trips byte-exactly, not just the IR.
//
// The existing test covers three lowered proposals. There are six document types and
// a few hundred fixtures; an encoder that drops an optional field, or writes one that
// was absent, changes the digest the document is cited by. That is a silent wrong
// answer, so it is checked on everything rather than on a sample.
func TestAuditEveryFixtureRoundTrips(t *testing.T) {
	readers := map[string]struct {
		read  func([]byte) (any, error)
		write func(any) ([]byte, error)
	}{
		"ir": {
			read:  func(b []byte) (any, error) { return ReadIR(b) },
			write: func(v any) ([]byte, error) { return WriteIR(v.(IR)) },
		},
		"result": {
			read:  func(b []byte) (any, error) { return ReadResult(b) },
			write: func(v any) ([]byte, error) { return WriteResult(v.(Result)) },
		},
		"proposal": {
			read:  func(b []byte) (any, error) { return ReadProposal(b) },
			write: func(v any) ([]byte, error) { return WriteProposal(v.(Proposal)) },
		},
		"entry": {
			read:  func(b []byte) (any, error) { return ReadEntry(b) },
			write: func(v any) ([]byte, error) { return WriteEntry(v.(Entry)) },
		},
		"comparison": {
			read:  func(b []byte) (any, error) { return ReadComparison(b) },
			write: func(v any) ([]byte, error) { return WriteComparison(v.(Comparison)) },
		},
	}

	kindOf := func(path string) string {
		name := filepath.Base(path)
		switch {
		case strings.HasSuffix(name, ".ir.json"), name == "lowered.json":
			return "ir"
		case strings.HasSuffix(name, ".result.json"), name == "result.json":
			return "result"
		case strings.HasSuffix(name, ".proposal.json"), name == "proposal.json":
			return "proposal"
		case name == "comparison.json":
			return "comparison"
		}
		if strings.Contains(path, "/registry/") {
			return "entry"
		}
		return ""
	}

	roots := []string{
		"../../fixtures/golden", "../../fixtures/bundles",
		"../../fixtures/generated/ir", "../../fixtures/replay", "../../registry",
	}
	checked := map[string]int{}
	refused := map[string]int{}
	for _, root := range roots {
		err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
			if err != nil || info.IsDir() || !strings.HasSuffix(path, ".json") {
				return nil
			}
			kind := kindOf(path)
			if kind == "" {
				return nil
			}
			raw, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			reader := readers[kind]
			document, err := reader.read(raw)
			if err != nil {
				// A corrupted bundle is SUPPOSED to be unreadable: its manifest says
				// which class it expects. Refusing it is the right answer, so the
				// manifest is consulted rather than the failure assumed to be a bug.
				if expected, ok := expectsRefusal(path); ok {
					refused[expected]++
					return nil
				}
				t.Errorf("%s: a fixture in the tree does not read as a %s: %v", path, kind, err)
				return nil
			}
			written, err := reader.write(document)
			if err != nil {
				t.Errorf("%s: %v", path, err)
				return nil
			}
			parsed, err := canon.Parse(raw)
			if err != nil {
				t.Errorf("%s: not canonical JSON: %v", path, err)
				return nil
			}
			expected, err := canon.Marshal(parsed)
			if err != nil {
				t.Errorf("%s: %v", path, err)
				return nil
			}
			if string(written) != string(expected) {
				t.Errorf("%s: re-encoding changed the document", path)
			}
			checked[kind]++
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
	t.Logf("round-tripped %v; refused as corrupt %v", checked, refused)
	// The corrupted bundles must actually be reaching this test, or the exemption
	// above would quietly excuse a real regression.
	if len(refused) == 0 {
		t.Error("no corrupted bundle was walked; the exemption is untested")
	}
	for _, kind := range []string{"ir", "result", "proposal", "entry"} {
		if checked[kind] == 0 {
			t.Errorf("no %s fixture was round-tripped; the test is not looking where it should", kind)
		}
	}
}

// expectsRefusal reports the class a bundle's manifest says it should be refused
// with, when the bundle is one of the deliberately corrupted ones.
func expectsRefusal(path string) (string, bool) {
	manifest := filepath.Join(filepath.Dir(path), "manifest.json")
	raw, err := os.ReadFile(manifest)
	if err != nil {
		return "", false
	}
	value, err := canon.Parse(raw)
	if err != nil {
		return "", false
	}
	object, ok := value.(map[string]any)
	if !ok {
		return "", false
	}
	expects, _ := object["expects"].(string)
	if expects == "" || expects == "accept" {
		return "", false
	}
	return expects, true
}
