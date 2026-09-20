// Package service serves stored answers over HTTP: three reads and one write, all
// idempotent.
//
//	POST /v1/checks                        lower, evaluate and store a proposal
//	GET  /v1/checks/{input_digest}         the stored result
//	GET  /v1/snapshots/{sha256}            the exact retained response bytes
//	GET  /v1/registry/{semantics_version}  the reading a result used
//
// Together these are everything a browser needs to verify a result WITHOUT trusting
// this server: it can re-derive the input digest from the proposal, re-hash every
// snapshot, re-compute each semantics version, and re-run the evaluation itself. The
// service is a convenience for fetching bytes, never an authority on what they mean.
//
// Standard library only, and bound to the loopback interface: this holds a person's
// position sizes and answers questions about their money. Nothing here signs, trades,
// or touches a key.
package service

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/evaluate"
	"hedgecheck/engine/lower"
	"hedgecheck/engine/store"
)

// Address is the only interface this service binds. A tool that answers questions
// about someone's positions has no business listening on a public interface, and a
// default that had to be tightened later would be a default that shipped wrong.
const Address = "127.0.0.1:8787"

// MaxBody bounds a request body. A proposal is a few kilobytes; a megabyte is
// generous. The limit is enforced on the READER, so an oversized body is never held
// in memory in the first place.
const MaxBody = 1 << 20

// Timeouts bound a connection's life. Without them a slow client holds a goroutine
// and a file descriptor open for as long as it likes.
const (
	ReadTimeout  = 10 * time.Second
	WriteTimeout = 30 * time.Second
	IdleTimeout  = 60 * time.Second
)

var (
	digestPattern  = regexp.MustCompile(`\A[0-9a-f]{64}\z`)
	versionPattern = regexp.MustCompile(`\A[0-9a-f]{64}\z`)
)

// Server answers from a store and a registry. Both are read-only here: a request can
// cause a result to be computed and filed, but never changes a snapshot or a reading.
type Server struct {
	Store    *store.Store
	Registry map[string]doc.Entry
}

// Handler builds the routing. Written as an explicit switch rather than a mux with
// wildcards, so what each path accepts is visible in one place.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/checks", s.checks)
	mux.HandleFunc("/v1/checks/", s.checkByDigest)
	mux.HandleFunc("/v1/snapshots/", s.snapshot)
	mux.HandleFunc("/v1/registry/", s.registryEntry)
	mux.HandleFunc("/", notFound)
	return mux
}

// NewHTTPServer wires the handler with the timeouts a public-facing socket needs,
// even on loopback.
func (s *Server) NewHTTPServer(address string) *http.Server {
	if address == "" {
		address = Address
	}
	return &http.Server{
		Addr:         address,
		Handler:      s.Handler(),
		ReadTimeout:  ReadTimeout,
		WriteTimeout: WriteTimeout,
		IdleTimeout:  IdleTimeout,
	}
}

// ---------------------------------------------------------------- the one write

// checks lowers, evaluates and stores a proposal.
//
// Idempotent: the answer is a function of the proposal, the snapshots it cites and
// the readings it pins, all of which are content-addressed. Posting the same proposal
// twice files the same bytes under the same digest, so a retry is free and a
// duplicate is not a second answer.
func (s *Server) checks(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w, http.MethodPost)
		return
	}
	body, err := readBody(r)
	if err != nil {
		fail(w, http.StatusRequestEntityTooLarge, "body_too_large", err.Error())
		return
	}
	proposal, err := doc.ReadProposal(body)
	if err != nil {
		fail(w, http.StatusBadRequest, "unreadable_proposal", err.Error())
		return
	}

	// Snapshots come from the store, by the digests the proposal cites. A proposal
	// cannot carry its own evidence: bytes supplied alongside a claim are not
	// evidence for it, and the store re-verifies every one against its digest.
	snapshots := lower.Snapshots{}
	for _, digest := range citedSnapshots(proposal) {
		raw, err := s.Store.Get(digest)
		if err != nil {
			// The digest, never the underlying error: a filesystem error carries the
			// store's absolute path, and where this server keeps its files is not
			// something a caller asked about or should learn from a refusal.
			var corrupt *store.Corrupt
			if errors.As(err, &corrupt) {
				fail(w, http.StatusInternalServerError, "snapshot_corrupt", corrupt.Error())
				return
			}
			fail(w, http.StatusUnprocessableEntity, "snapshot_not_retained",
				fmt.Sprintf("%s is cited but not retained here", short(digest)))
			return
		}
		if _, err := snapshots.Add(raw); err != nil {
			fail(w, http.StatusUnprocessableEntity, "snapshot_unreadable", err.Error())
			return
		}
	}

	ir, versions, err := lower.Lower(proposal, s.Registry, snapshots)
	if err != nil {
		var refused *lower.Refused
		if errors.As(err, &refused) {
			// A refusal is not a verdict. It gets its own status and its class, so a
			// caller cannot read "could not be lowered" as "does not meet the
			// objective".
			failRefusal(w, refused)
			return
		}
		fail(w, http.StatusUnprocessableEntity, "cannot_lower", err.Error())
		return
	}
	result, err := evaluate.Evaluate(ir)
	if err != nil {
		fail(w, http.StatusUnprocessableEntity, "cannot_evaluate", err.Error())
		return
	}
	inputDigest, err := lower.InputDigest(proposal, ir, versions)
	if err != nil {
		fail(w, http.StatusInternalServerError, "cannot_digest", err.Error())
		return
	}
	encoded, err := doc.WriteResult(result)
	if err != nil {
		fail(w, http.StatusInternalServerError, "cannot_encode", err.Error())
		return
	}
	if err := s.Store.PutResult(inputDigest, evaluate.Version, encoded); err != nil {
		// A storage failure is this server's problem, not the caller's, and the
		// error names a path on this machine. It is reported without one.
		fail(w, http.StatusInternalServerError, "cannot_store",
			"the result could not be stored")
		return
	}
	w.Header().Set("Location", "/v1/checks/"+inputDigest)
	writeCanonical(w, http.StatusOK, encoded)
}

// ---------------------------------------------------------------- the three reads

func (s *Server) checkByDigest(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		methodNotAllowed(w, http.MethodGet)
		return
	}
	digest := strings.TrimPrefix(r.URL.Path, "/v1/checks/")
	if !digestPattern.MatchString(digest) {
		fail(w, http.StatusBadRequest, "not_a_digest", "an input digest is 64 hex characters")
		return
	}
	version := r.URL.Query().Get("engine_version")
	if version == "" {
		version = evaluate.Version
	}
	encoded, err := s.Store.Result(digest, version)
	if err != nil {
		// Which engine versions DO have an answer is useful and leaks nothing: the
		// digest was already known to the caller.
		available, _ := s.Store.ResultVersions(digest)
		if len(available) > 0 {
			fail(w, http.StatusNotFound, "no_result_for_engine",
				fmt.Sprintf("stored engine versions: %s", strings.Join(available, ", ")))
			return
		}
		fail(w, http.StatusNotFound, "no_result", "nothing stored under that input digest")
		return
	}
	writeCanonical(w, http.StatusOK, encoded)
}

func (s *Server) snapshot(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		methodNotAllowed(w, http.MethodGet)
		return
	}
	digest := strings.TrimPrefix(r.URL.Path, "/v1/snapshots/")
	if !digestPattern.MatchString(digest) {
		fail(w, http.StatusBadRequest, "not_a_digest", "a snapshot is named by 64 hex characters")
		return
	}
	raw, err := s.Store.Get(digest)
	if err != nil {
		var corrupt *store.Corrupt
		if errors.As(err, &corrupt) {
			// The store found bytes that do not hash to their own name. Serving them
			// would pass the corruption on as evidence. The message names the two
			// digests and no path.
			fail(w, http.StatusInternalServerError, "snapshot_corrupt", corrupt.Error())
			return
		}
		fail(w, http.StatusNotFound, "no_snapshot", "that snapshot is not retained here")
		return
	}
	// The exact retained bytes, unreformatted: a reader must be able to hash what it
	// received and get the name it asked for.
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(http.StatusOK)
	w.Write(raw)
}

func (s *Server) registryEntry(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		methodNotAllowed(w, http.MethodGet)
		return
	}
	wanted := strings.TrimPrefix(r.URL.Path, "/v1/registry/")
	if !versionPattern.MatchString(wanted) {
		fail(w, http.StatusBadRequest, "not_a_version", "a semantics version is 64 hex characters")
		return
	}
	// Found by recomputing each entry's version rather than by trusting a name: the
	// version IS the entry's digest without its review key, so a lookup that matched
	// on a stored label could serve an entry that had since been edited.
	for _, family := range sortedFamilies(s.Registry) {
		entry := s.Registry[family]
		version, err := entry.SemanticsVersion()
		if err != nil {
			continue
		}
		if version != wanted {
			continue
		}
		encoded, err := doc.WriteEntry(entry)
		if err != nil {
			fail(w, http.StatusInternalServerError, "cannot_encode", err.Error())
			return
		}
		writeCanonical(w, http.StatusOK, encoded)
		return
	}
	fail(w, http.StatusNotFound, "no_entry", "no registry entry has that semantics version")
}

// ---------------------------------------------------------------- plumbing

// readBody reads at most MaxBody bytes, and reports a body that wanted to be larger.
// The limit is on the reader, so an oversized body is refused rather than buffered.
func readBody(r *http.Request) ([]byte, error) {
	limited := io.LimitReader(r.Body, MaxBody+1)
	body, err := io.ReadAll(limited)
	if err != nil {
		return nil, err
	}
	if len(body) > MaxBody {
		return nil, fmt.Errorf("a request body is at most %d bytes", MaxBody)
	}
	return body, nil
}

// citedSnapshots is every digest a proposal points at, deduplicated and in a fixed
// order so the same proposal always reads the same snapshots in the same sequence.
func citedSnapshots(proposal doc.Proposal) []string {
	seen := map[string]bool{}
	out := []string{}
	add := func(digest string) {
		if digest == "" || seen[digest] {
			return
		}
		seen[digest] = true
		out = append(out, digest)
	}
	add(proposal.Baseline.Snapshot)
	for _, leg := range proposal.Legs {
		add(leg.Instance.Catalogue)
		add(leg.Acquisition.Snapshot)
	}
	return out
}

func sortedFamilies(registry map[string]doc.Entry) []string {
	out := make([]string, 0, len(registry))
	for family := range registry {
		out = append(out, family)
	}
	// A registry is small and the order only has to be stable, not meaningful.
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j] < out[j-1]; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}

func writeCanonical(w http.ResponseWriter, status int, document []byte) {
	sum := sha256.Sum256(document)
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	// The digest of exactly these bytes, so a caller can check what it received
	// without re-canonicalising.
	w.Header().Set("X-Document-Sha256", hex.EncodeToString(sum[:]))
	w.WriteHeader(status)
	w.Write(document)
	w.Write([]byte("\n"))
}

// Problem is the one error shape this service returns.
type Problem struct {
	Error  string `json:"error"`
	Detail string `json:"detail"`
	// Class carries a refusal's class when there is one, and is absent otherwise, so
	// a caller can tell a refusal from a technical failure.
	Class string `json:"class,omitempty"`
}

func fail(w http.ResponseWriter, status int, code, detail string) {
	writeProblem(w, status, Problem{Error: code, Detail: detail})
}

// failRefusal reports a proposal that could not be lowered. It is 422 with the
// refusal's class, never a verdict: "could not be lowered" and "does not meet the
// objective" are different answers, and a caller must not confuse them.
func failRefusal(w http.ResponseWriter, refused *lower.Refused) {
	writeProblem(w, http.StatusUnprocessableEntity, Problem{
		Error: "refused", Detail: refused.Detail, Class: refused.Code,
	})
}

func writeProblem(w http.ResponseWriter, status int, problem Problem) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	encoded, err := json.Marshal(problem)
	if err != nil {
		return
	}
	w.Write(encoded)
	w.Write([]byte("\n"))
}

func methodNotAllowed(w http.ResponseWriter, allowed string) {
	w.Header().Set("Allow", allowed)
	fail(w, http.StatusMethodNotAllowed, "method_not_allowed", "this path accepts "+allowed)
}

func notFound(w http.ResponseWriter, r *http.Request) {
	fail(w, http.StatusNotFound, "no_such_path", "this service serves /v1/checks, /v1/snapshots and /v1/registry")
}

func short(digest string) string {
	if len(digest) <= 12 {
		return digest
	}
	return digest[:12]
}
