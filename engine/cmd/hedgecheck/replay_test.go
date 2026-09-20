package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const replayFixtures = "../../../fixtures/replay/2026-09-19"

// seedStore files the retained 19 September capture into a store laid out the way the
// spike's store lays one out, so the Go replay reads exactly what a Python run wrote.
func seedStore(t *testing.T) (root, inputDigest string) {
	t.Helper()
	root = t.TempDir()
	snapshots := filepath.Join(root, "snapshots")
	runs := filepath.Join(root, "runs")
	for _, directory := range []string{snapshots, runs} {
		if err := os.MkdirAll(directory, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	raw, err := os.ReadFile(filepath.Join(replayFixtures, "binary-no.run.json"))
	if err != nil {
		t.Skipf("no retained run to replay: %v", err)
	}
	var document struct {
		Digests      map[string]string `json:"digests"`
		InputDigests map[string]string `json:"input_digests"`
		Leg          string            `json:"leg"`
	}
	if err := json.Unmarshal(raw, &document); err != nil {
		t.Fatal(err)
	}
	for name, digest := range document.Digests {
		snapshot, err := os.ReadFile(filepath.Join(replayFixtures, name+".json"))
		if err != nil {
			t.Fatal(err)
		}
		sum := sha256.Sum256(snapshot)
		if hex.EncodeToString(sum[:]) != digest {
			t.Fatalf("%s.json does not hash to the digest the run cites", name)
		}
		if err := os.WriteFile(filepath.Join(snapshots, digest+".json"), snapshot, 0o644); err != nil {
			t.Fatal(err)
		}
		if record, err := os.ReadFile(filepath.Join(replayFixtures, name+".request.json")); err == nil {
			if err := os.WriteFile(filepath.Join(snapshots, digest+".request.json"), record, 0o644); err != nil {
				t.Fatal(err)
			}
		}
	}
	inputDigest = document.InputDigests[document.Leg]
	if err := os.WriteFile(filepath.Join(runs, inputDigest+".json"), raw, 0o644); err != nil {
		t.Fatal(err)
	}
	return root, inputDigest
}

// capture runs the CLI and returns its status and streams.
func invoke(t *testing.T, args ...string) (int, string, string) {
	t.Helper()
	outFile, err := os.CreateTemp(t.TempDir(), "out-*")
	if err != nil {
		t.Fatal(err)
	}
	errFile, err := os.CreateTemp(t.TempDir(), "err-*")
	if err != nil {
		t.Fatal(err)
	}
	status := run(args, outFile, errFile)
	outFile.Close()
	errFile.Close()
	stdout, _ := os.ReadFile(outFile.Name())
	stderr, _ := os.ReadFile(errFile.Name())
	return status, string(stdout), string(stderr)
}

// The Go engine replays a run document the PYTHON spike wrote, reproduces the result
// byte for byte and recomputes the same input digest. This is the cross-implementation
// claim the replay command makes.
func TestReplayReproducesThePythonRun(t *testing.T) {
	root, inputDigest := seedStore(t)
	status, stdout, stderr := invoke(t, "replay",
		"--input-digest", inputDigest, "--store", root, "--registry", "../../../registry")
	if status != exitNeedsReview {
		t.Fatalf("status %d, want %d (needs_review)\n%s", status, exitNeedsReview, stderr)
	}
	if !strings.Contains(stdout, "byte-identical") {
		t.Errorf("stdout does not report byte identity: %q", stdout)
	}
	if !strings.Contains(stdout, "488.69285") {
		t.Errorf("the replayed premium is not the one the spike recorded: %q", stdout)
	}
}

// A single changed byte is caught by the store before anything is evaluated.
func TestReplayRefusesATamperedSnapshot(t *testing.T) {
	root, inputDigest := seedStore(t)
	matches, err := filepath.Glob(filepath.Join(root, "snapshots", "*.json"))
	if err != nil || len(matches) == 0 {
		t.Fatal("no snapshots were seeded")
	}
	changed := false
	for _, path := range matches {
		if strings.HasSuffix(path, ".request.json") {
			continue
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(string(raw), `"sz"`) {
			continue
		}
		if err := os.WriteFile(path, []byte(strings.Replace(string(raw), `"sz"`, `"sZ"`, 1)), 0o644); err != nil {
			t.Fatal(err)
		}
		changed = true
		break
	}
	if !changed {
		t.Skip("no book snapshot to tamper with")
	}
	status, _, stderr := invoke(t, "replay",
		"--input-digest", inputDigest, "--store", root, "--registry", "../../../registry")
	if status == exitNeedsReview || status == exitPasses {
		t.Fatalf("a tampered snapshot still replayed, status %d", status)
	}
	if !strings.Contains(stderr, "hash to") {
		t.Errorf("the refusal does not name the hash mismatch: %q", stderr)
	}
}

// A book that is genuinely a different book, honestly filed under its own digest and
// cited by the run, passes the hash check and must then fail the RESULT comparison.
// Without this, "byte-identical" would only mean "the files were not edited".
func TestReplayDetectsADifferentBook(t *testing.T) {
	root, inputDigest := seedStore(t)
	runPath := filepath.Join(root, "runs", inputDigest+".json")
	raw, err := os.ReadFile(runPath)
	if err != nil {
		t.Fatal(err)
	}
	var document map[string]any
	if err := json.Unmarshal(raw, &document); err != nil {
		t.Fatal(err)
	}
	digests, _ := document["digests"].(map[string]any)
	leg, _ := document["leg"].(string)
	old, _ := digests[leg].(string)
	book, err := os.ReadFile(filepath.Join(root, "snapshots", old+".json"))
	if err != nil {
		t.Fatal(err)
	}
	// Widen the first ask by appending a digit, then file the result honestly.
	var parsed struct {
		Levels [][]struct {
			Px string `json:"px"`
		} `json:"levels"`
	}
	if err := json.Unmarshal(book, &parsed); err != nil {
		t.Fatal(err)
	}
	if len(parsed.Levels) < 2 || len(parsed.Levels[1]) == 0 {
		t.Skip("the retained book has no asks to change")
	}
	price := parsed.Levels[1][0].Px
	changed := []byte(strings.Replace(string(book), `"`+price+`"`, `"`+price+`9"`, 1))
	if string(changed) == string(book) {
		t.Skip("could not vary the book")
	}
	sum := sha256.Sum256(changed)
	newDigest := hex.EncodeToString(sum[:])
	if err := os.WriteFile(filepath.Join(root, "snapshots", newDigest+".json"), changed, 0o644); err != nil {
		t.Fatal(err)
	}
	digests[leg] = newDigest
	edited, err := json.MarshalIndent(document, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(runPath, append(edited, '\n'), 0o644); err != nil {
		t.Fatal(err)
	}

	status, stdout, stderr := invoke(t, "replay",
		"--input-digest", inputDigest, "--store", root, "--registry", "../../../registry")
	if status != exitFails {
		t.Fatalf("a different book replayed with status %d\nstdout: %s\nstderr: %s",
			status, stdout, stderr)
	}
	if !strings.Contains(stderr, "differs") {
		t.Errorf("the refusal does not say the replay differs: %q", stderr)
	}
	if strings.Contains(stdout, "byte-identical") {
		t.Error("a differing replay still claimed byte identity")
	}
}

// retain copies the bytes unchanged, so what lands in fixtures still hashes to the
// digest the run cites.
func TestRetainCopiesBytesUnchanged(t *testing.T) {
	root, inputDigest := seedStore(t)
	into := filepath.Join(t.TempDir(), "retained")
	status, stdout, stderr := invoke(t, "retain",
		"--input-digest", inputDigest, "--store", root, "--out", into)
	if status != exitPasses {
		t.Fatalf("retain failed with %d: %s", status, stderr)
	}
	if !strings.Contains(stdout, "retained") {
		t.Errorf("retain said nothing about what it did: %q", stdout)
	}
	raw, err := os.ReadFile(filepath.Join(root, "runs", inputDigest+".json"))
	if err != nil {
		t.Fatal(err)
	}
	var document struct {
		Digests map[string]string `json:"digests"`
	}
	if err := json.Unmarshal(raw, &document); err != nil {
		t.Fatal(err)
	}
	for name, digest := range document.Digests {
		copied, err := os.ReadFile(filepath.Join(into, name+".json"))
		if err != nil {
			t.Fatalf("%s was not retained: %v", name, err)
		}
		sum := sha256.Sum256(copied)
		if hex.EncodeToString(sum[:]) != digest {
			t.Errorf("%s: the retained bytes no longer hash to the cited digest", name)
		}
	}
}
