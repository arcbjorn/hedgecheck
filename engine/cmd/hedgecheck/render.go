package main

import (
	"fmt"
	"os"

	"hedgecheck/engine/doc"
	runner "hedgecheck/engine/run"
	"hedgecheck/engine/screen"
	"hedgecheck/engine/store"
)

// commandRender writes the result screen for a stored run.
//
// It reads a run document and renders it. Nothing is recomputed: the page shows what
// was stored, so what a reader sees is what was filed under that input digest and not
// a fresh answer that happens to look similar.
func commandRender(flags options, out, errOut *os.File) int {
	if flags.inputDigest == "" || flags.store == "" {
		fmt.Fprintln(errOut, "render needs --input-digest and --store")
		return exitUsage
	}
	keep := store.New(flags.store)
	raw, err := keep.Run(flags.inputDigest)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	document, err := runner.Decode(raw)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	page, err := pageFor(document)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	rendered, err := screen.Render(page)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	if flags.out != "" {
		if err := os.WriteFile(flags.out, rendered, 0o644); err != nil {
			fmt.Fprintln(errOut, err)
			return exitUsage
		}
		fmt.Fprintf(out, "wrote %s\n", flags.out)
		return exitPasses
	}
	out.Write(rendered)
	return exitPasses
}

// pageFor turns a run document into the view the screen renders.
func pageFor(document runner.Document) (screen.Page, error) {
	page := screen.Page{
		Underlying: document.Options.Underlying, Quantity: document.Options.Quantity,
		Floor: document.Options.Floor, Ceiling: document.Options.Ceiling,
		Baseline: document.Options.Baseline, BaselineKind: document.Options.BaselineKind,
		ValuationTime: document.Valuation, Observation: document.Observation,
		Expiry: document.Expiry,
	}
	if document.Capture != nil {
		page.CaptureSkewMs = document.Capture.SkewMs
		page.MaxSkewMs = document.Capture.MaxSkewMs
		page.MeasuredBy = document.Capture.MeasuredBy
	}

	// The cap is stated as a positive amount and held as a floor on P&L.
	capPnl, err := exactOf(document.Options.Cap)
	if err != nil {
		return screen.Page{}, err
	}
	capPnl = capPnl.Neg()
	page.CapText = capPnl.DecimalPlaces(2)

	notChecked := map[string]bool{}
	unreviewed := map[string]bool{}
	for _, id := range sortedResultIDs(document.Results) {
		result := document.Results[id]
		candidate, err := screen.FromResult(id, result, document.Sizes[id], capPnl, true)
		if err != nil {
			return screen.Page{}, err
		}
		page.Candidates = append(page.Candidates, candidate)
		for _, entry := range result.ChecksNotPerformed {
			notChecked[screen.NotCheckedWord(entry)] = true
		}
		for _, reduction := range result.Reductions {
			if reduction.Rule == "unreviewed_family" {
				unreviewed[reduction.Leg] = true
			}
		}
	}
	// The sell-down alternative is read from a result's own comparison, where the
	// engine already computed it. Recomputing it here would be a second opinion the
	// page has no way to reconcile with the one it is displaying.
	for _, id := range sortedResultIDs(document.Results) {
		reduction := document.Results[id].Comparisons.SmallestReduction
		page.Reduction = screen.ReductionRow{
			Sell: reduction.SellQuantity.String(), Keep: reduction.KeepQuantity.String(),
			WorstCase: reduction.WorstCase.Pnl.DecimalPlaces(2),
		}
		break
	}
	page.Candidates = screen.Ranked(page.Candidates)
	page.NotChecked = sortedSet(notChecked)
	page.Unreviewed = sortedSet(unreviewed)
	return page, nil
}

func sortedResultIDs(results map[string]doc.Result) []string {
	out := make([]string, 0, len(results))
	for id := range results {
		out = append(out, id)
	}
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j] < out[j-1]; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}

func sortedSet(values map[string]bool) []string {
	out := make([]string, 0, len(values))
	for value := range values {
		out = append(out, value)
	}
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j] < out[j-1]; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}
