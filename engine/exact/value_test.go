package exact

import (
	"testing"
)

// The property Q exists for: sharing a value can never let one holder change it for
// another. With *big.Rat, `a.Add(a, b)` rewrites a in place and every alias sees it.
func TestQIsImmutableUnderSharing(t *testing.T) {
	a := MustParseQ("1.5")
	alias := a
	stored := []Q{a, a, a}

	sum := a.Add(MustParseQ("100"))
	product := a.Mul(MustParseQ("7"))
	negated := a.Neg()
	_, _ = a.Div(MustParseQ("3"))

	for name, got := range map[string]Q{"original": a, "alias": alias, "stored[1]": stored[1]} {
		if got.String() != "1.5" {
			t.Fatalf("%s changed to %s after arithmetic on a shared value", name, got)
		}
	}
	if sum.String() != "101.5" || product.String() != "10.5" || negated.String() != "-1.5" {
		t.Fatalf("results wrong: sum=%s product=%s negated=%s", sum, product, negated)
	}
}

// A Q handed out must not expose a pointer anything can write through. The only way in
// is rat(), which copies; this checks that the copy is independent of the stored value.
func TestQDoesNotLeakItsPointer(t *testing.T) {
	q := MustParseQ("2/3")
	escaped := q.rat()
	escaped.SetInt64(99)
	if q.String() != "2/3" {
		t.Fatalf("writing through a returned rat changed the Q: %s", q)
	}
}

func TestZeroQIsZero(t *testing.T) {
	var zero Q
	if zero.Sign() != 0 || zero.String() != "0" {
		t.Fatalf("the zero Q is not zero: sign=%d string=%s", zero.Sign(), zero)
	}
	if got := zero.Add(MustParseQ("5")); got.String() != "5" {
		t.Fatalf("arithmetic on the zero Q: %s", got)
	}
}

func TestDivByZeroReportsRatherThanPanics(t *testing.T) {
	if _, ok := MustParseQ("1").Div(Zero()); ok {
		t.Fatal("division by zero reported success")
	}
}

func TestCompareAndSelect(t *testing.T) {
	small, large := MustParseQ("-2.5"), MustParseQ("0.1")
	if !small.Less(large) || large.LessEqual(small) || !small.Equal(MustParseQ("-2.5")) {
		t.Fatal("comparison is wrong")
	}
	if Min(small, large).String() != "-2.5" || Max(small, large).String() != "0.1" {
		t.Fatal("min or max is wrong")
	}
}

// Rounding to a lot is exact and signed correctly. big.Int truncates toward zero, so
// negatives are where a naive implementation goes wrong.
func TestFloorAndCeilToLot(t *testing.T) {
	one := One()
	for _, row := range []struct{ in, floor, ceil string }{
		{"1409", "1409", "1409"},
		{"1408.0001", "1408", "1409"},
		{"1408.9999", "1408", "1409"},
		{"-0.5", "-1", "0"},
		{"-3", "-3", "-3"},
		{"-3.2", "-4", "-3"},
		{"0", "0", "0"},
		{"18172417/12899", "1408", "1409"},
	} {
		floor, ok := MustParseQ(row.in).FloorLot(one)
		if !ok || floor.String() != row.floor {
			t.Fatalf("floor(%s) = %s, want %s", row.in, floor, row.floor)
		}
		ceil, ok := MustParseQ(row.in).CeilLot(one)
		if !ok || ceil.String() != row.ceil {
			t.Fatalf("ceil(%s) = %s, want %s", row.in, ceil, row.ceil)
		}
	}
	if _, ok := MustParseQ("5").FloorLot(Zero()); ok {
		t.Fatal("a zero lot reported success")
	}
	if _, ok := MustParseQ("5").FloorLot(MustParseQ("-1")); ok {
		t.Fatal("a negative lot reported success")
	}
}

// A lot larger than one contract still rounds to a multiple of the lot.
func TestLotLargerThanOne(t *testing.T) {
	lot := MustParseQ("25")
	floor, _ := MustParseQ("1409").FloorLot(lot)
	ceil, _ := MustParseQ("1409").CeilLot(lot)
	if floor.String() != "1400" || ceil.String() != "1425" {
		t.Fatalf("lot 25: floor=%s ceil=%s", floor, ceil)
	}
}

// Parsing goes through the grammar, not big.Rat's own reader.
func TestParseQEnforcesTheGrammar(t *testing.T) {
	for _, bad := range []string{"0x10", "1e3", "+5", ".5", "1_000", "05", " 5", "5\n", "1/0"} {
		if _, err := ParseQ(bad); err == nil {
			t.Fatalf("%q was accepted", bad)
		}
	}
	for _, good := range []string{"0", "-0", "1409", "0.00001", "8072113/17612500", "-999.90904"} {
		if _, err := ParseQ(good); err != nil {
			t.Fatalf("%q was refused: %v", good, err)
		}
	}
}
