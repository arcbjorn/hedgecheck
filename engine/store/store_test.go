package store

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// digestOf is derived by hand here rather than from the code under test: it is
// plain SHA-256 of the bytes, which is the property the store claims.
func digestOf(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func TestPutStoresUnderItsOwnDigest(t *testing.T) {
	store := New(t.TempDir())
	raw := []byte(`{"levels":[[],[]]}`)
	digest, err := store.Put(raw, nil)
	if err != nil {
		t.Fatal(err)
	}
	if want := digestOf(raw); digest != want {
		t.Errorf("stored under %s, want %s", digest, want)
	}
	got, err := store.Get(digest)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(raw) {
		t.Errorf("read back %q, want %q", got, raw)
	}
}

// The same response stored twice is one file, because the name is the content.
func TestPutIsIdempotent(t *testing.T) {
	root := t.TempDir()
	store := New(root)
	raw := []byte(`{"a":1}`)
	first, err := store.Put(raw, nil)
	if err != nil {
		t.Fatal(err)
	}
	second, err := store.Put(raw, nil)
	if err != nil {
		t.Fatal(err)
	}
	if first != second {
		t.Fatalf("two digests for one response: %s and %s", first, second)
	}
	matches, err := filepath.Glob(filepath.Join(root, "snapshots", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(matches) != 1 {
		t.Errorf("one response produced %d files", len(matches))
	}
}

// A file that no longer hashes to its own name is not the snapshot it claims to be.
// This is what makes a replay a check rather than a copy.
func TestGetRefusesTamperedBytes(t *testing.T) {
	root := t.TempDir()
	store := New(root)
	digest, err := store.Put([]byte(`{"px":"0.17399"}`), nil)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "snapshots", digest+".json")
	if err := os.WriteFile(path, []byte(`{"px":"0.17398"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err = store.Get(digest)
	var corrupt *Corrupt
	if err == nil {
		t.Fatal("a tampered snapshot was returned as if it were genuine")
	}
	if !asCorrupt(err, &corrupt) {
		t.Fatalf("got %v, want a Corrupt", err)
	}
	if corrupt.Digest != digest {
		t.Errorf("the refusal names %s, want %s", corrupt.Digest, digest)
	}
}

func asCorrupt(err error, target **Corrupt) bool {
	corrupt, ok := err.(*Corrupt)
	if ok {
		*target = corrupt
	}
	return ok
}

// A digest is 64 hex characters. Anything else is refused AS A DIGEST, before it can
// reach a path, so traversal is impossible rather than merely sanitised.
func TestDigestsAreValidatedBeforeTheyReachAPath(t *testing.T) {
	store := New(t.TempDir())
	bad := []string{
		"../../etc/passwd",
		strings.Repeat("a", 63),
		strings.Repeat("a", 65),
		strings.Repeat("A", 64), // uppercase is not the canonical form
		"",
		"/absolute",
		strings.Repeat("g", 64), // not hex
		// A real traversal payload carrying a well-formed digest. An unanchored
		// pattern matches the digest INSIDE this and lets the rest reach a path.
		"../../etc/" + strings.Repeat("a", 64),
		strings.Repeat("a", 64) + "/../../escaped",
		strings.Repeat("a", 64) + "\n" + strings.Repeat("b", 64),
	}
	for _, digest := range bad {
		if _, err := store.Get(digest); err == nil {
			t.Errorf("Get accepted %q as a digest", digest)
		}
		if _, err := store.Record(digest); err == nil {
			t.Errorf("Record accepted %q as a digest", digest)
		}
		if err := store.PutRun(digest, []byte("{}")); err == nil {
			t.Errorf("PutRun accepted %q as a digest", digest)
		}
		if _, err := store.Run(digest); err == nil {
			t.Errorf("Run accepted %q as a digest", digest)
		}
	}
}

// A traversal attempt must not create a file outside the store, even though it fails.
func TestRefusedDigestWritesNothing(t *testing.T) {
	root := t.TempDir()
	outside := filepath.Join(root, "outside")
	if err := os.MkdirAll(outside, 0o755); err != nil {
		t.Fatal(err)
	}
	store := New(filepath.Join(root, "store"))
	if err := store.PutRun("../outside/escaped", []byte("{}")); err == nil {
		t.Fatal("a traversing run name was accepted")
	}
	entries, err := os.ReadDir(outside)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Errorf("a refused write still created %d entries outside the store", len(entries))
	}
}

func TestRecordIsStoredBesideItsSnapshot(t *testing.T) {
	store := New(t.TempDir())
	raw := []byte(`{"time":1}`)
	record := []byte(`{"endpoint":"x"}`)
	digest, err := store.Put(raw, record)
	if err != nil {
		t.Fatal(err)
	}
	got, err := store.Record(digest)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != string(record) {
		t.Errorf("record read back as %q, want %q", got, record)
	}
}

func TestRunsAreListedSorted(t *testing.T) {
	store := New(t.TempDir())
	digests := []string{
		strings.Repeat("c", 64), strings.Repeat("a", 64), strings.Repeat("b", 64),
	}
	for _, digest := range digests {
		if err := store.PutRun(digest, []byte("{}")); err != nil {
			t.Fatal(err)
		}
	}
	got, err := store.Runs()
	if err != nil {
		t.Fatal(err)
	}
	want := []string{strings.Repeat("a", 64), strings.Repeat("b", 64), strings.Repeat("c", 64)}
	if len(got) != len(want) {
		t.Fatalf("got %d runs, want %d", len(got), len(want))
	}
	for index := range want {
		if got[index] != want[index] {
			t.Errorf("run %d is %s, want %s", index, got[index][:8], want[index][:8])
		}
	}
}

// A store write leaves no temporary file behind, so a later listing sees only
// snapshots.
func TestWritesLeaveNoTemporaryFiles(t *testing.T) {
	root := t.TempDir()
	store := New(root)
	if _, err := store.Put([]byte(`{"a":1}`), []byte(`{"b":2}`)); err != nil {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(filepath.Join(root, "snapshots"))
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".tmp-") {
			t.Errorf("a temporary file survived the write: %s", entry.Name())
		}
	}
}
