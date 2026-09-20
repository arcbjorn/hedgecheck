package main

import (
	"fmt"
	"os"
	"path/filepath"

	"hedgecheck/engine/canon"
	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
	"hedgecheck/engine/lower"
	runner "hedgecheck/engine/run"
	"hedgecheck/engine/store"
)

// Replay recomputes a stored result from stored bytes alone.
//
// It imports no network package, and it must not: the whole claim of a replay is that
// the answer came out of the retained snapshots rather than out of the venue. If this
// file could fetch, a replay that silently refreshed a book would still print
// "byte-identical" and mean nothing by it.

// replayRun recomputes the run a document describes and compares it to what was
// stored. The comparison is on canonical bytes with engine_version removed, which is
// the equality rule for two results: no other field may differ.
func replayRun(document runner.Document, snapshots lower.Snapshots,
	registry map[string]doc.Entry) (runner.Answer, error) {
	capture := runner.Capture{
		CatalogueDigest: document.Digests["catalogue"],
		ContextsDigest:  document.Digests["contexts"],
		BookDigests:     map[string]string{},
		Snapshots:       snapshots,
	}
	for name, digest := range document.Digests {
		if name == "catalogue" || name == "contexts" {
			continue
		}
		capture.BookDigests[name] = digest
	}
	options := runner.Options{
		Underlying:    document.Options.Underlying,
		BaselineKind:  document.Options.BaselineKind,
		ValuationTime: document.Options.ValuationTime,
		// The assertion is replayed as recorded. A replay cannot re-measure it: the
		// clocks it compared are long gone, and re-deriving it would change the
		// input digest the stored result is filed under.
		Capture: document.Capture,
	}
	var err error
	if options.Quantity, err = exactOf(document.Options.Quantity); err != nil {
		return runner.Answer{}, err
	}
	if options.Cap, err = exactOf(document.Options.Cap); err != nil {
		return runner.Answer{}, err
	}
	if options.Floor, err = exactOf(document.Options.Floor); err != nil {
		return runner.Answer{}, err
	}
	if options.Ceiling, err = exactOf(document.Options.Ceiling); err != nil {
		return runner.Answer{}, err
	}
	if document.Options.BaselineKind == "explicit" {
		if options.BaselinePrice, err = exactOf(document.Options.Baseline); err != nil {
			return runner.Answer{}, err
		}
	}
	return runner.Run(capture, options, registry)
}

// sameResult holds the equality rule: canonical bytes, minus engine_version.
func sameResult(left, right doc.Result) (bool, error) {
	a, err := strippedResult(left)
	if err != nil {
		return false, err
	}
	b, err := strippedResult(right)
	if err != nil {
		return false, err
	}
	return a == b, nil
}

func strippedResult(result doc.Result) (string, error) {
	encoded, err := doc.WriteResult(result)
	if err != nil {
		return "", err
	}
	value, err := canon.Parse(encoded)
	if err != nil {
		return "", err
	}
	object, ok := value.(map[string]any)
	if !ok {
		return "", fmt.Errorf("a result is an object")
	}
	delete(object, "engine_version")
	stripped, err := canon.Marshal(object)
	if err != nil {
		return "", err
	}
	return string(stripped), nil
}

func commandReplay(flags options, out, errOut *os.File) int {
	if flags.inputDigest == "" {
		fmt.Fprintln(errOut, "replay needs an input digest")
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

	// Every snapshot is re-verified against the digest the run cites, which is what
	// makes this a check rather than a copy.
	snapshots := lower.Snapshots{}
	for name, digest := range document.Digests {
		bytes, err := keep.Get(digest)
		if err != nil {
			fmt.Fprintf(errOut, "%s: %v\n", name, err)
			return exitUsage
		}
		if _, err := snapshots.Add(bytes); err != nil {
			fmt.Fprintf(errOut, "%s: %v\n", name, err)
			return exitUsage
		}
	}
	registry, err := loadRegistry(flags.registry, flags.reviewed)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}

	answer, err := replayRun(document, snapshots, registry)
	if err != nil {
		return refusalExit(err, errOut)
	}
	for _, row := range answer.Rows {
		if row.ID != document.Leg {
			continue
		}
		stored, known := document.Results[document.Leg]
		if !known {
			fmt.Fprintf(errOut, "the document carries no result for %s\n", document.Leg)
			return exitUsage
		}
		same, err := sameResult(stored, row.Result)
		if err != nil {
			fmt.Fprintln(errOut, err)
			return exitUsage
		}
		if !same {
			fmt.Fprintf(errOut, "replay differs for %s\n", document.Leg)
			return exitFails
		}
		if row.InputDigest != flags.inputDigest {
			fmt.Fprintf(errOut, "replay recomputed a different input_digest: %s\n", row.InputDigest)
			return exitFails
		}
		fmt.Fprintf(out, "replay of %s (%s): byte-identical\n",
			flags.inputDigest[:16], document.Leg)
		fmt.Fprintf(out, "verdict %s, cost %s\n",
			row.Result.ModelResult, row.Result.Cost.Premium)
		return verdictExit(row.Result)
	}
	fmt.Fprintf(errOut, "the replay produced no row for %s\n", document.Leg)
	return exitFails
}

// commandRetain copies a run's snapshots and document into fixtures/ as evidence.
func commandRetain(flags options, out, errOut *os.File) int {
	if flags.inputDigest == "" || flags.out == "" {
		fmt.Fprintln(errOut, "retain needs an input digest and --out")
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
	if err := os.MkdirAll(flags.out, 0o755); err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	for name, digest := range document.Digests {
		snapshot, err := keep.Get(digest)
		if err != nil {
			fmt.Fprintf(errOut, "%s: %v\n", name, err)
			return exitUsage
		}
		// The bytes are copied unchanged. A retained snapshot that was reformatted
		// would no longer hash to the digest the run cites.
		if err := os.WriteFile(filepath.Join(flags.out, name+".json"), snapshot, 0o644); err != nil {
			fmt.Fprintln(errOut, err)
			return exitUsage
		}
		record, err := keep.Record(digest)
		if err == nil {
			if err := os.WriteFile(filepath.Join(flags.out, name+".request.json"), record, 0o644); err != nil {
				fmt.Fprintln(errOut, err)
				return exitUsage
			}
		}
	}
	if err := os.WriteFile(filepath.Join(flags.out, document.Leg+".run.json"), raw, 0o644); err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	fmt.Fprintf(out, "retained %d snapshots and the run document into %s\n",
		len(document.Digests), flags.out)
	fmt.Fprintln(out, "the bytes are unchanged and each keeps its request record; commit them as evidence")
	return exitPasses
}

// exactOf parses a number the run document recorded as a string.
func exactOf(text string) (exact.Q, error) {
	if text == "" {
		return exact.Zero(), nil
	}
	return exact.ParseQ(text)
}
