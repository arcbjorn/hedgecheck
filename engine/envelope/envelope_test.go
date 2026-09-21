package envelope

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/evaluate"
	"hedgecheck/engine/exact"
	"hedgecheck/engine/lower"
)

// The pins.
//
// HAND-DERIVED from the retained books in fixtures/replay/2026-09-18/, not read out of
// this package, the oracle or the TypeScript checker. Any of the three could be wrong
// in the same way; a constant transcribed from one of them would not notice.
//
// 18 Sep bucket, book-bucket0-3971-yes.json, asks 0.17399 x 1200, 0.174 x 1200,
// 0.99999 x 100000. 924 <= 1200, so the whole order fills in the first level and that
// level is the highest the walk touches. 924 x 17399 = 900 x 17399 + 24 x 17399 =
// 15659100 + 417576 = 16076676, in units of 1e-5, so 160.76676.
//
// 18 Sep binary, book-3965-no.json. The cumulative ask sizes are 36, 151, 1151, 1192,
// 1232, 1253, 1293, 1333, 1383, and 1383 < 1409, so the last 26 come from the next
// level, 0.48404 x 3918 -- which is therefore the highest the walk touches. In units
// of 1e-5 the ladder costs
//
//	36 x 45100 =  1623600      40 x 47000 =  1880000
//	115 x 45250 =  5203750      40 x 48000 =  1920000
//	1000 x 45600 = 45600000      50 x 48123 =  2406150
//	41 x 45750 =  1875750      26 x 48404 =  1258504
//	40 x 46000 =  1840000
//	21 x 46150 =   969150
//
// summing to 1623600 + 5203750 = 6827350, + 45600000 = 52427350, + 1875750 = 54303100,
// + 1840000 = 56143100, + 969150 = 57112250, + 1880000 = 58992250, + 1920000 =
// 60912250, + 2406150 = 63318400, + 1258504 = 64576904, so 645.76904.
var pins = map[string]struct {
	coin, limit, maxCost, size string
}{
	"bucket0.proposal.json": {coin: "#39710", limit: "0.17399", maxCost: "160.76676", size: "924"},
	"binary.proposal.json":  {coin: "#39651", limit: "0.48404", maxCost: "645.76904", size: "1409"},
}

const replay = "../../fixtures/replay/2026-09-18"

func reviewedRegistry(t *testing.T) map[string]doc.Entry {
	t.Helper()
	matches, _ := filepath.Glob("../../registry/*.json")
	if len(matches) == 0 {
		t.Fatal("no registry entries")
	}
	out := map[string]doc.Entry{}
	for _, path := range matches {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		entry, err := doc.ReadEntry(raw)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		version, err := entry.SemanticsVersion()
		if err != nil {
			t.Fatal(err)
		}
		entry.SetReviewed("fixture", "2026-09-19", version)
		out[entry.Family] = entry
	}
	return out
}

func replaySnapshots(t *testing.T) lower.Snapshots {
	t.Helper()
	out := lower.Snapshots{}
	matches, _ := filepath.Glob(filepath.Join(replay, "*.json"))
	for _, path := range matches {
		name := filepath.Base(path)
		if strings.HasSuffix(name, ".request.json") || strings.HasSuffix(name, ".proposal.json") ||
			strings.HasSuffix(name, ".run.json") {
			continue
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := out.Add(raw); err != nil {
			t.Fatalf("%s: %v", path, err)
		}
	}
	return out
}

// answer lowers, evaluates and digests one replay proposal, the way the CLI does.
func answer(t *testing.T, file string) (doc.Proposal, doc.IR, doc.Result, string) {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(replay, file))
	if err != nil {
		t.Fatal(err)
	}
	proposal, err := doc.ReadProposal(raw)
	if err != nil {
		t.Fatal(err)
	}
	registry := reviewedRegistry(t)
	// The replay proposals pin the DRAFT digests, which reviewing does not move
	// (schema/CHANGES.md, the review.digest row), so the pins still match.
	ir, versions, err := lower.Lower(proposal, registry, replaySnapshots(t))
	if err != nil {
		t.Fatalf("%s: %v", file, err)
	}
	result, err := evaluate.Evaluate(ir)
	if err != nil {
		t.Fatal(err)
	}
	digest, err := lower.InputDigest(proposal, ir, versions)
	if err != nil {
		t.Fatal(err)
	}
	return proposal, ir, result, digest
}

func TestIssuesTheHandDerivedEnvelope(t *testing.T) {
	for file, want := range pins {
		proposal, ir, result, digest := answer(t, file)
		if result.ModelResult != "passes" {
			t.Fatalf("%s: the verdict is %s, so this case cannot exercise issuance", file, result.ModelResult)
		}
		issued, err := Issue(proposal, ir, result, digest)
		if err != nil {
			t.Fatalf("%s: %v", file, err)
		}
		if issued.ExecutionReadiness != "envelope_issued" {
			t.Errorf("%s: readiness is %q", file, issued.ExecutionReadiness)
		}
		envelope := issued.OrderEnvelope
		if envelope == nil {
			t.Fatalf("%s: no envelope", file)
		}
		if envelope.Coin != want.coin {
			t.Errorf("%s: coin %s, want %s", file, envelope.Coin, want.coin)
		}
		if envelope.Side != "buy" {
			t.Errorf("%s: side %s, want buy", file, envelope.Side)
		}
		if envelope.TimeInForce != "Ioc" {
			t.Errorf("%s: time in force %s, want Ioc", file, envelope.TimeInForce)
		}
		if envelope.Size.String() != want.size {
			t.Errorf("%s: size %s, want %s", file, envelope.Size.String(), want.size)
		}
		if envelope.LimitPrice.String() != want.limit {
			t.Errorf("%s: limit %s, want %s", file, envelope.LimitPrice.String(), want.limit)
		}
		if envelope.MaxCost.String() != want.maxCost {
			t.Errorf("%s: max cost %s, want %s", file, envelope.MaxCost.String(), want.maxCost)
		}
		if envelope.InputDigest != digest {
			t.Errorf("%s: the envelope names %s, the result is %s", file, envelope.InputDigest, digest)
		}
		// The bound and the order agree: the envelope's cost IS the premium the
		// verdict was reached with, never a second number beside it.
		if !envelope.MaxCost.Equal(result.Cost.Premium) {
			t.Errorf("%s: max cost %s, premium %s", file, envelope.MaxCost.String(), result.Cost.Premium.String())
		}
	}
}

// The limit is the price of the HIGHEST level the walk touched, which is a claim about
// one contract either side of it, not about the order as a whole.
func TestTheLimitIsTheHighestLevelTouched(t *testing.T) {
	proposal, ir, result, digest := answer(t, "binary.proposal.json")

	// 1,383 contracts stop exactly at the end of the 0.48123 level, so the walk never
	// reaches 0.48404 and the limit is one rung lower. 1,384 crosses into it.
	for _, row := range []struct{ size, limit string }{
		{"1383", "0.48123"},
		{"1384", "0.48404"},
	} {
		size := mustParse(t, row.size)
		resized := resize(t, proposal, ir, result, size)
		issued, err := Issue(resized.proposal, resized.ir, resized.result, digest)
		if err != nil {
			t.Fatalf("%s: %v", row.size, err)
		}
		if issued.OrderEnvelope.LimitPrice.String() != row.limit {
			t.Errorf("%s contracts: limit %s, want %s",
				row.size, issued.OrderEnvelope.LimitPrice.String(), row.limit)
		}
	}
}

type resized struct {
	proposal doc.Proposal
	ir       doc.IR
	result   doc.Result
}

// resize rewrites one leg's size in the proposal, the lowered form and the result's
// premium together, so the only thing under test is the walk.
func resize(t *testing.T, proposal doc.Proposal, ir doc.IR, result doc.Result, size exact.Q) resized {
	t.Helper()
	out := resized{proposal: proposal, ir: ir, result: result}
	out.proposal.Legs = append([]doc.ProposalLeg(nil), proposal.Legs...)
	out.proposal.Legs[0].Size = size
	out.ir.Legs = append([]doc.Leg(nil), ir.Legs...)
	out.ir.Legs[0].Size = size
	levels := out.ir.Legs[0].Premium.Levels
	remaining, cost := size, exact.Zero()
	for _, level := range levels {
		fill := exact.Min(remaining, level.Size)
		cost = cost.Add(fill.Mul(level.Price))
		remaining = remaining.Sub(fill)
	}
	if remaining.Sign() != 0 {
		t.Fatalf("the book does not fill %s", size.String())
	}
	premium := out.ir.Legs[0].Premium
	premium.Total = cost
	out.ir.Legs[0].Premium = premium
	out.result.Cost.Premium = cost
	return out
}

// Every way an envelope must NOT be issued. Each row is one thing wrong; a row that
// changed two would not say which one the gate caught.
func TestBlocksEverythingElse(t *testing.T) {
	proposal, ir, result, digest := answer(t, "bucket0.proposal.json")

	cases := []struct {
		name   string
		mutate func(*doc.Proposal, *doc.IR, *doc.Result, *string)
		why    string
	}{
		{"a failing verdict", func(_ *doc.Proposal, _ *doc.IR, r *doc.Result, _ *string) {
			r.ModelResult = "fails"
		}, "the verdict is fails"},
		{"a verdict that needs review", func(_ *doc.Proposal, _ *doc.IR, r *doc.Result, _ *string) {
			r.ModelResult = "needs_review"
		}, "the verdict is needs_review"},
		{"no input digest", func(_ *doc.Proposal, _ *doc.IR, _ *doc.Result, d *string) {
			*d = ""
		}, "does not name the input digest"},
		{"two legs", func(p *doc.Proposal, _ *doc.IR, _ *doc.Result, _ *string) {
			p.Legs = append(append([]doc.ProposalLeg(nil), p.Legs...), p.Legs[0])
		}, "has 2 legs"},
		{"a leg the lowered form does not have", func(p *doc.Proposal, _ *doc.IR, _ *doc.Result, _ *string) {
			p.Legs = append([]doc.ProposalLeg(nil), p.Legs...)
			p.Legs[0].ID = "elsewhere"
		}, "no such leg"},
		{"a hypothetical price", func(_ *doc.Proposal, i *doc.IR, _ *doc.Result, _ *string) {
			i.Legs = append([]doc.Leg(nil), i.Legs...)
			premium := i.Legs[0].Premium
			premium.Kind = "fixed"
			i.Legs[0].Premium = premium
		}, "bounds no real order"},
		{"sizes that disagree", func(p *doc.Proposal, _ *doc.IR, _ *doc.Result, _ *string) {
			p.Legs = append([]doc.ProposalLeg(nil), p.Legs...)
			p.Legs[0].Size = mustParse(t, "925")
		}, "the proposal asks for 925"},
		{"depth that does not fill the size", func(p *doc.Proposal, i *doc.IR, _ *doc.Result, _ *string) {
			p.Legs = append([]doc.ProposalLeg(nil), p.Legs...)
			i.Legs = append([]doc.Leg(nil), i.Legs...)
			p.Legs[0].Size = mustParse(t, "200000")
			i.Legs[0].Size = mustParse(t, "200000")
		}, "does not fill"},
		{"a premium that is not what the book says", func(_ *doc.Proposal, _ *doc.IR, r *doc.Result, _ *string) {
			r.Cost.Premium = mustParse(t, "160.76677")
		}, "the walk costs 160.76676"},
	}

	for _, row := range cases {
		t.Run(row.name, func(t *testing.T) {
			p, i, r, d := proposal, ir, result, digest
			row.mutate(&p, &i, &r, &d)
			issued, err := Issue(p, i, r, d)
			if err == nil {
				t.Fatalf("issued an envelope anyway: %+v", issued.OrderEnvelope)
			}
			var blocked *Blocked
			if !asBlocked(err, &blocked) {
				t.Fatalf("refused with %T, want *Blocked", err)
			}
			if !strings.Contains(blocked.Why, row.why) {
				t.Errorf("refused with %q, want it to mention %q", blocked.Why, row.why)
			}
			if issued.OrderEnvelope != nil {
				t.Error("a blocked result still carries an envelope")
			}
			if issued.ExecutionReadiness != "blocked" {
				t.Errorf("readiness is %q, want blocked", issued.ExecutionReadiness)
			}
		})
	}
}

// Issuing must not reach back into what it was given: a caller holding the original
// result must still be holding a result with no envelope on it.
func TestIssueDoesNotMutateItsInput(t *testing.T) {
	proposal, ir, result, digest := answer(t, "bucket0.proposal.json")
	before := result.ExecutionReadiness
	if _, err := Issue(proposal, ir, result, digest); err != nil {
		t.Fatal(err)
	}
	if result.OrderEnvelope != nil {
		t.Error("the original result grew an envelope")
	}
	if result.ExecutionReadiness != before {
		t.Errorf("the original readiness changed to %q", result.ExecutionReadiness)
	}
}

// The envelope survives the document round trip, and a result without one stays
// without one rather than gaining an empty shape.
func TestRoundTrip(t *testing.T) {
	proposal, ir, result, digest := answer(t, "binary.proposal.json")
	issued, err := Issue(proposal, ir, result, digest)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := doc.WriteResult(issued)
	if err != nil {
		t.Fatal(err)
	}
	back, err := doc.ReadResult(raw)
	if err != nil {
		t.Fatalf("%v\n%s", err, raw)
	}
	if back.OrderEnvelope == nil {
		t.Fatal("the envelope did not survive")
	}
	if back.OrderEnvelope.LimitPrice.String() != "0.48404" || back.OrderEnvelope.MaxCost.String() != "645.76904" {
		t.Errorf("round tripped to limit %s cost %s",
			back.OrderEnvelope.LimitPrice.String(), back.OrderEnvelope.MaxCost.String())
	}
	if back.ExecutionReadiness != "envelope_issued" {
		t.Errorf("readiness round tripped to %q", back.ExecutionReadiness)
	}

	plain, err := doc.WriteResult(result)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(plain), "order_envelope") {
		t.Error("a result nobody asked to execute carries an order_envelope key")
	}
}

func mustParse(t *testing.T, text string) exact.Q {
	t.Helper()
	value, err := exact.ParseQ(text)
	if err != nil {
		t.Fatalf("%q: %v", text, err)
	}
	return value
}

func asBlocked(err error, target **Blocked) bool {
	blocked, ok := err.(*Blocked)
	if ok {
		*target = blocked
	}
	return ok
}
