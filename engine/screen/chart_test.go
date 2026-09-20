package screen

import (
	"strings"
	"testing"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
)

func q(t *testing.T, text string) exact.Q {
	t.Helper()
	value, err := exact.ParseQ(text)
	if err != nil {
		t.Fatal(err)
	}
	return value
}

// A two-piece payoff, with coordinates derived by hand.
//
// The box is 720x280 with 48 padding, so the drawable width is 720-96=624 and the
// drawable height is 280-96=184. Prices run 60000..110000 and P&L runs -2000..0
// (widened to include zero), so:
//
//	x(60000)  = 48 + 0     * 624 = 48
//	x(110000) = 48 + 1     * 624 = 672
//	x(85000)  = 48 + 0.5   * 624 = 360
//	y(-2000)  = 280 - (48 + 0*184) = 232
//	y(0)      = 280 - (48 + 1*184) = 48
func TestPlotCoordinatesAreDerivedNotGuessed(t *testing.T) {
	result := doc.Result{
		Profile: []doc.Piece{
			{Interval: doc.Interval{Lower: q(t, "60000"), Upper: q(t, "85000"), LowerIncl: true},
				Slope: q(t, "0"), Intercept: q(t, "-2000")},
			{Interval: doc.Interval{Lower: q(t, "85000"), Upper: q(t, "110000"), UpperIncl: true},
				Slope: q(t, "0"), Intercept: q(t, "0")},
		},
		WorstCase: doc.NewWorstCase(q(t, "-2000"), q(t, "60000"), true),
	}
	plot, err := BuildPlot(result, q(t, "-1000"), true)
	if err != nil {
		t.Fatal(err)
	}
	if len(plot.Segments) != 2 {
		t.Fatalf("got %d segments, want 2", len(plot.Segments))
	}
	first, second := plot.Segments[0], plot.Segments[1]
	checks := []struct{ got, want, what string }{
		{first.X1, "48.00", "x at the low price"},
		{first.X2, "360.00", "x at the midpoint"},
		{second.X2, "672.00", "x at the high price"},
		{first.Y1, "232.00", "y at -2000"},
		{second.Y1, "48.00", "y at 0"},
		{plot.ZeroY, "48.00", "the zero line"},
	}
	for _, check := range checks {
		if check.got != check.want {
			t.Errorf("%s is %s, want %s", check.what, check.got, check.want)
		}
	}
	// The cap at -1000 is halfway between -2000 and 0: 280 - (48 + 0.5*184) = 140.
	if got := plot.CapLine(q(t, "-1000")); got != "140.00" {
		t.Errorf("the cap line is at %s, want 140.00", got)
	}
}

// The vertical extent always includes the cap, so a reader can see which side of the
// bound the payoff is on. A chart that cropped the cap out would draw a passing hedge
// and a failing one the same way.
func TestPlotAlwaysShowsTheCap(t *testing.T) {
	// A payoff far above a distant cap.
	result := doc.Result{
		Profile: []doc.Piece{
			{Interval: doc.Interval{Lower: q(t, "60000"), Upper: q(t, "110000"),
				LowerIncl: true, UpperIncl: true},
				Slope: q(t, "0"), Intercept: q(t, "5000")},
		},
		WorstCase: doc.NewWorstCase(q(t, "5000"), q(t, "60000"), true),
	}
	capPnl := q(t, "-9000")
	plot, err := BuildPlot(result, capPnl, true)
	if err != nil {
		t.Fatal(err)
	}
	if plot.MinPnl.Cmp(capPnl) > 0 {
		t.Errorf("the chart's floor is %s, above the cap at %s: the bound is off-screen",
			plot.MinPnl, capPnl)
	}
	// And the cap line lands inside the box.
	line := plot.CapLine(capPnl)
	if line == "" {
		t.Fatal("no cap line")
	}
}

// A flat payoff still draws: it gets a vertical range so the line lands in the box
// rather than on its edge.
func TestFlatPayoffStillDraws(t *testing.T) {
	result := doc.Result{
		Profile: []doc.Piece{
			{Interval: doc.Interval{Lower: q(t, "60000"), Upper: q(t, "110000"),
				LowerIncl: true, UpperIncl: true},
				Slope: q(t, "0"), Intercept: q(t, "0")},
		},
		WorstCase: doc.NewWorstCase(q(t, "0"), q(t, "60000"), true),
	}
	plot, err := BuildPlot(result, exact.Zero(), false)
	if err != nil {
		t.Fatal(err)
	}
	if len(plot.Segments) != 1 {
		t.Fatalf("got %d segments, want 1", len(plot.Segments))
	}
	if plot.MinPnl.Equal(plot.MaxPnl) {
		t.Error("a flat payoff got no vertical range, so every y is the same pixel")
	}
	for _, coordinate := range []string{plot.Segments[0].Y1, plot.Segments[0].Y2} {
		if strings.Contains(coordinate, "/") {
			t.Errorf("a coordinate is %q; an SVG cannot accept a ratio", coordinate)
		}
	}
}

// No coordinate is ever a ratio, because an SVG attribute cannot hold one. This is
// the whole reason DecimalPlaces exists.
func TestCoordinatesAreNeverRatios(t *testing.T) {
	result := doc.Result{
		Profile: []doc.Piece{
			// A domain whose thirds do not terminate as decimals.
			{Interval: doc.Interval{Lower: q(t, "1/3"), Upper: q(t, "2/3"), LowerIncl: true},
				Slope: q(t, "1/7"), Intercept: q(t, "-1/11")},
			{Interval: doc.Interval{Lower: q(t, "2/3"), Upper: q(t, "1"), UpperIncl: true},
				Slope: q(t, "1/13"), Intercept: q(t, "1/17")},
		},
		WorstCase: doc.NewWorstCase(q(t, "-1/11"), q(t, "1/3"), true),
		Cost:      doc.CostSummary{Breakevens: []exact.Q{q(t, "5/9")}},
	}
	plot, err := BuildPlot(result, q(t, "-1/23"), true)
	if err != nil {
		t.Fatal(err)
	}
	coordinates := []string{plot.ZeroY, plot.CapLine(q(t, "-1/23"))}
	for _, segment := range plot.Segments {
		coordinates = append(coordinates, segment.X1, segment.Y1, segment.X2, segment.Y2)
	}
	for _, mark := range plot.Breakevens {
		coordinates = append(coordinates, mark.X, mark.Y)
	}
	if plot.Worst != nil {
		coordinates = append(coordinates, plot.Worst.X, plot.Worst.Y)
	}
	for _, tick := range plot.Ticks {
		coordinates = append(coordinates, tick.X, tick.Y)
	}
	for _, coordinate := range coordinates {
		if strings.Contains(coordinate, "/") {
			t.Errorf("the coordinate %q is a ratio; an SVG cannot accept it", coordinate)
		}
		if coordinate == "" {
			t.Error("an empty coordinate would silently move a point to the origin")
		}
	}
}

// Endpoint ownership survives into the drawing: a piece that does not own its
// endpoint is drawn without a dot there. The engine is careful about which side of a
// strike owns a price, and a chart that closed every end would hide that care.
func TestOpenEndpointsAreMarkedOpen(t *testing.T) {
	result := doc.Result{
		Profile: []doc.Piece{
			{Interval: doc.Interval{Lower: q(t, "0"), Upper: q(t, "10"), LowerIncl: true},
				Slope: q(t, "1"), Intercept: q(t, "0")},
			{Interval: doc.Interval{Lower: q(t, "10"), Upper: q(t, "20"), UpperIncl: true},
				Slope: q(t, "0"), Intercept: q(t, "0")},
		},
		WorstCase: doc.NewWorstCase(q(t, "0"), q(t, "0"), true),
	}
	plot, err := BuildPlot(result, exact.Zero(), false)
	if err != nil {
		t.Fatal(err)
	}
	if plot.Segments[0].LowerOpen {
		t.Error("the first piece owns its lower endpoint but is drawn open")
	}
	if !plot.Segments[0].UpperOpen {
		t.Error("the first piece does not own its upper endpoint but is drawn closed")
	}
	// The fixture gives the endpoint at 10 to the FIRST piece's upper end being open
	// and the second's lower end being open too -- neither owns it, which is what
	// this profile says. The drawing must repeat that rather than tidy it away.
	if !plot.Segments[1].LowerOpen {
		t.Error("the second piece does not own its lower endpoint but is drawn closed")
	}
	if plot.Segments[1].UpperOpen {
		t.Error("the second piece owns its upper endpoint but is drawn open")
	}
}

// An empty profile draws nothing rather than crashing.
func TestEmptyProfileDrawsNothing(t *testing.T) {
	plot, err := BuildPlot(doc.Result{}, exact.Zero(), false)
	if err != nil {
		t.Fatal(err)
	}
	if len(plot.Segments) != 0 {
		t.Errorf("an empty profile produced %d segments", len(plot.Segments))
	}
}

// The ranking is by exact premium, not by the rounded text beside it: two candidates
// a hundredth apart round to the same cents and must still be ordered.
func TestRankingUsesExactCostNotRoundedText(t *testing.T) {
	cheaper := Candidate{ID: "cheaper", Sized: true, Premium: q(t, "100.001")}
	dearer := Candidate{ID: "dearer", Sized: true, Premium: q(t, "100.004")}
	unsized := Candidate{ID: "unsized", Sized: false}

	if cheaper.Premium.DecimalPlaces(2) != dearer.Premium.DecimalPlaces(2) {
		t.Fatal("the fixture no longer exercises the case: the two round differently")
	}
	ranked := Ranked([]Candidate{unsized, dearer, cheaper})
	want := []string{"cheaper", "dearer", "unsized"}
	for index, expected := range want {
		if ranked[index].ID != expected {
			t.Errorf("position %d is %s, want %s", index, ranked[index].ID, expected)
		}
	}
}

// Ranking does not reorder the input, so a caller's slice is not shuffled underneath
// it by a function it called to read.
func TestRankingDoesNotMutateItsInput(t *testing.T) {
	input := []Candidate{
		{ID: "b", Sized: true, Premium: q(t, "2")},
		{ID: "a", Sized: true, Premium: q(t, "1")},
	}
	Ranked(input)
	if input[0].ID != "b" || input[1].ID != "a" {
		t.Error("Ranked reordered the slice it was given")
	}
}

// A piece that crosses the cap is split at the crossing, so the colour changes at the
// price where the bound is crossed and nowhere else.
//
// Found by looking at a rendered page: the whole line was red although it sat well
// above the cap on the right. Colouring a piece by whether it dips below the bound
// ANYWHERE answers the reader's question wrongly along most of its length.
func TestPieceCrossingTheCapIsSplitThere(t *testing.T) {
	// P&L = 0.1*price - 8237.95 on [60000, 110000]: -2237.95 at the low end,
	// +2762.05 at the high end. With a cap of -1500 it crosses at
	// (−1500 + 8237.95)/0.1 = 67379.5.
	result := doc.Result{
		Profile: []doc.Piece{
			{Interval: doc.Interval{Lower: q(t, "60000"), Upper: q(t, "110000"),
				LowerIncl: true, UpperIncl: true},
				Slope: q(t, "0.1"), Intercept: q(t, "-8237.95")},
		},
		WorstCase: doc.NewWorstCase(q(t, "-2237.95"), q(t, "60000"), true),
	}
	capPnl := q(t, "-1500")
	plot, err := BuildPlot(result, capPnl, true)
	if err != nil {
		t.Fatal(err)
	}
	if len(plot.Segments) != 2 {
		t.Fatalf("got %d segments, want 2: the piece crosses the cap", len(plot.Segments))
	}
	if !plot.Segments[0].Below {
		t.Error("the stretch below the cap is not marked below")
	}
	if plot.Segments[1].Below {
		t.Error("the stretch above the cap is marked below")
	}
	// The split lands at the crossing price, 67379.5, not at either end.
	wantX := plot.x(q(t, "67379.5"))
	if plot.Segments[0].X2 != wantX {
		t.Errorf("the split is at x=%s, want %s (price 67379.5)", plot.Segments[0].X2, wantX)
	}
	if plot.Segments[1].X1 != plot.Segments[0].X2 {
		t.Error("the two segments do not meet, so the line has a gap")
	}
	// Both halves meet at the cap's own height.
	capY := plot.CapLine(capPnl)
	if plot.Segments[0].Y2 != capY || plot.Segments[1].Y1 != capY {
		t.Errorf("the split is at y=%s/%s, want the cap line %s",
			plot.Segments[0].Y2, plot.Segments[1].Y1, capY)
	}
}

// A piece entirely on one side of the cap is one segment: nothing is split that does
// not cross.
func TestPieceNotCrossingTheCapIsOneSegment(t *testing.T) {
	for _, testCase := range []struct {
		intercept string
		below     bool
		what      string
	}{
		{"-9000", true, "entirely below the cap"},
		{"0", false, "entirely above the cap"},
	} {
		result := doc.Result{
			Profile: []doc.Piece{
				{Interval: doc.Interval{Lower: q(t, "60000"), Upper: q(t, "110000"),
					LowerIncl: true, UpperIncl: true},
					Slope: q(t, "0"), Intercept: q(t, testCase.intercept)},
			},
			WorstCase: doc.NewWorstCase(q(t, testCase.intercept), q(t, "60000"), true),
		}
		plot, err := BuildPlot(result, q(t, "-1500"), true)
		if err != nil {
			t.Fatal(err)
		}
		if len(plot.Segments) != 1 {
			t.Errorf("%s: got %d segments, want 1", testCase.what, len(plot.Segments))
			continue
		}
		if plot.Segments[0].Below != testCase.below {
			t.Errorf("%s: Below is %v", testCase.what, plot.Segments[0].Below)
		}
	}
}
