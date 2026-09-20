package evaluate

import (
	"os"
	"path/filepath"
	"sort"
	"testing"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
)

// A loose bound can make a proposal need review; it can never fail one.
//
// This is the most safety-critical invariant in the engine: `fails` is the only
// verdict that condemns, and it must rest on something the engine actually
// established. Until now it was held by ONE Python fixture -- the horizon case,
// re-run with its rule made loose. That checks the rule in one place; this checks it
// everywhere, by taking every generated case that HAS a reduction and loosening it.
//
// Loosening can only ever remove information. A verdict that moves to `fails`
// because the engine knows LESS would be the engine condemning a hedge on the
// strength of its own ignorance.
func TestAuditLooseningNeverCondemns(t *testing.T) {
	files, err := filepath.Glob("../../fixtures/generated/ir/*.ir.json")
	if err != nil || len(files) == 0 {
		t.Skipf("no generated IR cases: %v", err)
	}
	sort.Strings(files)

	loosened, checked := 0, 0
	for _, path := range files {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		ir, err := doc.ReadIR(raw)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		before, err := Evaluate(ir)
		if err != nil {
			continue
		}
		checked++

		// Loosen every tight reduction this case has.
		anyTight := false
		relaxed := ir
		relaxed.Reductions = append([]doc.Reduction(nil), ir.Reductions...)
		for index := range relaxed.Reductions {
			if relaxed.Reductions[index].Tight {
				relaxed.Reductions[index].Tight = false
				anyTight = true
			}
		}
		if !anyTight {
			continue
		}
		loosened++

		after, err := Evaluate(relaxed)
		if err != nil {
			t.Errorf("%s: loosening made the case unevaluable: %v", filepath.Base(path), err)
			continue
		}
		if after.ModelResult == "fails" && before.ModelResult != "fails" {
			t.Errorf("%s: loosening a bound moved the verdict from %s to fails. "+
				"A bound that establishes LESS cannot condemn more.",
				filepath.Base(path), before.ModelResult)
		}
		// A loose result must not claim a failing interval either: that is the
		// document saying it found a price where the objective is broken.
		if after.ModelResult == "needs_review" && len(after.FailingIntervals) > 0 {
			t.Errorf("%s: a needs_review result carries %d failing intervals",
				filepath.Base(path), len(after.FailingIntervals))
		}
	}
	t.Logf("evaluated %d cases, loosened %d of them", checked, loosened)
	if loosened < 10 {
		t.Errorf("only %d cases had a tight reduction to loosen; "+
			"the invariant is barely being exercised", loosened)
	}
}

// The other half of the same rule, stated correctly.
//
// A first attempt asserted that a failing verdict may carry no loose reduction at
// all. That is wrong, and the engine was right: a proposal CAN fail while holding a
// loose leg, as long as the failure does not depend on the loose part. The engine
// establishes this with the UPPER profile -- the best the proposal could possibly be,
// crediting every reduced leg with its full size. If the objective breaks even there,
// nothing the loose leg turns out to be worth can rescue it.
//
// So the real invariant is: wherever a result fails, its own upper profile must also
// break the objective at the witness. That is what makes the verdict established
// rather than assumed.
func TestAuditFailsIsEstablishedOnTheUpperProfile(t *testing.T) {
	files, err := filepath.Glob("../../fixtures/generated/ir/*.ir.json")
	if err != nil || len(files) == 0 {
		t.Skipf("no generated IR cases: %v", err)
	}
	sort.Strings(files)

	failing := 0
	for _, path := range files {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		ir, err := doc.ReadIR(raw)
		if err != nil {
			continue
		}
		result, err := Evaluate(ir)
		if err != nil || result.ModelResult != "fails" {
			continue
		}
		failing++
		hasLoose := false
		for _, reduction := range result.Reductions {
			if !reduction.Tight {
				hasLoose = true
			}
		}
		if !hasLoose {
			continue
		}
		// A failure resting on a loosely reduced leg must carry the upper profile
		// that establishes it, and a witness that says which adverse states it
		// assumed. Without those, the verdict would be an assumption.
		if len(result.UpperProfile) == 0 {
			t.Errorf("%s: fails while holding a loose reduction but carries no upper profile",
				filepath.Base(path))
			continue
		}
		for _, interval := range result.FailingIntervals {
			if len(interval.Witness.AdverseStates) == 0 {
				t.Errorf("%s: a failing interval names no adverse state, though a leg was reduced loosely",
					filepath.Base(path))
				break
			}
			// The witness must be admissible on the UPPER profile: the objective
			// breaks even when every reduced leg is credited in full.
			best := valueOn(result.UpperProfile, interval.Witness.Price)
			if best.Sign() == 0 && interval.Witness.Pnl.Sign() == 0 {
				continue
			}
			if !best.Less(minPnlFor(ir, interval.Clause)) {
				t.Errorf("%s: at the witness %s the upper profile gives %s, which meets the clause. "+
					"The failure rests on the loose bound rather than on what was established.",
					filepath.Base(path), interval.Witness.Price, best)
			}
		}
	}
	t.Logf("checked %d failing verdicts", failing)
	if failing == 0 {
		t.Error("no case failed, so this test established nothing")
	}
}

// And the third: every undecided interval names the loose legs it rests on, so a
// reader can see WHY nothing was established there rather than being told to trust it.
func TestAuditUndecidedIntervalsNameTheirLooseLegs(t *testing.T) {
	files, err := filepath.Glob("../../fixtures/generated/ir/*.ir.json")
	if err != nil || len(files) == 0 {
		t.Skipf("no generated IR cases: %v", err)
	}
	sort.Strings(files)

	seen := 0
	for _, path := range files {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		ir, err := doc.ReadIR(raw)
		if err != nil {
			continue
		}
		result, err := Evaluate(ir)
		if err != nil {
			continue
		}
		for _, interval := range result.UndecidedIntervals {
			seen++
			if len(interval.ResponsibleLegs) == 0 {
				t.Errorf("%s: an undecided interval names no responsible leg",
					filepath.Base(path))
				continue
			}
			// Each named leg is genuinely one the result reduced loosely.
			looseLegs := map[string]bool{}
			for _, reduction := range result.Reductions {
				if !reduction.Tight {
					looseLegs[reduction.Leg] = true
				}
			}
			for _, leg := range interval.ResponsibleLegs {
				if !looseLegs[leg] {
					t.Errorf("%s: an undecided interval blames %s, which was not reduced loosely",
						filepath.Base(path), leg)
				}
			}
		}
	}
	t.Logf("checked %d undecided intervals", seen)
	if seen == 0 {
		t.Error("no undecided interval was produced, so this test established nothing")
	}
}

// valueOn evaluates a piecewise profile at a price, exactly.
func valueOn(pieces []doc.Piece, price exact.Q) exact.Q {
	for _, piece := range pieces {
		if price.Less(piece.Lower) || piece.Upper.Less(price) {
			continue
		}
		if price.Equal(piece.Lower) && !piece.LowerIncl {
			continue
		}
		if price.Equal(piece.Upper) && !piece.UpperIncl {
			continue
		}
		return piece.Slope.Mul(price).Add(piece.Intercept)
	}
	return exact.Zero()
}

// minPnlFor is the floor the named clause states.
func minPnlFor(ir doc.IR, clause string) exact.Q {
	for _, candidate := range ir.Objective {
		if candidate.ID == clause {
			return candidate.MinPnl
		}
	}
	return exact.Zero()
}
