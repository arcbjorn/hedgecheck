# Demo recording script — target 2:45, hard limit 3:00

Every command below was run on 12 October and produced the output shown. Timings are
real: the slowest step is 0.5 s, so there is no dead air to talk over.

**Before you record**

```sh
cd ~/projects/hedgecheck
make check            # warms the Go build cache; otherwise the first command pauses
clear
```

Terminal at a readable font size. Have the browser open on a second tab at
`https://arcbjorn.github.io/hedgecheck/`, scrolled to "Verify a result in this browser".

Do **not** run `--live` on camera. It depends on the market that minute, and a demo that
needs the world to cooperate is a demo that fails on the day. The retained captures prove
the same thing and cannot surprise you.

---

## 0:00–0:20 — The question

> "If you hold Bitcoin and you want a bound on your loss, you can buy an outcome
> contract to hedge it. The question nobody answers is whether the specific position
> you're about to take actually meets the specific bound you have in mind — and what
> it costs you compared to the alternatives.
>
> HedgeCheck answers that before you trade. Let me show you the case that matters."

---

## 0:20–1:05 — Start with the refusal

Type:

```sh
cd engine
go run ./cmd/hedgecheck check \
  --proposal ../fixtures/replay/2026-09-18/bucket0-horizon.proposal.json \
  --registry ../registry \
  --snapshots ../fixtures/replay/2026-09-18 2>/dev/null \
  | jq '{verdict: .model_result, worst_case: .worst_case.pnl,
         rule: .reductions[0].rule, tight: .reductions[0].tight, codes: .reason_codes}'
```

Output:

```json
{
  "verdict": "fails",
  "worst_case": "-1923.90676",
  "rule": "horizon_mismatch",
  "tight": true,
  "codes": ["LEG_WORST_CASED_HORIZON", "LOSS_BOUND_EXCEEDED"]
}
```

The `2>/dev/null` matters on camera: this proposal exits 1, because **the exit status is
the verdict** — and `go run` prints its own "exit status 1" line to stderr, which looks
like a crash on a recording. It is not; it is the tool answering "fails".

Say, while it is on screen:

> "This hedge looks fine. It isn't. The contract settles a day before the objective is
> valued, so by the time the risk matters the protection has expired.
>
> The tool doesn't guess what happens in between — it worst-cases that leg to zero and
> says so. `tight: true` means that bound is actually reached, not an estimate.
>
> The number that matters: hedged, the worst case is **minus 1,923**. Unhedged it was
> **minus 1,763**. You paid premium to be *worse off*. A tool that passed this would be
> dangerous, and this is the kind of thing a payoff diagram will not tell you."

---

## 1:05–1:50 — Then the comparison

> "Now the same objective, hedged properly — two different instruments, both sound."

```sh
for p in bucket0 binary; do
  go run ./cmd/hedgecheck check \
    --proposal ../fixtures/replay/2026-09-18/$p.proposal.json \
    --registry ../registry --snapshots ../fixtures/replay/2026-09-18 2>/dev/null \
    | jq -r --arg p "$p" '"\($p)\t\(.model_result)\tpremium \(.cost.premium)\tworst \(.worst_case.pnl)"'
done
```

Output:

```
bucket0	passes	premium 160.76676	worst -999.90676
binary	passes	premium 645.76904	worst -999.90904
```

> "Both meet a thousand-dollar cap. One costs 160, the other 645 — four times the
> premium for the same protection.
>
> That's the actual question a trader has: not *is this hedge sound*, but *which sound
> hedge is cheapest*. And those premiums aren't the tool's opinion — they're walked off
> the retained order book, exact, no floating point anywhere."

---

## 1:50–2:20 — It works on real live markets

> "That's a retained capture. Here's the same pipeline against a live mainnet book
> nobody had seen before."

```sh
cd .. && python3 tools/replay_live.py fixtures/live/2026-10-05
```

Output:

```
4 snapshot digests re-derived from the retained bytes
replay of c8390a8c99a160cb (binary-no): byte-identical
verdict passes, cost 350.3793
```

> "987 contracts, worst case minus 1,999 against a 2,000 cap — 62 cents of headroom.
>
> Every snapshot is hashed as the exchange sent it, so this replays byte-identically.
> Change one digit of one price and it fails before it even runs.
>
> And for the eleven days before this, the tool refused every cap — protection cost
> 99.999% of its payoff. Those refusals are the evidence. A tool that only ever passes
> hasn't been shown to work."

---

## 2:20–2:45 — Don't trust me, verify it

Switch to the browser. Click **Run the checker**.

Output appears in the box:

```
snapshot 00118f3902a1a8c4 verified
snapshot a1692390028fdbfa verified
snapshot ed779f0670253d58 verified

running the checker...

ACCEPTED
  verdict      passes
  premium      160.76676
  worst case   -999.90676 at 60000
```

> "This is running in your browser, not on a server. It's the TypeScript
> implementation — one of three independent implementations of the same spec, which all
> have to agree or the build fails.
>
> It re-derives the verdict from the raw exchange bytes. So you don't have to trust the
> page, or me: you can check the claim yourself, from the same data."

Close:

> "Open-source, reproducible offline, and it tells you what it *doesn't* establish as
> plainly as what it does."

---

## If you overrun

Cut the **1:50–2:20** live-replay section. The refusal and the comparison are the
argument; the live pass is corroboration.

## If a command fails on camera

Stop, say "let me re-run that", and re-run it. Every command here is deterministic and
offline — a failure means a typo, not a broken tool. Do not improvise a different
command.
