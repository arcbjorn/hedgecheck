package main

import (
	"fmt"
	"os"
	"regexp"

	"hedgecheck/engine/adapter/hyperliquid"
	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
	runner "hedgecheck/engine/run"
	"hedgecheck/engine/store"
)

// The live path. This file and the adapter are the only places that reach the venue,
// and the arch test holds that.
//
// Read-only: one endpoint, three request types, one request per 1.5 s, at most 40 per
// run. Nothing here signs, trades, or touches a key.

// venueClient adapts the hyperliquid client to the Venue interface the capture uses.
// The interface exists so the capture SEQUENCE is testable offline; this is the one
// implementation that actually fetches.
type venueClient struct{ client *hyperliquid.Client }

func (v venueClient) Catalogue() (Retrieved, error) { return convert(v.client.Catalogue()) }
func (v venueClient) Contexts() (Retrieved, error)  { return convert(v.client.Contexts()) }
func (v venueClient) Book(coin string) (Retrieved, error) {
	return convert(v.client.Book(coin))
}
func (v venueClient) Spent() int { return v.client.Spent() }

func convert(response hyperliquid.Response, err error) (Retrieved, error) {
	if err != nil {
		return Retrieved{}, err
	}
	return Retrieved{Digest: response.Digest, Raw: response.Raw, Record: response.Record}, nil
}

// valuationTimePattern is the grammar a contract document requires: a UTC instant
// ending in Z. The CLI checks it HERE, before anything is built, because the
// document readers only check on the way IN -- an engine that builds a document and
// writes it without reading it back never passes through that check.
var valuationTimePattern = regexp.MustCompile(`\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\z`)

// NextExpiry asks for the contract's own expiry instant, which is only known once the
// catalogue has been fetched. It is resolved after discovery, never carried into a
// document: "next-expiry" is a request, not a time.
const NextExpiry = "next-expiry"

// liveOptions are the question a live check answers. None of them has a default:
// each decides what the answer MEANS, and a default would be this tool choosing the
// meaning on the operator's behalf.
type liveOptions struct {
	underlying    string
	quantity      exact.Q
	cap           exact.Q
	floor         exact.Q
	ceiling       exact.Q
	baselineKind  string
	baselinePrice exact.Q
	valuationTime string
}

func parseLiveOptions(flags options, errOut *os.File) (liveOptions, bool) {
	out := liveOptions{underlying: flags.underlying, valuationTime: flags.valuationTime}
	missing := []string{}
	if flags.underlying == "" {
		missing = append(missing, "--underlying")
	}
	if flags.quantity == "" {
		missing = append(missing, "--quantity")
	}
	if flags.capAmount == "" {
		missing = append(missing, "--cap")
	}
	if flags.floor == "" {
		missing = append(missing, "--floor")
	}
	if flags.ceiling == "" {
		missing = append(missing, "--ceiling")
	}
	if flags.baseline == "" {
		missing = append(missing, "--baseline")
	}
	if flags.valuationTime == "" {
		missing = append(missing, "--valuation-time")
	}
	if len(missing) > 0 {
		fmt.Fprintf(errOut, "check --live needs %v\n", missing)
		fmt.Fprintln(errOut, "none of these has a default: each decides what the answer means")
		return out, false
	}

	var err error
	for _, field := range []struct {
		text  string
		into  *exact.Q
		named string
	}{
		{flags.quantity, &out.quantity, "--quantity"},
		{flags.capAmount, &out.cap, "--cap"},
		{flags.floor, &out.floor, "--floor"},
		{flags.ceiling, &out.ceiling, "--ceiling"},
	} {
		if *field.into, err = exact.ParseQ(field.text); err != nil {
			fmt.Fprintf(errOut, "%s %q is not in the number grammar\n", field.named, field.text)
			return out, false
		}
	}

	if flags.valuationTime != NextExpiry && !valuationTimePattern.MatchString(flags.valuationTime) {
		fmt.Fprintf(errOut, "--valuation-time %q is not a UTC instant like 2026-09-21T06:00:00Z, nor %s\n",
			flags.valuationTime, NextExpiry)
		return out, false
	}

	// analysis_time reads the mark from the captured contexts; explicit:<price> is
	// the operator's own number. Nothing else is accepted, because a baseline that
	// was guessed at would make every comparison meaningless.
	switch {
	case flags.baseline == "analysis_time":
		out.baselineKind = "analysis_time"
	case len(flags.baseline) > 9 && flags.baseline[:9] == "explicit:":
		out.baselineKind = "explicit"
		if out.baselinePrice, err = exact.ParseQ(flags.baseline[9:]); err != nil {
			fmt.Fprintf(errOut, "--baseline explicit:%s is not a number\n", flags.baseline[9:])
			return out, false
		}
	default:
		fmt.Fprintln(errOut, "--baseline is analysis_time or explicit:<price>")
		return out, false
	}
	return out, true
}

func commandCheckLive(flags options, out, errOut *os.File) int {
	if flags.store == "" || flags.registry == "" {
		fmt.Fprintln(errOut, "check --live needs --store and --registry")
		return exitUsage
	}
	settings, ok := parseLiveOptions(flags, errOut)
	if !ok {
		return exitUsage
	}
	registry, err := loadRegistry(flags.registry, flags.reviewed)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}

	keep := store.New(flags.store)
	client := hyperliquid.NewClient()
	fmt.Fprintf(out, "capturing from %s, at most %d requests, one per %v\n",
		hyperliquid.Endpoint, hyperliquid.Budget, hyperliquid.Pace)

	captured, err := CaptureLive(venueClient{client}, keep, settings.underlying,
		hyperliquid.RetrievedAt)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	fmt.Fprintf(out, "captured %d snapshots in %d requests, expiry %s\n",
		len(captured.Capture.BookDigests)+2, captured.Requests, captured.Expiry)
	for _, name := range sortedKeys(captured.Skew.Details) {
		fmt.Fprintf(out, "  skew %s: book venue - local retrieval = %d ms\n",
			name, captured.Skew.Details[name])
	}

	// The capture asserts what it measured, and refuses a set too spread out to be
	// treated as one moment. A refusal here is not a verdict: nothing was evaluated.
	assertion, err := captured.Skew.Assert("go-engine check --live")
	if err != nil {
		fmt.Fprintf(errOut, "refused: %v\n", err)
		return exitRefused
	}
	fmt.Fprintf(out, "capture skew %s ms, within the %s ms bound\n",
		assertion.SkewMs, assertion.MaxSkewMs)

	// "next-expiry" is a request for the contract's own instant, which is only known
	// now that the catalogue has been read. Resolving it here means no document ever
	// carries the sentinel.
	valuation := settings.valuationTime
	if valuation == NextExpiry {
		valuation = ""
	}

	answer, err := runner.Run(captured.Capture, runner.Options{
		Underlying:    settings.underlying,
		Quantity:      settings.quantity,
		Cap:           settings.cap,
		Floor:         settings.floor,
		Ceiling:       settings.ceiling,
		BaselineKind:  settings.baselineKind,
		BaselinePrice: settings.baselinePrice,
		ValuationTime: valuation,
		Capture:       assertion,
	}, registry)
	if err != nil {
		return refusalExit(err, errOut)
	}

	fmt.Fprintf(out, "baseline %s (%s)\n", answer.Baseline, settings.baselineKind)
	fmt.Fprintf(out, "valuation time %s\n", answer.ValuationTime)
	printAnswer(out, answer)

	document := buildRunDocument(captured, answer, settings, assertion)
	worst := exitPasses
	for _, row := range answer.Rows {
		if !row.Sized {
			continue
		}
		perLeg := document
		perLeg.Leg = row.ID
		encoded, err := runner.Encode(perLeg)
		if err != nil {
			fmt.Fprintln(errOut, err)
			return exitUsage
		}
		if err := keep.PutRun(row.InputDigest, append(encoded, '\n')); err != nil {
			fmt.Fprintln(errOut, err)
			return exitUsage
		}
		resultBytes, err := doc.WriteResult(row.Result)
		if err != nil {
			fmt.Fprintln(errOut, err)
			return exitUsage
		}
		if err := keep.PutResult(row.InputDigest, string(row.Result.EngineVersion), resultBytes); err != nil {
			fmt.Fprintln(errOut, err)
			return exitUsage
		}
		fmt.Fprintf(out, "%s: input_digest %s\n", row.ID, row.InputDigest)
		if status := verdictExit(row.Result); status > worst {
			worst = status
		}
	}
	return worst
}

// buildRunDocument assembles what a replay needs and nothing it would have to fetch.
func buildRunDocument(captured Captured, answer runner.Answer, settings liveOptions,
	assertion *doc.Capture) runner.Document {
	digests := map[string]string{
		"catalogue": captured.Capture.CatalogueDigest,
		"contexts":  captured.Capture.ContextsDigest,
	}
	for name, digest := range captured.Capture.BookDigests {
		digests[name] = digest
	}
	skew := map[string]runner.SkewDetail{}
	for name, value := range captured.Skew.Details {
		skew[name] = runner.SkewDetail{SkewMs: value}
	}
	results := map[string]doc.Result{}
	inputs := map[string]string{}
	for _, row := range answer.Rows {
		if !row.Sized {
			continue
		}
		results[row.ID] = row.Result
		inputs[row.ID] = row.InputDigest
	}
	baseline := answer.Baseline.String()
	return runner.Document{
		Options: runner.DocumentOptions{
			Underlying: settings.underlying, Quantity: settings.quantity.String(),
			Cap: settings.cap.String(), Floor: settings.floor.String(),
			Ceiling: settings.ceiling.String(), Baseline: baseline,
			BaselineKind: settings.baselineKind, ValuationTime: answer.ValuationTime,
		},
		Expiry: captured.Expiry, Observation: answer.ObservationTime,
		Valuation: answer.ValuationTime, Digests: digests, Skew: skew,
		Capture: assertion, Results: results, InputDigests: inputs,
	}
}

func printAnswer(out *os.File, answer runner.Answer) {
	fmt.Fprintln(out)
	fmt.Fprintf(out, "%-14s %-14s %-12s %-14s %s\n", "leg", "verdict", "size", "premium", "worst case")
	for _, row := range answer.Rows {
		if !row.Sized {
			why := "no size on the displayed book meets the cap"
			if row.NotNeeded {
				why = "no hedge needed: the holding already meets the cap"
			}
			fmt.Fprintf(out, "%-14s %s\n", row.ID, why)
			continue
		}
		fmt.Fprintf(out, "%-14s %-14s %-12s %-14s %s\n", row.ID, row.Result.ModelResult,
			row.Size, row.Result.Cost.Premium, row.Result.WorstCase.Pnl)
	}
	fmt.Fprintf(out, "%-14s %-14s %-12s %-14s %s\n", "sell-down", "no premium",
		answer.Reduction.Sell, "0", answer.Reduction.WorstCase)
}

func sortedKeys(values map[string]int64) []string {
	out := make([]string, 0, len(values))
	for key := range values {
		out = append(out, key)
	}
	for i := 1; i < len(out); i++ {
		for j := i; j > 0 && out[j] < out[j-1]; j-- {
			out[j], out[j-1] = out[j-1], out[j]
		}
	}
	return out
}
