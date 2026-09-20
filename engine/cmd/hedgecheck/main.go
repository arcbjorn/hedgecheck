// Command hedgecheck answers a proposal from the command line.
//
// This package does file I/O and nothing else. Every computation is a call into a
// pure package, so the only thing that can be wrong here is which bytes went where.
//
// Exit status says what happened, so a caller can branch without parsing output:
//
//	0  passes
//	1  fails
//	2  needs_review
//	3  refused, with the code on stderr
//	4  usage or technical error
//
// A technical error never prints a verdict. "Could not read the book" and "the hedge
// does not meet your objective" are different answers, and conflating them would let
// a broken pipe read as a failed hedge.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/evaluate"
	"hedgecheck/engine/lower"
)

const (
	exitPasses      = 0
	exitFails       = 1
	exitNeedsReview = 2
	exitRefused     = 3
	exitUsage       = 4
)

const usage = `hedgecheck — check whether a proposed hedge meets an explicit objective.

  hedgecheck lower    --proposal P --registry DIR --snapshots DIR
  hedgecheck evaluate --lowered L
  hedgecheck check    --proposal P --registry DIR --snapshots DIR
  hedgecheck bundle   --proposal P --registry DIR --snapshots DIR --out DIR
  hedgecheck compare  --result R --result R [--result R ...]

Options:
  --pretty      indent the output; canonical JSON otherwise
  --reviewed    treat every registry entry as reviewed (fixtures only, never live)

Exit status:
  0  passes
  1  fails
  2  needs_review
  3  refused: the proposal could not be lowered, and the code is on stderr
  4  usage or technical error

A refusal is not a verdict. A proposal that cannot be lowered has no result, so
status 3 never means the objective was evaluated and found wanting.
`

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

func run(args []string, out, errOut *os.File) int {
	if len(args) == 0 || args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
		fmt.Fprint(out, usage)
		if len(args) == 0 {
			return exitUsage
		}
		return exitPasses
	}
	command, rest := args[0], args[1:]
	flags, err := parseFlags(rest)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	switch command {
	case "lower":
		return commandLower(flags, out, errOut)
	case "evaluate":
		return commandEvaluate(flags, out, errOut)
	case "check":
		return commandCheck(flags, out, errOut)
	case "bundle":
		return commandBundle(flags, out, errOut)
	case "compare":
		return commandCompare(flags, out, errOut)
	}
	fmt.Fprintf(errOut, "unknown command %q\n\n%s", command, usage)
	return exitUsage
}

type options struct {
	proposal  string
	lowered   string
	registry  string
	snapshots string
	out       string
	results   []string
	pretty    bool
	reviewed  bool
}

func parseFlags(args []string) (options, error) {
	flags := options{}
	for index := 0; index < len(args); index++ {
		name := args[index]
		value := func() (string, error) {
			if index+1 >= len(args) {
				return "", fmt.Errorf("%s needs a value", name)
			}
			index++
			return args[index], nil
		}
		var err error
		switch name {
		case "--proposal":
			flags.proposal, err = value()
		case "--lowered":
			flags.lowered, err = value()
		case "--registry":
			flags.registry, err = value()
		case "--snapshots":
			flags.snapshots, err = value()
		case "--out":
			flags.out, err = value()
		case "--result":
			var path string
			path, err = value()
			flags.results = append(flags.results, path)
		case "--pretty":
			flags.pretty = true
		case "--reviewed":
			flags.reviewed = true
		default:
			return flags, fmt.Errorf("unknown option %q", name)
		}
		if err != nil {
			return flags, err
		}
	}
	return flags, nil
}

// ---------------------------------------------------------------- loading

func loadRegistry(directory string, reviewed bool) (map[string]doc.Entry, error) {
	matches, err := filepath.Glob(filepath.Join(directory, "*.json"))
	if err != nil || len(matches) == 0 {
		return nil, fmt.Errorf("no registry entries in %s", directory)
	}
	out := map[string]doc.Entry{}
	for _, path := range matches {
		raw, err := os.ReadFile(path)
		if err != nil {
			return nil, err
		}
		entry, err := doc.ReadEntry(raw)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", path, err)
		}
		if reviewed {
			version, err := entry.SemanticsVersion()
			if err != nil {
				return nil, err
			}
			entry.SetReviewed("operator", "2026-09-20", version)
		}
		out[entry.Family] = entry
	}
	return out, nil
}

func loadSnapshots(directory string) (lower.Snapshots, error) {
	matches, err := filepath.Glob(filepath.Join(directory, "*.json"))
	if err != nil {
		return nil, err
	}
	out := lower.Snapshots{}
	for _, path := range matches {
		name := filepath.Base(path)
		// Request records and contract documents are not venue responses.
		if strings.HasSuffix(name, ".request.json") || strings.HasSuffix(name, ".proposal.json") ||
			strings.HasSuffix(name, ".run.json") || strings.HasSuffix(name, ".result.json") ||
			strings.HasSuffix(name, ".ir.json") {
			continue
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return nil, err
		}
		if _, err := out.Add(raw); err != nil {
			return nil, fmt.Errorf("%s: %w", path, err)
		}
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("no snapshots in %s", directory)
	}
	return out, nil
}

func write(out *os.File, document []byte, pretty bool) error {
	if !pretty {
		_, err := fmt.Fprintln(out, string(document))
		return err
	}
	var value any
	if err := json.Unmarshal(document, &value); err != nil {
		return err
	}
	indented, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, string(indented))
	return err
}

// refusalExit reports a refusal with its code, and never a verdict.
func refusalExit(err error, errOut *os.File) int {
	var refused *lower.Refused
	if ok := asRefused(err, &refused); ok {
		fmt.Fprintf(errOut, "%s: %s\n", refused.Code, refused.Detail)
		return exitRefused
	}
	fmt.Fprintln(errOut, err)
	return exitUsage
}

func asRefused(err error, target **lower.Refused) bool {
	refused, ok := err.(*lower.Refused)
	if ok {
		*target = refused
	}
	return ok
}

func verdictExit(result doc.Result) int {
	switch result.ModelResult {
	case "passes":
		return exitPasses
	case "fails":
		return exitFails
	}
	return exitNeedsReview
}

// ---------------------------------------------------------------- commands

func lowerFrom(flags options) (doc.Proposal, doc.IR, []string, error) {
	raw, err := os.ReadFile(flags.proposal)
	if err != nil {
		return doc.Proposal{}, doc.IR{}, nil, err
	}
	proposal, err := doc.ReadProposal(raw)
	if err != nil {
		return doc.Proposal{}, doc.IR{}, nil, err
	}
	registry, err := loadRegistry(flags.registry, flags.reviewed)
	if err != nil {
		return doc.Proposal{}, doc.IR{}, nil, err
	}
	snapshots, err := loadSnapshots(flags.snapshots)
	if err != nil {
		return doc.Proposal{}, doc.IR{}, nil, err
	}
	ir, versions, err := lower.Lower(proposal, registry, snapshots)
	return proposal, ir, versions, err
}

func commandLower(flags options, out, errOut *os.File) int {
	if flags.proposal == "" || flags.registry == "" || flags.snapshots == "" {
		fmt.Fprintln(errOut, "lower needs --proposal, --registry and --snapshots")
		return exitUsage
	}
	_, ir, _, err := lowerFrom(flags)
	if err != nil {
		return refusalExit(err, errOut)
	}
	encoded, err := doc.WriteIR(ir)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	if err := write(out, encoded, flags.pretty); err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	return exitPasses
}

func commandEvaluate(flags options, out, errOut *os.File) int {
	if flags.lowered == "" {
		fmt.Fprintln(errOut, "evaluate needs --lowered")
		return exitUsage
	}
	raw, err := os.ReadFile(flags.lowered)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	ir, err := doc.ReadIR(raw)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	result, err := evaluate.Evaluate(ir)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	encoded, err := doc.WriteResult(result)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	if err := write(out, encoded, flags.pretty); err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	return verdictExit(result)
}

func commandCheck(flags options, out, errOut *os.File) int {
	if flags.proposal == "" || flags.registry == "" || flags.snapshots == "" {
		fmt.Fprintln(errOut, "check needs --proposal, --registry and --snapshots")
		return exitUsage
	}
	_, ir, _, err := lowerFrom(flags)
	if err != nil {
		return refusalExit(err, errOut)
	}
	result, err := evaluate.Evaluate(ir)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	encoded, err := doc.WriteResult(result)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	if err := write(out, encoded, flags.pretty); err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	return verdictExit(result)
}

func commandBundle(flags options, out, errOut *os.File) int {
	if flags.proposal == "" || flags.registry == "" || flags.snapshots == "" || flags.out == "" {
		fmt.Fprintln(errOut, "bundle needs --proposal, --registry, --snapshots and --out")
		return exitUsage
	}
	proposal, ir, _, err := lowerFrom(flags)
	if err != nil {
		return refusalExit(err, errOut)
	}
	result, err := evaluate.Evaluate(ir)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	registry, err := loadRegistry(flags.registry, flags.reviewed)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	snapshots, err := loadSnapshots(flags.snapshots)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	if err := writeBundle(flags.out, proposal, ir, result, registry, snapshots); err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	fmt.Fprintf(out, "%s\n", flags.out)
	return verdictExit(result)
}

// writeBundle lays out everything a checker needs and nothing it would have to fetch.
// A bundle is self-contained on purpose: refusing it must never depend on the state of
// the tree it was built from.
func writeBundle(directory string, proposal doc.Proposal, ir doc.IR, result doc.Result,
	registry map[string]doc.Entry, snapshots lower.Snapshots) error {
	if err := os.MkdirAll(directory, 0o755); err != nil {
		return err
	}
	put := func(name string, document []byte) error {
		return os.WriteFile(filepath.Join(directory, name), append(document, '\n'), 0o644)
	}
	encodedProposal, err := doc.WriteProposal(proposal)
	if err != nil {
		return err
	}
	encodedIR, err := doc.WriteIR(ir)
	if err != nil {
		return err
	}
	encodedResult, err := doc.WriteResult(result)
	if err != nil {
		return err
	}
	if err := put("proposal.json", encodedProposal); err != nil {
		return err
	}
	if err := put("lowered.json", encodedIR); err != nil {
		return err
	}
	if err := put("result.json", encodedResult); err != nil {
		return err
	}

	manifest := doc.Manifest{
		SchemaVersion: "1",
		Name:          filepath.Base(directory),
		Expects:       "accept",
		Proposal:      "proposal.json",
		Lowered:       "lowered.json",
		Result:        "result.json",
	}
	// Sorted, so the same inputs write the same manifest twice running.
	families := make([]string, 0, len(registry))
	for family := range registry {
		families = append(families, family)
	}
	sort.Strings(families)
	for _, family := range families {
		name := "registry-" + family + ".json"
		encoded, err := doc.WriteEntry(registry[family])
		if err != nil {
			return err
		}
		if err := put(name, encoded); err != nil {
			return err
		}
		manifest.Registry = append(manifest.Registry, doc.NamedFile{Key: family, Path: name})
	}

	// Only the snapshots this proposal cites: a bundle carries its evidence, not the
	// capture session's leftovers.
	cited := map[string]bool{}
	if proposal.Baseline.Snapshot != "" {
		cited[proposal.Baseline.Snapshot] = true
	}
	for _, leg := range proposal.Legs {
		cited[leg.Instance.Catalogue] = true
		if leg.Acquisition.Snapshot != "" {
			cited[leg.Acquisition.Snapshot] = true
		}
	}
	digests := make([]string, 0, len(cited))
	for digest := range cited {
		digests = append(digests, digest)
	}
	sort.Strings(digests)
	for _, digest := range digests {
		snapshot, ok := snapshots[digest]
		if !ok {
			return fmt.Errorf("the proposal cites %s, which was not supplied", digest[:12])
		}
		name := "snapshot-" + digest[:16] + ".json"
		if err := os.WriteFile(filepath.Join(directory, name), snapshot.Raw, 0o644); err != nil {
			return err
		}
		manifest.Snapshots = append(manifest.Snapshots, doc.NamedFile{Key: digest, Path: name})
	}

	encodedManifest, err := doc.WriteManifest(manifest)
	if err != nil {
		return err
	}
	return put("manifest.json", encodedManifest)
}

func commandCompare(flags options, out, errOut *os.File) int {
	if len(flags.results) < 2 {
		fmt.Fprintln(errOut, "compare needs at least two --result files")
		return exitUsage
	}
	candidates := []evaluate.Candidate{}
	for _, path := range flags.results {
		// A comparison cites results by digest, and re-derives the ranking from them.
		// The lowered proposal beside each result supplies the shared terms.
		resultRaw, err := os.ReadFile(path)
		if err != nil {
			fmt.Fprintln(errOut, err)
			return exitUsage
		}
		result, err := doc.ReadResult(resultRaw)
		if err != nil {
			fmt.Fprintf(errOut, "%s: %v\n", path, err)
			return exitUsage
		}
		irPath := strings.TrimSuffix(path, "result.json") + "lowered.json"
		irRaw, err := os.ReadFile(irPath)
		if err != nil {
			fmt.Fprintf(errOut, "%s: a result is compared beside its lowered proposal: %v\n", path, err)
			return exitUsage
		}
		ir, err := doc.ReadIR(irRaw)
		if err != nil {
			fmt.Fprintf(errOut, "%s: %v\n", irPath, err)
			return exitUsage
		}
		candidates = append(candidates, evaluate.Candidate{
			Label: label(path), IR: ir, Result: result,
		})
	}
	comparison, err := evaluate.Compare(candidates)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	encoded, err := doc.WriteComparison(comparison)
	if err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	if err := write(out, encoded, flags.pretty); err != nil {
		fmt.Fprintln(errOut, err)
		return exitUsage
	}
	return exitPasses
}

// label names a candidate after the directory holding its result, lower-cased to a
// slug so it can travel in a document.
func label(path string) string {
	name := filepath.Base(filepath.Dir(path))
	out := strings.Map(func(r rune) rune {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9':
			return r
		case r >= 'A' && r <= 'Z':
			return r + ('a' - 'A')
		}
		return '_'
	}, name)
	if out == "" || out[0] < 'a' || out[0] > 'z' {
		out = "c" + out
	}
	return out
}
