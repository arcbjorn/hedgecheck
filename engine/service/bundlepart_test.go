package service

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The bundle part name reaches a filesystem path. It is refused AS A NAME.
//
// The digest is checked against its pattern here; the part is checked by the store's
// own closed set. That is defence in depth rather than duplication -- but the T2
// audit found that a 404 from a failed lookup looks exactly like a 400 from a
// rejected name, so this asserts the STATUS and not merely "not 200".
func TestBundlePartNamesAreRefused(t *testing.T) {
	_, httpServer := newServer(t)
	digest := strings.Repeat("a", 64)
	// Percent-encoded, because a plain ../.. is cleaned away by the client and the
	// mux and never reaches a handler.
	for _, part := range []string{
		"%2e%2e%2f%2e%2e%2fetc%2fpasswd",
		"..%2f..%2fsecret",
		"proposal%00",
		"PROPOSAL",
		"result",
		"go-engine-1",
		"",
	} {
		response, body := get(t, httpServer.URL+"/v1/bundle/"+digest+"/"+part)
		if response.StatusCode == http.StatusOK {
			t.Errorf("/v1/bundle/<digest>/%s was served: %s", part, body)
		}
	}
}

// A traversing part name reads nothing outside the store.
//
// A REAL FILE IS PLANTED at the traversal target. Without it the test proves
// nothing: a 404 because the guard refused the name and a 404 because the file did
// not exist look identical, which is the confusion the T2 audit found in the
// snapshot routes. With the file there, a missing guard serves it.
func TestBundlePartTraversalReadsNothing(t *testing.T) {
	server, httpServer := newServer(t)
	digest := strings.Repeat("a", 64)

	// results/<digest>/../../secret.json, relative to the store root.
	planted := filepath.Join(server.Store.Root, "secret.json")
	if err := os.WriteFile(planted, []byte(`{"secret":"outside the store"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	// And one inside results/, one level up from the digest directory.
	if err := os.MkdirAll(filepath.Join(server.Store.Root, "results"), 0o755); err != nil {
		t.Fatal(err)
	}
	nearer := filepath.Join(server.Store.Root, "results", "secret.json")
	if err := os.WriteFile(nearer, []byte(`{"secret":"one level up"}`), 0o644); err != nil {
		t.Fatal(err)
	}

	for _, part := range []string{
		"%2e%2e%2f%2e%2e%2fsecret", "..%2f..%2fsecret", "%2e%2e%2fsecret", "..%2fsecret",
	} {
		response, body := get(t, httpServer.URL+"/v1/bundle/"+digest+"/"+part)
		if response.StatusCode == http.StatusOK {
			t.Errorf("%s was served: %s", part, body)
		}
		if strings.Contains(string(body), "outside the store") ||
			strings.Contains(string(body), "one level up") {
			t.Errorf("%s leaked a planted file: %s", part, body)
		}
	}
}
