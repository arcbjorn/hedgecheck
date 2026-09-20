package doc

import (
	"hedgecheck/engine/canon"
)

// Encoding back to a canon value, with one rule that matters more than the rest:
// an optional field that was absent stays absent. Emitting it empty would change the
// document's digest, and a digest is what a result is cited by.
//
// The round-trip test holds this: decode then encode every accepted fixture and the
// canonical bytes must come back identical.

// Objects are plain map[string]any, not a named type: canon.Marshal type-switches on
// the underlying map, and a named type would silently fall through to "unsupported".
func setIf(out map[string]any, present bool, key string, value any) {
	if present {
		out[key] = value
	}
}

func textList(values []string) []any {
	out := make([]any, 0, len(values))
	for _, value := range values {
		out = append(out, value)
	}
	return out
}

// WriteIR encodes a lowered proposal as canonical bytes.
func WriteIR(ir IR) ([]byte, error) {
	return canon.Marshal(encodeIR(ir))
}

func encodeIR(ir IR) map[string]any {
	out := map[string]any{
		"schema_version": ir.SchemaVersion,
		"units": map[string]any{
			"money": ir.Units.Money, "price": ir.Units.Price,
			"exposure": ir.Units.Exposure, "size": ir.Units.Size,
		},
		"domain":                   map[string]any{"lower": ir.Domain.Lower.String(), "upper": ir.Domain.Upper.String()},
		"baseline":                 encodeBaseline(ir.Baseline),
		"exposure":                 map[string]any{"kind": ir.Exposure.Kind, "quantity": ir.Exposure.Quantity.String()},
		"legs":                     encodeLegs(ir.Legs),
		"objective":                encodeObjective(ir.Objective),
		"objective_valuation_time": ir.ObjectiveValuationTime,
		"other_costs":              ir.OtherCosts.String(),
		"assumptions":              textList(ir.Assumptions),
	}
	setIf(out, ir.Reductions != nil, "reductions", encodeReductions(ir.Reductions))
	if ir.Capture != nil {
		out["capture"] = (map[string]any{
			"skew_ms": ir.Capture.SkewMs, "max_skew_ms": ir.Capture.MaxSkewMs,
			"measured_by": ir.Capture.MeasuredBy,
		})
	}
	return out
}

func encodeBaseline(baseline Baseline) map[string]any {
	out := map[string]any{"kind": baseline.Kind, "price": baseline.Price.String()}
	switch baseline.Kind {
	case "explicit":
		out["label"] = (baseline.Label)
	case "analysis_time":
		out["source"] = (map[string]any{"snapshot": baseline.Snapshot, "coin": baseline.Coin})
	}
	return out
}

func encodeLegs(legs []Leg) []any {
	out := make([]any, 0, len(legs))
	for _, leg := range legs {
		item := map[string]any{
			"id": leg.ID, "kind": leg.Kind, "size": leg.Size.String(),
			"premium":          encodeCost(leg.Premium),
			"observation_time": leg.ObservationTime,
			"semantics":        leg.Semantics,
		}
		switch leg.Kind {
		case "indicator":
			item["pays_on"] = (encodePaysOn(leg.PaysOn))
		case "ramp":
			item["direction"] = (leg.Direction)
			item["low"] = (leg.Low.String())
			item["high"] = (leg.High.String())
		}
		out = append(out, item)
	}
	return out
}

// encodePaysOn writes only the bounds that were present. An unbounded end is the
// absence of a key, never a key holding a sentinel.
func encodePaysOn(paysOn PaysOn) map[string]any {
	out := map[string]any{}
	if paysOn.Lower.Present {
		out["lower"] = (paysOn.Lower.Value.String())
		out["lower_inclusive"] = (paysOn.Lower.Inclusive)
	}
	if paysOn.Upper.Present {
		out["upper"] = (paysOn.Upper.Value.String())
		out["upper_inclusive"] = (paysOn.Upper.Inclusive)
	}
	return out
}

func encodeCost(cost Cost) map[string]any {
	out := map[string]any{"kind": cost.Kind}
	switch cost.Kind {
	case "fixed":
		out["price"] = (cost.Price.String())
	case "walked":
		out["total"] = (cost.Total.String())
		out["path"] = (cost.Path)
		out["snapshot"] = (cost.Snapshot)
		levels := make([]any, 0, len(cost.Levels))
		for _, level := range cost.Levels {
			levels = append(levels, []any{level.Price.String(), level.Size.String()})
		}
		out["levels"] = (levels)
	}
	return out
}

func encodeObjective(clauses []Clause) []any {
	out := make([]any, 0, len(clauses))
	for _, clause := range clauses {
		item := map[string]any{"id": clause.ID, "min_pnl": clause.MinPnl.String()}
		if clause.On != nil {
			item["on"] = (encodeInterval(*clause.On))
		}
		out = append(out, item)
	}
	return out
}

func encodeInterval(interval Interval) map[string]any {
	return map[string]any{
		"lower": interval.Lower.String(), "lower_inclusive": interval.LowerIncl,
		"upper": interval.Upper.String(), "upper_inclusive": interval.UpperIncl,
	}
}

func encodeReductions(reductions []Reduction) []any {
	out := make([]any, 0, len(reductions))
	for _, reduction := range reductions {
		out = append(out, map[string]any{
			"leg": reduction.Leg, "rule": reduction.Rule,
			"tight": reduction.Tight, "reason_code": reduction.ReasonCode,
		})
	}
	return out
}
