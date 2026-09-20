package screen

import (
	"regexp"
	"strings"
	"testing"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
)

// The screen answers a stated objective. It is not advice, and it does not promise.
//
// PLAN.md §3: "It answers a stated objective; it is not advice." and "Never call a
// window executable." This test holds the rendered page to that, because the failure
// it guards against is not a crash: a page that reads like a recommendation is a page
// someone acts on, and every word here is a word this tool has no standing to say.
//
// Each entry names WHY it is forbidden, so a future reader can tell a banned word
// from an unlucky one and argue with the reason rather than the list.
var forbiddenWords = []struct {
	pattern *regexp.Regexp
	why     string
}{
	// Advice. The tool evaluates; the person decides.
	{regexp.MustCompile(`(?i)\brecommend(s|ed|ation)?\b`), "a recommendation is advice"},
	{regexp.MustCompile(`(?i)\bshould buy\b`), "telling someone to buy is advice"},
	{regexp.MustCompile(`(?i)\byou should\b`), "telling someone what to do is advice"},
	{regexp.MustCompile(`(?i)\bwe suggest\b`), "a suggestion is advice"},
	{regexp.MustCompile(`(?i)\bbest (choice|option|hedge|trade)\b`), "ranking by cost is not a judgement about what is best"},
	{regexp.MustCompile(`(?i)\boptimal\b`), "the cheapest size that met one objective is not optimal in general"},
	// "advice" is allowed only in the sentence disclaiming it. RE2 has no lookahead,
	// so the exception is a separate check below rather than a clause in the pattern.

	// Promises. Nothing here is guaranteed, and a book read once is not a fill.
	{regexp.MustCompile(`(?i)\bguarantee(s|d)?\b`), "nothing is guaranteed: the answer is about one snapshot"},
	{regexp.MustCompile(`(?i)\brisk[- ]free\b`), "no position here is risk-free"},
	{regexp.MustCompile(`(?i)\bsafe\b`), "safety is a judgement the objective does not contain"},
	{regexp.MustCompile(`(?i)\bprofit(able)?\b`), "the page reports P&L on a domain, not a profit"},
	{regexp.MustCompile(`(?i)\bwill (earn|pay|make|return)\b`), "a future tense claims something not established"},

	// Execution. A size window is priced, never executable.
	{regexp.MustCompile(`(?i)\bexecutable\b`), "PLAN.md: never call a window executable"},
	{regexp.MustCompile(`(?i)\bfill(ed|s)? at\b`), "the book was read, not traded against"},
	{regexp.MustCompile(`(?i)\bguaranteed fill\b`), "displayed depth is not a fill"},
	{regexp.MustCompile(`(?i)\bexecute(s|d)? (this|the) (trade|order)\b`), "this tool places no orders"},

	// Certainty the evaluation does not have.
	{regexp.MustCompile(`(?i)\bproven\b`), "a verdict on one snapshot is not a proof about the world"},
	{regexp.MustCompile(`(?i)\bcertain(ly)?\b`), "certainty is not what a bound on a domain gives"},
	{regexp.MustCompile(`(?i)\bno risk\b`), "the page states a worst case, which is a risk"},
}

// renderSample builds a page with every branch populated, so the test sees the words
// the template can actually produce rather than only its skeleton.
func renderSample(t *testing.T) string {
	t.Helper()
	q := func(text string) exact.Q {
		t.Helper()
		value, err := exact.ParseQ(text)
		if err != nil {
			t.Fatal(err)
		}
		return value
	}
	result := doc.Result{
		SchemaVersion: "1", ModelResult: "needs_review",
		Profile: []doc.Piece{
			{Interval: doc.Interval{Lower: q("60000"), Upper: q("80000"), LowerIncl: true},
				Slope: q("0.1"), Intercept: q("-8000")},
			{Interval: doc.Interval{Lower: q("80000"), Upper: q("110000"), UpperIncl: true},
				Slope: q("0.1"), Intercept: q("-9000")},
		},
		WorstCase: doc.NewWorstCase(q("-2000"), q("60000"), true),
		Cost: doc.CostSummary{
			Premium: q("488.69285"), OtherCosts: q("0"), PnlAtBaseline: q("-488.69285"),
			Breakevens: []exact.Q{q("86406.9285")},
		},
		Reductions: []doc.Reduction{
			{Leg: "binary-no", Rule: "unreviewed_family", Tight: false, ReasonCode: "UNREVIEWED_FAMILY"},
		},
		InputDigest: strings.Repeat("a", 64),
	}
	sized, err := FromResult("binary-no", result, "1409", q("-1000"), true)
	if err != nil {
		t.Fatal(err)
	}
	page := Page{
		Underlying: "BTC", Quantity: "0.1", CapText: "-1000",
		Floor: "60000", Ceiling: "110000", Baseline: "81520",
		BaselineKind: "analysis_time", ValuationTime: "2026-09-21T06:00:00Z",
		Expiry: "20260921-0600",
		Candidates: []Candidate{
			sized,
			{ID: "bucket0-yes", Sized: false},
			{ID: "other", Sized: false, NotNeeded: true},
		},
		Reduction:     ReductionRow{Sell: "72/1345", Keep: "25/538", WorstCase: "-1000.00"},
		CaptureSkewMs: "-689", MaxSkewMs: "5000", MeasuredBy: "go-engine check --live",
		NotChecked: []string{
			"settlement mechanics beyond the stated reading",
			"whether the venue will quote these prices again",
		},
		Unreviewed: []string{"recurring.priceBinary"},
	}
	rendered, err := Render(page)
	if err != nil {
		t.Fatal(err)
	}
	return string(rendered)
}

func TestPageSaysNothingItCannotStandBehind(t *testing.T) {
	page := renderSample(t)
	for _, banned := range forbiddenWords {
		if found := banned.pattern.FindString(page); found != "" {
			t.Errorf("the page says %q: %s", found, banned.why)
		}
	}

	// The word "advice" may appear only where the page disclaims giving any. Every
	// other use would be the page describing itself as something it is not.
	allowed := regexp.MustCompile(`(?i)\bit is not advice\b`)
	uses := regexp.MustCompile(`(?i)\badvice\b`).FindAllStringIndex(page, -1)
	disclaimers := allowed.FindAllStringIndex(page, -1)
	if len(uses) != len(disclaimers) {
		t.Errorf("the page uses \"advice\" %d times but disclaims it %d times; "+
			"the only permitted use is \"it is not advice\"", len(uses), len(disclaimers))
	}
	if len(disclaimers) == 0 {
		t.Error("the page never says it is not advice")
	}
}

// The verdict wording is checked directly, because it is the sentence a reader acts
// on and the one most likely to be softened later.
func TestVerdictWordingStatesOnlyWhatWasEstablished(t *testing.T) {
	cases := map[string]string{
		"passes":       "meets the stated objective",
		"fails":        "does not meet the stated objective",
		"needs_review": "not established either way",
	}
	for verdict, want := range cases {
		if got := verdictWord(verdict); got != want {
			t.Errorf("%s reads %q, want %q", verdict, got, want)
		}
	}
	// "needs review" must not read as a weaker "fails": they are different findings.
	if strings.Contains(verdictWord("needs_review"), "not meet") {
		t.Error("needs_review reads as a failure; it establishes nothing either way")
	}
	for _, banned := range forbiddenWords {
		for verdict := range cases {
			if found := banned.pattern.FindString(verdictWord(verdict)); found != "" {
				t.Errorf("the %s wording says %q: %s", verdict, found, banned.why)
			}
		}
	}
}

// The page states what it does NOT establish, and does so on the page rather than
// behind a link. An honest answer that hides its limits is not an honest answer.
func TestPageStatesWhatItDoesNotEstablish(t *testing.T) {
	page := renderSample(t)
	for _, required := range []string{
		"does not establish",
		"not advice",
		"one book that was read once",
		"draft reading",
		"not tight",
	} {
		if !strings.Contains(strings.ToLower(page), strings.ToLower(required)) {
			t.Errorf("the page never says %q", required)
		}
	}
	// Every checks_not_performed entry the result carried reaches the page.
	for _, entry := range []string{
		"settlement mechanics beyond the stated reading",
		"whether the venue will quote these prices again",
	} {
		if !strings.Contains(page, entry) {
			t.Errorf("the page drops the limitation %q", entry)
		}
	}
}

// A venue string that arrives as markup is shown as text. The catalogue is untrusted
// input and reaches the page through an instrument id.
func TestPageEscapesUntrustedText(t *testing.T) {
	page := Page{
		Underlying: `<script>alert(1)</script>`,
		Candidates: []Candidate{{ID: `"><img src=x onerror=alert(1)>`, Sized: false}},
	}
	rendered, err := Render(page)
	if err != nil {
		t.Fatal(err)
	}
	text := string(rendered)
	if strings.Contains(text, "<script>alert(1)</script>") {
		t.Error("a script tag from the venue reached the page unescaped")
	}
	// The payload survives as TEXT, which is correct and safe: what must not survive
	// is the markup around it. An unescaped `<img` would open a tag; `&lt;img` is a
	// string a reader sees.
	if strings.Contains(text, "<img") {
		t.Error("an img tag from an instrument id reached the page as markup")
	}
	if strings.Contains(text, `"><img`) {
		t.Error("an attribute break from an instrument id reached the page")
	}
	if !strings.Contains(text, "&lt;img") {
		t.Error("the escaped img is not present either; the value vanished silently")
	}
	if !strings.Contains(text, "&lt;script&gt;") {
		t.Error("the escaped form is not present either; the value vanished silently")
	}
}

// Every code in the closed checks_not_performed vocabulary becomes a sentence, and
// the sentences obey the same language rules as the rest of the page.
func TestNotCheckedCodesBecomeEnglish(t *testing.T) {
	for _, code := range []string{"LIVE_EXECUTION", "PATH_RISK"} {
		word := NotCheckedWord(code)
		if word == code {
			t.Errorf("%s is shown as a code; a reader cannot act on that", code)
		}
		if !strings.Contains(word, " ") {
			t.Errorf("%s became %q, which is not a sentence", code, word)
		}
		for _, banned := range forbiddenWords {
			if found := banned.pattern.FindString(word); found != "" {
				t.Errorf("the %s wording says %q: %s", code, found, banned.why)
			}
		}
	}
	// An unrecognised code is shown as itself, never dropped: a limitation this page
	// does not know about is still a limitation.
	if NotCheckedWord("SOMETHING_NEW") != "SOMETHING_NEW" {
		t.Error("an unknown code was not passed through, so it would vanish from the page")
	}
}
