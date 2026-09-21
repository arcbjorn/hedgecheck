package service

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/evaluate"
	"hedgecheck/engine/store"
)

const (
	replay   = "../../fixtures/replay/2026-09-18"
	registry = "../../registry"
)

// newServer builds a service over a store seeded with the 18 September replay
// snapshots, which is the set those proposals cite.
func newServer(t *testing.T) (*Server, *httptest.Server) {
	t.Helper()
	keep := store.New(t.TempDir())
	matches, err := filepath.Glob(filepath.Join(replay, "*.json"))
	if err != nil || len(matches) == 0 {
		t.Skipf("no replay fixtures: %v", err)
	}
	for _, path := range matches {
		name := filepath.Base(path)
		if strings.HasSuffix(name, ".request.json") || strings.HasSuffix(name, ".proposal.json") ||
			strings.HasSuffix(name, ".run.json") || strings.HasSuffix(name, ".result.json") ||
			strings.HasSuffix(name, ".ir.json") {
			continue
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := keep.Put(raw, nil); err != nil {
			t.Fatal(err)
		}
	}

	entries := map[string]doc.Entry{}
	registryFiles, err := filepath.Glob(filepath.Join(registry, "*.json"))
	if err != nil || len(registryFiles) == 0 {
		t.Skip("no registry entries")
	}
	for _, path := range registryFiles {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		entry, err := doc.ReadEntry(raw)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		entries[entry.Family] = entry
	}

	server := &Server{Store: keep, Registry: entries}
	httpServer := httptest.NewServer(server.Handler())
	t.Cleanup(httpServer.Close)
	return server, httpServer
}

func aProposal(t *testing.T) []byte {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(replay, "bucket0.proposal.json"))
	if err != nil {
		t.Skipf("no proposal fixture: %v", err)
	}
	return raw
}

func post(t *testing.T, base string, body []byte) (*http.Response, []byte) {
	t.Helper()
	response, err := http.Post(base+"/v1/checks", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	raw, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	return response, raw
}

func get(t *testing.T, url string) (*http.Response, []byte) {
	t.Helper()
	response, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	raw, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	return response, raw
}

// A posted proposal is lowered, evaluated, stored, and readable back at the location
// the response points to.
func TestPostChecksStoresAndServesTheResult(t *testing.T) {
	_, httpServer := newServer(t)
	response, body := post(t, httpServer.URL, aProposal(t))
	if response.StatusCode != http.StatusOK {
		t.Fatalf("status %d: %s", response.StatusCode, body)
	}
	location := response.Header.Get("Location")
	if !strings.HasPrefix(location, "/v1/checks/") {
		t.Fatalf("no Location pointing at the stored result: %q", location)
	}
	result, err := doc.ReadResult(bytes.TrimSpace(body))
	if err != nil {
		t.Fatalf("the served result is not a valid result: %v", err)
	}
	if result.ModelResult == "" {
		t.Error("the result carries no verdict")
	}

	// The same bytes come back from the read endpoint.
	readResponse, readBody := get(t, httpServer.URL+location)
	if readResponse.StatusCode != http.StatusOK {
		t.Fatalf("reading back gave %d: %s", readResponse.StatusCode, readBody)
	}
	if !bytes.Equal(bytes.TrimSpace(body), bytes.TrimSpace(readBody)) {
		t.Error("the stored result differs from the one that was returned")
	}
}

// The write is idempotent: the answer is a function of content, so posting twice
// files the same bytes under the same digest rather than making a second answer.
func TestPostChecksIsIdempotent(t *testing.T) {
	_, httpServer := newServer(t)
	proposal := aProposal(t)
	first, firstBody := post(t, httpServer.URL, proposal)
	second, secondBody := post(t, httpServer.URL, proposal)
	if first.StatusCode != http.StatusOK || second.StatusCode != http.StatusOK {
		t.Fatalf("statuses %d and %d", first.StatusCode, second.StatusCode)
	}
	if first.Header.Get("Location") != second.Header.Get("Location") {
		t.Errorf("two locations for one proposal: %s and %s",
			first.Header.Get("Location"), second.Header.Get("Location"))
	}
	if !bytes.Equal(firstBody, secondBody) {
		t.Error("posting the same proposal twice gave different bytes")
	}
}

// Concurrent posts of the same proposal must not race, and must all agree. The store
// writes through a temp file and renames, so a reader never sees a half-written
// result even while another request is filing one.
func TestConcurrentPostsAgree(t *testing.T) {
	_, httpServer := newServer(t)
	proposal := aProposal(t)

	const workers = 12
	bodies := make([][]byte, workers)
	locations := make([]string, workers)
	statuses := make([]int, workers)
	var group sync.WaitGroup
	for index := 0; index < workers; index++ {
		group.Add(1)
		go func(slot int) {
			defer group.Done()
			response, err := http.Post(httpServer.URL+"/v1/checks",
				"application/json", bytes.NewReader(proposal))
			if err != nil {
				return
			}
			defer response.Body.Close()
			raw, err := io.ReadAll(response.Body)
			if err != nil {
				return
			}
			bodies[slot] = raw
			locations[slot] = response.Header.Get("Location")
			statuses[slot] = response.StatusCode
		}(index)
	}
	group.Wait()

	for index := 0; index < workers; index++ {
		if statuses[index] != http.StatusOK {
			t.Fatalf("worker %d got status %d: %s", index, statuses[index], bodies[index])
		}
		if locations[index] != locations[0] {
			t.Errorf("worker %d filed under %s, worker 0 under %s",
				index, locations[index], locations[0])
		}
		if !bytes.Equal(bodies[index], bodies[0]) {
			t.Errorf("worker %d got different bytes", index)
		}
	}

	// Concurrent reads of what was written are also served whole.
	var readers sync.WaitGroup
	for index := 0; index < workers; index++ {
		readers.Add(1)
		go func() {
			defer readers.Done()
			response, err := http.Get(httpServer.URL + locations[0])
			if err != nil {
				return
			}
			defer response.Body.Close()
			raw, _ := io.ReadAll(response.Body)
			if response.StatusCode == http.StatusOK && !bytes.Equal(
				bytes.TrimSpace(raw), bytes.TrimSpace(bodies[0])) {
				t.Error("a concurrent read saw different bytes")
			}
		}()
	}
	readers.Wait()
}

// The snapshot endpoint serves the EXACT retained bytes, so a reader can hash what it
// received and get the name it asked for.
func TestSnapshotServesExactBytes(t *testing.T) {
	server, httpServer := newServer(t)
	proposal, err := doc.ReadProposal(aProposal(t))
	if err != nil {
		t.Fatal(err)
	}
	cited := citedSnapshots(proposal)
	if len(cited) == 0 {
		t.Skip("the proposal cites no snapshots")
	}
	for _, digest := range cited {
		response, raw := get(t, httpServer.URL+"/v1/snapshots/"+digest)
		if response.StatusCode != http.StatusOK {
			t.Fatalf("%s: status %d", short(digest), response.StatusCode)
		}
		sum := sha256.Sum256(raw)
		if hex.EncodeToString(sum[:]) != digest {
			t.Errorf("%s: the served bytes do not hash to the name they were asked for", short(digest))
		}
		stored, err := server.Store.Get(digest)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(raw, stored) {
			t.Errorf("%s: the served bytes differ from the stored ones", short(digest))
		}
	}
}

// A registry entry is found by RECOMPUTING each version, so an entry that was edited
// cannot be served under the version it used to have.
func TestRegistryIsFoundByRecomputedVersion(t *testing.T) {
	server, httpServer := newServer(t)
	for family, entry := range server.Registry {
		version, err := entry.SemanticsVersion()
		if err != nil {
			t.Fatal(err)
		}
		response, raw := get(t, httpServer.URL+"/v1/registry/"+version)
		if response.StatusCode != http.StatusOK {
			t.Fatalf("%s: status %d: %s", family, response.StatusCode, raw)
		}
		served, err := doc.ReadEntry(bytes.TrimSpace(raw))
		if err != nil {
			t.Fatalf("%s: the served entry is not a valid entry: %v", family, err)
		}
		servedVersion, err := served.SemanticsVersion()
		if err != nil {
			t.Fatal(err)
		}
		if servedVersion != version {
			t.Errorf("%s: served an entry whose version is %s, asked for %s",
				family, short(servedVersion), short(version))
		}
	}
}

// Every path validates what reaches it, and the refusal is a 400 about the NAME --
// not a 404 that happened to miss.
//
// The distinction matters: a handler with no validation also returns 404, because the
// lookup fails. Asserting 400 is what proves the name was rejected AS a name, before
// it could become part of a filesystem path.
func TestMalformedNamesAreRefused(t *testing.T) {
	_, httpServer := newServer(t)
	bad := []string{
		"not-a-digest", strings.Repeat("a", 63), strings.Repeat("a", 65),
		strings.Repeat("A", 64), strings.Repeat("g", 64),
		// Percent-encoded, because a plain "../.." is cleaned away by the client and
		// the mux and so never reaches a handler. These arrive intact, which is
		// exactly why the pattern is checked rather than the path sanitised.
		"%2e%2e%2f%2e%2e%2fetc%2fpasswd",
		"..%2f..%2fetc%2fpasswd",
		strings.Repeat("a", 64) + "%2f..%2f..%2fescaped",
		"%2e%2e%2f" + strings.Repeat("a", 64),
		strings.Repeat("a", 64) + "%00",
		strings.Repeat("a", 64) + "%0a" + strings.Repeat("b", 64),
	}
	for _, name := range bad {
		for _, prefix := range []string{"/v1/checks/", "/v1/snapshots/", "/v1/registry/"} {
			response, body := get(t, httpServer.URL+prefix+name)
			if response.StatusCode != http.StatusBadRequest {
				t.Errorf("%s%s gave %d, want 400 refusing the name itself: %s",
					prefix, name, response.StatusCode, bytes.TrimSpace(body))
			}
		}
	}
}

// A traversing name must not read a file outside the store, whatever status it
// returns. This is the property the pattern exists for, asserted directly.
func TestTraversalReadsNothingOutsideTheStore(t *testing.T) {
	server, httpServer := newServer(t)
	secret := filepath.Join(filepath.Dir(server.Store.Root), "secret.json")
	if err := os.WriteFile(secret, []byte(`{"secret":true}`), 0o644); err != nil {
		t.Fatal(err)
	}
	// Aimed at ../secret.json relative to snapshots/, percent-encoded so it survives.
	for _, name := range []string{
		"%2e%2e%2f%2e%2e%2fsecret", "..%2f..%2fsecret", "%2e%2e%2fsecret",
	} {
		response, body := get(t, httpServer.URL+"/v1/snapshots/"+name)
		if response.StatusCode == http.StatusOK {
			t.Fatalf("%s was served: %s", name, body)
		}
		if bytes.Contains(body, []byte("secret")) && bytes.Contains(body, []byte("true")) {
			t.Fatalf("%s leaked a file outside the store: %s", name, body)
		}
	}
}

// A body larger than the limit is refused rather than buffered.
func TestOversizedBodyIsRefused(t *testing.T) {
	_, httpServer := newServer(t)
	huge := bytes.Repeat([]byte("x"), MaxBody+1024)
	response, body := post(t, httpServer.URL, huge)
	if response.StatusCode != http.StatusRequestEntityTooLarge {
		t.Errorf("status %d, want %d", response.StatusCode, http.StatusRequestEntityTooLarge)
	}
	var problem Problem
	if err := json.Unmarshal(bytes.TrimSpace(body), &problem); err != nil {
		t.Fatal(err)
	}
	if problem.Error != "body_too_large" {
		t.Errorf("error %q, want body_too_large", problem.Error)
	}
}

// A proposal citing evidence that was never retained is refused, and the refusal is
// not a verdict: "could not read the book" must never read as "does not meet the
// objective".
func TestMissingEvidenceIsRefused(t *testing.T) {
	_, httpServer := newServer(t)
	proposal, err := doc.ReadProposal(aProposal(t))
	if err != nil {
		t.Fatal(err)
	}
	proposal.Legs[0].Acquisition.Snapshot = strings.Repeat("b", 64)
	encoded, err := doc.WriteProposal(proposal)
	if err != nil {
		t.Fatal(err)
	}
	response, body := post(t, httpServer.URL, encoded)
	if response.StatusCode != http.StatusUnprocessableEntity {
		t.Fatalf("status %d, want 422: %s", response.StatusCode, body)
	}
	var problem Problem
	if err := json.Unmarshal(bytes.TrimSpace(body), &problem); err != nil {
		t.Fatal(err)
	}
	if problem.Error != "snapshot_not_retained" {
		t.Errorf("error %q, want snapshot_not_retained", problem.Error)
	}
	if _, err := doc.ReadResult(bytes.TrimSpace(body)); err == nil {
		t.Error("a refusal was served as a readable result")
	}
}

// A proposal whose evidence IS retained but which lowering refuses comes back as a
// refusal carrying its CLASS. This is the path through lower.Refused, which the
// missing-evidence case above never reaches: that one is caught earlier, by the
// store. Both must refuse, and neither may look like a verdict.
func TestLoweringRefusalCarriesItsClass(t *testing.T) {
	_, httpServer := newServer(t)
	proposal, err := doc.ReadProposal(aProposal(t))
	if err != nil {
		t.Fatal(err)
	}
	// Pricing at displayed asks requires the zero_base_fee assumption. Dropping it
	// is a refusal with a named class, not a failing hedge.
	kept := []string{}
	for _, assumption := range proposal.Assumptions {
		if assumption != "zero_base_fee" {
			kept = append(kept, assumption)
		}
	}
	proposal.Assumptions = kept
	encoded, err := doc.WriteProposal(proposal)
	if err != nil {
		t.Fatal(err)
	}
	response, body := post(t, httpServer.URL, encoded)
	if response.StatusCode != http.StatusUnprocessableEntity {
		t.Fatalf("status %d, want 422: %s", response.StatusCode, body)
	}
	var problem Problem
	if err := json.Unmarshal(bytes.TrimSpace(body), &problem); err != nil {
		t.Fatal(err)
	}
	if problem.Error != "refused" {
		t.Errorf("error %q, want refused", problem.Error)
	}
	if problem.Class != "ASSUMPTION_REQUIRED" {
		t.Errorf("class %q, want ASSUMPTION_REQUIRED", problem.Class)
	}
	if _, err := doc.ReadResult(bytes.TrimSpace(body)); err == nil {
		t.Error("a refusal was served as a readable result")
	}
}

// Unreadable input is refused as unreadable, not lowered.
func TestUnreadableProposalIsRefused(t *testing.T) {
	_, httpServer := newServer(t)
	for _, body := range []string{"", "{", "null", `{"schema_version":"9"}`, "[]"} {
		response, raw := post(t, httpServer.URL, []byte(body))
		if response.StatusCode == http.StatusOK {
			t.Errorf("%q was accepted: %s", body, raw)
		}
	}
}

// Each path accepts only the methods it is for.
func TestMethodsAreConstrained(t *testing.T) {
	_, httpServer := newServer(t)
	digest := strings.Repeat("a", 64)
	cases := []struct{ method, path string }{
		{http.MethodGet, "/v1/checks"},
		{http.MethodDelete, "/v1/checks"},
		{http.MethodPost, "/v1/checks/" + digest},
		{http.MethodPost, "/v1/snapshots/" + digest},
		{http.MethodDelete, "/v1/registry/" + digest},
	}
	for _, testCase := range cases {
		request, err := http.NewRequest(testCase.method, httpServer.URL+testCase.path, nil)
		if err != nil {
			t.Fatal(err)
		}
		response, err := http.DefaultClient.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		response.Body.Close()
		if response.StatusCode != http.StatusMethodNotAllowed {
			t.Errorf("%s %s gave %d, want 405", testCase.method, testCase.path, response.StatusCode)
		}
		if allow := response.Header.Get("Allow"); allow == "" {
			t.Errorf("%s %s: a 405 states no Allow header", testCase.method, testCase.path)
		}
	}
}

// The service binds loopback only, and its timeouts are set.
func TestServerIsBoundToLoopbackWithTimeouts(t *testing.T) {
	if !strings.HasPrefix(Address, "127.0.0.1:") {
		t.Errorf("the default address is %q, which is not loopback", Address)
	}
	server := (&Server{}).NewHTTPServer("")
	if server.Addr != Address {
		t.Errorf("address %q", server.Addr)
	}
	if server.ReadTimeout == 0 || server.WriteTimeout == 0 || server.IdleTimeout == 0 {
		t.Error("a connection can be held open indefinitely")
	}
}

// An unknown path says so rather than falling through to something else.
func TestUnknownPathsAreNotFound(t *testing.T) {
	_, httpServer := newServer(t)
	for _, path := range []string{"/", "/v1", "/v1/nope", "/v2/checks"} {
		response, _ := get(t, httpServer.URL+path)
		if response.StatusCode != http.StatusNotFound {
			t.Errorf("%s gave %d, want 404", path, response.StatusCode)
		}
	}
}

// The served document's digest header names exactly the bytes that were sent.
func TestDocumentDigestHeaderMatchesTheBody(t *testing.T) {
	_, httpServer := newServer(t)
	response, body := post(t, httpServer.URL, aProposal(t))
	if response.StatusCode != http.StatusOK {
		t.Fatalf("status %d", response.StatusCode)
	}
	claimed := response.Header.Get("X-Document-Sha256")
	sum := sha256.Sum256(bytes.TrimSpace(body))
	if claimed != hex.EncodeToString(sum[:]) {
		t.Errorf("the digest header %s does not name the served document", short(claimed))
	}
}

// No refusal names a path on this machine.
//
// A filesystem error carries the store's absolute path, and where this server keeps
// its files is not something a caller asked about. The check is on the SHAPE of the
// message rather than on one known string, so a new error path that forwards a raw
// os error is caught too.
func TestRefusalsDoNotLeakPaths(t *testing.T) {
	server, httpServer := newServer(t)
	root := server.Store.Root

	missing := strings.Repeat("b", 64)
	proposal, err := doc.ReadProposal(aProposal(t))
	if err != nil {
		t.Fatal(err)
	}
	proposal.Legs[0].Acquisition.Snapshot = missing
	withMissing, err := doc.WriteProposal(proposal)
	if err != nil {
		t.Fatal(err)
	}

	type probe struct {
		what string
		body []byte
		get  string
	}
	probes := []probe{
		{what: "missing snapshot in a proposal", body: withMissing},
		{what: "unreadable proposal", body: []byte("{")},
		{what: "empty body", body: []byte("")},
		{what: "unknown snapshot", get: "/v1/snapshots/" + missing},
		{what: "unknown result", get: "/v1/checks/" + missing},
		{what: "unknown entry", get: "/v1/registry/" + missing},
		{what: "malformed name", get: "/v1/snapshots/%2e%2e%2fsecret"},
	}
	for _, p := range probes {
		var body []byte
		if p.get != "" {
			_, body = get(t, httpServer.URL+p.get)
		} else {
			_, body = post(t, httpServer.URL, p.body)
		}
		text := string(body)
		if strings.Contains(text, root) {
			t.Errorf("%s: the refusal names the store root: %s", p.what, text)
		}
		for _, marker := range []string{"/var/folders", "/tmp/", "/Users/", "no such file or directory"} {
			if strings.Contains(text, marker) {
				t.Errorf("%s: the refusal leaks %q: %s", p.what, marker, text)
			}
		}
	}
}

// A LOOPBACK BIND KEEPS OTHER MACHINES OUT. IT KEEPS NO WEB PAGE OUT.
//
// Any page the operator visits can reach 127.0.0.1, and the browser supplies their
// reachability rather than the attacker's. These are the two doors that were open, both
// confirmed against a running server before they were closed:
//
//   - a cross-origin `text/plain` POST returned 200 and the check RAN
//   - `Host: attacker.example` was served exactly as localhost, so a name re-pointed by
//     whoever owns its DNS reached this service
func TestServiceIsNotOpenToAnyWebPage(t *testing.T) {
	server, httpServer := newServer(t)
	proposal := aProposal(t)

	// A write must be application/json, because that is the one content type a
	// cross-origin fetch cannot send without a preflight -- and the preflight fails,
	// since no CORS headers are ever sent from here.
	for _, mediaType := range []string{
		"text/plain",
		"application/x-www-form-urlencoded",
		"multipart/form-data; boundary=x",
		"text/plain;charset=UTF-8",
		"",
	} {
		req, err := http.NewRequest(http.MethodPost, httpServer.URL+"/v1/checks", bytes.NewReader(proposal))
		if err != nil {
			t.Fatal(err)
		}
		if mediaType != "" {
			req.Header.Set("Content-Type", mediaType)
		}
		req.Header.Set("Origin", "https://evil.example")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusUnsupportedMediaType {
			t.Errorf("a %q write gave %d, want 415", mediaType, resp.StatusCode)
		}
	}

	// And the real client is unaffected.
	if resp, body := post(t, httpServer.URL, proposal); resp.StatusCode != http.StatusOK {
		t.Errorf("an application/json write gave %d: %s", resp.StatusCode, body)
	}

	// The Host header names this machine, by NAME. The port is not part of the rule:
	// the bind address chooses it, and a test binds an ephemeral one.
	handler := server.Handler()
	for _, allowed := range []string{"localhost:8787", "127.0.0.1:8787", "localhost", "127.0.0.1:41234", "[::1]:8787"} {
		req := httptest.NewRequest(http.MethodGet, "/v1/checks/"+strings.Repeat("a", 64), nil)
		req.Host = allowed
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code == http.StatusMisdirectedRequest {
			t.Errorf("Host %q was refused; it names this machine", allowed)
		}
	}
	for _, refused := range []string{"attacker.example", "hedgecheck.evil.test", "", "localhost.evil.test", "127.0.0.1.evil.test"} {
		req := httptest.NewRequest(http.MethodGet, "/v1/checks/"+strings.Repeat("a", 64), nil)
		req.Host = refused
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusMisdirectedRequest {
			t.Errorf("Host %q gave %d, want 421: a rebound name is served as localhost", refused, rec.Code)
		}
	}
}

// A STORED RESULT DOES NOT CONTRADICT THE DIGEST IT IS SERVED UNDER.
//
// A snapshot is content-addressed, so the store re-hashes it. A result is filed under
// `input_digest` -- a claim about its inputs, not a hash of itself -- so nothing in the
// store catches a file swapped for one answering a different question. It was served as
// authentic: requested dfd48569…, served a document claiming dead8569…, status 200.
func TestAServedResultDoesNotContradictItsDigest(t *testing.T) {
	server, httpServer := newServer(t)
	resp, body := post(t, httpServer.URL, aProposal(t))
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("post: %d %s", resp.StatusCode, body)
	}
	digest := strings.TrimPrefix(resp.Header.Get("Location"), "/v1/checks/")
	if digest == "" {
		t.Fatal("the write states no Location")
	}

	// Read back cleanly first, so the refusal below is caused by the swap and not by
	// something this test got wrong about the shape of a result.
	if ok, _ := get(t, httpServer.URL+"/v1/checks/"+digest); ok.StatusCode != http.StatusOK {
		t.Fatalf("the genuine result read back as %d", ok.StatusCode)
	}

	var stored map[string]any
	if err := json.Unmarshal(body, &stored); err != nil {
		t.Fatal(err)
	}
	stored["input_digest"] = "dead" + digest[4:]
	swapped, err := json.Marshal(stored)
	if err != nil {
		t.Fatal(err)
	}
	if err := server.Store.PutResult(digest, evaluate.Version, swapped); err != nil {
		t.Fatal(err)
	}

	after, served := get(t, httpServer.URL+"/v1/checks/"+digest)
	if after.StatusCode != http.StatusInternalServerError {
		t.Errorf("a result answering a different input was served with %d: %s", after.StatusCode, served)
	}
	if strings.Contains(string(served), "dead") {
		t.Errorf("the refusal quotes the stored value: %s", served)
	}
}

// A SERVER WITH NO STORE ANSWERS, RATHER THAN PANICKING.
//
// Found while probing the host check: a zero `Server` panicked with a nil dereference
// in `store.resultPath` on a well-formed request. `serve` refuses without `--store`, so
// this is not reachable from the CLI -- but `Handler()` is exported, and a panic in a
// handler goroutine is a worse answer than a status.
func TestAServerWithoutAStoreDoesNotPanic(t *testing.T) {
	handler := (&Server{}).Handler()
	for _, path := range []string{
		"/v1/checks/" + strings.Repeat("a", 64),
		"/v1/snapshots/" + strings.Repeat("b", 64),
		"/v1/registry/recurring.priceBucket",
		"/v1/bundle/" + strings.Repeat("c", 64) + "/result.json",
	} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		req.Host = "localhost:8787"
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req) // must not panic
		if rec.Code != http.StatusServiceUnavailable {
			t.Errorf("%s gave %d, want 503", path, rec.Code)
		}
	}
}
