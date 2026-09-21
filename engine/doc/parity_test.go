package doc

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"hedgecheck/engine/canon"
)

// readers maps a schema name to the decoder that must judge its documents. The Go
// decoder and the Python validator are held to the same files, so a disagreement
// between them is a finding about one of the two, not about a test.
var readers = map[string]func([]byte) error{
	"ir":              func(raw []byte) error { _, err := ReadIR(raw); return err },
	"result":          func(raw []byte) error { _, err := ReadResult(raw); return err },
	"proposal":        func(raw []byte) error { _, err := ReadProposal(raw); return err },
	"registry-entry":  func(raw []byte) error { _, err := ReadEntry(raw); return err },
	"comparison":      func(raw []byte) error { _, err := ReadComparison(raw); return err },
	"bundle-manifest": func(raw []byte) error { _, err := ReadManifest(raw); return err },
}

// Every document under fixtures/rejected/ must be refused, by the same decoder the
// engine uses. These are the files the Python validator also refuses.
func TestRefusesEveryRejectedDocument(t *testing.T) {
	root := "../../fixtures/rejected"
	directories, err := os.ReadDir(root)
	if err != nil {
		t.Fatalf("read %s: %v", root, err)
	}
	checked := 0
	for _, directory := range directories {
		if !directory.IsDir() {
			continue
		}
		read, known := readers[directory.Name()]
		if !known {
			t.Errorf("no Go decoder for schema %q; the two sides cover different documents", directory.Name())
			continue
		}
		matches, _ := filepath.Glob(filepath.Join(root, directory.Name(), "*.json"))
		if len(matches) == 0 {
			t.Errorf("%s/ has no documents", directory.Name())
		}
		for _, path := range matches {
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("%s: %v", path, err)
			}
			if err := read(raw); err == nil {
				why, _ := os.ReadFile(strings.TrimSuffix(path, ".json") + ".why")
				t.Errorf("%s/%s was ACCEPTED; it must be refused: %s",
					directory.Name(), filepath.Base(path), strings.TrimSpace(string(why)))
			}
			checked++
		}
	}
	if checked < 40 {
		t.Fatalf("only %d rejected documents checked; the set is meant to be broad", checked)
	}
	t.Logf("refused %d documents across %d schemas", checked, len(readers))
}

// Every document already in the tree is an accepted case, and must survive a round
// trip byte for byte against its own canonical form.
func TestAcceptsAndRoundTripsEveryValidDocument(t *testing.T) {
	type target struct {
		glob  string
		read  func([]byte) (any, error)
		write func(any) ([]byte, error)
	}
	targets := []target{
		{"../../fixtures/golden/*.ir.json",
			func(raw []byte) (any, error) { return ReadIR(raw) },
			func(value any) ([]byte, error) { return WriteIR(value.(IR)) }},
		{"../../fixtures/bundles/good*/lowered.json",
			func(raw []byte) (any, error) { return ReadIR(raw) },
			func(value any) ([]byte, error) { return WriteIR(value.(IR)) }},
		{"../../fixtures/golden/*.result.json",
			func(raw []byte) (any, error) { return ReadResult(raw) },
			func(value any) ([]byte, error) { return WriteResult(value.(Result)) }},
		{"../../fixtures/bundles/good*/result.json",
			func(raw []byte) (any, error) { return ReadResult(raw) },
			func(value any) ([]byte, error) { return WriteResult(value.(Result)) }},
		{"../../fixtures/replay/*/*.proposal.json",
			func(raw []byte) (any, error) { return ReadProposal(raw) },
			func(value any) ([]byte, error) { return WriteProposal(value.(Proposal)) }},
		{"../../fixtures/bundles/*/proposal.json",
			func(raw []byte) (any, error) { return ReadProposal(raw) },
			func(value any) ([]byte, error) { return WriteProposal(value.(Proposal)) }},
		{"../../registry/*.json",
			func(raw []byte) (any, error) { return ReadEntry(raw) },
			func(value any) ([]byte, error) { return WriteEntry(value.(Entry)) }},
		{"../../fixtures/bundles/*/manifest.json",
			func(raw []byte) (any, error) { return ReadManifest(raw) },
			func(value any) ([]byte, error) { return WriteManifest(value.(Manifest)) }},
	}

	total := 0
	for _, item := range targets {
		matches, _ := filepath.Glob(item.glob)
		if len(matches) == 0 {
			t.Errorf("%s matched nothing", item.glob)
			continue
		}
		for _, path := range matches {
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("%s: %v", path, err)
			}
			decoded, err := item.read(raw)
			if err != nil {
				t.Errorf("%s: refused a valid document: %v", path, err)
				continue
			}
			out, err := item.write(decoded)
			if err != nil {
				t.Errorf("%s: %v", path, err)
				continue
			}
			// Against the canonical form of the input: some fixtures are hand-formatted
			// for a reader, and re-indenting them is not the encoder's job.
			parsed, err := canon.Parse(raw)
			if err != nil {
				t.Fatalf("%s: %v", path, err)
			}
			want, err := canon.Marshal(parsed)
			if err != nil {
				t.Fatalf("%s: %v", path, err)
			}
			if string(out) != string(want) {
				t.Errorf("%s: round trip is not byte-exact", path)
			}
			total++
		}
	}
	t.Logf("accepted and round-tripped %d documents", total)
}

// The closed list in Go is the closed list in the schema.
//
// RefusalClasses is a hand-copy of refusal.schema.json's enum. That copy silently
// drifted the first time a class was added after the freeze: the schema gained
// ENVELOPE_MISMATCH, the Go decoder did not, and four bundle manifests that were
// valid became undecodable. The list is small enough to copy and small enough to
// forget, which is exactly the pair a test exists for.
func TestRefusalClassesMatchTheSchema(t *testing.T) {
	raw, err := os.ReadFile("../../schema/refusal.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	// encoding/json, not canon: a schema file is a specification, not evidence, and
	// its "$defs" key is outside the canonical profile the checker's parser enforces.
	var document map[string]any
	if err := json.Unmarshal(raw, &document); err != nil {
		t.Fatal(err)
	}
	defs, ok := document["$defs"].(map[string]any)
	if !ok {
		t.Fatal("no $defs")
	}
	class, ok := defs["class"].(map[string]any)
	if !ok {
		t.Fatal("no $defs.class")
	}
	items, ok := class["enum"].([]any)
	if !ok {
		t.Fatal("$defs.class has no enum")
	}
	want := make([]string, 0, len(items))
	for _, item := range items {
		text, ok := item.(string)
		if !ok {
			t.Fatalf("a class that is not a string: %v", item)
		}
		want = append(want, text)
	}
	if len(want) != len(RefusalClasses) {
		t.Fatalf("the schema has %d classes, Go has %d: %v vs %v", len(want), len(RefusalClasses), want, RefusalClasses)
	}
	for index, name := range want {
		if RefusalClasses[index] != name {
			t.Errorf("class %d: the schema says %q, Go says %q", index, name, RefusalClasses[index])
		}
	}
}
