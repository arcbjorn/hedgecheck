package lower

import (
	"testing"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
)

func q(t *testing.T, text string) exact.Q {
	t.Helper()
	value, err := exact.ParseQ(text)
	if err != nil {
		t.Fatalf("parse %q: %v", text, err)
	}
	return value
}

// THE PATH DOMAIN IS THE HULL of the terminal domain and where the price starts.
//
// PLAN section 2: "every price between now and the valuation time, so it contains the current
// price and the terminal domain". A baseline OUTSIDE the terminal domain widens it, which is
// right: the path starts there whatever the terminal range says. No bundle exercises that,
// because the 18 September baseline sits inside its domain -- so without this test the hull
// could be replaced by the terminal domain and every fixture would still pass.
func TestPathDomainIsTheHull(t *testing.T) {
	domain := doc.Domain{Lower: q(t, "60000"), Upper: q(t, "110000")}
	for _, each := range []struct {
		name             string
		baseline, lo, hi string
	}{
		{"inside", "77631", "60000", "110000"},
		{"above", "120000", "60000", "120000"},
		{"below", "50000", "50000", "110000"},
	} {
		low, high := pathDomain(domain, q(t, each.baseline))
		if low.String() != each.lo || high.String() != each.hi {
			t.Errorf("a baseline %s the domain gives [%s, %s], want [%s, %s]",
				each.name, low.String(), high.String(), each.lo, each.hi)
		}
	}
}
