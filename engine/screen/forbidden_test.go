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
		// Verifiable, so the sample carries the checker's script and the guards
		// below see what a reader with scripts enabled would run.
		Verifiable:  true,
		CheckDigest: strings.Repeat("a", 64),
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

// With scripts disabled the page is fully readable, and it says plainly that the
// result has NOT been checked in this browser.
//
// A page that silently omitted the check would let a reader believe they had seen
// one. The unchecked notice is in the HTML itself, so it is what a reader sees
// unless a script replaces it.
func TestPageWithoutScriptsSaysItIsUnchecked(t *testing.T) {
	page := renderSample(t)
	// Everything outside <script> is what a reader sees with scripts disabled.
	withoutScripts := stripScripts(page)
	for _, required := range []string{
		"Not checked in this browser",
		"the smallest size that met the objective",
		"does not establish",
		"not advice",
	} {
		if !strings.Contains(withoutScripts, required) {
			t.Errorf("without scripts the page never says %q", required)
		}
	}
	// The table and the chart survive: the page is readable, not a stub.
	if !strings.Contains(withoutScripts, "<table>") {
		t.Error("the ranked table is inside a script and vanishes without one")
	}
	if !strings.Contains(withoutScripts, "<svg") {
		t.Error("the payoff chart is inside a script and vanishes without one")
	}
}

func stripScripts(page string) string {
	out := page
	for {
		start := strings.Index(out, "<script")
		if start < 0 {
			return out
		}
		end := strings.Index(out[start:], "</script>")
		if end < 0 {
			return out[:start]
		}
		out = out[:start] + out[start+end+len("</script>"):]
	}
}

// A REFUSAL IS NEVER STYLED AS A LESSER EVENT THAN A FAILING VERDICT.
//
// A checker saying "this result is not what it claims" is at least as serious as a
// result saying "this hedge does not meet your objective". If the refusal were
// smaller, lighter or quieter, a reader would skim past the one thing they must not.
func TestARefusalIsNotStyledMoreQuietlyThanAFailure(t *testing.T) {
	page := renderSample(t)
	rules := styleRules(page)

	refused, ok := rules[".check-refused"]
	if !ok {
		t.Fatal("the page has no style for a refusal")
	}
	failure, ok := rules[".verdict-fails"]
	if !ok {
		t.Fatal("the page has no style for a failing verdict")
	}
	// Both use the same colour: a refusal is not a milder shade.
	if !strings.Contains(refused, "var(--below)") || !strings.Contains(failure, "var(--below)") {
		t.Errorf("a refusal and a failure use different colours: %q vs %q", refused, failure)
	}
	// The refusal is not made quieter.
	for _, quiet := range []string{"var(--quiet)", "opacity", "font-size: .8", "font-size: .9"} {
		if strings.Contains(refused, quiet) {
			t.Errorf("the refusal style contains %q, which makes it quieter than a failure", quiet)
		}
	}
	// And the block it sits in is not smaller than the body text.
	block, ok := rules[".check"]
	if !ok {
		t.Fatal("the page has no style for the check block")
	}
	if strings.Contains(block, "font-size: .") {
		t.Errorf("the check block is smaller than the body text: %q", block)
	}
}

// styleRules maps a selector to its declarations, for the one stylesheet the page
// carries inline.
func styleRules(page string) map[string]string {
	out := map[string]string{}
	start := strings.Index(page, "<style>")
	end := strings.Index(page, "</style>")
	if start < 0 || end < 0 {
		return out
	}
	for _, rule := range strings.Split(page[start+len("<style>"):end], "}") {
		brace := strings.Index(rule, "{")
		if brace < 0 {
			continue
		}
		for _, selector := range strings.Split(rule[:brace], ",") {
			out[strings.TrimSpace(selector)] = rule[brace+1:]
		}
	}
	return out
}

// The page's inline script PLANS FETCHES. It never decides anything.
//
// The script uses JSON.parse to read which snapshots a proposal cites, which is safe
// because the answer does not depend on it: every fetched snapshot is hashed in the
// page, and verify() re-parses the proposal with the strict canonical reader and
// looks up snapshots by the digest IT read. A proposal with duplicate keys would at
// worst make the page over-fetch, and would then be refused by verify().
//
// That reasoning holds only while the script confines itself to planning. This guard
// holds it there: the page may not compare numbers, judge a verdict, or reach a
// conclusion of its own. The one authority on accept-or-refuse is the checker module.
func TestThePageScriptDecidesNothing(t *testing.T) {
	page := renderSample(t)
	script := scriptsOf(page)
	if !strings.Contains(script, "verify(") {
		t.Fatal("the script does not call verify; the test is not looking where it should")
	}

	// Vocabulary that would mean the page had formed its own opinion.
	banned := []struct {
		pattern *regexp.Regexp
		why     string
	}{
		{regexp.MustCompile(`\bmodel_result\b`), "reading the verdict means judging it"},
		{regexp.MustCompile(`\bworst_case\b`), "the page does not compare the engine's numbers"},
		{regexp.MustCompile(`"passes"|'passes'`), "a verdict literal is a decision"},
		{regexp.MustCompile(`"fails"|'fails'`), "a verdict literal is a decision"},
		{regexp.MustCompile(`\bBigInt\b`), "arithmetic in the page is arithmetic outside the checker"},
		{regexp.MustCompile(`\bparseFloat\b|\bNumber\(`), "a quantity must never become a JavaScript number"},
	}
	for _, entry := range banned {
		if found := entry.pattern.FindString(script); found != "" {
			t.Errorf("the page script contains %q: %s", found, entry.why)
		}
	}

	// And the accept-or-refuse branch reads the CHECKER's outcome, not its own.
	if !strings.Contains(script, "outcome.accepted") {
		t.Error("the script does not branch on the checker's outcome")
	}
	if !strings.Contains(script, "outcome.refusal.class") {
		t.Error("the script does not report the checker's refusal class")
	}
}

// A snapshot the page fetched is hashed BY THE PAGE before it is believed.
//
// The service says which bytes it holds under a name. The page does not take its
// word for that: it hashes what arrived and compares. Without this, a server could
// serve any bytes under any hash and the check would proceed on them.
func TestThePageHashesWhatItFetched(t *testing.T) {
	script := scriptsOf(renderSample(t))
	if !strings.Contains(script, `crypto.subtle.digest("SHA-256"`) {
		t.Error("the page does not hash anything it fetched")
	}
	if !strings.Contains(script, "does not hash to the name it was served under") {
		t.Error("the page does not refuse a snapshot whose bytes do not match its name")
	}
}

func scriptsOf(page string) string {
	var out strings.Builder
	rest := page
	for {
		start := strings.Index(rest, "<script")
		if start < 0 {
			return out.String()
		}
		open := strings.Index(rest[start:], ">")
		end := strings.Index(rest[start:], "</script>")
		if open < 0 || end < 0 {
			return out.String()
		}
		out.WriteString(rest[start+open+1 : start+end])
		rest = rest[start+end+len("</script>"):]
	}
}
