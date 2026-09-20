package run

import (
	"os"
	"path/filepath"
	"testing"

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
