package hyperliquid

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"regexp"
	"strings"
	"testing"
	"time"
)

// The constants are the network contract this package promises. They are asserted
// against hand-written literals, not against themselves, so a change to any of them
// is a deliberate edit to this test rather than a silent widening.
func TestNetworkContract(t *testing.T) {
	if Endpoint != "https://api.hyperliquid.xyz/info" {
		t.Errorf("endpoint is %q", Endpoint)
	}
	if Pace != 1500*time.Millisecond {
		t.Errorf("pace is %v, want 1.5s", Pace)
	}
	if Budget != 40 {
		t.Errorf("budget is %d, want 40", Budget)
	}
	for _, kind := range []string{"outcomeMeta", "metaAndAssetCtxs", "l2Book"} {
		if !allowed[kind] {
			t.Errorf("%s is not in the allowed set", kind)
		}
	}
	if len(allowed) != 3 {
		t.Errorf("the allowed set has %d entries, want exactly 3", len(allowed))
	}
}

// A request type outside the closed set is refused BEFORE any connection is made, so
// a typo cannot reach an endpoint this package was not built to call. The client is
// given a transport that fails the test if it is ever used.
func TestDisallowedTypeNeverReachesTheNetwork(t *testing.T) {
	client := NewClient()
	client.HTTP = &http.Client{Transport: refuseTransport{t}}
	for _, kind := range []string{"userState", "order", "exchange", "", "allMids"} {
		_, err := client.Fetch(map[string]any{"type": kind})
		if err == nil {
			t.Errorf("Fetch sent a %q request", kind)
		}
		if err != nil && !strings.Contains(err.Error(), "is not one of") {
			t.Errorf("%q: got %v, want a closed-set refusal", kind, err)
		}
	}
	if client.Spent() != 0 {
		t.Errorf("a refused request spent %d of the budget", client.Spent())
	}
}

type refuseTransport struct{ t *testing.T }

func (r refuseTransport) RoundTrip(*http.Request) (*http.Response, error) {
	r.t.Fatal("a request reached the network")
	return nil, nil
}

// The budget is a hard stop, not a warning: once spent, the next call returns rather
// than connecting.
func TestBudgetStopsTheRun(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"time":1}`))
	}))
	defer server.Close()

	client := &Client{HTTP: server.Client(), Pace: 0, Budget: 2}
	client.endpoint = server.URL
	for attempt := 1; attempt <= 2; attempt++ {
		if _, err := client.Fetch(map[string]any{"type": "outcomeMeta"}); err != nil {
			t.Fatalf("request %d: %v", attempt, err)
		}
	}
	_, err := client.Fetch(map[string]any{"type": "outcomeMeta"})
	if err == nil {
		t.Fatal("the third request was made against a budget of two")
	}
	if _, ok := err.(*BudgetSpent); !ok {
		t.Fatalf("got %v, want a BudgetSpent", err)
	}
	if client.Spent() != 2 {
		t.Errorf("spent %d, want 2", client.Spent())
	}
}

// The digest names the exact response bytes, which is what the store will file it
// under and what a replay re-verifies.
func TestFetchDigestsTheExactBytes(t *testing.T) {
	body := `{"time":1758300000000,"levels":[[],[]]}`
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(body))
	}))
	defer server.Close()

	client := &Client{HTTP: server.Client(), Pace: 0, Budget: 1}
	client.endpoint = server.URL
	response, err := client.Fetch(map[string]any{"type": "l2Book", "coin": "x"})
	if err != nil {
		t.Fatal(err)
	}
	if string(response.Raw) != body {
		t.Errorf("raw bytes are %q, want %q", response.Raw, body)
	}
	// Hand-derived: sha256 of the body above, computed outside this package.
	if len(response.Digest) != 64 {
		t.Errorf("digest %q is not a SHA-256", response.Digest)
	}
	for _, field := range []string{"endpoint", "requested_at", "retrieved_at", "response_sha256", "http_status"} {
		if !strings.Contains(string(response.Record), field) {
			t.Errorf("the request record omits %s", field)
		}
	}
}

// The pace is enforced between requests, not merely documented.
func TestPaceIsEnforcedBetweenRequests(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{}`))
	}))
	defer server.Close()

	pace := 120 * time.Millisecond
	client := &Client{HTTP: server.Client(), Pace: pace, Budget: 3}
	client.endpoint = server.URL
	start := time.Now()
	for attempt := 0; attempt < 3; attempt++ {
		if _, err := client.Fetch(map[string]any{"type": "outcomeMeta"}); err != nil {
			t.Fatal(err)
		}
	}
	// Three requests wait twice; the first does not wait.
	if elapsed := time.Since(start); elapsed < 2*pace {
		t.Errorf("three requests took %v, want at least %v", elapsed, 2*pace)
	}
}

func TestBookTimeReadsTheVenueTimestamp(t *testing.T) {
	milliseconds, ok := BookTime([]byte(`{"time":1758300000123,"levels":[[],[]]}`))
	if !ok {
		t.Fatal("a book with a time reported none")
	}
	if milliseconds != 1758300000123 {
		t.Errorf("read %d, want 1758300000123", milliseconds)
	}
}

// A book without a usable timestamp reports so rather than defaulting to zero, which
// would silently read as a 55-year skew.
func TestBookTimeRefusesWhatItCannotRead(t *testing.T) {
	for _, raw := range []string{`{}`, `{"time":"x"}`, `not json`, `{"time":1.5}`, `[]`} {
		if _, ok := BookTime([]byte(raw)); ok {
			t.Errorf("BookTime accepted %q", raw)
		}
	}
}

func TestRetrievedAtRoundTrips(t *testing.T) {
	record := []byte(`{"retrieved_at":"2026-09-20T05:20:00.500Z"}`)
	milliseconds, ok := RetrievedAt(record)
	if !ok {
		t.Fatal("a record with a retrieval time reported none")
	}
	want := time.Date(2026, 9, 20, 5, 20, 0, 500_000_000, time.UTC).UnixMilli()
	if milliseconds != want {
		t.Errorf("read %d, want %d", milliseconds, want)
	}
}

func TestRetrievedAtRefusesWhatItCannotRead(t *testing.T) {
	for _, raw := range []string{`{}`, `{"retrieved_at":"yesterday"}`, `nope`} {
		if _, ok := RetrievedAt([]byte(raw)); ok {
			t.Errorf("RetrievedAt accepted %q", raw)
		}
	}
}

// A request record's timestamps match snapshot-record.schema.json, which is frozen at
// v1 and describes the fifty records retained at 085ccfb.
//
// Found on 20 September: the adapter wrote RFC 3339 with a Z, the schema requires an
// explicit +00:00, and the first Go-captured records failed validation. The schema is
// the specification, so the engine conforms to the evidence.
func TestRequestRecordTimestampsMatchTheSchema(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"time":1}`))
	}))
	defer server.Close()

	client := &Client{HTTP: server.Client(), Pace: 0, Budget: 1}
	client.endpoint = server.URL
	response, err := client.Fetch(map[string]any{"type": "outcomeMeta"})
	if err != nil {
		t.Fatal(err)
	}
	var record map[string]any
	if err := json.Unmarshal(response.Record, &record); err != nil {
		t.Fatal(err)
	}
	// The schema's own pattern, transcribed by hand from the frozen file.
	pattern := regexp.MustCompile(`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+\+00:00$`)
	for _, field := range []string{"requested_at", "retrieved_at"} {
		value, _ := record[field].(string)
		if !pattern.MatchString(value) {
			t.Errorf("%s is %q, which snapshot-record.schema.json refuses", field, value)
		}
		if strings.HasSuffix(value, "Z") {
			t.Errorf("%s ends in Z; the retained records all use +00:00", field)
		}
	}
}

// What the adapter writes, RetrievedAt reads back.
func TestRetrievedAtReadsWhatTheAdapterWrites(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"time":1}`))
	}))
	defer server.Close()

	client := &Client{HTTP: server.Client(), Pace: 0, Budget: 1}
	client.endpoint = server.URL
	before := time.Now().UTC().Add(-time.Second).UnixMilli()
	response, err := client.Fetch(map[string]any{"type": "outcomeMeta"})
	if err != nil {
		t.Fatal(err)
	}
	after := time.Now().UTC().Add(time.Second).UnixMilli()
	milliseconds, ok := RetrievedAt(response.Record)
	if !ok {
		t.Fatal("the adapter wrote a retrieval time it cannot read back")
	}
	if milliseconds < before || milliseconds > after {
		t.Errorf("read %d, which is outside the second this call took", milliseconds)
	}
}

// The retained Python records are read too: they use the same +00:00 form, and a
// replay must be able to measure skew from evidence either implementation captured.
func TestRetrievedAtReadsRetainedPythonRecords(t *testing.T) {
	raw, err := os.ReadFile("../../../fixtures/replay/2026-09-19/binary-no.request.json")
	if err != nil {
		t.Skipf("no retained record: %v", err)
	}
	milliseconds, ok := RetrievedAt(raw)
	if !ok {
		t.Fatal("a retained Python record could not be read")
	}
	// Pinned from the run document the spike wrote for this capture.
	if milliseconds != 1789842197425 {
		t.Errorf("read %d, the run recorded 1789842197425", milliseconds)
	}
}
