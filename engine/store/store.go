// Package store keeps retained responses, content-addressed.
//
// A snapshot is its bytes: the file name is the SHA-256 of the response, so the same
// response stored twice is one file, and a file that does not hash to its own name is
// not the snapshot it claims to be. Reads re-verify, which is what makes a replay a
// check rather than a copy.
//
// Writes are atomic: a temporary file, then a rename. A half-written snapshot under a
// digest that promises the whole thing would be worse than no snapshot at all.
package store

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// digestPattern is checked BEFORE a digest reaches a path. A digest is 64 hex
// characters and nothing else, so "../../etc/passwd" is refused as a digest rather
// than sanitised as a path.
var digestPattern = regexp.MustCompile(`\A[0-9a-f]{64}\z`)

// Corrupt reports a stored file that does not hash to its own name.
type Corrupt struct{ Digest, Actual string }

func (e *Corrupt) Error() string {
	return fmt.Sprintf("%s: stored bytes hash to %s", e.Digest[:12], e.Actual[:12])
}

// Store is a directory of content-addressed snapshots and the runs that cite them.
type Store struct{ Root string }

// New opens a store rooted at a directory. Nothing is created until something is put.
func New(root string) *Store { return &Store{Root: root} }

func (s *Store) snapshotPath(digest string) (string, error) {
	if !digestPattern.MatchString(digest) {
		return "", fmt.Errorf("store: %q is not a SHA-256", digest)
	}
	return filepath.Join(s.Root, "snapshots", digest+".json"), nil
}

func (s *Store) recordPath(digest string) (string, error) {
	if !digestPattern.MatchString(digest) {
		return "", fmt.Errorf("store: %q is not a SHA-256", digest)
	}
	return filepath.Join(s.Root, "snapshots", digest+".request.json"), nil
}

// Put stores a response under its own digest, beside its request record.
func (s *Store) Put(raw, record []byte) (string, error) {
	sum := sha256.Sum256(raw)
	digest := hex.EncodeToString(sum[:])
	path, err := s.snapshotPath(digest)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return "", err
	}
	if err := writeAtomic(path, raw); err != nil {
		return "", err
	}
	if len(record) > 0 {
		recordFile, err := s.recordPath(digest)
		if err != nil {
			return "", err
		}
		if err := writeAtomic(recordFile, record); err != nil {
			return "", err
		}
	}
	return digest, nil
}

// Get returns the exact stored bytes, re-verified against the name they are under.
func (s *Store) Get(digest string) ([]byte, error) {
	path, err := s.snapshotPath(digest)
	if err != nil {
		return nil, err
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(raw)
	actual := hex.EncodeToString(sum[:])
	if actual != digest {
		return nil, &Corrupt{Digest: digest, Actual: actual}
	}
	return raw, nil
}

// Record returns a snapshot's request record.
func (s *Store) Record(digest string) ([]byte, error) {
	path, err := s.recordPath(digest)
	if err != nil {
		return nil, err
	}
	return os.ReadFile(path)
}

// versionPattern is checked before an engine version reaches a path. A version is a
// short slug and nothing else, so it cannot climb out of the store's directory any
// more than a digest can.
var versionPattern = regexp.MustCompile(`\A[a-z][a-z0-9-]{0,63}\z`)

// resultPath is results/<input_digest>/<engine_version>.json.
//
// A result is immutable for one engine version, so the version is part of the path
// rather than something that overwrites: two engines may answer the same question,
// and a store that kept only the newest would silently lose the comparison.
func (s *Store) resultPath(inputDigest, engineVersion string) (string, error) {
	if !digestPattern.MatchString(inputDigest) {
		return "", fmt.Errorf("store: %q is not a SHA-256", inputDigest)
	}
	if !versionPattern.MatchString(engineVersion) {
		return "", fmt.Errorf("store: %q is not an engine version", engineVersion)
	}
	return filepath.Join(s.Root, "results", inputDigest, engineVersion+".json"), nil
}

// PutResult stores a result under its input digest and the engine that produced it.
func (s *Store) PutResult(inputDigest, engineVersion string, document []byte) error {
	path, err := s.resultPath(inputDigest, engineVersion)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return writeAtomic(path, document)
}

// Result returns a stored result.
func (s *Store) Result(inputDigest, engineVersion string) ([]byte, error) {
	path, err := s.resultPath(inputDigest, engineVersion)
	if err != nil {
		return nil, err
	}
	return os.ReadFile(path)
}

// ResultVersions lists the engine versions that have answered one question, sorted so
// the order does not depend on the filesystem.
func (s *Store) ResultVersions(inputDigest string) ([]string, error) {
	if !digestPattern.MatchString(inputDigest) {
		return nil, fmt.Errorf("store: %q is not a SHA-256", inputDigest)
	}
	matches, err := filepath.Glob(filepath.Join(s.Root, "results", inputDigest, "*.json"))
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(matches))
	for _, path := range matches {
		out = append(out, strings.TrimSuffix(filepath.Base(path), ".json"))
	}
	sort.Strings(out)
	return out, nil
}

// PutBundlePart stores a proposal or lowered proposal beside the result it belongs
// to, so a browser can fetch the whole bundle and verify it for itself.
//
// A result alone cannot be checked: a checker that re-derives nothing is reading the
// engine's own answer back. The proposal is what the answer is derived FROM, and the
// lowered proposal is the intermediate the result's ir_digest covers.
func (s *Store) PutBundlePart(inputDigest, part string, document []byte) error {
	path, err := s.bundlePath(inputDigest, part)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return writeAtomic(path, document)
}

// BundlePart returns a stored proposal or lowered proposal.
func (s *Store) BundlePart(inputDigest, part string) ([]byte, error) {
	path, err := s.bundlePath(inputDigest, part)
	if err != nil {
		return nil, err
	}
	return os.ReadFile(path)
}

// bundlePart is the closed set of parts a bundle carries beside its result. Closed,
// so a caller cannot invent a file name that reaches a path.
var bundleParts = map[string]bool{"proposal": true, "lowered": true}

func (s *Store) bundlePath(inputDigest, part string) (string, error) {
	if !digestPattern.MatchString(inputDigest) {
		return "", fmt.Errorf("store: %q is not a SHA-256", inputDigest)
	}
	if !bundleParts[part] {
		return "", fmt.Errorf("store: %q is not a bundle part", part)
	}
	return filepath.Join(s.Root, "results", inputDigest, part+".json"), nil
}

// PutRun stores a run document under its input digest.
func (s *Store) PutRun(inputDigest string, document []byte) error {
	if !digestPattern.MatchString(inputDigest) {
		return fmt.Errorf("store: %q is not a SHA-256", inputDigest)
	}
	path := filepath.Join(s.Root, "runs", inputDigest+".json")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return writeAtomic(path, document)
}

// Run returns a stored run document.
func (s *Store) Run(inputDigest string) ([]byte, error) {
	if !digestPattern.MatchString(inputDigest) {
		return nil, fmt.Errorf("store: %q is not a SHA-256", inputDigest)
	}
	return os.ReadFile(filepath.Join(s.Root, "runs", inputDigest+".json"))
}

// Runs lists the stored runs, newest name order being meaningless so they are sorted.
func (s *Store) Runs() ([]string, error) {
	matches, err := filepath.Glob(filepath.Join(s.Root, "runs", "*.json"))
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(matches))
	for _, path := range matches {
		out = append(out, strings.TrimSuffix(filepath.Base(path), ".json"))
	}
	sort.Strings(out)
	return out, nil
}

// writeAtomic writes through a temporary file and renames, so a reader never sees a
// half-written snapshot under a name that promises the whole one.
func writeAtomic(path string, raw []byte) error {
	temporary, err := os.CreateTemp(filepath.Dir(path), ".tmp-*")
	if err != nil {
		return err
	}
	name := temporary.Name()
	defer os.Remove(name)
	if _, err := temporary.Write(raw); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	return os.Rename(name, path)
}
