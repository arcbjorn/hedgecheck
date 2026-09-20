// Package screen renders a result as a page a person can read.
//
// Pure: documents in, HTML out. No I/O, no clock, and no floating point -- the chart
// coordinates are computed in exact arithmetic and rounded ONCE, at the moment they
// become text in an SVG attribute. A picture of the answer is not the answer, and
// nothing rounded here ever flows back into a number.
//
// The page states what was asked, what the answer is, and what was NOT checked. It is
// not advice: it answers an objective someone stated, and `forbidden_test.go` holds
// the language to that.
package screen

import (
	"sort"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/exact"
)

// Plot is a drawable payoff: the pieces, in a box, with the axes' extents.
type Plot struct {
	Width, Height int64
	Pad           int64
	MinPrice      exact.Q
	MaxPrice      exact.Q
	MinPnl        exact.Q
	MaxPnl        exact.Q
	Segments      []Segment
	ZeroY         string
	Breakevens    []Mark
	Worst         *Mark
	Ticks         []Tick
}

// Segment is one piece of the payoff, already in pixels.
type Segment struct {
	X1, Y1, X2, Y2 string
	// Open ends are drawn without a dot, because the endpoint is not owned here.
	LowerOpen, UpperOpen bool
	// Below is true where the piece is under the cap, which is the part a reader is
	// looking for. It is derived from the clause, not from the drawing.
	Below bool
}

// Mark is a labelled point on the plot.
type Mark struct {
	X, Y  string
	Label string
}

// Tick is one axis label.
type Tick struct {
	X, Y  string
	Label string
}

// chartBox is the drawing area. Fixed, because a chart that resized with its data
// would make two results look different when only the window had changed.
const (
	chartWidth  int64 = 720
	chartHeight int64 = 280
	chartPad    int64 = 48
)

// BuildPlot turns a result's profile into pixels.
//
// The vertical extent covers the payoff AND the cap, so a reader can always see which
// side of the bound the line is on. A chart that cropped the cap out of view would
// show a passing hedge and a failing one as the same picture.
func BuildPlot(result doc.Result, capPnl exact.Q, hasCap bool) (Plot, error) {
	pieces := result.Profile
	if len(pieces) == 0 {
		return Plot{}, nil
	}
	plot := Plot{Width: chartWidth, Height: chartHeight, Pad: chartPad}
	plot.MinPrice, plot.MaxPrice = pieces[0].Lower, pieces[len(pieces)-1].Upper

	// The vertical extent is the payoff's own range, widened to include the cap and
	// the zero line, so the reader always has both references.
	low, high := valueAt(pieces[0], pieces[0].Lower), valueAt(pieces[0], pieces[0].Lower)
	for _, piece := range pieces {
		for _, at := range []exact.Q{piece.Lower, piece.Upper} {
			value := valueAt(piece, at)
			if value.Less(low) {
				low = value
			}
			if high.Less(value) {
				high = value
			}
		}
	}
	if hasCap {
		if capPnl.Less(low) {
			low = capPnl
		}
		if high.Less(capPnl) {
			high = capPnl
		}
	}
	if exact.Zero().Less(low) {
		low = exact.Zero()
	}
	if high.Less(exact.Zero()) {
		high = exact.Zero()
	}
	// A flat payoff has no vertical range to scale against; give it one so the line
	// lands in the middle of the box rather than on its edge.
	if low.Equal(high) {
		low, high = low.Sub(exact.One()), high.Add(exact.One())
	}
	plot.MinPnl, plot.MaxPnl = low, high

	for _, piece := range pieces {
		plot.Segments = append(plot.Segments, plot.segmentsFor(piece, capPnl, hasCap)...)
	}
	plot.ZeroY = plot.y(exact.Zero())

	for _, breakeven := range result.Cost.Breakevens {
		plot.Breakevens = append(plot.Breakevens, Mark{
			X: plot.x(breakeven), Y: plot.y(exact.Zero()), Label: breakeven.String(),
		})
	}
	sort.SliceStable(plot.Breakevens, func(i, j int) bool {
		return plot.Breakevens[i].Label < plot.Breakevens[j].Label
	})

	worst := Mark{
		X: plot.x(result.WorstCase.Price), Y: plot.y(result.WorstCase.Pnl),
		Label: result.WorstCase.Pnl.String(),
	}
	plot.Worst = &worst

	plot.Ticks = plot.buildTicks()
	return plot, nil
}

// segmentsFor draws one piece, split at the cap crossing when it has one.
//
// A piece is affine, so it crosses the cap at most once. Colouring the whole piece by
// whether it dips below the cap ANYWHERE would paint a line red along the stretch
// where it is comfortably above the bound -- which is the reader's actual question,
// answered wrongly. The crossing price is solved exactly and the piece is cut there,
// so the colour changes at the price where the bound is crossed and nowhere else.
func (p Plot) segmentsFor(piece doc.Piece, capPnl exact.Q, hasCap bool) []Segment {
	atLower, atUpper := valueAt(piece, piece.Lower), valueAt(piece, piece.Upper)
	whole := Segment{
		X1: p.x(piece.Lower), Y1: p.y(atLower),
		X2: p.x(piece.Upper), Y2: p.y(atUpper),
		LowerOpen: !piece.LowerIncl, UpperOpen: !piece.UpperIncl,
	}
	if !hasCap {
		return []Segment{whole}
	}
	lowerBelow, upperBelow := atLower.Less(capPnl), atUpper.Less(capPnl)
	if lowerBelow == upperBelow {
		whole.Below = lowerBelow
		return []Segment{whole}
	}
	// It crosses. Solve slope*price + intercept = cap for the price.
	crossing, ok := capPnl.Sub(piece.Intercept).Div(piece.Slope)
	if !ok || crossing.LessEqual(piece.Lower) || piece.Upper.LessEqual(crossing) {
		// A crossing outside the piece means the ends disagree for a reason this
		// cannot express; draw one segment rather than invent a split.
		whole.Below = lowerBelow
		return []Segment{whole}
	}
	atCrossing := p.y(capPnl)
	crossingX := p.x(crossing)
	return []Segment{
		{X1: whole.X1, Y1: whole.Y1, X2: crossingX, Y2: atCrossing,
			LowerOpen: !piece.LowerIncl, Below: lowerBelow},
		{X1: crossingX, Y1: atCrossing, X2: whole.X2, Y2: whole.Y2,
			UpperOpen: !piece.UpperIncl, Below: upperBelow},
	}
}

// valueAt evaluates an affine piece. Exact: slope*price + intercept.
func valueAt(piece doc.Piece, price exact.Q) exact.Q {
	return piece.Slope.Mul(price).Add(piece.Intercept)
}

// x maps a price to a pixel column.
func (p Plot) x(price exact.Q) string {
	span := p.MaxPrice.Sub(p.MinPrice)
	if span.Sign() == 0 {
		return exact.FromInt(p.Pad).DecimalPlaces(2)
	}
	fraction, ok := price.Sub(p.MinPrice).Div(span)
	if !ok {
		return exact.FromInt(p.Pad).DecimalPlaces(2)
	}
	inner := exact.FromInt(p.Width - 2*p.Pad)
	return exact.FromInt(p.Pad).Add(fraction.Mul(inner)).DecimalPlaces(2)
}

// y maps a P&L to a pixel row. SVG's origin is top-left, so the axis is inverted
// here: a larger P&L is a smaller y.
func (p Plot) y(value exact.Q) string {
	span := p.MaxPnl.Sub(p.MinPnl)
	if span.Sign() == 0 {
		return exact.FromInt(p.Height / 2).DecimalPlaces(2)
	}
	fraction, ok := value.Sub(p.MinPnl).Div(span)
	if !ok {
		return exact.FromInt(p.Height / 2).DecimalPlaces(2)
	}
	inner := exact.FromInt(p.Height - 2*p.Pad)
	fromBottom := exact.FromInt(p.Pad).Add(fraction.Mul(inner))
	return exact.FromInt(p.Height).Sub(fromBottom).DecimalPlaces(2)
}

// buildTicks labels the price axis at its two ends. The domain's ends are the honest
// labels: the chart shows the payoff on exactly the interval the objective named, and
// interpolated gridlines would suggest prices that were never evaluated.
func (p Plot) buildTicks() []Tick {
	return []Tick{
		{X: p.x(p.MinPrice), Y: p.yLabel(), Label: p.MinPrice.String()},
		{X: p.x(p.MaxPrice), Y: p.yLabel(), Label: p.MaxPrice.String()},
	}
}

func (p Plot) yLabel() string {
	return exact.FromInt(p.Height - p.Pad/2).DecimalPlaces(2)
}

// CapLine is the y of the cap, when the objective states one.
func (p Plot) CapLine(capPnl exact.Q) string { return p.y(capPnl) }
