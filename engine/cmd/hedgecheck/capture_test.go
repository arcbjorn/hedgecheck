package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"hedgecheck/engine/lower"
	"hedgecheck/engine/store"
)

// fakeVenue replays the retained 19 September responses in whatever order it is
// asked for them, and RECORDS the order.
//
// The capture sequence is the thing most likely to be got wrong and the thing a live
// run cannot check: if contexts were fetched after the books, every run would still
// succeed and every baseline would describe a moment the prices had not reached.
type fakeVenue struct {
	t         *testing.T
	calls     []string
	spent     int
	failOn    string
	responses map[string][]byte
	records   map[string][]byte
}

func newFakeVenue(t *testing.T) *fakeVenue {
	t.Helper()
	venue := &fakeVenue{
		t:         t,
		responses: map[string][]byte{},
		records:   map[string][]byte{},
	}
	for _, name := range []string{"catalogue", "contexts", "binary-no", "bucket0-yes"} {
		raw, err := os.ReadFile(filepath.Join(replayFixtures, name+".json"))
		if err != nil {
			t.Skipf("no retained %s: %v", name, err)
		}
		venue.responses[name] = raw
		record, err := os.ReadFile(filepath.Join(replayFixtures, name+".request.json"))
		if err == nil {
			venue.records[name] = record
		}
	}
	return venue
}

func (v *fakeVenue) reply(name string) (Retrieved, error) {
	v.calls = append(v.calls, name)
	if v.failOn == name {
		return Retrieved{}, fmt.Errorf("the venue refused %s", name)
	}
	v.spent++
	raw := v.responses[name]
	sum := sha256.Sum256(raw)
	return Retrieved{
		Digest: hex.EncodeToString(sum[:]), Raw: raw, Record: v.records[name],
	}, nil
}

func (v *fakeVenue) Catalogue() (Retrieved, error) { return v.reply("catalogue") }
func (v *fakeVenue) Contexts() (Retrieved, error)  { return v.reply("contexts") }
func (v *fakeVenue) Book(coin string) (Retrieved, error) {
	// The coin is discovered, never configured, so the fake maps it back to the
	// retained book by matching what discovery derived.
	for _, name := range []string{"binary-no", "bucket0-yes"} {
		if v.coinFor(name) == coin {
			return v.reply(name)
		}
	}
	v.calls = append(v.calls, "book:"+coin)
	return Retrieved{}, fmt.Errorf("no retained book for %s", coin)
}

func (v *fakeVenue) coinFor(leg string) string {
	raw, err := os.ReadFile(filepath.Join(replayFixtures, "binary-no.run.json"))
	if err != nil {
		return ""
	}
	var document struct {
		Results map[string]struct {
			Legs []struct {
				Instance struct {
					Coin string `json:"coin"`
				} `json:"instance"`
			} `json:"legs"`
		} `json:"results"`
	}
	if err := json.Unmarshal(raw, &document); err != nil {
		return ""
	}
	// The run document's results do not carry the instance, so derive the coin the
	// same way discovery does instead: from the book's own response.
	book, err := os.ReadFile(filepath.Join(replayFixtures, leg+".json"))
	if err != nil {
		return ""
	}
	var parsed struct {
		Coin string `json:"coin"`
	}
	if err := json.Unmarshal(book, &parsed); err != nil {
		return ""
	}
	return parsed.Coin
}

func (v *fakeVenue) Spent() int { return v.spent }

// The capture order is catalogue, then contexts, then the books.
//
// Catalogue first because the coins are discovered from it. Contexts before the books
// so the baseline is never NEWER than the prices it is compared against: a baseline
// fetched last would describe a moment the prices had not reached, and every
// comparison would be wrong in whichever direction the market moved.
func TestCaptureOrderIsCatalogueContextsThenBooks(t *testing.T) {
	venue := newFakeVenue(t)
	keep := store.New(t.TempDir())
	captured, err := CaptureLive(venue, keep, "BTC", retrievedAtForTest)
	if err != nil {
		t.Fatal(err)
	}
	if len(venue.calls) < 3 {
		t.Fatalf("only %d calls were made: %v", len(venue.calls), venue.calls)
	}
	if venue.calls[0] != "catalogue" {
		t.Errorf("the first call is %s, want catalogue: the coins come from it", venue.calls[0])
	}
	if venue.calls[1] != "contexts" {
		t.Errorf("the second call is %s, want contexts: the baseline must not be newer than the books",
			venue.calls[1])
	}
	for index, call := range venue.calls[2:] {
		if call == "catalogue" || call == "contexts" {
			t.Errorf("call %d is %s, after the books had started", index+2, call)
		}
	}
	if captured.Expiry == "" {
		t.Error("the capture records no expiry")
	}
	if len(captured.Capture.BookDigests) != 2 {
		t.Errorf("captured %d books, want 2", len(captured.Capture.BookDigests))
	}
}

// Every response is filed under its own digest as it arrives, so an interrupted
// capture leaves retained bytes rather than nothing.
func TestCaptureFilesEachResponseAsItArrives(t *testing.T) {
	venue := newFakeVenue(t)
	venue.failOn = "bucket0-yes"
	root := t.TempDir()
	keep := store.New(root)

	if _, err := CaptureLive(venue, keep, "BTC", retrievedAtForTest); err == nil {
		t.Fatal("a refused book still produced a capture")
	}
	// Whatever arrived before the failure is on disk and verifies.
	matches, err := filepath.Glob(filepath.Join(root, "snapshots", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	kept := 0
	for _, path := range matches {
		if strings.HasSuffix(path, ".request.json") {
			continue
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		sum := sha256.Sum256(raw)
		name := strings.TrimSuffix(filepath.Base(path), ".json")
		if hex.EncodeToString(sum[:]) != name {
			t.Errorf("%s does not hash to its own name", name[:12])
		}
		kept++
	}
	if kept < 3 {
		t.Errorf("only %d responses survived the interruption, want the 3 that arrived", kept)
	}
}

// The capture measures skew across the books it retained, and reproduces what the
// spike recorded for this very capture: -621 and -689 ms, worst -689.
func TestCaptureMeasuresTheRetainedSkew(t *testing.T) {
	venue := newFakeVenue(t)
	keep := store.New(t.TempDir())
	captured, err := CaptureLive(venue, keep, "BTC", retrievedAtForTest)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]int64{"binary-no": -621, "bucket0-yes": -689}
	for name, expected := range want {
		if captured.Skew.Details[name] != expected {
			t.Errorf("%s: measured %d ms, the spike recorded %d ms",
				name, captured.Skew.Details[name], expected)
		}
	}
	if captured.Skew.WorstMs != -689 {
		t.Errorf("worst skew %d, want -689 with its sign", captured.Skew.WorstMs)
	}
	assertion, err := captured.Skew.Assert("test")
	if err != nil {
		t.Fatal(err)
	}
	if assertion.SkewMs != "-689" {
		t.Errorf("the assertion says %q, want -689", assertion.SkewMs)
	}
}

// A capture whose adapter and store disagree about a digest is an error, never a
// silent substitution: the two hashed the same bytes, so they can only differ if
// something changed them in between.
func TestCaptureRefusesADigestMismatch(t *testing.T) {
	keep := store.New(t.TempDir())
	out := Captured{
		Records: map[string][]byte{},
	}
	out.Capture.Snapshots = lower.Snapshots{}
	wrong := Retrieved{
		Digest: strings.Repeat("a", 64),
		Raw:    []byte(`{"not":"what the digest says"}`),
	}
	err := retain(keep, &out, "catalogue", wrong)
	if err == nil {
		t.Fatal("a response was filed under a digest that is not its own")
	}
	if !strings.Contains(err.Error(), "the adapter says") {
		t.Errorf("the error does not name the disagreement: %v", err)
	}
}

// retrievedAtForTest reads the local retrieval time a request record carries. The
// adapter owns the production reader, because parsing an RFC 3339 instant needs a
// clock library a pure package may not import.
func retrievedAtForTest(record []byte) (int64, bool) {
	var value struct {
		RetrievedAt string `json:"retrieved_at"`
	}
	if err := json.Unmarshal(record, &value); err != nil {
		return 0, false
	}
	moment, err := time.Parse(time.RFC3339Nano, value.RetrievedAt)
	if err != nil {
		return 0, false
	}
	return moment.UnixMilli(), true
}
