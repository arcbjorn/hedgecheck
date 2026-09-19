package pwa

import (
	"testing"

	"hedgecheck/engine/exact"
)

func q(s string) exact.Q { return exact.MustParseQ(s) }

func TestInfimumReportsAnAttainedPrice(t *testing.T) {
	ind, _ := Indicator(q("700"), NegInf(), Finite(q("90000"), true))
	f := ind.Add(Cash(q("-100")))
	value, attained, at := f.Infimum(q("60000"), q("110000"))
	t.Logf("value=%s attained=%v at=%s f(at)=%s", value, attained, at, f.At(at))
	if attained && !f.At(at).Equal(value) {
		t.Fatalf("reported %s as attaining %s, but f there is %s", at, value, f.At(at))
	}
}

func TestBelowAndWitness(t *testing.T) {
	// The golden case: 0.1 from 100000, digital below 90000 paying 1000, less 200.
	ind, _ := Indicator(q("1000"), NegInf(), Finite(q("90000"), false))
	f := Sum(Linear(q("0.1"), q("100000")), ind, Cash(q("-200")))
	got := f.Below(q("-1000"), q("60000"), q("110000"))
	for _, iv := range got {
		price, value := f.Witness(iv)
		t.Logf("[%s%s, %s%s] witness %s -> %s", incl(iv.LoInclusive), iv.Lo, iv.Hi, incl2(iv.HiInclusive), price, value)
	}
	if len(got) != 2 {
		t.Fatalf("want 2 failing intervals, got %d", len(got))
	}
	if got[0].Lo.String() != "60000" || got[0].Hi.String() != "82000" || got[0].HiInclusive {
		t.Errorf("first interval wrong: %v", got[0])
	}
	if got[1].Lo.String() != "90000" || !got[1].LoInclusive || got[1].Hi.String() != "92000" || got[1].HiInclusive {
		t.Errorf("second interval wrong: %v", got[1])
	}
	if v, _, at := f.Infimum(q("60000"), q("110000")); v.String() != "-3200" || at.String() != "60000" {
		t.Errorf("infimum %s at %s, want -3200 at 60000", v, at)
	}
}

func incl(b bool) string {
	if b {
		return "["
	}
	return "("
}
func incl2(b bool) string {
	if b {
		return "]"
	}
	return ")"
}

func TestSizeWindowMatchesThePins(t *testing.T) {
	// bucket0: 0.1 from 77631.4, digital below 75908, the retained ladder.
	base := Linear(q("0.1"), q("77631.4"))
	unit, _ := Indicator(q("1"), NegInf(), Finite(q("75908"), false))
	levels := []Level{{q("0.17399"), q("1200")}, {q("0.174"), q("1200")}, {q("0.99999"), q("100000")}}
	win, err := SizeWindowFor(base, unit, levels, q("-1000"), q("60000"), q("110000"), exact.One())
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("smallest=%s largest=%s lower=%s upper=%s binding=%v",
		win.Smallest, win.Largest, win.LowerBound, win.UpperBound, win.Binding)
	if win.Smallest.String() != "924" || win.Largest.String() != "2810" {
		t.Errorf("window %s..%s, want 924..2810", win.Smallest, win.Largest)
	}
	if win.LowerBound.String() != "76314000/82601" || win.UpperBound.String() != "281004800/99999" {
		t.Errorf("bounds %s and %s", win.LowerBound, win.UpperBound)
	}
}

func TestBandInfimumShrinksTheMiddleBucket(t *testing.T) {
	P1, P2, n, band := q("75908"), q("79007"), q("924"), q("50")
	mid, _ := Indicator(n, Finite(P1, true), Finite(P2, false))
	reduced, err := mid.BandInfimum(band)
	if err != nil {
		t.Fatal(err)
	}
	for _, row := range []struct{ at, want string }{
		{"75907", "0"}, {"75908", "0"}, {"75957", "0"}, {"75958", "924"},
		{"78956", "924"}, {"78957", "0"}, {"79006", "0"},
	} {
		if got := reduced.At(q(row.at)); got.String() != row.want {
			t.Errorf("band infimum at %s = %s, want %s", row.at, got, row.want)
		}
	}
}
