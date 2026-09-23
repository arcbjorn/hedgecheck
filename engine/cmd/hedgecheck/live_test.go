package main

import (
	"os"
	"strings"
	"testing"
)

// invokeLive runs the CLI's argument parsing without any network: parseLiveOptions
// is reached before anything is fetched, so the whole of the validation can be
// checked offline.
func parseFor(t *testing.T, flags options) (liveOptions, bool, string) {
	t.Helper()
	errFile, err := os.CreateTemp(t.TempDir(), "err-*")
	if err != nil {
		t.Fatal(err)
	}
	settings, ok := parseLiveOptions(flags, errFile)
	errFile.Close()
	raw, _ := os.ReadFile(errFile.Name())
	return settings, ok, string(raw)
}

func validFlags() options {
	return options{
		underlying: "BTC", quantity: "0.1", capAmount: "1000",
		floor: "60000", ceiling: "110000", baseline: "analysis_time",
		valuationTime: "2026-09-21T06:00:00Z",
	}
}

// A valuation time must be a UTC instant, or the sentinel that asks for the
// contract's own.
//
// Found live on 20 September: "next-expiry" was passed straight through into the
// stored result's objective_valuation_time, where the schema requires an instant
// ending in Z. The document readers check that pattern on the way IN, so an engine
// that builds a document and writes it without reading it back never meets the
// check. The CLI therefore checks it here, before anything is built.
func TestValuationTimeMustBeAnInstant(t *testing.T) {
	bad := []string{
		"next expiry", "tomorrow", "2026-09-21", "2026-09-21T06:00:00",
		"2026-09-21T06:00:00+02:00", "2026-09-21t06:00:00z", "",
	}
	for _, value := range bad {
		flags := validFlags()
		flags.valuationTime = value
		_, ok, stderr := parseFor(t, flags)
		if ok {
			t.Errorf("--valuation-time %q was accepted", value)
		}
		if value != "" && !strings.Contains(stderr, "UTC instant") {
			t.Errorf("%q: the message does not say what is wanted: %s", value, stderr)
		}
	}

	good := []string{"2026-09-21T06:00:00Z", NextExpiry}
	for _, value := range good {
		flags := validFlags()
		flags.valuationTime = value
		if _, ok, stderr := parseFor(t, flags); !ok {
			t.Errorf("--valuation-time %q was refused: %s", value, stderr)
		}
	}
}

// The sentinel is a request, not a time. It must never be carried into a document,
// so it is resolved after discovery and the raw option is not what gets recorded.
func TestNextExpiryIsResolvedNotCarried(t *testing.T) {
	flags := validFlags()
	flags.valuationTime = NextExpiry
	settings, ok, stderr := parseFor(t, flags)
	if !ok {
		t.Fatalf("the sentinel was refused: %s", stderr)
	}
	if settings.valuationTime != NextExpiry {
		t.Fatalf("parsing changed the sentinel to %q", settings.valuationTime)
	}
	// commandCheckLive maps the sentinel to "", which run.Run reads as "use the
	// contract's own observation time". Asserting the mapping here keeps the two
	// halves of that contract in one place.
	valuation := settings.valuationTime
	if valuation == NextExpiry {
		valuation = ""
	}
	if valuation != "" {
		t.Errorf("the sentinel resolved to %q, want the empty string run.Run expects", valuation)
	}
}

// Each option that decides what the answer MEANS is required, with no default.
func TestLiveOptionsHaveNoDefaults(t *testing.T) {
	required := map[string]func(*options){
		"--underlying":     func(o *options) { o.underlying = "" },
		"--quantity":       func(o *options) { o.quantity = "" },
		"--cap":            func(o *options) { o.capAmount = "" },
		"--floor":          func(o *options) { o.floor = "" },
		"--ceiling":        func(o *options) { o.ceiling = "" },
		"--baseline":       func(o *options) { o.baseline = "" },
		"--valuation-time": func(o *options) { o.valuationTime = "" },
	}
	for name, clear := range required {
		flags := validFlags()
		clear(&flags)
		_, ok, stderr := parseFor(t, flags)
		if ok {
			t.Errorf("%s was defaulted rather than required", name)
		}
		if !strings.Contains(stderr, name) {
			t.Errorf("%s: the message does not name it: %s", name, stderr)
		}
	}
}

// A baseline is read from the capture or given explicitly. Nothing else, because a
// guessed baseline would make every comparison meaningless.
func TestBaselineIsAnalysisTimeOrExplicit(t *testing.T) {
	flags := validFlags()
	flags.baseline = "explicit:80315.5"
	settings, ok, stderr := parseFor(t, flags)
	if !ok {
		t.Fatalf("an explicit baseline was refused: %s", stderr)
	}
	if settings.baselineKind != "explicit" || settings.baselinePrice.String() != "80315.5" {
		t.Errorf("explicit baseline read as %s %s", settings.baselineKind, settings.baselinePrice)
	}

	for _, value := range []string{"guess", "mark", "explicit:", "explicit:abc", "80315"} {
		flags := validFlags()
		flags.baseline = value
		if _, ok, _ := parseFor(t, flags); ok {
			t.Errorf("--baseline %q was accepted", value)
		}
	}
}

// Every number is read in the exact grammar, never through a float. Scientific
// notation and hex are refused; "p/q" is NOT, because a ratio in lowest terms is part
// of the canonical grammar -- the retained runs carry sizes like "25/538".
func TestLiveNumbersAreExact(t *testing.T) {
	for _, value := range []string{"abc", "1e5", "1E5", "0x10", "", " 1", "1 ", "1.0.0", "--1", "NaN", "Infinity"} {
		flags := validFlags()
		flags.quantity = value
		if _, ok, _ := parseFor(t, flags); ok {
			t.Errorf("--quantity %q was accepted", value)
		}
	}
	for _, value := range []string{"0.1", "1/2", "25/538", "1000"} {
		flags := validFlags()
		flags.quantity = value
		if _, ok, stderr := parseFor(t, flags); !ok {
			t.Errorf("--quantity %q was refused: %s", value, stderr)
		}
	}
}

// A NEGATIVE --cap IS REFUSED, because accepting one produced a wrong answer silently.
//
// Found 23 September, on live mainnet data. `smallestReduction` computes keep = -cap/span and
// its caller in run.go already passes `cap.Neg()`, so the two negations cancel for a POSITIVE
// cap and compound for a negative one: `--cap -2000` gave a negative keep, a sell-down row of
// 0.182 BTC against a 0.1 holding -- selling more than is held -- and a worst case printed as
// +2000 where a loss cap is -2000.
//
// Every existing test passed throughout, because every one of them supplies a positive cap
// (this file's own validFlags uses "1000"), so the double negation cancels in the tests and
// only bites a real caller. The schema's min_pnl is negative and this flag is positive, which
// is exactly the confusion that produced it.
func TestRefusesANegativeOrZeroCap(t *testing.T) {
	for _, bad := range []string{"-2000", "-0.01", "0"} {
		flags := validFlags()
		flags.capAmount = bad
		_, ok, message := parseFor(t, flags)
		if ok {
			t.Fatalf("--cap %s was accepted; a negative cap double-negates into a negative keep", bad)
		}
		if !strings.Contains(message, "--cap") {
			t.Errorf("--cap %s refused without naming the flag: %q", bad, message)
		}
	}
	// And the positive form still works, so the rule refuses the wrong input rather than every
	// input -- the failure mode a sign check invites.
	if _, ok, message := parseFor(t, validFlags()); !ok {
		t.Fatalf("a positive --cap was refused: %q", message)
	}
}
