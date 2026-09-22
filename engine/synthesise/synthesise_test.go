package synthesise

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"hedgecheck/engine/exact"
	"hedgecheck/engine/pwa"
)

const fixtures = "../../fixtures/synthesis"

func q(t *testing.T, text string) exact.Q {
	t.Helper()
	value, err := exact.ParseQ(text)
	if err != nil {
		t.Fatalf("parse %q: %v", text, err)
	}
	return value
}

type document struct {
	Request struct {
		Objective struct {
			MinPnl string `json:"min_pnl"`
		} `json:"objective"`
		Domain struct {
			Lower string `json:"lower"`
			Upper string `json:"upper"`
		} `json:"domain"`
		Base []struct {
			Kind     string `json:"kind"`
			Quantity string `json:"quantity"`
			Baseline string `json:"baseline"`
			Size     string `json:"size"`
			Amount   string `json:"amount"`
			PaysOn   struct {
				Lower          *string `json:"lower"`
				LowerInclusive bool    `json:"lower_inclusive"`
				Upper          *string `json:"upper"`
				UpperInclusive bool    `json:"upper_inclusive"`
			} `json:"pays_on"`
		} `json:"base"`
		Candidates []struct {
			ID     string `json:"id"`
			Price  string `json:"price"`
			PaysOn struct {
				Lower          *string `json:"lower"`
				LowerInclusive bool    `json:"lower_inclusive"`
				Upper          *string `json:"upper"`
				UpperInclusive bool    `json:"upper_inclusive"`
			} `json:"pays_on"`
		} `json:"candidates"`
		Lot string `json:"lot"`
	} `json:"request"`
	Status  string   `json:"status"`
	Cost    string   `json:"cost"`
	Relaxed []string `json:"relaxed"`
	Sizes   []struct {
		Candidate string `json:"candidate"`
		Size      string `json:"size"`
	} `json:"sizes"`
}

type paysOn struct {
	Lower          *string
	LowerInclusive bool
	Upper          *string
	UpperInclusive bool
}

func bounds(t *testing.T, on paysOn) (pwa.Bound, pwa.Bound) {
	t.Helper()
	lo, hi := pwa.NegInf(), pwa.PosInf()
	if on.Lower != nil {
		lo = pwa.Finite(q(t, *on.Lower), on.LowerInclusive)
	}
	if on.Upper != nil {
		hi = pwa.Finite(q(t, *on.Upper), on.UpperInclusive)
	}
	return lo, hi
}

// GO SOLVES THE ORACLE'S QUESTIONS, and is held to the STATUS and the RELAXED OPTIMUM COST.
//
// Not to the sizes. A linear program's optimum is unique but its argmin is not, so two
// implementations can return different optimal vertices and both be right -- with two
// candidates at the same price, (1250, 0) and (0, 1250) are both optimal at a relaxed cost of
// 250, and which one comes back depends on the pivot order. Demanding one of them would test
// the pivot rule rather than the arithmetic. What IS determined: whether the program is
// feasible, and what the relaxed optimum costs. Both are checked here, and the sizes Go
// returns are then checked VALID against the rows rather than compared to the oracle's.
func TestAgreesWithTheOracleOnSynthesis(t *testing.T) {
	// The hand-written cases AND the generated ones. The five hand-written questions are
	// good questions, but they are questions somebody thought to ask; the generated ones are
	// not, so the three implementations are held to agreeing on programs none of their
	// authors saw. Evaluation has had that since T2 (320 cases); synthesis has it now.
	hand, err := filepath.Glob(filepath.Join(fixtures, "good-*.json"))
	if err != nil {
		t.Fatal(err)
	}
	drawn, err := filepath.Glob(filepath.Join(fixtures, "case-*.json"))
	if err != nil {
		t.Fatal(err)
	}
	matches := append(hand, drawn...)
	if len(matches) == 0 {
		t.Fatal("no synthesis fixtures found. They are generated, not committed: run `make generated`")
	}
	if len(hand) < 4 {
		t.Fatalf("only %d hand-written fixtures; the set is meant to cover every status", len(hand))
	}
	if len(drawn) < 50 {
		t.Fatalf("only %d generated questions; the corpus is meant to be broad", len(drawn))
	}
	seen := map[string]int{}
	for _, path := range matches {
		name := strings.TrimSuffix(filepath.Base(path), ".json")
		t.Run(name, func(t *testing.T) {
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			var parsed document
			if err := json.Unmarshal(raw, &parsed); err != nil {
				t.Fatal(err)
			}

			parts := []pwa.Fn{}
			for _, part := range parsed.Request.Base {
				switch part.Kind {
				case "linear":
					parts = append(parts, pwa.Linear(q(t, part.Quantity), q(t, part.Baseline)))
				case "indicator":
					lo, hi := bounds(t, paysOn(part.PaysOn))
					fn, err := pwa.Indicator(q(t, part.Size), lo, hi)
					if err != nil {
						t.Fatal(err)
					}
					parts = append(parts, fn)
				case "cash":
					parts = append(parts, pwa.Cash(q(t, part.Amount)))
				default:
					t.Fatalf("unsupported base kind %q", part.Kind)
				}
			}
			if len(parts) == 0 {
				parts = append(parts, pwa.Cash(exact.Zero()))
			}
			base := pwa.Sum(parts...)

			units := []pwa.Fn{}
			prices := []exact.Q{}
			for _, candidate := range parsed.Request.Candidates {
				lo, hi := bounds(t, paysOn(candidate.PaysOn))
				fn, err := pwa.Indicator(exact.One(), lo, hi)
				if err != nil {
					t.Fatal(err)
				}
				units = append(units, fn)
				prices = append(prices, q(t, candidate.Price))
			}

			lot := exact.One()
			if parsed.Request.Lot != "" {
				lot = q(t, parsed.Request.Lot)
			}
			floor := q(t, parsed.Request.Objective.MinPnl)
			lower := q(t, parsed.Request.Domain.Lower)
			upper := q(t, parsed.Request.Domain.Upper)

			answer := Synthesise(base, units, prices, floor, lower, upper, lot)
			if answer.Status != parsed.Status {
				t.Fatalf("status %q, the oracle said %q", answer.Status, parsed.Status)
			}
			seen[answer.Status]++

			// THE RELAXED OPTIMUM IS UNIQUE, so it is compared exactly.
			if len(parsed.Relaxed) > 0 {
				oracleRelaxed := exact.Zero()
				for index, text := range parsed.Relaxed {
					oracleRelaxed = oracleRelaxed.Add(prices[index].Mul(q(t, text)))
				}
				if !answer.RelaxedCost.Equal(oracleRelaxed) {
					t.Errorf("relaxed optimum %s, the oracle's relaxed point costs %s",
						answer.RelaxedCost.String(), oracleRelaxed.String())
				}
			}

			// AN INFEASIBLE ANSWER'S CERTIFICATE IS CHECKED, on every generated question and
			// not only on the hand-written one. A Farkas witness is y >= 0 with A^T y <= 0 and
			// b . y > 0; any valid witness proves infeasibility, so this checks validity
			// rather than comparing Go's witness to the oracle's.
			//
			// It also reaches the flipped-row sign. A row flips when the base alone already
			// clears the floor there -- 562 of the corpus's 686 rows -- and 2 of the 64 carried
			// weights sit on one, so the sign correction is exercised here and nowhere else.
			if answer.Status == "infeasible" {
				derived := Rows(base, units, lower, upper)
				byKey := map[string]int{}
				for index, row := range derived {
					byKey[row.Price.String()+"|"+string(row.Side)] = index
				}
				weights := make([]exact.Q, len(derived))
				for index := range weights {
					weights[index] = exact.Zero()
				}
				for _, weight := range answer.Certificate {
					if weight.Weight.Sign() <= 0 {
						t.Errorf("weight at %s (%s) is %s, not strictly positive",
							weight.Price.String(), weight.Side, weight.Weight.String())
					}
					index, known := byKey[weight.Price.String()+"|"+string(weight.Side)]
					if !known {
						t.Fatalf("the certificate names %s (%s), not a row of this program",
							weight.Price.String(), weight.Side)
					}
					weights[index] = weight.Weight
				}
				right := exact.Zero()
				for column := range units {
					total := exact.Zero()
					for index, row := range derived {
						total = total.Add(weights[index].Mul(row.Coefficients[column].Sub(prices[column])))
					}
					if total.Sign() > 0 {
						t.Errorf("column %d of A^T y is %s, positive, so the weights do not cancel",
							column, total.String())
					}
				}
				for index, row := range derived {
					right = right.Add(weights[index].Mul(floor.Sub(row.Alpha)))
				}
				if right.Sign() <= 0 {
					t.Errorf("b . y is %s, not positive, so the rows are not contradictory",
						right.String())
				}
				return
			}
			if answer.Status != "feasible" {
				return
			}

			// THE SIZES ARE CHECKED VALID, not compared: every row, at Go's own answer.
			derived := Rows(base, units, lower, upper)
			for _, row := range derived {
				value := row.Alpha
				for index, size := range answer.Sizes {
					value = value.Add(row.Coefficients[index].Sub(prices[index]).Mul(size))
				}
				if value.Less(floor) {
					t.Errorf("at %s (%s) Go's own answer is worth %s, below the floor of %s",
						row.Price.String(), row.Side, value.String(), floor.String())
				}
			}
			// And they cost no more than the oracle's, so Go is not answering a laxer question.
			if parsed.Cost != "" && q(t, parsed.Cost).Less(answer.Cost) {
				t.Errorf("Go's answer costs %s, the oracle found one at %s",
					answer.Cost.String(), parsed.Cost)
			}
		})
	}
	// Every status is exercised. Without this the suite could pass while only ever seeing the
	// easy one.
	for _, status := range []string{"feasible", "infeasible", "rounding_failed"} {
		if seen[status] == 0 {
			t.Errorf("no fixture exercised the %q status", status)
		}
	}
}

// The rows are the CONSTRAINT SET, and this engine must find the same one the oracle and the
// checker do. Pinned by hand: the PLAN section 3 program is 0.1 BTC from 100,000 over
// [60,000, 110,000] with one digital below 90,000, and its four distinct constraints are the
// domain floor, both sides of the strike, and the domain top.
func TestRowsAreTheFourDistinctConstraints(t *testing.T) {
	base := pwa.Linear(q(t, "0.1"), q(t, "100000"))
	unit, err := pwa.Indicator(exact.One(), pwa.NegInf(), pwa.Finite(q(t, "90000"), false))
	if err != nil {
		t.Fatal(err)
	}
	got := [][]string{}
	for _, row := range Rows(base, []pwa.Fn{unit}, q(t, "60000"), q(t, "110000")) {
		got = append(got, []string{row.Price.String(), string(row.Side),
			row.Alpha.String(), row.Coefficients[0].String()})
	}
	want := [][]string{
		{"60000", "at", "-4000", "1"},
		{"90000", "at", "-1000", "0"},
		{"90000", "below", "-1000", "1"},
		{"110000", "at", "1000", "0"},
	}
	if len(got) != len(want) {
		t.Fatalf("%d rows, want %d: %v", len(got), len(want), got)
	}
	for index := range want {
		for field := range want[index] {
			if got[index][field] != want[index][field] {
				t.Errorf("row %d: got %v, want %v", index, got[index], want[index])
				break
			}
		}
	}
}

// A LIMIT ROW'S VALUE IS A LIMIT, not the value at the price.
//
// Below the strike one contract pays 1; at the strike it pays nothing. Reading the point value
// for the `below` row would make the constraint say the protection is gone where it is still
// paying -- which is the bug the TypeScript checker had before it was written this way.
func TestLimitRowsAreLimits(t *testing.T) {
	base := pwa.Linear(q(t, "0.1"), q(t, "100000"))
	unit, err := pwa.Indicator(exact.One(), pwa.NegInf(), pwa.Finite(q(t, "90000"), false))
	if err != nil {
		t.Fatal(err)
	}
	found := map[string]string{}
	for _, row := range Rows(base, []pwa.Fn{unit}, q(t, "60000"), q(t, "110000")) {
		if row.Price.String() == "90000" {
			found[string(row.Side)] = row.Coefficients[0].String()
		}
	}
	if found["below"] != "1" {
		t.Errorf("just below the strike one contract pays %q, want 1", found["below"])
	}
	if found["at"] != "0" {
		t.Errorf("at the strike one contract pays %q, want 0", found["at"])
	}
}

// A JUMPING BASE'S LIMIT ROW IS A LIMIT TOO, and dropping it loses a constraint.
//
// A position already held jumps at its own strike: 500 contracts paying below 85,000 means the
// base is 0.1*(85,000-100,000) = -1,500 at 85,000 and -1,000 just below it. Reading the point
// value for the `below` row makes the two collapse into one as duplicates, so the constraint
// where the held protection still pays is simply gone -- and a program is then solved against
// fewer rows than the objective has.
func TestAJumpingBaseKeepsItsLimitRow(t *testing.T) {
	held, err := pwa.Indicator(q(t, "500"), pwa.NegInf(), pwa.Finite(q(t, "85000"), false))
	if err != nil {
		t.Fatal(err)
	}
	base := pwa.Sum(pwa.Linear(q(t, "0.1"), q(t, "100000")), held)
	unit, err := pwa.Indicator(exact.One(), pwa.NegInf(), pwa.Finite(q(t, "90000"), false))
	if err != nil {
		t.Fatal(err)
	}
	found := map[string]string{}
	for _, row := range Rows(base, []pwa.Fn{unit}, q(t, "60000"), q(t, "110000")) {
		if row.Price.String() == "85000" {
			found[string(row.Side)] = row.Alpha.String()
		}
	}
	if found["at"] != "-1500" {
		t.Errorf("at the held strike the base is %q, want -1500", found["at"])
	}
	if found["below"] != "-1000" {
		t.Errorf("just below it the base is %q, want -1000 (the held position still pays)", found["below"])
	}
}

// The certificate this engine produces is a valid Farkas witness: y >= 0, A^T y <= 0 and
// b . y > 0. Checked here rather than compared to the oracle's, because any valid witness
// proves infeasibility and two implementations need not find the same one.
func TestCertificateIsAValidFarkasWitness(t *testing.T) {
	base := pwa.Linear(q(t, "0.1"), q(t, "100000"))
	unit, err := pwa.Indicator(exact.One(), pwa.NegInf(), pwa.Finite(q(t, "90000"), false))
	if err != nil {
		t.Fatal(err)
	}
	units := []pwa.Fn{unit}
	prices := []exact.Q{q(t, "0.2")}
	floor := q(t, "-1000")
	lower, upper := q(t, "60000"), q(t, "110000")

	answer := Synthesise(base, units, prices, floor, lower, upper, exact.One())
	if answer.Status != "infeasible" {
		t.Fatalf("the PLAN section 3 example is infeasible, got %q", answer.Status)
	}
	if len(answer.Certificate) == 0 {
		t.Fatal("an infeasible answer carries no certificate")
	}

	derived := Rows(base, units, lower, upper)
	byKey := map[string]int{}
	for index, row := range derived {
		byKey[row.Price.String()+"|"+string(row.Side)] = index
	}
	weights := make([]exact.Q, len(derived))
	for index := range weights {
		weights[index] = exact.Zero()
	}
	for _, weight := range answer.Certificate {
		if weight.Weight.Sign() <= 0 {
			t.Errorf("weight at %s (%s) is %s, not strictly positive",
				weight.Price.String(), weight.Side, weight.Weight.String())
		}
		index, known := byKey[weight.Price.String()+"|"+string(weight.Side)]
		if !known {
			t.Fatalf("the certificate names %s (%s), which is not a row of this program",
				weight.Price.String(), weight.Side)
		}
		weights[index] = weight.Weight
	}

	column := exact.Zero()
	right := exact.Zero()
	for index, row := range derived {
		net := row.Coefficients[0].Sub(prices[0])
		column = column.Add(weights[index].Mul(net))
		right = right.Add(weights[index].Mul(floor.Sub(row.Alpha)))
	}
	if column.Sign() > 0 {
		t.Errorf("A^T y is %s, which is positive, so the weights do not cancel the sizes",
			column.String())
	}
	if right.Sign() <= 0 {
		t.Errorf("b . y is %s, which is not positive, so the rows are not contradictory",
			right.String())
	}
}

// DEGENERATE OPTIMA ARE REAL, which is why the conformance bar is the cost and not the sizes.
// Two candidates with the same payoff at the same price: any split of the total is optimal, so
// the argmin is a choice the pivot rule makes and the cost is the fact.
func TestTheRelaxedCostIsDeterminedWhereTheSizesAreNot(t *testing.T) {
	base := pwa.Linear(q(t, "0.1"), q(t, "100000"))
	one, err := pwa.Indicator(exact.One(), pwa.NegInf(), pwa.Finite(q(t, "90000"), false))
	if err != nil {
		t.Fatal(err)
	}
	prices := []exact.Q{q(t, "0.2"), q(t, "0.2")}
	answer := Synthesise(base, []pwa.Fn{one, one}, prices, q(t, "-3000"),
		q(t, "60000"), q(t, "110000"), exact.One())
	if answer.Status != "feasible" {
		t.Fatalf("status %q, want feasible", answer.Status)
	}
	// Hand-derived: 1,250 contracts at 0.20 costs 250, and any split of the 1,250 between two
	// identical instruments costs the same.
	if answer.RelaxedCost.String() != "250" {
		t.Errorf("relaxed cost %s, want 250", answer.RelaxedCost.String())
	}
	total := exact.Zero()
	for _, size := range answer.Sizes {
		total = total.Add(size)
	}
	if total.String() != "1250" {
		t.Errorf("the sizes total %s, want 1250 however they are split", total.String())
	}
}
