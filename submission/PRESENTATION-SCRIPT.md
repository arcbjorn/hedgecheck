# Presentation recording script — target 2:30, hard limit 3:00

Spoken, not read. Word counts assume ~150 wpm; each section's target is in brackets.

The rules list two scoring sets. Rules §8 is binding — functionality, impact, novelty,
UX, composability, business plan — while the FAQ says reviewers score founder–market
fit, insight, product and execution, market size, communication, viability and
**traction**. This script answers both, and is honest where the honest answer is weak:
traction is nil, and claiming otherwise is the one thing that disqualifies.

---

## 1. The problem [0:00–0:30, ~70 words]

> "Hyperliquid launched HIP-4 outcome markets this year — binary and bucketed contracts
> on the price of an asset. They're genuinely useful for hedging: if you're long
> Bitcoin, you can buy a contract that pays out when the price falls.
>
> But before you place that trade you have a question, and nothing answers it: does this
> specific position actually hold my loss under the specific number I care about? And
> what does it cost me, compared to the alternatives?
>
> Today you answer that by hand, or you guess."

---

## 2. What it does [0:30–1:00, ~75 words]

> "HedgeCheck takes the objective as an input. You state it: I hold a tenth of a Bitcoin,
> I'll accept losing at most two thousand dollars anywhere between sixty and a hundred
> and ten thousand.
>
> It discovers the live contracts, reads the order book, and returns a verdict —
> passes, fails, or needs review — with the premium, the smallest size that would have
> worked, the ranked alternatives, and for a failure, the exact price where it breaks.
>
> It also refuses. If it can't establish an answer, it says so instead of guessing.
> That's the difference between a verifier and a calculator."

---

## 3. The insight [1:00–1:40, ~95 words]

> "The insight is that a hedge can look right and be wrong in ways a payoff diagram
> hides.
>
> Our clearest case: a contract that settles a day before the objective is valued. Same
> instrument, same premium, looks like protection. It isn't — by the time the risk
> materialises the contract has expired. Hedged, the worst case is minus 1,923. Unhedged
> it was minus 1,763. You paid for the privilege of being worse off.
>
> Or: two contracts that both meet the same cap, where one costs four times the other.
> That's not a modelling subtlety, that's 485 dollars on a 0.1 BTC position.
>
> So the product isn't 'is this hedge sound'. It's 'which sound hedge is cheapest, and
> where does each one break'."

---

## 4. Execution [1:40–2:10, ~80 words]

> "On execution, three things.
>
> There are three independent implementations of the same specification — Python, Go and
> TypeScript — and the build fails if any two disagree. A verdict is a claim three
> separately written programs reached from the same bytes.
>
> There's no floating point on any evaluation path. Exact rationals throughout, because
> a hedge that passes by a rounding error hasn't passed.
>
> And every guard was watched failing before it was trusted. When we built the website
> last week, testing its own verification claim found a real defect: two of our three
> implementations were taking a summary number on trust. Both re-derive it now."

---

## 5. Market and honesty [2:10–2:30, ~55 words]

> "Market: anyone running a position against these contracts, which today is a small
> number of traders on a venue that launched this year — so the honest framing is that
> this is infrastructure arriving with the market rather than a validated demand.
>
> We have no users and no traction, and I'm not going to pretend otherwise. What we have
> is a tool that's correct, reproducible offline, and tells you what it doesn't
> establish as plainly as what it does.
>
> Everything is open source. You can verify every number in this presentation yourself."

---

## Delivery notes

**Say the numbers.** −1,923 against −1,763, and 160 against 645. Specific numbers are
the whole credibility of this pitch; "significant savings" is worth nothing.

**Don't oversell the market.** A reviewer scoring market size will mark down a claim
they don't believe faster than they'll mark down a small honest one. §13 of our own plan
forbids it, and misrepresentation disqualifies.

**The defect story is an asset, not a confession.** It demonstrates the discipline the
rest of the pitch asserts. Keep it to one sentence and move on.

**Lead with the failure, not the success**, in both videos. It is the most memorable
thirty seconds available and no competitor will do it.

**If you overrun**, cut section 5 to its last two sentences. Never cut section 3 — the
insight is what's being scored.

---

## Facts, with their sources

Each is checkable, and none should be stated more strongly than this.

| Claim | Where |
|---|---|
| −1,923.90676 hedged vs −1,763.14 unhedged | `fixtures/replay/2026-09-18/bucket0-horizon.proposal.json`, run offline |
| 160.76676 vs 645.76904 for the same cap | same capture, both legs; walked off the retained book |
| Two live mainnet passes, 5 and 12 Oct | `fixtures/live/`, replay byte-identically |
| Three implementations must agree | `make check`, 8,225 checks |
| Worst-case defect found via the website | EVIDENCE §9, "Two implementations took the `worst_case` summary on trust" |
| No users | PLAN §8 — demand is explicitly unproven |

**Do not claim** the live testnet order works. It does not: testnet lists the daily
binary and bucket three hours apart and all sixteen of its recurring books are empty.
Everything up to the send is proven, and that is the claim to make.
