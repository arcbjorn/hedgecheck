package run

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sort"

	"hedgecheck/engine/doc"
)

// SchemaVersion is the run document's version, shared with the spike's.
const SchemaVersion = "1"

// Document is everything a replay needs and nothing a replay would have to fetch.
//
// It is one document per leg, because the input digest it is stored under identifies
// one answered question. The other legs' results ride along so a reader sees the
// comparison the run made, but `leg` says which one this document is about.
type Document struct {
	Options      DocumentOptions
	Expiry       string
	Observation  string
	Valuation    string
	Digests      map[string]string
	Skew         map[string]SkewDetail
	Capture      *doc.Capture
	Results      map[string]doc.Result
	InputDigests map[string]string
	Leg          string
}

// DocumentOptions is the question, as the document records it.
type DocumentOptions struct {
	Underlying    string
	Quantity      string
	Cap           string
	Floor         string
	Ceiling       string
	Baseline      string
	BaselineKind  string
	ValuationTime string
}

// SkewDetail is one book's measured timing, kept per book so a reader can see which
// snapshot was the stale one rather than only that something was.
type SkewDetail struct {
	BookVenueMs    int64
	LocalRetrieved int64
	SkewMs         int64
	ContextsGapMs  int64
}

// A run document is an OPERATIONAL RECORD, not a contract document.
//
// It is never digested and nothing verifies it, so it is not held to the canonical
// profile -- and it could not be: it keys `digests` and `skew` by leg id, and a leg id
// may contain a hyphen ([a-z][a-z0-9-]*) while a canonical key may not
// ([a-z][a-z0-9_]*). It also carries venue timestamps as bare numbers where the
// canonical profile demands exact strings. Both the Python and Go canonical readers
// refuse this document, correctly.
//
// What IS canonical is every result embedded inside it. Those are contract documents,
// they carry the digests a replay checks, and they go through the strict reader. The
// envelope around them is a record of one operation, written with the ordinary JSON
// encoder and read back with UseNumber so no timestamp passes through a float.

// Encode renders a run document. Keys are sorted, so two runs of the same capture
// produce the same bytes even though this envelope is not a canonical document.
func Encode(document Document) ([]byte, error) {
	return marshalSorted(encodeDocument(document))
}

func encodeDocument(document Document) map[string]any {
	results := map[string]any{}
	for name, result := range document.Results {
		results[name] = doc.EncodeResult(result)
	}
	digests := map[string]any{}
	for name, digest := range document.Digests {
		digests[name] = digest
	}
	inputs := map[string]any{}
	for name, digest := range document.InputDigests {
		inputs[name] = digest
	}
	skew := map[string]any{}
	for name, detail := range document.Skew {
		skew[name] = map[string]any{
			"book_venue_ms":      detail.BookVenueMs,
			"local_retrieved_ms": detail.LocalRetrieved,
			"skew_ms":            detail.SkewMs,
			"contexts_gap_ms":    detail.ContextsGapMs,
		}
	}
	out := map[string]any{
		"schema_version": SchemaVersion,
		"options": map[string]any{
			"underlying":     document.Options.Underlying,
			"quantity":       document.Options.Quantity,
			"cap":            document.Options.Cap,
			"floor":          document.Options.Floor,
			"ceiling":        document.Options.Ceiling,
			"baseline":       document.Options.Baseline,
			"baseline_kind":  document.Options.BaselineKind,
			"valuation_time": document.Options.ValuationTime,
		},
		"expiry":           document.Expiry,
		"observation_time": document.Observation,
		"valuation_time":   document.Valuation,
		"digests":          digests,
		"skew":             skew,
		"results":          results,
		"input_digests":    inputs,
		"leg":              document.Leg,
	}
	if document.Capture != nil {
		out["capture"] = map[string]any{
			"skew_ms": document.Capture.SkewMs, "max_skew_ms": document.Capture.MaxSkewMs,
			"measured_by": document.Capture.MeasuredBy,
		}
	} else {
		out["capture"] = nil
	}
	return out
}

// Decode reads a run document, strictly: an unknown key is a refusal, because a
// document carrying something this engine does not understand cannot be replayed
// faithfully by ignoring it.
func Decode(raw []byte) (Document, error) {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
		return Document{}, err
	}
	root, ok := value.(map[string]any)
	if !ok {
		return Document{}, fmt.Errorf("run: a run document is an object")
	}
	known := map[string]bool{
		"schema_version": true, "options": true, "expiry": true, "observation_time": true,
		"valuation_time": true, "digests": true, "skew": true, "capture": true,
		"results": true, "input_digests": true, "leg": true,
	}
	unknown := []string{}
	for key := range root {
		if !known[key] {
			unknown = append(unknown, key)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return Document{}, fmt.Errorf("run: the run document carries unknown keys %v", unknown)
	}
	if version, _ := root["schema_version"].(string); version != SchemaVersion {
		return Document{}, fmt.Errorf("run: unsupported run document schema_version %q", version)
	}

	out := Document{
		Digests: map[string]string{}, InputDigests: map[string]string{},
		Skew: map[string]SkewDetail{}, Results: map[string]doc.Result{},
	}
	out.Expiry, _ = root["expiry"].(string)
	out.Observation, _ = root["observation_time"].(string)
	out.Valuation, _ = root["valuation_time"].(string)
	out.Leg, _ = root["leg"].(string)

	options, _ := root["options"].(map[string]any)
	out.Options = DocumentOptions{
		Underlying:    text(options["underlying"]),
		Quantity:      text(options["quantity"]),
		Cap:           text(options["cap"]),
		Floor:         text(options["floor"]),
		Ceiling:       text(options["ceiling"]),
		Baseline:      text(options["baseline"]),
		BaselineKind:  text(options["baseline_kind"]),
		ValuationTime: text(options["valuation_time"]),
	}

	digests, _ := root["digests"].(map[string]any)
	for name, value := range digests {
		out.Digests[name] = text(value)
	}
	inputs, _ := root["input_digests"].(map[string]any)
	for name, value := range inputs {
		out.InputDigests[name] = text(value)
	}
	skew, _ := root["skew"].(map[string]any)
	for name, value := range skew {
		entry, _ := value.(map[string]any)
		out.Skew[name] = SkewDetail{
			BookVenueMs:    whole(entry["book_venue_ms"]),
			LocalRetrieved: whole(entry["local_retrieved_ms"]),
			SkewMs:         whole(entry["skew_ms"]),
			ContextsGapMs:  whole(entry["contexts_gap_ms"]),
		}
	}
	if capture, ok := root["capture"].(map[string]any); ok {
		out.Capture = doc.NewCapture(text(capture["skew_ms"]),
			text(capture["max_skew_ms"]), text(capture["measured_by"]))
	}

	// Each embedded result IS a contract document, so it goes through the strict
	// reader that refuses an unknown key rather than being read loosely here.
	results, _ := root["results"].(map[string]any)
	for name, value := range results {
		encoded, err := marshalSorted(value)
		if err != nil {
			return Document{}, err
		}
		result, err := doc.ReadResult(encoded)
		if err != nil {
			return Document{}, fmt.Errorf("run: result %s: %w", name, err)
		}
		out.Results[name] = result
	}
	if out.Leg == "" {
		return Document{}, fmt.Errorf("run: the run document does not say which leg it is about")
	}
	if _, ok := out.Results[out.Leg]; !ok {
		return Document{}, fmt.Errorf("run: the document is about %q, which has no result", out.Leg)
	}
	return out, nil
}

func text(value any) string {
	out, _ := value.(string)
	return out
}

// whole reads an integer from a venue-style number without passing through a float.
func whole(value any) int64 {
	switch typed := value.(type) {
	case int64:
		return typed
	case interface{ Int64() (int64, error) }:
		out, err := typed.Int64()
		if err != nil {
			return 0
		}
		return out
	}
	return 0
}

// marshalSorted encodes with sorted keys and no HTML escaping, so the bytes depend on
// the content and not on map iteration. Go's encoder already sorts map keys; this
// turns off the escaping that would otherwise rewrite characters inside strings.
func marshalSorted(value any) ([]byte, error) {
	buffer := &bytes.Buffer{}
	encoder := json.NewEncoder(buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		return nil, err
	}
	return bytes.TrimRight(buffer.Bytes(), "\n"), nil
}
