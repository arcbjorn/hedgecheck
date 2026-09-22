package lower

import (
	"fmt"
	"strconv"
	"strings"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
)

// termsOf parses a catalogue description, "key:value|key:value".
func termsOf(description string) (map[string]string, error) {
	out := map[string]string{}
	for _, part := range strings.Split(description, "|") {
		key, value, found := strings.Cut(part, ":")
		if key == "" || !found {
			return nil, refuse("CATALOGUE_UNREADABLE", "description part %q is not key:value", part)
		}
		out[key] = value
	}
	return out, nil
}

func findOutcome(catalogue any, outcome string) (map[string]any, error) {
	typed, _ := catalogue.(map[string]any)
	items, _ := typed["outcomes"].([]any)
	for _, item := range items {
		entry, _ := item.(map[string]any)
		if numberText(entry["outcome"]) == outcome {
			return entry, nil
		}
	}
	return nil, refuse("INSTANCE_NOT_IN_CATALOGUE", "outcome %s is not in the cited catalogue", outcome)
}

// questionOf finds the question that names an outcome, for families whose terms live
// on the parent rather than on the instance.
func questionOf(catalogue any, outcome string) (map[string]any, error) {
	typed, _ := catalogue.(map[string]any)
	items, _ := typed["questions"].([]any)
	for _, item := range items {
		question, _ := item.(map[string]any)
		named, _ := question["namedOutcomes"].([]any)
		for _, candidate := range named {
			if numberText(candidate) == outcome {
				return question, nil
			}
		}
	}
	return nil, refuse("INSTANCE_NOT_IN_CATALOGUE", "no question names outcome %s", outcome)
}

// numberText renders a venue JSON number without ever passing through a float.
// json.Number keeps the literal text, which is the only lossless reading of it.
func numberText(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	case interface{ String() string }:
		return typed.String()
	}
	return ""
}

// expiryCompact turns "2026-09-19T06:00:00Z" into the catalogue's "20260919-0600".
func expiryCompact(iso string) (string, error) {
	if len(iso) != 20 || !strings.HasSuffix(iso, "Z") {
		return "", refuse("TERMS_MISMATCH", "expiry %q is not an ISO instant ending in Z", iso)
	}
	return fmt.Sprintf("%s%s%s-%s%s", iso[0:4], iso[5:7], iso[8:10], iso[11:13], iso[14:16]), nil
}

// checkTerms holds the rule that stops a proposal being evaluated against terms
// nobody verified: the numbers the kernel uses come from the catalogue, not the leg.
func checkTerms(leg doc.ProposalLeg, catalogue any) ([]exact.Q, error) {
	item, err := findOutcome(catalogue, leg.Instance.Outcome)
	if err != nil {
		return nil, err
	}
	description, _ := item["description"].(string)

	switch leg.Family {
	case "recurring.priceBinary":
		described, err := termsOf(description)
		if err != nil {
			return nil, err
		}
		expiry, err := expiryCompact(text(leg.Terms["expiry"]))
		if err != nil {
			return nil, err
		}
		want := map[string]string{
			"class": "priceBinary", "underlying": text(leg.Terms["underlying"]),
			"expiry": expiry, "targetPrice": text(leg.Terms["target_price"]),
			"period": text(leg.Terms["period"]),
		}
		if !sameTerms(described, want) {
			return nil, refuse("TERMS_MISMATCH",
				"%s: catalogue says %q, leg says %v", leg.ID, description, want)
		}
		target, err := exact.ParseQ(text(leg.Terms["target_price"]))
		if err != nil {
			return nil, refuse("TERMS_MISMATCH", "%s: target_price is not a number", leg.ID)
		}
		return []exact.Q{target}, nil

	case "recurring.priceBucket":
		// The outcome carries only its index; the thresholds live on the parent question.
		described, err := termsOf(description)
		if err != nil {
			return nil, err
		}
		if described["index"] != text(leg.Terms["index"]) {
			return nil, refuse("TERMS_MISMATCH",
				"%s: catalogue says index %q, leg says %q", leg.ID, described["index"], text(leg.Terms["index"]))
		}
		question, err := questionOf(catalogue, leg.Instance.Outcome)
		if err != nil {
			return nil, err
		}
		questionText, _ := question["description"].(string)
		describedQuestion, err := termsOf(questionText)
		if err != nil {
			return nil, err
		}
		thresholds := textList(leg.Terms["thresholds"])
		expiry, err := expiryCompact(text(leg.Terms["expiry"]))
		if err != nil {
			return nil, err
		}
		want := map[string]string{
			"class": "priceBucket", "underlying": text(leg.Terms["underlying"]),
			"expiry": expiry, "priceThresholds": strings.Join(thresholds, ","),
			"period": text(leg.Terms["period"]),
		}
		if !sameTerms(describedQuestion, want) {
			return nil, refuse("TERMS_MISMATCH",
				"%s: question says %q, leg says %v", leg.ID, questionText, want)
		}
		named, _ := question["namedOutcomes"].([]any)
		position := -1
		for index, candidate := range named {
			if numberText(candidate) == leg.Instance.Outcome {
				position = index
				break
			}
		}
		wanted, err := strconv.Atoi(text(leg.Terms["index"]))
		if err != nil || position != wanted {
			return nil, refuse("TERMS_MISMATCH",
				"%s: outcome is not at index %s of its question", leg.ID, text(leg.Terms["index"]))
		}
		out := make([]exact.Q, 0, len(thresholds))
		for _, threshold := range thresholds {
			value, err := exact.ParseQ(threshold)
			if err != nil {
				return nil, refuse("TERMS_MISMATCH", "%s: a threshold is not a number", leg.ID)
			}
			out = append(out, value)
		}
		return out, nil
	}
	if leg.Family == "template.binaryPrice" {
		// A DEPLOYER-TEMPLATED binary. Every field the catalogue carries is checked, the
		// price description included: the reference map keys on that exact text, so a leg
		// that disagreed about it would be mapped to a series its instance does not name.
		described, err := termsOf(description)
		if err != nil {
			return nil, err
		}
		expiry, err := expiryCompact(text(leg.Terms["expiry"]))
		if err != nil {
			return nil, err
		}
		want := map[string]string{
			"perp": text(leg.Terms["underlying"]), "priceDescription": described["priceDescription"],
			"seconds": text(leg.Terms["seconds"]), "threshold": text(leg.Terms["target_price"]),
			"time": expiry,
		}
		if !sameTerms(described, want) {
			return nil, refuse("TERMS_MISMATCH",
				"%s: catalogue says %q, leg says %v", leg.ID, description, want)
		}
		value, err := exact.ParseQ(text(leg.Terms["target_price"]))
		if err != nil {
			return nil, refuse("TERMS_MISMATCH", "%s: the threshold is not a number", leg.ID)
		}
		return []exact.Q{value}, nil
	}
	return nil, refuse("UNSUPPORTED_FAMILY", "%s: lowering has no rule for %s", leg.ID, leg.Family)
}

func sameTerms(left, right map[string]string) bool {
	if len(left) != len(right) {
		return false
	}
	for key, value := range right {
		if left[key] != value {
			return false
		}
	}
	return true
}

func text(value any) string {
	if typed, ok := value.(string); ok {
		return typed
	}
	return ""
}

func textList(value any) []string {
	items, _ := value.([]any)
	out := make([]string, 0, len(items))
	for _, item := range items {
		out = append(out, text(item))
	}
	return out
}

// paysOnFor resolves the entry's payoff for this leg's side into an interval of
// prices. A row that expands to more than one indicator is not lowered here: the
// middle bucket's NO side needs two, and a single leg cannot carry both.
func paysOnFor(entry doc.Entry, leg doc.ProposalLeg, values []exact.Q) (doc.PaysOn, error) {
	var chosen *doc.Payoff
	for index := range entry.Payoffs {
		payoff := entry.Payoffs[index]
		if payoff.Side != leg.Side {
			continue
		}
		if payoff.HasIndex && payoff.Index != text(leg.Terms["index"]) {
			continue
		}
		chosen = &payoff
		break
	}
	if chosen == nil {
		return doc.PaysOn{}, refuse("NO_PAYOFF_FOR_SIDE",
			"%s: the entry defines no payoff for side %q", leg.ID, leg.Side)
	}
	if len(chosen.Pays) != 1 || chosen.Pays[0].Primitive != "indicator" {
		return doc.PaysOn{}, refuse("UNSUPPORTED_PAYOFF",
			"%s: only a single indicator is lowered here", leg.ID)
	}
	spec := chosen.Pays[0]
	out := doc.PaysOn{}
	if spec.Lower.Present {
		value, err := boundValue(spec.Lower.Bound, values, leg)
		if err != nil {
			return doc.PaysOn{}, err
		}
		out.Lower = doc.Bound{Value: value, Present: true, Inclusive: spec.Lower.Inclusive}
	}
	if spec.Upper.Present {
		value, err := boundValue(spec.Upper.Bound, values, leg)
		if err != nil {
			return doc.PaysOn{}, err
		}
		out.Upper = doc.Bound{Value: value, Present: true, Inclusive: spec.Upper.Inclusive}
	}
	if !out.Lower.Present && !out.Upper.Present {
		return doc.PaysOn{}, refuse("UNSUPPORTED_PAYOFF",
			"%s: an indicator that pays nowhere in particular", leg.ID)
	}
	return out, nil
}

// boundValue resolves a bound stated in terms into the price it names.
func boundValue(bound doc.TermBound, values []exact.Q, leg doc.ProposalLeg) (exact.Q, error) {
	if bound.HasAt {
		index, err := strconv.Atoi(bound.At)
		if err != nil || index < 0 || index >= len(values) {
			return exact.Q{}, refuse("UNSUPPORTED_PAYOFF",
				"%s: a bound points at position %s, which the terms do not have", leg.ID, bound.At)
		}
		return values[index], nil
	}
	if len(values) == 0 {
		return exact.Q{}, refuse("UNSUPPORTED_PAYOFF", "%s: a bound names no value", leg.ID)
	}
	return values[0], nil
}
