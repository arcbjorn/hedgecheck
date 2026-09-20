package main

import (
	"fmt"
	"time"

	"hedgecheck/engine/discover"
	"hedgecheck/engine/lower"
	runner "hedgecheck/engine/run"
	"hedgecheck/engine/store"
)

// Capturing one coherent set of responses.
//
// The order is load-bearing and is asserted, not merely intended:
//
//	catalogue  first, because the coins are discovered from it
//	contexts   next, so the baseline is never NEWER than the prices it is compared to
//	books      one per candidate, in candidate order
//
// If the baseline were fetched after the books, it would describe a moment the prices
// had not reached, and every comparison against it would be quietly wrong in the
// direction the market happened to move.

// Venue is the small part of the adapter a capture needs. It is an interface so the
// capture SEQUENCE can be tested without a network: the order of calls is the thing
// most likely to be got wrong, and it is exactly what a live-only test cannot check.
type Venue interface {
	Catalogue() (Retrieved, error)
	Contexts() (Retrieved, error)
	Book(coin string) (Retrieved, error)
	Spent() int
}

// Retrieved is a response with the record of how it was obtained.
type Retrieved struct {
	Digest string
	Raw    []byte
	Record []byte
}

// Captured is one coherent set, ready to be answered.
type Captured struct {
	Capture    runner.Capture
	Expiry     string
	Candidates []discover.Candidate
	Skew       runner.Skew
	Records    map[string][]byte
	Requests   int
}

// CaptureLive fetches one coherent set and files every response under its own digest
// as it arrives. Filing as we go means an interrupted capture leaves retained bytes
// rather than nothing: the responses are evidence whether or not the run completes.
func CaptureLive(venue Venue, keep *store.Store, underlying string,
	retrievedAt func([]byte) (int64, bool)) (Captured, error) {
	out := Captured{
		Capture: runner.Capture{BookDigests: map[string]string{}, Snapshots: lower.Snapshots{}},
		Records: map[string][]byte{},
	}

	catalogueResponse, err := venue.Catalogue()
	if err != nil {
		return out, err
	}
	if err := retain(keep, &out, "catalogue", catalogueResponse); err != nil {
		return out, err
	}
	out.Capture.CatalogueDigest = catalogueResponse.Digest

	catalogue, err := parseCatalogue(catalogueResponse.Raw)
	if err != nil {
		return out, err
	}
	expiry, candidates, err := discover.Candidates(catalogue, underlying, "")
	if err != nil {
		return out, err
	}
	out.Expiry, out.Candidates = expiry, candidates

	contextsResponse, err := venue.Contexts()
	if err != nil {
		return out, err
	}
	if err := retain(keep, &out, "contexts", contextsResponse); err != nil {
		return out, err
	}
	out.Capture.ContextsDigest = contextsResponse.Digest

	books := map[string][]byte{}
	bookRecords := map[string][]byte{}
	for _, candidate := range candidates {
		bookResponse, err := venue.Book(candidate.Coin)
		if err != nil {
			return out, err
		}
		if err := retain(keep, &out, candidate.ID, bookResponse); err != nil {
			return out, err
		}
		out.Capture.BookDigests[candidate.ID] = bookResponse.Digest
		books[candidate.ID] = bookResponse.Raw
		bookRecords[candidate.ID] = bookResponse.Record
	}

	skew, err := runner.Measure(books, bookRecords, runner.BookTime, retrievedAt)
	if err != nil {
		return out, err
	}
	out.Skew = skew
	out.Requests = venue.Spent()
	return out, nil
}

// retain files one response under its own digest and keeps its record.
func retain(keep *store.Store, out *Captured, name string, response Retrieved) error {
	filed, err := keep.Put(response.Raw, response.Record)
	if err != nil {
		return err
	}
	if filed != response.Digest {
		// The adapter hashed the bytes and so did the store. They cannot disagree
		// unless something changed the bytes in between.
		return fmt.Errorf("%s: the adapter says %s, the store says %s",
			name, short(response.Digest), short(filed))
	}
	if _, err := out.Capture.Snapshots.Add(response.Raw); err != nil {
		return err
	}
	out.Records[name] = response.Record
	return nil
}

// parseCatalogue reads venue JSON with UseNumber, never through a float.
func parseCatalogue(raw []byte) (any, error) { return runner.ParseVenue(raw) }

func short(digest string) string {
	if len(digest) <= 12 {
		return digest
	}
	return digest[:12]
}

// today is the date a retained capture is filed under, in UTC. The venue's day and
// the operator's day are different things, and evidence is filed by the former.
func today() string { return time.Now().UTC().Format("2006-01-02") }
