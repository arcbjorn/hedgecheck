package pwa

import (
	"encoding/json"
	"os"
	"testing"

	"hedgecheck/engine/exact"
)

// The generated agreement fixture. Go builds every function through its own
// constructors from the leg description, so this compares two implementations rather
// than handing one the other's answer.
type kernelCase struct {
	Name      string          `json:"name"`
	Legs      []legSpec       `json:"legs"`
	BaseLegs  []legSpec       `json:"base_legs"`
	UnitLegs  []legSpec       `json:"unit_legs"`
	Query     string          `json:"query"`
	Lower     string          `json:"lower"`
	Upper     string          `json:"upper"`
	Threshold string          `json:"threshold"`
	Cuts      []string        `json:"cuts"`
	Band      string          `json:"band"`
	Probes    []string        `json:"probes"`
	Levels    [][2]string     `json:"levels"`
	Size      string          `json:"size"`
	FloorPnl  string          `json:"floor_pnl"`
	Answer    json.RawMessage `json:"answer"`
}

type legSpec struct {
	Kind           string `json:"kind"`
	Quantity       string `json:"quantity"`
	Baseline       string `json:"baseline"`
	Amount         string `json:"amount"`
	Size           string `json:"size"`
	Lower          string `json:"lower"`
	LowerInclusive bool   `json:"lower_inclusive"`
	Upper          string `json:"upper"`
	UpperInclusive bool   `json:"upper_inclusive"`
	Low            string `json:"low"`
	High           string `json:"high"`
	HasLower       bool   `json:"-"`
	HasUpper       bool   `json:"-"`
}

// UnmarshalJSON records whether the optional bounds were present at all. An absent
// bound is unbounded; a present one owns its price or does not.
func (l *legSpec) UnmarshalJSON(raw []byte) error {
	type plain legSpec
	var probe map[string]json.RawMessage
	if err := json.Unmarshal(raw, &probe); err != nil {
		return err
	}
	var out plain
	if err := json.Unmarshal(raw, &out); err != nil {
		return err
	}
	*l = legSpec(out)
	_, l.HasLower = probe["lower"]
	_, l.HasUpper = probe["upper"]
	return nil
}

func buildFn(t *testing.T, legs []legSpec) Fn {
	t.Helper()
	parts := []Fn{}
	for _, leg := range legs {
		switch leg.Kind {
		case "linear":
			parts = append(parts, Linear(q(leg.Quantity), q(leg.Baseline)))
		case "cash":
			parts = append(parts, Cash(q(leg.Amount)))
		case "indicator":
			lo, hi := NegInf(), PosInf()
			if leg.HasLower {
				lo = Finite(q(leg.Lower), leg.LowerInclusive)
			}
			if leg.HasUpper {
				hi = Finite(q(leg.Upper), leg.UpperInclusive)
			}
			fn, err := Indicator(q(leg.Size), lo, hi)
			if err != nil {
				t.Fatalf("indicator: %v", err)
			}
			parts = append(parts, fn)
		case "ramp_long":
			fn, err := RampLong(q(leg.Size), q(leg.Low), q(leg.High))
			if err != nil {
				t.Fatalf("ramp_long: %v", err)
			}
			parts = append(parts, fn)
		case "ramp_short":
			fn, err := RampShort(q(leg.Size), q(leg.Low), q(leg.High))
			if err != nil {
				t.Fatalf("ramp_short: %v", err)
			}
			parts = append(parts, fn)
		default:
			t.Fatalf("unknown leg kind %q", leg.Kind)
		}
	}
	return Sum(parts...)
}

func levelsOf(rows [][2]string) []Level {
	out := make([]Level, 0, len(rows))
	for _, row := range rows {
		out = append(out, Level{Price: q(row[0]), Size: q(row[1])})
	}
	return out
}

func TestAgreesWithTheOracle(t *testing.T) {
	raw, err := os.ReadFile("../../fixtures/kernel/cases.json")
	if err != nil {
		t.Fatalf("read cases: %v", err)
	}
	var file struct {
		Cases []kernelCase `json:"cases"`
	}
	if err := json.Unmarshal(raw, &file); err != nil {
		t.Fatalf("parse cases: %v", err)
	}
	if len(file.Cases) < 400 {
		t.Fatalf("only %d cases; the fixture is meant to be broad", len(file.Cases))
	}

	for _, kase := range file.Cases {
		t.Run(kase.Name, func(t *testing.T) {
			got := runCase(t, kase)
			want := normalise(t, kase.Answer)
			if got != want {
				t.Errorf("disagreement\n  go     %s\n  oracle %s", got, want)
			}
		})
	}
}

// runCase answers one case and renders the answer as canonical JSON, so comparison is
// on bytes rather than on a shape that might differ by field order.
func runCase(t *testing.T, kase kernelCase) string {
	t.Helper()
	switch kase.Query {
	case "profile":
		fn := buildFn(t, kase.Legs)
		return render(t, piecesJSON(fn.Profile(q(kase.Lower), q(kase.Upper))))
	case "infimum":
		fn := buildFn(t, kase.Legs)
		value, attained, at := fn.Infimum(q(kase.Lower), q(kase.Upper))
		return render(t, map[string]any{"value": value.String(), "attained": attained, "at": at.String()})
	case "below":
		fn := buildFn(t, kase.Legs)
		cuts := make([]exact.Q, 0, len(kase.Cuts))
		for _, cut := range kase.Cuts {
			cuts = append(cuts, q(cut))
		}
		return render(t, intervalsJSON(fn.Below(q(kase.Threshold), q(kase.Lower), q(kase.Upper), cuts...)))
	case "witness":
		fn := buildFn(t, kase.Legs)
		out := []map[string]string{}
		for _, interval := range fn.Below(q(kase.Threshold), q(kase.Lower), q(kase.Upper)) {
			price, value := fn.Witness(interval)
			out = append(out, map[string]string{"price": price.String(), "pnl": value.String()})
		}
		return render(t, out)
	case "band":
		fn := buildFn(t, kase.Legs)
		reduced, err := fn.BandInfimum(q(kase.Band))
		if err != nil {
			t.Fatalf("band infimum: %v", err)
		}
		out := []map[string]string{}
		for _, probe := range kase.Probes {
			out = append(out, map[string]string{"at": q(probe).String(), "value": reduced.At(q(probe)).String()})
		}
		return render(t, out)
	case "ask_cost":
		cost, covered := AskCost(levelsOf(kase.Levels), q(kase.Size))
		answer := map[string]any{"covered": covered, "total": nil}
		if covered {
			answer["total"] = cost.String()
		}
		return render(t, answer)
	case "size_window":
		base, unit := buildFn(t, kase.BaseLegs), buildFn(t, kase.UnitLegs)
		window, err := SizeWindowFor(base, unit, levelsOf(kase.Levels), q(kase.FloorPnl),
			q(kase.Lower), q(kase.Upper), exact.One())
		if err != nil {
			t.Fatalf("size window: %v", err)
		}
		answer := map[string]any{"status": "nonempty", "binding": []map[string]string{}}
		if window.Empty {
			answer["status"] = "empty"
		}
		binding := []map[string]string{}
		for _, site := range window.Binding {
			binding = append(binding, map[string]string{"price": site.Price.String(), "side": site.Side})
		}
		answer["binding"] = binding
		if !window.Empty || window.HasWhole || window.LowerBound.Sign() != 0 || window.UpperBound.Sign() != 0 {
			if len(window.Binding) > 0 || window.HasWhole || !window.Empty {
				answer["lower_bound"] = window.LowerBound.String()
				answer["upper_bound"] = window.UpperBound.String()
			}
		}
		if window.HasWhole {
			answer["smallest"] = window.Smallest.String()
			answer["largest"] = window.Largest.String()
		}
		return render(t, answer)
	}
	t.Fatalf("unknown query %q", kase.Query)
	return ""
}

func piecesJSON(pieces []Piece) []map[string]any {
	out := []map[string]any{}
	for _, piece := range pieces {
		out = append(out, map[string]any{
			"lower": piece.Lo.Value.String(), "lower_inclusive": piece.Lo.Closed,
			"upper": piece.Hi.Value.String(), "upper_inclusive": piece.Hi.Closed,
			"slope": piece.Slope.String(), "intercept": piece.Intercept.String(),
		})
	}
	return out
}

func intervalsJSON(intervals []Interval) []map[string]any {
	out := []map[string]any{}
	for _, interval := range intervals {
		out = append(out, map[string]any{
			"lower": interval.Lo.String(), "lower_inclusive": interval.LoInclusive,
			"upper": interval.Hi.String(), "upper_inclusive": interval.HiInclusive,
		})
	}
	return out
}

func render(t *testing.T, value any) string {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("render: %v", err)
	}
	return normalise(t, raw)
}

// normalise re-encodes through a generic value so both sides are compared with the
// same key ordering and number formatting.
func normalise(t *testing.T, raw []byte) string {
	t.Helper()
	var value any
	if err := json.Unmarshal(raw, &value); err != nil {
		t.Fatalf("normalise: %v", err)
	}
	out, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("normalise: %v", err)
	}
	return string(out)
}
