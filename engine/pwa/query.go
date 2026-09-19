package pwa

import (
	"fmt"
	"sort"

	"hedgecheck/engine/exact"
)

// Interval is a maximal run of prices, with explicit ownership of each end.
type Interval struct {
	Lo, Hi                   exact.Q
	LoInclusive, HiInclusive bool
}

// Window returns the pieces of f restricted to [lower, upper], split additionally at
// every cut. Cuts can only ADD boundaries: the function's own are always present, so
// no caller can withhold one.
func (f Fn) Window(lower, upper exact.Q, cuts ...exact.Q) []Piece {
	marks := []exact.Q{lower, upper}
	for _, piece := range f.pieces {
		if !piece.Lo.Unbounded && lower.Less(piece.Lo.Value) && piece.Lo.Value.Less(upper) {
			marks = append(marks, piece.Lo.Value)
		}
		if !piece.Hi.Unbounded && lower.Less(piece.Hi.Value) && piece.Hi.Value.Less(upper) {
			marks = append(marks, piece.Hi.Value)
		}
	}
	for _, cut := range cuts {
		if lower.Less(cut) && cut.Less(upper) {
			marks = append(marks, cut)
		}
	}
	marks = dedupeSorted(marks)

	out := []Piece{}
	for index, mark := range marks {
		piece := f.pieceContaining(mark)
		out = append(out, Piece{Lo: Finite(mark, true), Hi: Finite(mark, true), Slope: piece.Slope, Intercept: piece.Intercept})
		if index+1 < len(marks) {
			inner := f.pieceContaining(midpoint(mark, marks[index+1]))
			out = append(out, Piece{
				Lo: Finite(mark, false), Hi: Finite(marks[index+1], false),
				Slope: inner.Slope, Intercept: inner.Intercept,
			})
		}
	}
	return out
}

// Profile returns the maximal affine pieces of f on [lower, upper], each carrying its
// own endpoint ownership.
//
// Ownership follows the value, not the construction. A boundary belongs to the piece
// whose line passes through it: at a discontinuity that is exactly one side, and at a
// continuous join it is both, so the left piece takes it and the two merge. That rule
// makes the profile the shortest description of the function, and makes two equal
// functions produce identical pieces however they were built.
func (f Fn) Profile(lower, upper exact.Q, cuts ...exact.Q) []Piece {
	out := []Piece{}
	for _, span := range f.Window(lower, upper, cuts...) {
		if span.Singleton() {
			price, value := span.Lo.Value, span.At(span.Lo.Value)
			if n := len(out); n > 0 {
				last := out[n-1]
				if last.Hi.Value.Equal(price) && last.At(price).Equal(value) {
					out[n-1].Hi.Closed = true
					continue
				}
			}
			out = append(out, Piece{Lo: Finite(price, true), Hi: Finite(price, true),
				Slope: exact.Zero(), Intercept: value})
			continue
		}
		if n := len(out); n > 0 {
			last := out[n-1]
			// The open span extends the previous piece when that piece already owns the
			// shared boundary and describes the same line there.
			sameLine := last.Slope.Equal(span.Slope) && last.Intercept.Equal(span.Intercept)
			singletonOnTheLine := last.Singleton() && span.At(last.Lo.Value).Equal(last.Intercept)
			if last.Hi.Value.Equal(span.Lo.Value) && last.Hi.Closed && (sameLine || singletonOnTheLine) {
				out[n-1].Hi = Finite(span.Hi.Value, false)
				out[n-1].Slope, out[n-1].Intercept = span.Slope, span.Intercept
				continue
			}
		}
		out = append(out, Piece{Lo: Finite(span.Lo.Value, false), Hi: Finite(span.Hi.Value, false),
			Slope: span.Slope, Intercept: span.Intercept})
	}
	return out
}

// Infimum returns the greatest lower bound of f on [lower, upper], whether it is
// attained, and a price that attains it.
//
// When attained, the price is one f really attains: the smallest such price when the
// attaining set has a minimum, otherwise the midpoint of the first attaining open
// piece. An open piece's excluded endpoints are limit points, not members; reporting
// one would name a price where the value is something else. (The oracle had this bug
// until 20 Sep; see EVIDENCE section 9.)
func (f Fn) Infimum(lower, upper exact.Q) (value exact.Q, attained bool, at exact.Q) {
	// The zero Q is a legitimate number, so "nothing seen yet" is a flag, never a
	// sentinel value.
	found := false
	offer := func(candidate exact.Q, isAttained bool, where exact.Q) {
		better := !found || candidate.Less(value) || (candidate.Equal(value) && isAttained && !attained)
		if better {
			value, attained, at, found = candidate, isAttained, where, true
		}
	}
	for _, piece := range f.Window(lower, upper) {
		switch {
		case piece.Singleton():
			offer(piece.At(piece.Lo.Value), true, piece.Lo.Value)
		case piece.Slope.Sign() == 0:
			// Flat and open: attained everywhere inside, at neither end.
			offer(piece.Intercept, true, midpoint(piece.Lo.Value, piece.Hi.Value))
		default:
			// Sloped and open: approached at an excluded end, never attained there.
			offer(piece.At(piece.Lo.Value), false, piece.Lo.Value)
			offer(piece.At(piece.Hi.Value), false, piece.Hi.Value)
		}
	}
	if !found {
		panic("pwa: an empty window has no infimum")
	}
	return value, attained, at
}

// Below returns {S in [lower, upper] : f(S) < threshold} as maximal intervals.
func (f Fn) Below(threshold, lower, upper exact.Q, cuts ...exact.Q) []Interval {
	parts := []Interval{}
	for _, piece := range f.Window(lower, upper, cuts...) {
		if piece.Singleton() {
			if piece.At(piece.Lo.Value).Less(threshold) {
				parts = append(parts, Interval{Lo: piece.Lo.Value, Hi: piece.Lo.Value, LoInclusive: true, HiInclusive: true})
			}
			continue
		}
		lo, hi := piece.Lo.Value, piece.Hi.Value
		if piece.Slope.Sign() == 0 {
			if piece.Intercept.Less(threshold) {
				parts = append(parts, Interval{Lo: lo, Hi: hi})
			}
			continue
		}
		cross, _ := threshold.Sub(piece.Intercept).Div(piece.Slope)
		start, end := lo, hi
		if piece.Slope.Sign() > 0 {
			end = exact.Min(hi, cross)
		} else {
			start = exact.Max(lo, cross)
		}
		if start.Less(end) {
			parts = append(parts, Interval{Lo: start, Hi: end})
		}
	}
	return mergeIntervals(parts)
}

// Witness returns an admissible price inside the interval and the value there: the
// attained minimum when the interval owns it, otherwise the midpoint. A witness must
// be a price the interval actually contains.
func (f Fn) Witness(interval Interval) (price, value exact.Q) {
	if interval.Lo.Equal(interval.Hi) {
		return interval.Lo, f.At(interval.Lo)
	}
	_, attained, where := f.Infimum(interval.Lo, interval.Hi)
	owned := (!where.Equal(interval.Lo) || interval.LoInclusive) &&
		(!where.Equal(interval.Hi) || interval.HiInclusive)
	if attained && owned {
		return where, f.At(where)
	}
	mid := midpoint(interval.Lo, interval.Hi)
	return mid, f.At(mid)
}

// Level is one rung of displayed depth: a price and the size available at it.
type Level struct {
	Price, Size exact.Q
}

// AskCost returns the cost of buying size by walking the levels in order, and false
// when the displayed depth cannot fill it.
func AskCost(levels []Level, size exact.Q) (exact.Q, bool) {
	remaining, cost := size, exact.Zero()
	for _, level := range levels {
		fill := exact.Min(remaining, level.Size)
		cost = cost.Add(fill.Mul(level.Price))
		remaining = remaining.Sub(fill)
		if remaining.Sign() == 0 {
			return cost, true
		}
	}
	return exact.Q{}, false
}

// Site is a price and the side of it a constraint binds at.
type Site struct {
	Price exact.Q
	Side  string // "at", "above" or "below"
}

// SizeWindow is the set of sizes meeting a floor on the whole window.
type SizeWindow struct {
	Empty             bool
	LowerBound        exact.Q
	UpperBound        exact.Q
	Smallest, Largest exact.Q
	HasWhole          bool
	Binding           []Site
}

// Window returns the sizes n in [0, displayed depth] with
// base(S) + n*unit(S) - C(n) >= floorPnl for every S in [lower, upper].
//
// For a fixed size the combined P&L is affine on every open piece, so the condition
// holds there exactly when it holds at both endpoint limits. Each site gives
// beta*n - C(n) >= floorPnl - alpha, concave in n because C is convex, so the feasible
// sizes form one interval. Contiguity is asserted rather than assumed.
func SizeWindowFor(base, unit Fn, levels []Level, floorPnl, lower, upper, lot exact.Q) (SizeWindow, error) {
	type site struct {
		price       exact.Q
		side        string
		alpha, beta exact.Q
	}
	sites := []site{}
	basePieces := base.Window(lower, upper, unitCuts(unit)...)
	unitPieces := unit.Window(lower, upper, unitCuts(base)...)
	if len(basePieces) != len(unitPieces) {
		return SizeWindow{}, fmt.Errorf("pwa: the base and unit windows disagree on their boundaries")
	}
	for index := range basePieces {
		b, u := basePieces[index], unitPieces[index]
		if b.Singleton() {
			sites = append(sites, site{b.Lo.Value, "at", b.At(b.Lo.Value), u.At(b.Lo.Value)})
			continue
		}
		sites = append(sites, site{b.Lo.Value, "above", b.At(b.Lo.Value), u.At(b.Lo.Value)})
		sites = append(sites, site{b.Hi.Value, "below", b.At(b.Hi.Value), u.At(b.Hi.Value)})
	}

	depth := exact.Zero()
	for _, level := range levels {
		depth = depth.Add(level.Size)
	}
	low, high := exact.Zero(), depth
	var lowSite, highSite *Site

	for _, s := range sites {
		start, spent := exact.Zero(), exact.Zero()
		spans := [][2]exact.Q{}
		for _, level := range levels {
			end := start.Add(level.Size)
			gain := s.beta.Sub(level.Price)
			need := floorPnl.Sub(s.alpha).Add(spent).Sub(level.Price.Mul(start))
			var span [2]exact.Q
			ok := false
			switch {
			case gain.Sign() == 0:
				if need.Sign() <= 0 {
					span, ok = [2]exact.Q{start, end}, true
				}
			case gain.Sign() > 0:
				edge, _ := need.Div(gain)
				span, ok = [2]exact.Q{exact.Max(start, edge), end}, true
			default:
				edge, _ := need.Div(gain)
				span, ok = [2]exact.Q{start, exact.Min(end, edge)}, true
			}
			if ok && span[0].LessEqual(span[1]) {
				spans = append(spans, span)
			}
			start, spent = end, spent.Add(level.Price.Mul(level.Size))
		}
		if len(spans) == 0 {
			return SizeWindow{Empty: true, Binding: []Site{{Price: s.price, Side: s.side}}}, nil
		}
		for index := 0; index+1 < len(spans); index++ {
			if !spans[index][1].Equal(spans[index+1][0]) {
				return SizeWindow{}, fmt.Errorf("pwa: feasible sizes are not contiguous; the cost is not convex")
			}
		}
		if low.Less(spans[0][0]) {
			low = spans[0][0]
			lowSite = &Site{Price: s.price, Side: s.side}
		}
		if spans[len(spans)-1][1].Less(high) {
			high = spans[len(spans)-1][1]
			highSite = &Site{Price: s.price, Side: s.side}
		}
	}

	out := SizeWindow{LowerBound: low, UpperBound: high}
	if lowSite != nil {
		out.Binding = append(out.Binding, *lowSite)
	}
	if highSite != nil {
		out.Binding = append(out.Binding, *highSite)
	}
	first, ok := low.CeilLot(lot)
	if !ok {
		return SizeWindow{}, fmt.Errorf("pwa: the lot must be positive")
	}
	last, _ := high.FloorLot(lot)
	if first.LessEqual(last) {
		out.Smallest, out.Largest, out.HasWhole = first, last, true
	} else {
		out.Empty = true
	}
	return out, nil
}

func unitCuts(f Fn) []exact.Q {
	out := []exact.Q{}
	for _, piece := range f.pieces {
		if !piece.Lo.Unbounded {
			out = append(out, piece.Lo.Value)
		}
		if !piece.Hi.Unbounded {
			out = append(out, piece.Hi.Value)
		}
	}
	return out
}

// BandInfimum is the lower envelope of f over a band: inf over [S-band, S+band].
//
// For a monotone payoff this is a shift, but not in general: the middle bucket
// [P1, P2) shrinks from both sides to [P1+band, P2-band). The true breakpoints include
// the crossings of the candidate lines, not only the shifted boundaries, which is why
// they are computed rather than guessed.
func (f Fn) BandInfimum(band exact.Q) (Fn, error) {
	if band.Sign() < 0 {
		return Fn{}, fmt.Errorf("pwa: a negative band")
	}
	if band.Sign() == 0 {
		return f, nil
	}

	// The envelope is the pointwise minimum of every piece's line shifted both ways.
	// A sloped piece shifts: for an increasing line the infimum over [S-b, S+b] is at
	// S-b. A function with no finite breakpoint still shifts, which is why there is no
	// shortcut for that case.
	type line struct{ slope, intercept exact.Q }
	lines := []line{}
	plateaus := []exact.Q{}
	for _, piece := range f.pieces {
		for _, delta := range []exact.Q{band.Neg(), band} {
			lines = append(lines, line{piece.Slope, piece.Intercept.Add(piece.Slope.Mul(delta))})
		}
		// A jump's own value becomes a plateau of the envelope wherever the band covers
		// it. Where a sloped candidate meets that plateau, the envelope switches which
		// one wins -- a breakpoint no shift and no line-to-line crossing produces.
		if piece.Singleton() {
			plateaus = append(plateaus, piece.Intercept)
		}
		if !piece.Lo.Unbounded {
			plateaus = append(plateaus, piece.At(piece.Lo.Value))
		}
		if !piece.Hi.Unbounded {
			plateaus = append(plateaus, piece.At(piece.Hi.Value))
		}
	}

	// Breakpoints of the envelope: every original boundary moved both ways, plus every
	// crossing of two candidate lines. The crossings are the ones a shift alone misses.
	marks := []exact.Q{}
	for _, piece := range f.pieces {
		for _, bound := range []Bound{piece.Lo, piece.Hi} {
			if !bound.Unbounded {
				marks = append(marks, bound.Value.Sub(band), bound.Value, bound.Value.Add(band))
			}
		}
	}
	for i := 0; i < len(lines); i++ {
		for j := i + 1; j < len(lines); j++ {
			if lines[i].slope.Equal(lines[j].slope) {
				continue
			}
			cross, ok := lines[j].intercept.Sub(lines[i].intercept).Div(lines[i].slope.Sub(lines[j].slope))
			if ok {
				marks = append(marks, cross)
			}
		}
	}
	for _, candidate := range lines {
		if candidate.slope.Sign() == 0 {
			continue
		}
		for _, plateau := range plateaus {
			cross, ok := plateau.Sub(candidate.intercept).Div(candidate.slope)
			if ok {
				marks = append(marks, cross)
			}
		}
	}
	marks = dedupeSorted(marks)

	value := func(price exact.Q) exact.Q {
		v, _, _ := f.Infimum(price.Sub(band), price.Add(band))
		return v
	}

	// Rebuild as explicit pieces. Each span's line is recovered from two interior
	// probes; the marks already contain every crossing, so the envelope is affine there.
	lineOn := func(a, b exact.Q) (exact.Q, exact.Q) {
		slope, _ := value(b).Sub(value(a)).Div(b.Sub(a))
		return slope, value(a).Sub(slope.Mul(a))
	}

	if len(marks) == 0 {
		slope, intercept := lineOn(exact.Zero(), exact.One())
		return New([]Piece{{Lo: NegInf(), Hi: PosInf(), Slope: slope, Intercept: intercept}})
	}

	pieces := []Piece{}
	first := marks[0]
	slope, intercept := lineOn(first.Sub(exact.FromInt(2)), first.Sub(exact.One()))
	pieces = append(pieces, Piece{Lo: NegInf(), Hi: Finite(first, false), Slope: slope, Intercept: intercept})
	for index, mark := range marks {
		pieces = append(pieces, Piece{Lo: Finite(mark, true), Hi: Finite(mark, true),
			Slope: exact.Zero(), Intercept: value(mark)})
		if index+1 < len(marks) {
			next := marks[index+1]
			a := midpoint(mark, midpoint(mark, next))
			b := midpoint(midpoint(mark, next), next)
			slope, intercept := lineOn(a, b)
			pieces = append(pieces, Piece{Lo: Finite(mark, false), Hi: Finite(next, false),
				Slope: slope, Intercept: intercept})
		}
	}
	last := marks[len(marks)-1]
	slope, intercept = lineOn(last.Add(exact.One()), last.Add(exact.FromInt(2)))
	pieces = append(pieces, Piece{Lo: Finite(last, false), Hi: PosInf(), Slope: slope, Intercept: intercept})

	// A singleton whose value lies on a neighbouring line is not a real breakpoint.
	return New(dropRedundant(pieces))
}

// dropRedundant folds a singleton into a neighbour whose line already passes through
// it, then merges adjacent pieces on the same line. Without it the envelope would
// carry boundaries that describe no change in the function.
func dropRedundant(pieces []Piece) []Piece {
	out := []Piece{}
	for _, piece := range pieces {
		if n := len(out); n > 0 {
			last := out[n-1]
			if piece.Singleton() && last.Hi.Value.Equal(piece.Lo.Value) &&
				last.At(piece.Lo.Value).Equal(piece.Intercept) {
				out[n-1].Hi.Closed = true
				continue
			}
			if last.Singleton() && !piece.Singleton() && last.Lo.Value.Equal(piece.Lo.Value) &&
				piece.At(last.Lo.Value).Equal(last.Intercept) {
				out[n-1] = Piece{Lo: Finite(last.Lo.Value, true), Hi: piece.Hi,
					Slope: piece.Slope, Intercept: piece.Intercept}
				continue
			}
			if last.Slope.Equal(piece.Slope) && last.Intercept.Equal(piece.Intercept) &&
				!last.Hi.Unbounded && !piece.Lo.Unbounded &&
				last.Hi.Value.Equal(piece.Lo.Value) && last.Hi.Closed != piece.Lo.Closed {
				out[n-1].Hi = piece.Hi
				continue
			}
		}
		out = append(out, piece)
	}
	return out
}

// ---------------------------------------------------------------- helpers

func (f Fn) pieceContaining(price exact.Q) Piece {
	for _, piece := range f.pieces {
		if piece.Contains(price) {
			return piece
		}
	}
	panic("pwa: the pieces do not cover " + price.String())
}

func midpoint(a, b exact.Q) exact.Q {
	half, _ := a.Add(b).Div(exact.FromInt(2))
	return half
}

func dedupeSorted(values []exact.Q) []exact.Q {
	sort.Slice(values, func(i, j int) bool { return values[i].Less(values[j]) })
	out := []exact.Q{}
	for _, value := range values {
		if n := len(out); n > 0 && out[n-1].Equal(value) {
			continue
		}
		out = append(out, value)
	}
	return out
}

// mergeRun folds adjacent pieces on the same line, so a profile is maximal.
func mergeRun(pieces []Piece) []Piece {
	out := []Piece{}
	for _, piece := range pieces {
		if n := len(out); n > 0 {
			last := out[n-1]
			if last.Slope.Equal(piece.Slope) && last.Intercept.Equal(piece.Intercept) &&
				last.Hi.Value.Equal(piece.Lo.Value) && last.Hi.Closed != piece.Lo.Closed {
				out[n-1].Hi = piece.Hi
				continue
			}
		}
		out = append(out, piece)
	}
	return out
}

func mergeIntervals(parts []Interval) []Interval {
	out := []Interval{}
	for _, part := range parts {
		if n := len(out); n > 0 {
			last := out[n-1]
			if last.Hi.Equal(part.Lo) && (last.HiInclusive || part.LoInclusive) {
				out[n-1].Hi, out[n-1].HiInclusive = part.Hi, part.HiInclusive
				continue
			}
		}
		out = append(out, part)
	}
	return out
}
