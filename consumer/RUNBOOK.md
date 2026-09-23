# The live testnet order

For the owner, by hand. No agent runs any step on this page.

**No mainnet key is ever used.** Every step here is testnet. The script refuses
`--network mainnet` outright; reaching mainnet is not a flag away.

## STOP — there is no testnet bundle to run today

**Do not point this at `fixtures/bundles/`.** Every bundle in the repository is built
from MAINNET books and carries the coin `#39710` — outcome 3971, asset id
`100,039,710`. Testnet's outcomes are a different range entirely (10217–20489, asset
ids `100,102,170`–`100,204,891`), so that envelope names an instrument that does not
exist there.

The gate does not catch this, and cannot: the bundle is internally consistent and the
check is sound. It approves, signs, and sends asset `100,039,710` to the testnet
exchange. Either testnet rejects it — in which case the run proves nothing — or some
unrelated testnet instrument answers to that id and **you buy something you did not
choose**.

    $ node --experimental-strip-types consumer/src/run.ts \
        --bundle fixtures/bundles/good-envelope --network testnet
    APPROVED {"coin":"#39710", ...}        <-- a MAINNET instrument

**A testnet bundle cannot be built today either — and the reason is LIQUIDITY, not
listing.** Corrected 22 Sep; the earlier wording on this page said testnet lists no expiry
carrying both a binary and a bucket, which is true and was the wrong blocker.

**A bucket is not required.** Long the underlying, YES at one strike and NO at another is a
hedge this tool verifies, and testnet lists those ladders routinely — verified against the
retained 21 September catalogue:

| Underlying | Expiry | Strikes at that expiry |
|---|---|---|
| `xyz:XYZ100` | `20260921-1900` | 29,100 · 29,300 · 29,500 · 29,700 · 29,900 |
| `xyz:AAPL` | `20260921-1900` | 7,600 · 7,650 · 7,700 · 7,750 · 7,800 |
| `BTC` | `20260921-1200` | 81,100 · 81,500 · 81,900 |

(Testnet carries no price bucket at all — the only `*Bucket` outcomes are
`policyRateBucket`, on Fed rates. That is why waiting for one was waiting for the wrong
thing.)

**Measured 23 Sep, and THE BLOCKER IS GONE.** Run the sweep yourself — it is the check, and it
is read-only:

    $ python3 tools/sweep_testnet.py

Two corrections to what this page said on 22 Sep, both of them errors in the earlier probe and
not in the venue:

- The two retained instances are dated `20260921` and have **expired**: `#204891` and
  `#203580` return `null`, not an empty book. Those are different facts, and reporting the
  first as the second claims something false about a market that is not there.
- **"0 bids and 0 asks" was a measurement bug.** The earlier probe asked for `#10218` — the
  raw outcome id — where the venue's coin is `'#' + (10*outcome + side)`, yes=0 no=1, so
  outcome 10218 YES is `#102180`. A wrong coin answers `null`, which the probe read as an
  empty book. `engine/discover/discover.go` had the rule right all along.

Swept properly over all 618 outcomes, both sides:

| | count |
|---|---|
| books returning a book | 1,236 |
| carrying at least one quote | 114 |
| empty (0 bids, 0 asks) | 1,122 |

Of those, some are **structured price markets** — carrying `perp`, `priceDescription`,
`seconds` and `threshold`, the template fields a price leg is built from — and the sweep prints
how many, and how many of their books are quoted, under `quoted AND a price market`. On 23 Sep
it was 56 markets and 28 quoted books. **Read the count from the sweep, not from this line:**
these are dated instruments, `make check` is offline and cannot verify a live number, and a
figure written here is stale the moment an expiry passes. The rest of the quoted depth is
World Cup and CPI markets, which this tool refuses as price legs rather than inventing a
series for.

**A hedgeable ladder exists today.** `xyz:AAPL` at `20260923-1900` carries five strikes —
7,600 · 7,650 · 7,700 · 7,750 · 7,800 — with asks on both YES and NO at several of them, and
`xyz:XYZ100` at the same expiry carries five more. `BTC` has `70000` at `20260930-1200` quoted
on both sides. A long position plus YES at one strike and NO at another is the shape this
project verifies.

**So step 0 no longer blocks.** Re-run the sweep first anyway: these are dated instruments and
`20260923-1900` expires today, so the ladder that unblocks you this hour may be gone the next.
Build the proposal from a CURRENT capture, never from a bundle in this repository — see the
mainnet warning above.

## There is a second path, and it is a different page

This page is the OFF-CHAIN order: the gate in `consumer/` decides, signs, and sends to the
exchange endpoint. There is also an on-chain path — `onchain/ApprovedOrderGate.sol`, sending
through CoreWriter — with its own runbook at [`onchain/RUNBOOK.md`](../onchain/RUNBOOK.md).

They bound different things. Here the gate runs the checker itself, so the decision and the
send are one step. On chain the contract cannot verify a certificate at all — the evidence a
cost bound rests on is not visible to a contract — so you check it off chain and approve its
digest, and the gate holds the order to what you approved. Read that page's STOP section before
using it.

## What this run will establish, and what it will not

It exercises the **order path**: envelope to signed action, one send, and the answer
read back. It does **not** exercise the hedge check — an empty or thin testnet book
does not bound anything, and the bound this tool exists to compute is a mainnet
question. Do not read a success here as a checked hedge.

## 0. What the checker will and will not trust

**The file the checker consults is the allowlist**, derived at build time from the
registry entries that are genuinely reviewed:

    $ cat checker/dist/allowlist.json
    {
      "reviewed": [
        "0f75191302086ba1cf59587956d1593a73372a729a98cd94556d56cda3a2b539",
        "6fa3d6ba76bb0b092bcb0fbaa22e783f5f84cf45df18eca47d7b11100615cf63"
      ]
    }

Both registry entries are reviewed, so a good bundle is accepted and an envelope
reaches the gate:

    $ node --experimental-strip-types consumer/src/run.ts \
        --bundle fixtures/bundles/good-envelope --network testnet
    mode: REHEARSAL, nothing will be sent
    REHEARSAL, nothing sent: {"coin":"#39710",...,"size":"924","limit_price":"0.17399"}
    APPROVED {"coin":"#39710",...}
    orders sent: 0

**Do not diagnose a bundle from `registry/`.** That directory is the review SOURCE, not
what the checker reads for a given bundle. A bundle carries its own `registry-*.json`
copies, and the two can disagree. **The allowlist is what decides**, and it is derived
from `registry/` at build time — so after any review you must rebuild:

    $ python3 tools/build_checker.py

### If a family is not in this checker's allowlist

A bundle built against a reviewed copy, checked by a build that was not told to trust
that version, is refused like this:

    REFUSED CHECKER_REFUSED: REDUCTION_UNDECLARED at $result.reductions: leg bucket0-yes
      rests on recurring.priceBucket at version 0f751913…b539, which is not in this
      checker's allowlist, so this checker reduces it under unreviewed_family; the
      result declares no reduction for that leg
    orders sent: 0

**Zero orders sent. This is correct behaviour, not a fault.** The message names the leg,
the family, the exact version, and the reason — so the fix is either to review that
entry and rebuild, or to accept that this checker does not trust that reading.

This refusal used to arrive as `PROFILE_COVERAGE at $result.profile`, which reads like a
broken payoff profile and sent operators looking two steps away from the cause. If you
see `PROFILE_COVERAGE` now, it means what it says: the profile really does disagree.

**A review is the owner's, and only the owner's.** Until an entry is `reviewed` with a
digest matching its `semantics_version`, every real check on it is `needs_review` and
the gate refuses to place. `needs_review` is not a softer pass.

## 1. Create a testnet agent wallet

In the venue's own interface, on **testnet**:

1. Open the API / agent wallet section.
2. Create an **agent** (API wallet). An agent signs orders; it cannot withdraw.
3. Copy the agent's private key when shown. It is shown once.

Never use your main wallet's key. The agent is the blast radius.

## 2. Fund the testnet account

Use the venue's testnet faucet to credit the account the agent acts for. Testnet funds
have no value. Fund the minimum the venue requires to accept an order.

## 3. The key, in the environment, for the length of the run

The key is read from **`HEDGECHECK_AGENT_KEY`** and nowhere else. Nothing reads a key
from a file, a flag, or a config; a test greps the whole of `consumer/` for another
source and fails if one appears.

Type it as input rather than putting it on a command line, so it never reaches your
shell history:

    read -rs HEDGECHECK_AGENT_KEY && export HEDGECHECK_AGENT_KEY

`read -rs` does not echo. History records command LINES, and the key is typed as
input, so it is not a history candidate either way. `export` then keeps the value for
the life of this shell — it does not expire on its own — so unset it the moment the
run is done:

    unset HEDGECHECK_AGENT_KEY

**For the length of one run.** Not a session, not a day, not a `.env` file.

## 4. The single command

    node --experimental-strip-types consumer/src/run.ts \
      --bundle <BUNDLE_DIR> --network testnet

**This sends nothing.** Without `--send` it is a rehearsal: the gate runs in full and
stops before the venue. Sending is opt-in, so a flag that goes missing leaves the run
harmless rather than armed. Every run states its mode on the first line, before the
gate, including refusals:

    mode: REHEARSAL, nothing will be sent
    mode: LIVE SEND

**Check that line.** It is the only thing that tells you which run you are in.

To actually place the order, add `--send` AND affirm the bundle matches the network:

    node --experimental-strip-types consumer/src/run.ts \
      --bundle <BUNDLE_DIR> --network testnet \
      --send --bundle-is-for-this-network

`--send` alone refuses (exit 2). A bundle records no network — the retained request
records do, but they are not bundle parts — so nothing in it can be checked against
`--network`, and the gate cannot catch a mainnet bundle aimed at testnet. You assert it,
having confirmed the bundle's instruments exist there. See the STOP section above:
today, for every bundle in this repository, they do not.

An unrecognised argument is refused rather than ignored, so a mistyped flag stops the
run instead of silently changing what it does.

`--captured-at <ms>` states when the book was captured, in whole milliseconds since
the epoch. It defaults to now. It is your statement: the bundle records a skew, never
an instant, so nothing can re-derive it. A capture 15 minutes old or older is stale
and the gate refuses.

## 5. What to expect

Every outcome prints an `orders sent:` line. **If that line is missing, or the count
is not what you expect, stop and check your fills before running anything again.**

**Refusal** (exit 1).

    REFUSED <REASON>: <detail>
    orders sent: 0

Reasons: `CHECKER_REFUSED`, `NOT_PASSES`, `NO_ENVELOPE`, `DIGEST_MISMATCH`,
`CAPTURE_STALE`, `POLICY_INVALID`, `CHECKER_THREW`, `UNREADABLE`.

**Usage error** (exit 2). A bad argument, an unknown network, or mainnet. Nothing was
read and nothing was sent.

**Failed before the gate** (exit 3). A bad `--captured-at`, a missing bundle, a
manifest naming a path outside its own directory.

    FAILED BEFORE THE GATE: <what>
    orders sent: 0

A distinct code from a refusal, so "it crashed" and "it said no" are never confused.
No order can have been sent: the gate had not run.

**Failed during the send** (exit 4).

    FAILED: <what>
    orders sent: <count>

Read the count. If it is 1, an order reached the venue and you do not yet know what it
did — go to "Timeout / no answer" below.

**Success** (exit 0).

    APPROVED {"coin":"#...","side":"buy","size":"...","limit_price":"...", ...}
    venue answered: {"status":200,"body":"..."}

Read `body` for what actually filled. The order is `Ioc`, so it fills what it can at
the limit and cancels the rest.

**Partial fill.** The position is not the one the bound was computed for. A smaller
position can miss an objective the full size met. Re-check it:
`proposalAfterFill` in `consumer/src/recheck.ts` builds the proposal for what is
actually held — the filled size, at the price actually paid, with the baseline
inherited so the premium counts once. Put that through the gate as a new question.
Topping up is a new proposal through the same gate; it is never automatic.

**Timeout / no answer.** The order was sent once and is **not** retried. An `Ioc` that
timed out may still have filled. Do not re-run the command. Query your fills in the
venue's interface, find out what actually happened, and decide from there.

## 6. Retain the bytes as evidence

    node --experimental-strip-types consumer/src/run.ts \
      --bundle <BUNDLE_DIR> --network testnet \
      --send --bundle-is-for-this-network \
      > research/testnet-run-$(date -u +%Y%m%dT%H%M%SZ).log 2>&1

`2>&1` captures errors as well as output, which is what you want for evidence — and
is why nothing on this path is allowed to put a key into an error. A malformed or
out-of-range key is refused by name before it reaches the signing library, and the
library's own errors are replaced rather than passed through. Read the log once
before you keep it.

Record alongside it: the UTC time, the bundle directory and its manifest digest, the
agent address (not the key), and the venue's response body verbatim. Note whether the
run was `--dry-run`.

Never paste the key into the log, an issue, or a commit. If a key reaches a log, treat
it as disclosed: revoke it (step 7) and create a new agent.

## 7. Revoke the agent afterwards

In the venue's interface, on testnet, revoke or deauthorize the agent wallet as soon
as the run is finished. Then:

    unset HEDGECHECK_AGENT_KEY

An agent left authorized is a signing key with no further purpose.

## On builder fees

`ApproveBuilderFee` **must be signed by the user's main wallet** — an agent cannot do
it, and no step here does it. If you want a builder fee approved, do it by hand in the
venue's interface, knowingly.

This tool does not send `ApproveBuilderFee` and does not need it for the run above.

Fees are carried as a dated assumption: the venue's own text says fees are currently
zero for outcome markets for initial testing. That is a stated-as-of fact, not a
permanent one. Whether builder fees apply to the buying side of outcome orders is
**unresolved** — the venue's own pages disagree. Do not assume zero cost on mainnet.
