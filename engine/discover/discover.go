// Package discover finds the live canonical instruments in a catalogue. Pure: a
// parsed catalogue in, candidate instruments out.
//
// An instance id is never configuration. Instruments are found by class, underlying
// and expiry, every run, because ids rotate daily: outcome 3061 was pruned from the
// live catalogue within a day of settling (EVIDENCE section 4). A literal id in
// source would pin the engine to a series that has already rolled over by morning,
// and `discover_test.go` fails if one appears.
package discover

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// NotFound reports that no live instance of a family exists for an underlying.
type NotFound struct{ Why string }

func (e *NotFound) Error() string { return e.Why }

// Candidate is one instrument to compare, with everything a proposal needs but size.
type Candidate struct {
	ID         string
	Family     string
	Side       string
	Outcome    string
	Coin       string
	Terms      map[string]any
	StrikeTerm string
}

// TermsOf parses a catalogue description, "key:value|key:value".
func TermsOf(description string) (map[string]string, error) {
	out := map[string]string{}
	for _, part := range strings.Split(description, "|") {
		key, value, found := strings.Cut(part, ":")
		if key == "" || !found {
			return nil, fmt.Errorf("description part %q is not key:value", part)
		}
		out[key] = value
	}
	return out, nil
}

// sideCoin encodes outcome and side: '#' + (10*outcome + side), yes=0, no=1.
func sideCoin(outcome string, side string) (string, error) {
	number, err := strconv.Atoi(outcome)
	if err != nil {
		return "", fmt.Errorf("outcome %q is not a number", outcome)
	}
	offset := 1
	if side == "yes" || side == "long" {
		offset = 0
	}
	return fmt.Sprintf("#%d", 10*number+offset), nil
}

type binary struct {
	outcome, expiry, target, period string
}

type bucket struct {
	question, expiry, period string
	thresholds               []string
	named                    []string
}

// text renders a venue JSON value without passing through a float. json.Number keeps
// the literal text, which is the only lossless reading of it.
func text(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	case interface{ String() string }:
		return typed.String()
	}
	return ""
}

func binaries(catalogue any, underlying string) []binary {
	typed, _ := catalogue.(map[string]any)
	items, _ := typed["outcomes"].([]any)
	out := []binary{}
	for _, item := range items {
		entry, _ := item.(map[string]any)
		if name, _ := entry["name"].(string); name != "Recurring" {
			continue
		}
		description, _ := entry["description"].(string)
		terms, err := TermsOf(description)
		if err != nil {
			continue
		}
		if terms["class"] != "priceBinary" || terms["underlying"] != underlying {
			continue
		}
		out = append(out, binary{
			outcome: text(entry["outcome"]), expiry: terms["expiry"],
			target: terms["targetPrice"], period: terms["period"],
		})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].expiry != out[j].expiry {
			return out[i].expiry < out[j].expiry
		}
		return out[i].outcome < out[j].outcome
	})
	return out
}

func buckets(catalogue any, underlying string) []bucket {
	typed, _ := catalogue.(map[string]any)
	items, _ := typed["questions"].([]any)
	out := []bucket{}
	for _, item := range items {
		entry, _ := item.(map[string]any)
		if name, _ := entry["name"].(string); name != "Recurring" {
			continue
		}
		description, _ := entry["description"].(string)
		terms, err := TermsOf(description)
		if err != nil {
			continue
		}
		if terms["class"] != "priceBucket" || terms["underlying"] != underlying {
			continue
		}
		named := []string{}
		list, _ := entry["namedOutcomes"].([]any)
		for _, outcome := range list {
			named = append(named, text(outcome))
		}
		out = append(out, bucket{
			question: text(entry["question"]), expiry: terms["expiry"],
			thresholds: strings.Split(terms["priceThresholds"], ","),
			period:     terms["period"], named: named,
		})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].expiry != out[j].expiry {
			return out[i].expiry < out[j].expiry
		}
		return out[i].question < out[j].question
	})
	return out
}

// SoonestExpiry is the earliest expiry at which BOTH a binary and a bucket exist.
//
// Both instruments must answer the same question for a comparison to mean anything,
// so the expiry is chosen where both live rather than per instrument.
func SoonestExpiry(catalogue any, underlying string) (string, error) {
	inBucket := map[string]bool{}
	for _, found := range buckets(catalogue, underlying) {
		inBucket[found.expiry] = true
	}
	shared := []string{}
	for _, found := range binaries(catalogue, underlying) {
		if inBucket[found.expiry] {
			shared = append(shared, found.expiry)
		}
	}
	if len(shared) == 0 {
		return "", &NotFound{Why: "no expiry with both a binary and a bucket for " + underlying}
	}
	sort.Strings(shared)
	return shared[0], nil
}

// Candidates returns the canonical instruments to compare at one expiry.
//
// NO on the binary and YES on the lowest bucket both pay below a threshold, which is
// what a long holder is hedging. They are the two canonical ways to buy that payoff.
func Candidates(catalogue any, underlying, expiry string) (string, []Candidate, error) {
	if expiry == "" {
		found, err := SoonestExpiry(catalogue, underlying)
		if err != nil {
			return "", nil, err
		}
		expiry = found
	}

	var chosenBinary *binary
	for index, found := range binaries(catalogue, underlying) {
		if found.expiry == expiry {
			chosenBinary = &binaries(catalogue, underlying)[index]
			break
		}
	}
	if chosenBinary == nil {
		return "", nil, &NotFound{Why: "no live recurring.priceBinary for " + underlying + " expiring " + expiry}
	}
	var chosenBucket *bucket
	all := buckets(catalogue, underlying)
	for index, found := range all {
		if found.expiry == expiry {
			chosenBucket = &all[index]
			break
		}
	}
	if chosenBucket == nil {
		return "", nil, &NotFound{Why: "no live recurring.priceBucket for " + underlying + " expiring " + expiry}
	}
	if len(chosenBucket.named) == 0 {
		return "", nil, &NotFound{Why: "the " + underlying + " bucket question expiring " + expiry + " names no outcomes"}
	}

	binaryCoin, err := sideCoin(chosenBinary.outcome, "no")
	if err != nil {
		return "", nil, err
	}
	bucketOutcome := chosenBucket.named[0]
	bucketCoin, err := sideCoin(bucketOutcome, "yes")
	if err != nil {
		return "", nil, err
	}
	iso, err := ExpiryToISO(expiry)
	if err != nil {
		return "", nil, err
	}
	thresholds := make([]any, 0, len(chosenBucket.thresholds))
	for _, threshold := range chosenBucket.thresholds {
		thresholds = append(thresholds, threshold)
	}
	return expiry, []Candidate{
		{
			ID: "binary-no", Family: "recurring.priceBinary", Side: "no",
			Outcome: chosenBinary.outcome, Coin: binaryCoin, StrikeTerm: "target_price",
			Terms: map[string]any{
				"underlying": underlying, "target_price": chosenBinary.target,
				"period": chosenBinary.period, "expiry": iso,
			},
		},
		{
			ID: "bucket0-yes", Family: "recurring.priceBucket", Side: "yes",
			Outcome: bucketOutcome, Coin: bucketCoin, StrikeTerm: "thresholds",
			Terms: map[string]any{
				"underlying": underlying, "thresholds": thresholds, "index": "0",
				"period": chosenBucket.period, "expiry": iso,
			},
		},
	}, nil
}

// ExpiryToISO turns the catalogue's "20260919-0600" into "2026-09-19T06:00:00Z".
func ExpiryToISO(expiry string) (string, error) {
	date, time, found := strings.Cut(expiry, "-")
	if !found || len(date) != 8 || len(time) != 4 {
		return "", fmt.Errorf("expiry %q is not YYYYMMDD-HHMM", expiry)
	}
	return fmt.Sprintf("%s-%s-%sT%s:%s:00Z", date[0:4], date[4:6], date[6:8], time[0:2], time[2:4]), nil
}
