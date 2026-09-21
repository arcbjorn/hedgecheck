// Package envelope issues the order a depth-priced cost bound assumes, or says why it
// will not.
//
// IT IS A SEPARATE STEP ON PURPOSE. `evaluate.Evaluate` is pure and cannot do this:
// the lowered proposal carries no instance id, by design (PLAN section 6, "Instance
// ids are never in it"), so the kernel does not know which instrument a leg is, and
// the input digest is computed after evaluation, so a result does not know its own
// name while it is being made. A result nobody asked to execute therefore keeps
// `execution_readiness: not_evaluated`, exactly as it did before this package existed.
//
// The envelope is not a recommendation and not permission. It is the statement of
// which order, and only which order, the number in `cost.premium` bounds.
package envelope

import (
	"fmt"

	"hedgecheck/engine/doc"
	"hedgecheck/engine/pwa"
)

// Blocked says an envelope was asked for and refused, with the reason a person reads.
// It is not an error: "this cannot be executed" is an answer, and a caller that
// treated it as a failure would be confusing a refusal with a fault.
type Blocked struct{ Why string }

func (b *Blocked) Error() string { return b.Why }

// Issue returns the result with an order envelope attached and
// `execution_readiness: envelope_issued`, or the result marked `blocked` together
// with a *Blocked saying why. It never mutates what it is given.
//
// An envelope is issued only when ALL of these hold:
//
//   - the verdict is `passes`. A `fails` is a proposal that does not meet the
//     objective, and a `needs_review` is one where nothing has been established;
//     executing either is executing an answer nobody gave.
//   - the proposal has exactly one leg. Two legs are two orders, and this envelope
//     describes one. An envelope that quietly covered the first would bound a cost
//     that includes the second.
//   - that leg is priced by walking a book. A hypothetical per-unit price bounds
//     nothing about a real order.
//   - the displayed depth fills the size, and the walked total is the premium the
//     result states. If the result's number and the book's number differ, the number
//     in the envelope would not be the one that was checked.
//   - the result names the input digest it belongs to.
func Issue(proposal doc.Proposal, ir doc.IR, result doc.Result, inputDigest string) (doc.Result, error) {
	out := result
	out.OrderEnvelope = nil
	out.ExecutionReadiness = "blocked"

	block := func(why string, args ...any) (doc.Result, error) {
		return out, &Blocked{Why: fmt.Sprintf(why, args...)}
	}

	if result.ModelResult != "passes" {
		return block("the verdict is %s, so there is nothing to execute", result.ModelResult)
	}
	if inputDigest == "" {
		return block("the result does not name the input digest it belongs to")
	}
	if len(proposal.Legs) != 1 {
		return block("the proposal has %d legs; an envelope describes one order", len(proposal.Legs))
	}
	leg := proposal.Legs[0]
	if leg.Side != "yes" && leg.Side != "no" {
		return block("%s: unsupported side %q", leg.ID, leg.Side)
	}

	// The levels come from the LOWERED leg, which is where lowering recorded what it
	// walked, and the leg is matched by id so a reordering cannot pair them wrongly.
	var priced *doc.Leg
	for index := range ir.Legs {
		if ir.Legs[index].ID == leg.ID {
			priced = &ir.Legs[index]
		}
	}
	if priced == nil {
		return block("%s: the lowered proposal has no such leg", leg.ID)
	}
	if priced.Premium.Kind != "walked" {
		return block("%s: priced at a fixed %s, which bounds no real order", leg.ID, priced.Premium.Kind)
	}
	if !priced.Size.Equal(leg.Size) {
		return block("%s: the proposal asks for %s and the lowered leg says %s",
			leg.ID, leg.Size.String(), priced.Size.String())
	}
	if leg.Size.Sign() <= 0 {
		return block("%s: a size of %s is not an order", leg.ID, leg.Size.String())
	}

	levels := make([]pwa.Level, 0, len(priced.Premium.Levels))
	for _, level := range priced.Premium.Levels {
		levels = append(levels, pwa.Level{Price: level.Price, Size: level.Size})
	}
	cost, covered := pwa.AskCost(levels, leg.Size)
	if !covered {
		return block("%s: the displayed depth does not fill %s contracts", leg.ID, leg.Size.String())
	}
	limit, ok := pwa.WalkLimit(levels, leg.Size)
	if !ok {
		return block("%s: the displayed depth does not fill %s contracts", leg.ID, leg.Size.String())
	}
	// The premium the verdict was reached with must be the cost of the order being
	// written down. They come from the same walk, so a difference means one of them
	// was edited, and an envelope built on the other would bound the wrong number.
	if !cost.Equal(result.Cost.Premium) {
		return block("%s: the walk costs %s and the result claims a premium of %s",
			leg.ID, cost.String(), result.Cost.Premium.String())
	}

	out.ExecutionReadiness = "envelope_issued"
	out.OrderEnvelope = &doc.OrderEnvelope{
		Coin:        leg.Instance.Coin,
		Side:        "buy",
		Size:        leg.Size,
		LimitPrice:  limit,
		TimeInForce: "Ioc",
		MaxCost:     cost,
		InputDigest: inputDigest,
	}
	return out, nil
}
