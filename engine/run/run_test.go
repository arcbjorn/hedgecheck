package run

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
	"hedgecheck/engine/lower"
)

// The 19 September capture, which the Python spike answered and recorded in
// binary-no.run.json. Every expectation below is read from THAT file or derived by
// hand from the catalogue, never from this package.
const fixtures = "../../fixtures/replay/2026-09-19"

func loadCapture(t *testing.T) Capture {
	t.Helper()
	snapshots := lower.Snapshots{}
	digest := func(name string) string {
		t.Helper()
		raw, err := os.ReadFile(filepath.Join(fixtures, name))
		if err != nil {
			t.Fatal(err)
		}
		sum, err := snapshots.Add(raw)
		if err != nil {
			t.Fatal(err)
		}
		return sum
	}
	return Capture{
		CatalogueDigest: digest("catalogue.json"),
		ContextsDigest:  digest("contexts.json"),
		BookDigests: map[string]string{
			"binary-no":   digest("binary-no.json"),
			"bucket0-yes": digest("bucket0-yes.json"),
		},
		Snapshots: snapshots,
	}
}

func loadRegistry(t *testing.T) map[string]doc.Entry {
	t.Helper()
	matches, err := filepath.Glob("../../registry/*.json")
	if err != nil || len(matches) == 0 {
		t.Fatalf("no registry entries: %v", err)
	}
	out := map[string]doc.Entry{}
	for _, path := range matches {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		entry, err := doc.ReadEntry(raw)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		out[entry.Family] = entry
	}
	return out
}

func mustQ(t *testing.T, text string) exact.Q {
	t.Helper()
	value, err := exact.ParseQ(text)
	if err != nil {
		t.Fatal(err)
	}
	return value
}

// The options the spike recorded under "options" in its run document.
func spikeOptions(t *testing.T) Options {
	t.Helper()
	return Options{
		Underlying:    "BTC",
		Quantity:      mustQ(t, "0.1"),
		Cap:           mustQ(t, "1000"),
		Floor:         mustQ(t, "60000"),
		Ceiling:       mustQ(t, "110000"),
		BaselineKind:  "analysis_time",
		ValuationTime: "2026-09-20T06:00:00Z",
	}
}

func TestRunReproducesTheSpikeRun(t *testing.T) {
	answer, err := Run(loadCapture(t), spikeOptions(t), loadRegistry(t))
	if err != nil {
		t.Fatal(err)
	}

	// Pinned from the spike's run document.
	if answer.Expiry != "20260920-0600" {
		t.Errorf("expiry %q, want 20260920-0600", answer.Expiry)
	}
	if answer.ObservationTime != "2026-09-20T06:00:00Z" {
		t.Errorf("observation time %q", answer.ObservationTime)
	}
	if got := answer.Baseline.String(); got != "81520" {
		t.Errorf("baseline %s, want 81520 (the mark in the contexts snapshot)", got)
	}
	if len(answer.Rows) != 2 {
		t.Fatalf("got %d rows, want 2", len(answer.Rows))
	}

	// Both legs rest on an unreviewed family, so each is reduced to no value and the
	// verdict is needs_review rather than fails: a loose bound never condemns.
	want := map[string]struct{ verdict, worst, premium string }{
		"binary-no":   {"needs_review", "-2640.69285", "488.69285"},
		"bucket0-yes": {"needs_review", "-2197.636", "45.636"},
	}
	for _, row := range answer.Rows {
		expected, known := want[row.ID]
		if !known {
			t.Errorf("unexpected row %q", row.ID)
			continue
		}
		if !row.Sized {
			t.Errorf("%s: no size window; the spike sized this leg", row.ID)
			continue
		}
		if got := string(row.Result.ModelResult); got != expected.verdict {
			t.Errorf("%s: verdict %q, want %q", row.ID, got, expected.verdict)
		}
		if got := row.Result.WorstCase.Pnl.String(); got != expected.worst {
			t.Errorf("%s: worst case %s, want %s", row.ID, got, expected.worst)
		}
		if got := row.Result.Cost.Premium.String(); got != expected.premium {
			t.Errorf("%s: premium %s, want %s", row.ID, got, expected.premium)
		}
	}
}

// Two candidates answering the same question are ranked; the comparison restates no
// numbers of its own.
func TestRunComparesBothCandidates(t *testing.T) {
	answer, err := Run(loadCapture(t), spikeOptions(t), loadRegistry(t))
	if err != nil {
		t.Fatal(err)
	}
	if answer.Comparison == nil {
		t.Fatal("two sized candidates produced no comparison")
	}
}

// The same capture answered twice gives the same bytes. This is what makes a replay
// a check: nothing here may depend on map order, a clock or an address.
func TestRunIsDeterministic(t *testing.T) {
	first, err := Run(loadCapture(t), spikeOptions(t), loadRegistry(t))
	if err != nil {
		t.Fatal(err)
	}
	for attempt := 0; attempt < 8; attempt++ {
		again, err := Run(loadCapture(t), spikeOptions(t), loadRegistry(t))
		if err != nil {
			t.Fatal(err)
		}
		if len(again.Rows) != len(first.Rows) {
			t.Fatalf("row count changed between runs")
		}
		for index := range first.Rows {
			if again.Rows[index].ID != first.Rows[index].ID {
				t.Errorf("row %d is %s, was %s: the order is not stable",
					index, again.Rows[index].ID, first.Rows[index].ID)
			}
			if again.Rows[index].InputDigest != first.Rows[index].InputDigest {
				t.Errorf("%s: the input digest changed between identical runs",
					first.Rows[index].ID)
			}
		}
	}
}

// A run whose catalogue was not supplied is an error, not an empty answer.
func TestRunRefusesAMissingSnapshot(t *testing.T) {
	capture := loadCapture(t)
	capture.CatalogueDigest = "0000000000000000000000000000000000000000000000000000000000000000"
	if _, err := Run(capture, spikeOptions(t), loadRegistry(t)); err == nil {
		t.Fatal("a missing catalogue produced an answer")
	}
}

// A book that was never captured cannot be silently skipped: the answer would then be
// about fewer instruments than it claims.
func TestRunRefusesAMissingBook(t *testing.T) {
	capture := loadCapture(t)
	delete(capture.BookDigests, "bucket0-yes")
	if _, err := Run(capture, spikeOptions(t), loadRegistry(t)); err == nil {
		t.Fatal("a missing book produced an answer")
	}
}

// An explicit baseline is used as given, and the contexts snapshot is not consulted.
func TestExplicitBaselineIsUsedAsGiven(t *testing.T) {
	options := spikeOptions(t)
	options.BaselineKind = "explicit"
	options.BaselinePrice = mustQ(t, "80000")
	answer, err := Run(loadCapture(t), options, loadRegistry(t))
	if err != nil {
		t.Fatal(err)
	}
	if got := answer.Baseline.String(); got != "80000" {
		t.Errorf("baseline %s, want the 80000 that was given", got)
	}
}

// The no-premium alternative: selling down to what meets the cap. Derived by hand
// here: keeping k at a baseline of 81520 with a floor of 60000 loses k*(60000-81520),
// so the cap of 1000 allows k = 1000/21520 = 25/538, which is what the spike recorded
// under "smallest_reduction".
func TestSmallestReductionMatchesTheSpike(t *testing.T) {
	answer, err := Run(loadCapture(t), spikeOptions(t), loadRegistry(t))
	if err != nil {
		t.Fatal(err)
	}
	if got := answer.Reduction.Keep.String(); got != "25/538" {
		t.Errorf("keep %s, want 25/538", got)
	}
	if got := answer.Reduction.Sell.String(); got != "72/1345" {
		t.Errorf("sell %s, want 72/1345", got)
	}
	if got := answer.Reduction.WorstCase.String(); got != "-1000" {
		t.Errorf("worst case %s, want exactly the -1000 cap", got)
	}
}

// Skew is measured across a capture and reported as the worst, so one stale book
// cannot hide behind a fresh one.
func TestMeasureReportsTheWorstSkew(t *testing.T) {
	books := map[string][]byte{"a": []byte("a"), "b": []byte("b"), "c": []byte("c")}
	records := map[string][]byte{"a": []byte("a"), "b": []byte("b"), "c": []byte("c")}
	venue := map[string]int64{"a": 1000, "b": 1000, "c": 1000}
	local := map[string]int64{"a": 1300, "b": 1900, "c": 1100}
	skew, err := Measure(books, records,
		func(raw []byte) (int64, bool) { return venue[string(raw)], true },
		func(raw []byte) (int64, bool) { return local[string(raw)], true })
	if err != nil {
		t.Fatal(err)
	}
	if skew.WorstMs != -900 {
		t.Errorf("worst skew %d, want -900", skew.WorstMs)
	}
	if skew.Details["a"] != -300 || skew.Details["c"] != -100 {
		t.Errorf("details are %v", skew.Details)
	}
}

// A book with no readable timestamp stops the run rather than reporting a skew of
// zero, which would read as a perfectly fresh capture.
func TestMeasureRefusesAnUnreadableTimestamp(t *testing.T) {
	books := map[string][]byte{"a": []byte("a")}
	records := map[string][]byte{"a": []byte("a")}
	_, err := Measure(books, records,
		func([]byte) (int64, bool) { return 0, false },
		func([]byte) (int64, bool) { return 0, true })
	if err == nil {
		t.Fatal("an unreadable venue timestamp was reported as no skew")
	}
}

// The spike measured -689 ms at worst on this capture, and the bound is 5000.
func TestTheRecordedSkewIsWithinTheBound(t *testing.T) {
	if MaxSkewMs != 5000 {
		t.Errorf("the bound is %d, want 5000", MaxSkewMs)
	}
	if worst := int64(-689); abs(worst) > MaxSkewMs {
		t.Errorf("the recorded worst skew %d exceeds the bound", worst)
	}
}

// The assertion keeps the sign the retained 19 September run recorded, and refuses a
// capture spread too far apart to be one moment. Pinned: the spike measured -621 and
// -689 ms on that capture, and recorded -689.
func TestAssertKeepsTheSignAndHoldsTheBound(t *testing.T) {
	within := Skew{WorstMs: -689}
	assertion, err := within.Assert("go-engine check")
	if err != nil {
		t.Fatal(err)
	}
	if assertion.SkewMs != "-689" {
		t.Errorf("recorded skew %q, want -689 with its sign kept", assertion.SkewMs)
	}
	if assertion.MaxSkewMs != "5000" {
		t.Errorf("recorded bound %q, want 5000", assertion.MaxSkewMs)
	}

	// The bound is about distance from zero, so it bites on either side.
	for _, worst := range []int64{MaxSkewMs + 1, -(MaxSkewMs + 1)} {
		if _, err := (Skew{WorstMs: worst}).Assert("go-engine check"); err == nil {
			t.Errorf("a skew of %d ms was accepted", worst)
		}
	}
	// Exactly at the bound is within it.
	if _, err := (Skew{WorstMs: -MaxSkewMs}).Assert("go-engine check"); err != nil {
		t.Errorf("a skew exactly at the bound was refused: %v", err)
	}
}

// Measuring the retained 19 September bytes reproduces the skew the spike recorded.
// This is the cross-implementation check on the assertion itself: the Python capturer
// wrote -689 into the fixture, and the Go capturer measures the same bytes the same
// way. The per-book values -621 and -689 are read from that run document.
func TestMeasureReproducesTheRetainedSkew(t *testing.T) {
	books, records := map[string][]byte{}, map[string][]byte{}
	for _, name := range []string{"binary-no", "bucket0-yes"} {
		book, err := os.ReadFile(filepath.Join(fixtures, name+".json"))
		if err != nil {
			t.Fatal(err)
		}
		record, err := os.ReadFile(filepath.Join(fixtures, name+".request.json"))
		if err != nil {
			t.Fatal(err)
		}
		books[name], records[name] = book, record
	}
	skew, err := Measure(books, records, BookTime, retrievedAtForTest)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]int64{"binary-no": -621, "bucket0-yes": -689}
	for name, expected := range want {
		if skew.Details[name] != expected {
			t.Errorf("%s: measured %d ms, the run recorded %d ms",
				name, skew.Details[name], expected)
		}
	}
	if skew.WorstMs != -689 {
		t.Errorf("worst skew %d, want -689 exactly as recorded", skew.WorstMs)
	}
	assertion, err := skew.Assert("go-engine check")
	if err != nil {
		t.Fatal(err)
	}
	if assertion.SkewMs != "-689" {
		t.Errorf("the assertion says %q, the fixture says -689", assertion.SkewMs)
	}
}

// retrievedAtForTest parses the local retrieval time a request record carries. The
// adapter owns the production reader because parsing an RFC 3339 instant needs a
// clock library that a pure package may not import; this reads the same field with
// the string handling a test can afford.
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

// A cap the unhedged position already meets needs no hedge, and a zero-size leg is
// not a hedge: it is the unhedged position wearing a proposal's clothes.
//
// Found live on 20 September. With quantity 0.1, a baseline of 80247 and a floor of
// 60000, the unhedged worst case is -2024.70. Against a cap of 2100 that already
// passes, so the smallest feasible whole size is 0 -- and the engine built a proposal
// with a zero-size leg, which lowering then refused with SIZE_NOT_WHOLE. The refusal
// was correct and the proposal should never have been built.
func TestACapTheHoldingAlreadyMeetsNeedsNoHedge(t *testing.T) {
	options := spikeOptions(t)
	// Chosen so the unhedged position passes: 0.1 * (60000 - 81520) = -2152.
	options.Cap = mustQ(t, "3000")
	answer, err := Run(loadCapture(t), options, loadRegistry(t))
	if err != nil {
		t.Fatalf("a cap the holding already meets was an error, not an answer: %v", err)
	}
	for _, row := range answer.Rows {
		if row.Sized && row.Size.Sign() <= 0 {
			t.Errorf("%s: sized at %s; a leg of zero contracts is not a hedge",
				row.ID, row.Size)
		}
	}
	// Every leg is left unsized, which here means "no hedge is needed" rather than
	// "no hedge is possible". The window itself still reports 0 as feasible, and it
	// is right to: pwa answers what the arithmetic says, and run decides what is
	// worth proposing.
	for _, row := range answer.Rows {
		if row.Sized {
			t.Errorf("%s: sized at %s against a cap the holding already meets",
				row.ID, row.Size)
		}
		if !row.Window.HasWhole {
			t.Errorf("%s: pwa should still report 0 as feasible here", row.ID)
		}
	}
	if answer.Comparison != nil {
		t.Error("a comparison was made between candidates that were never sized")
	}
}

// The two reasons a row carries no size are opposite answers and must not be
// confused: "no hedge is needed" and "no hedge is possible" would have a reader do
// opposite things.
func TestUnsizedRowsSayWhichReason(t *testing.T) {
	needed := spikeOptions(t)
	needed.Cap = mustQ(t, "3000") // the holding already passes
	answer, err := Run(loadCapture(t), needed, loadRegistry(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, row := range answer.Rows {
		if !row.NotNeeded {
			t.Errorf("%s: not marked as needing no hedge", row.ID)
		}
	}

	// A cap nothing can meet is the other reason, and must not be marked NotNeeded.
	impossible := spikeOptions(t)
	impossible.Cap = mustQ(t, "1")
	answer, err = Run(loadCapture(t), impossible, loadRegistry(t))
	if err != nil {
		t.Fatal(err)
	}
	for _, row := range answer.Rows {
		if row.Sized {
			continue
		}
		if row.NotNeeded {
			t.Errorf("%s: an impossible cap was reported as needing no hedge", row.ID)
		}
	}
}
