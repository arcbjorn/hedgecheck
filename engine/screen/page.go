package screen

import (
	"bytes"
	"fmt"
	"html/template"
	"sort"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
)

// Candidate is one row of the comparison: an instrument, its cost, and its answer.
type Candidate struct {
	ID          string
	Verdict     string
	Size        string
	Premium     exact.Q
	PremiumText string
	WorstCase   string
	Breakevens  []string
	InputDigest string
	Plot        Plot
	// CapY is where the objective's bound sits in the drawing. A chart of a hedge
	// against a bound that does not show the bound leaves the reader to guess the
	// one line they came to see.
	CapY string
	// Sized is false when no size on the displayed book met the objective, and
	// NotNeeded distinguishes the two reasons for that. They are opposite findings.
	Sized     bool
	NotNeeded bool
	// Loose names the reductions the verdict rests on. A loose bound can leave a
	// proposal needing review; it can never fail one.
	Loose []string
}

// Page is everything the screen shows.
type Page struct {
	Underlying    string
	Quantity      string
	CapText       string
	Floor         string
	Ceiling       string
	Baseline      string
	BaselineKind  string
	ValuationTime string
	Observation   string
	Expiry        string

	// Candidates in the order the screen ranks them: by the cost of the smallest
	// size that met the objective. Cheapest first.
	Candidates []Candidate
	// Reduction is the no-premium alternative: sell down until the holding alone
	// meets the bound. It is in the ranking because "buy nothing" is a real option
	// and a comparison that omitted it would flatter every hedge.
	Reduction ReductionRow

	CaptureSkewMs string
	MaxSkewMs     string
	MeasuredBy    string

	// NotChecked is what this answer does NOT establish, taken from the result's own
	// checks_not_performed. It is shown, not hidden behind a link.
	NotChecked []string
	// Unreviewed lists families whose reading is still a draft.
	Unreviewed []string

	// Verifiable is set when the checker is mounted and this result has the bundle
	// parts stored beside it. The page then loads the checker and re-derives the
	// answer in the reader's own browser.
	Verifiable bool
	// CheckDigest is the input digest the browser fetches the bundle under.
	CheckDigest string
}

// ReductionRow is the sell-down alternative.
type ReductionRow struct {
	Sell      string
	Keep      string
	WorstCase string
}

// Ranked orders the candidates by the cost of the smallest passing size, cheapest
// first, and puts the unsized ones last.
func Ranked(candidates []Candidate) []Candidate {
	out := append([]Candidate(nil), candidates...)
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Sized != out[j].Sized {
			return out[i].Sized
		}
		if !out[i].Sized {
			return false
		}
		return out[i].Premium.Less(out[j].Premium)
	})
	return out
}

// Render writes the page. html/template escapes every value, so a venue string that
// arrived as markup is shown as text rather than run as markup.
func Render(page Page) ([]byte, error) {
	buffer := &bytes.Buffer{}
	if err := pageTemplate.Execute(buffer, page); err != nil {
		return nil, fmt.Errorf("screen: %w", err)
	}
	return buffer.Bytes(), nil
}

// FromResult builds a candidate row from a result.
func FromResult(id string, result doc.Result, size string, capPnl exact.Q, hasCap bool) (Candidate, error) {
	plot, err := BuildPlot(result, capPnl, hasCap)
	if err != nil {
		return Candidate{}, err
	}
	row := Candidate{
		ID: id, Verdict: result.ModelResult, Size: size,
		CapY:    plot.CapLine(capPnl),
		Premium: result.Cost.Premium, PremiumText: result.Cost.Premium.DecimalPlaces(2),
		WorstCase:   result.WorstCase.Pnl.DecimalPlaces(2),
		InputDigest: result.InputDigest, Plot: plot, Sized: true,
	}
	for _, breakeven := range result.Cost.Breakevens {
		row.Breakevens = append(row.Breakevens, breakeven.String())
	}
	for _, reduction := range result.Reductions {
		if !reduction.Tight {
			row.Loose = append(row.Loose, reduction.Leg+": "+reduction.Rule)
		}
	}
	sort.Strings(row.Loose)
	return row, nil
}

var pageTemplate = template.Must(template.New("page").Funcs(template.FuncMap{
	"verdictWord": verdictWord,
}).Parse(pageHTML))

// NotCheckedWord turns a result's checks_not_performed code into a sentence.
func NotCheckedWord(code string) string {
	switch code {
	case "LIVE_EXECUTION":
		return "whether these prices can still be traded: the book was read, not acted on"
	case "PATH_RISK":
		return "anything about the path between now and settlement, including margin along the way"
	}
	return code
}

// verdictWord is the one place a verdict becomes English.
func verdictWord(verdict string) string {
	switch verdict {
	case "passes":
		return "meets the stated objective"
	case "fails":
		return "does not meet the stated objective"
	case "needs_review":
		return "not established either way"
	}
	return verdict
}

const pageHTML = `<!DOCTYPE html>
<meta charset="utf-8">
<title>HedgeCheck result</title>
<style>
 :root { color-scheme: light dark; --ink: #16181d; --paper: #fbfbf9; --rule: #d6d4cc;
         --quiet: #62656d; --below: #b03a2e; --above: #1d6f42; }
 @media (prefers-color-scheme: dark) {
   :root { --ink: #e8e6e0; --paper: #16181d; --rule: #343842; --quiet: #9aa0ab;
           --below: #e2725b; --above: #4ea672; } }
 body { background: var(--paper); color: var(--ink); margin: 0 auto; max-width: 56rem;
        padding: 2rem 1rem 4rem; font: 15px/1.55 ui-sans-serif, system-ui, sans-serif; }
 h1 { font-size: 1.25rem; margin: 0 0 .25rem; letter-spacing: -.01em; }
 h2 { font-size: .95rem; margin: 2rem 0 .5rem; letter-spacing: .02em;
      text-transform: uppercase; color: var(--quiet); }
 .asked { color: var(--quiet); margin: 0 0 1.5rem; }
 table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
 th, td { text-align: left; padding: .5rem .75rem .5rem 0; border-bottom: 1px solid var(--rule); }
 th { font-weight: 600; color: var(--quiet); font-size: .85rem; }
 td.n, th.n { text-align: right; padding-right: 1.5rem; }
 .verdict-passes { color: var(--above); }
 /* A REFUSAL IS NOT A LESSER EVENT THAN A FAILING VERDICT. It uses the same
    weight, the same size and the same colour: a checker saying "this result is
    not what it claims" is at least as serious as the result saying "this hedge
    does not meet your objective", and styling it as a footnote would invite a
    reader to skim past the one thing they must not. */
 .check { border: 2px solid var(--rule); border-radius: 4px; padding: .75rem 1rem;
          margin: 1.5rem 0; font-size: 1.05rem; }
 .check-accepted { border-color: var(--above); color: var(--above); }
 .check-refused  { border-color: var(--below); color: var(--below); font-weight: 600; }
 .check-unchecked { border-color: var(--quiet); color: var(--quiet); }
 .check-class { font: 13px/1.4 ui-monospace, monospace; }
 .verdict-fails { color: var(--below); }
 .verdict-needs_review { color: var(--quiet); }
 figure { margin: 1rem 0 2rem; }
 figcaption { color: var(--quiet); font-size: .85rem; margin-top: .4rem; }
 .note { color: var(--quiet); font-size: .9rem; }
 ul { margin: .25rem 0 0; padding-left: 1.1rem; }
 code { font: 13px/1.4 ui-monospace, monospace; word-break: break-all; }
 .digest { color: var(--quiet); font-size: .8rem; }
</style>

<h1>{{.Underlying}} {{.Quantity}} against an objective</h1>
<p class="asked">
 Worst case not below {{.CapText}} for a price anywhere in
 [{{.Floor}}, {{.Ceiling}}], valued at {{.ValuationTime}}.
 Baseline {{.Baseline}} ({{.BaselineKind}}). Contracts expiring {{.Expiry}}.
</p>

<h2>Ranked by the cost of the smallest size that met the objective</h2>
<table>
 <tr><th>instrument</th><th class="n">size</th><th class="n">premium</th>
     <th class="n">worst case</th><th>answer</th></tr>
 {{range .Candidates}}
 <tr>
  <td>{{.ID}}</td>
  {{if .Sized}}
  <td class="n">{{.Size}}</td>
  <td class="n">{{.PremiumText}}</td>
  <td class="n">{{.WorstCase}}</td>
  <td class="verdict-{{.Verdict}}">{{verdictWord .Verdict}}</td>
  {{else}}
  <td class="n">&mdash;</td><td class="n">&mdash;</td><td class="n">&mdash;</td>
  <td class="note">{{if .NotNeeded}}no contracts needed: the holding alone meets the
   objective{{else}}no size on the book that was read met the objective{{end}}</td>
  {{end}}
 </tr>
 {{end}}
 <tr>
  <td>sell down instead</td>
  <td class="n">{{.Reduction.Sell}}</td>
  <td class="n">0.00</td>
  <td class="n">{{.Reduction.WorstCase}}</td>
  <td class="note">keep {{.Reduction.Keep}}, buy nothing</td>
 </tr>
</table>

<div class="check check-unchecked" id="check">
{{if .Verifiable}}
 <strong>Not checked in this browser.</strong>
 This page was served with a checker, but scripts are not running, so nothing here
 has been re-derived. The numbers above are the server&rsquo;s own answer.
{{else}}
 <strong>Not checked in this browser.</strong>
 No checker is mounted for this result.
{{end}}
</div>
{{if .Verifiable}}
<script type="module">
 // Re-derive the result from the bundle, in the reader's own browser.
 //
 // Every part is fetched separately and HASHED HERE. The service says which bytes
 // it holds; this page does not take its word for which bytes those are.
 import { verify } from "/checker.js";

 const digest = {{.CheckDigest}};
 const box = document.getElementById("check");

 const sha256 = async (bytes) => {
   const hash = await crypto.subtle.digest("SHA-256", bytes);
   return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
 };
 const fetchBytes = async (path) => {
   const response = await fetch(path);
   if (!response.ok) throw new Error(path + ": " + response.status);
   return new Uint8Array(await response.arrayBuffer());
 };

 const show = (kind, headline, detail) => {
   box.className = "check check-" + kind;
   box.innerHTML = "";
   const strong = document.createElement("strong");
   strong.textContent = headline;
   box.append(strong);
   if (detail) {
     box.append(" ");
     const span = document.createElement("span");
     span.className = "check-class";
     span.textContent = detail;
     box.append(span);
   }
 };

 try {
   const [result, proposal, lowered] = await Promise.all([
     fetchBytes("/v1/checks/" + digest),
     fetchBytes("/v1/bundle/" + digest + "/proposal"),
     fetchBytes("/v1/bundle/" + digest + "/lowered"),
   ]);

   // The snapshots and registry entries the PROPOSAL cites, read from the parsed
   // document rather than scraped from its text.
   const cited = [];
   const versions = [];
   const document = JSON.parse(new TextDecoder().decode(proposal));
   const source = document.baseline && document.baseline.source;
   if (source && typeof source.snapshot === "string") cited.push(source.snapshot);
   for (const leg of document.legs || []) {
     if (leg.instance && typeof leg.instance.catalogue === "string") {
       cited.push(leg.instance.catalogue);
     }
     if (leg.acquisition && typeof leg.acquisition.snapshot === "string") {
       cited.push(leg.acquisition.snapshot);
     }
     if (typeof leg.semantics_version === "string") versions.push(leg.semantics_version);
   }

   const snapshots = new Map();
   for (const want of new Set(cited)) {
     const bytes = await fetchBytes("/v1/snapshots/" + want);
     const got = await sha256(bytes);
     if (got !== want) throw new Error("a snapshot does not hash to the name it was served under");
     snapshots.set(got, bytes);
   }
   const registry = new Map();
   for (const version of new Set(versions)) {
     const bytes = await fetchBytes("/v1/registry/" + version);
     registry.set(JSON.parse(new TextDecoder().decode(bytes)).family, bytes);
   }

   const outcome = await verify(
     { proposal, lowered, result, manifest: new Uint8Array(), snapshots, registry },
     {},
   );
   if (outcome.accepted) {
     show("accepted", "ACCEPTED.",
       "re-derived in this browser from the proposal and the snapshots it cites");
   } else {
     show("refused", "REFUSED: " + outcome.refusal.class + ".",
       outcome.refusal.at + " " + outcome.refusal.detail);
   }
 } catch (error) {
   // A checker that could not finish has established nothing. It says so rather
   // than leaving the reader with the unchecked notice, which would read as
   // "nobody tried" when in fact something went wrong.
   show("refused", "NOT ESTABLISHED.", String(error && error.message || error));
 }
</script>
{{end}}

{{range .Candidates}}{{if .Sized}}
<h2>{{.ID}}</h2>
<figure>
 <svg viewBox="0 0 {{.Plot.Width}} {{.Plot.Height}}" width="100%"
      role="img" aria-label="Payoff of {{.ID}} across the stated price range">
  <line x1="{{.Plot.Pad}}" y1="{{.Plot.ZeroY}}"
        x2="{{.Plot.Width}}" y2="{{.Plot.ZeroY}}"
        stroke="var(--rule)" stroke-width="1"/>
  <line x1="{{.Plot.Pad}}" y1="{{.CapY}}" x2="{{.Plot.Width}}" y2="{{.CapY}}"
        stroke="var(--below)" stroke-width="1" stroke-dasharray="4 4" opacity="0.7"/>
  <text x="{{.Plot.Pad}}" y="{{.CapY}}" dy="-4" font-size="11"
        fill="var(--below)">cap</text>
  {{range .Plot.Segments}}
  <line x1="{{.X1}}" y1="{{.Y1}}" x2="{{.X2}}" y2="{{.Y2}}"
        stroke="{{if .Below}}var(--below){{else}}var(--above){{end}}"
        stroke-width="2" stroke-linecap="round"/>
  {{end}}
  {{if .Plot.Worst}}
  <circle cx="{{.Plot.Worst.X}}" cy="{{.Plot.Worst.Y}}" r="3" fill="var(--below)"/>
  {{end}}
  {{range .Plot.Ticks}}
  <text x="{{.X}}" y="{{.Y}}" font-size="11" fill="var(--quiet)"
        text-anchor="middle">{{.Label}}</text>
  {{end}}
 </svg>
 <figcaption>
  P&amp;L across [{{.Plot.MinPrice}}, {{.Plot.MaxPrice}}]. The dashed line is the
  stated bound; red is where the payoff is below it. The marked point is the worst
  case, {{.WorstCase}}.
  {{if .Breakevens}}Breakeven at {{range $i, $b := .Breakevens}}{{if $i}}, {{end}}{{$b}}{{end}}.{{end}}
 </figcaption>
</figure>
{{if .Loose}}
<p class="note">This answer rests on bounds that are not tight:</p>
<ul>{{range .Loose}}<li class="note">{{.}}</li>{{end}}</ul>
{{end}}
<p class="digest">input digest <code>{{.InputDigest}}</code></p>
{{end}}{{end}}

<h2>What this does not establish</h2>
<ul>
 {{range .NotChecked}}<li class="note">{{.}}</li>{{end}}
 {{range .Unreviewed}}<li class="note">{{.}} is a draft reading, not a reviewed one</li>{{end}}
 <li class="note">Prices come from one book that was read once. A later book may differ.</li>
 <li class="note">The snapshots were captured {{.CaptureSkewMs}} ms apart at worst,
  which the capturer asserts and no reader can re-derive. The bound was {{.MaxSkewMs}} ms.</li>
</ul>
<p class="note">
 This page answers the objective stated above, on the snapshots named above.
 It is not advice, and it says nothing about any objective other than the one stated.
</p>
<p class="note">
 The check above runs in this browser and re-derives the answer from the proposal
 and the snapshots it cites. It protects against a mistake in the engine that
 computed the result. <strong>It does not protect against a dishonest server</strong>,
 which could serve a dishonest checker alongside a dishonest result. Running your
 own copy is what makes the check yours.
</p>
`
