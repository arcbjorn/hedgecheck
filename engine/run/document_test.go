package run

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"hedgecheck/engine/canon"
	"hedgecheck/engine/doc"
)

// The Go decoder reads the document the Python spike wrote, and re-encoding it
// reproduces the same canonical bytes. This is the cross-implementation agreement the
// run document needs: a replay must read what a live run wrote, whichever wrote it.
func TestRunDocumentRoundTripsThePythonDocument(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join(fixtures, "binary-no.run.json"))
	if err != nil {
		t.Fatal(err)
	}
	document, err := Decode(raw)
	if err != nil {
		t.Fatal(err)
	}
	if document.Leg != "binary-no" {
		t.Errorf("leg %q, want binary-no", document.Leg)
	}
	if document.Expiry != "20260920-0600" {
		t.Errorf("expiry %q", document.Expiry)
	}
	if document.Capture == nil || document.Capture.SkewMs != "-689" {
		t.Fatalf("capture assertion not read back: %+v", document.Capture)
	}
	if got := document.Skew["bucket0-yes"].SkewMs; got != -689 {
		t.Errorf("bucket0-yes skew %d, want -689", got)
	}
	if got := document.Skew["binary-no"].BookVenueMs; got != 1789842196804 {
		t.Errorf("binary-no venue time %d", got)
	}
	if len(document.Results) != 2 {
		t.Errorf("got %d results, want 2", len(document.Results))
	}
	if document.Options.Baseline != "81520" {
		t.Errorf("baseline %q", document.Options.Baseline)
	}

	encoded, err := Encode(document)
	if err != nil {
		t.Fatal(err)
	}
	again, err := Decode(encoded)
	if err != nil {
		t.Fatalf("a document this engine wrote cannot be read back: %v", err)
	}
	twice, err := Encode(again)
	if err != nil {
		t.Fatal(err)
	}
	if string(encoded) != string(twice) {
		t.Error("encoding is not stable across a decode/encode round trip")
	}
}

// A run document carrying a key this engine does not understand is refused, not
// silently replayed as if the key were not there.
func TestRunDocumentRefusesUnknownKeys(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join(fixtures, "binary-no.run.json"))
	if err != nil {
		t.Fatal(err)
	}
	tampered := `{"surprise":1,` + string(raw)[1:]
	if _, err := Decode([]byte(tampered)); err == nil {
		t.Fatal("an unknown key was accepted")
	}
}

// Every result embedded in the Python document re-encodes to the exact canonical
// bytes the Python engine wrote, after removing engine_version -- which is the
// equality rule the addendum states. This is the whole-document agreement: Python
// wrote these results, Go read them with the strict reader and wrote them back.
func TestEmbeddedResultsReencodeIdentically(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join(fixtures, "binary-no.run.json"))
	if err != nil {
		t.Fatal(err)
	}
	var envelope struct {
		Results map[string]json.RawMessage `json:"results"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		t.Fatal(err)
	}
	if len(envelope.Results) != 2 {
		t.Fatalf("got %d embedded results, want 2", len(envelope.Results))
	}
	for name, encoded := range envelope.Results {
		// Canonicalise what Python wrote, so the comparison is about content and not
		// about the indentation json.dumps happened to use.
		var value any
		if err := json.Unmarshal(encoded, &value); err != nil {
			t.Fatal(err)
		}
		canonicalPython, err := canon.Marshal(value)
		if err != nil {
			t.Fatalf("%s: the embedded result is not canonical: %v", name, err)
		}
		result, err := doc.ReadResult(canonicalPython)
		if err != nil {
			t.Fatalf("%s: the strict reader refuses Python's result: %v", name, err)
		}
		canonicalGo, err := doc.WriteResult(result)
		if err != nil {
			t.Fatal(err)
		}
		if withoutEngineVersion(t, canonicalGo) != withoutEngineVersion(t, canonicalPython) {
			t.Errorf("%s: re-encoding Python's result gives different bytes", name)
		}
	}
}

// Two results are equal when their canonical bytes agree after removing the single
// key engine_version. No other field may differ.
func withoutEngineVersion(t *testing.T, encoded []byte) string {
	t.Helper()
	var value map[string]any
	if err := json.Unmarshal(encoded, &value); err != nil {
		t.Fatal(err)
	}
	delete(value, "engine_version")
	stripped, err := canon.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return string(stripped)
}
