# The live testnet order

For the owner, by hand. No agent runs any step on this page.

**No mainnet key is ever used.** Every step here is testnet. The script refuses
`--network mainnet` outright; reaching mainnet is not a flag away.

## What this run establishes, and what it does not

It exercises the **order path**: envelope to signed action, one send, and the answer
read back. It does **not** exercise the hedge check.

Testnet has no shared expiry across its outcome markets, and both books were empty
when the venue was last read (0 bids, 0 asks). A depth walk over an empty book prices
nothing, so there is no testnet hedge to check. The bound this tool exists to compute
is a mainnet question, and this run does not answer it.

Do not read a success here as a checked hedge.

## 0. Before anything: the gate will refuse today

Both registry entries are `draft`:

    $ python3 -c "import json;print(json.load(open('registry/recurring.priceBucket.json'))['review']['state'])"
    draft

The build derives its allowlist from genuinely reviewed entries, so it is empty:

    $ cat checker/dist/allowlist.json
    {"reviewed": []}

An unreviewed family reduces its leg, the reduced leg contributes zero to the lower
profile, and the re-derived profile no longer matches the one the result states:

    $ node --experimental-strip-types consumer/src/run.ts \
        --bundle fixtures/bundles/good --network testnet --dry-run
    REFUSED CHECKER_REFUSED: PROFILE_COVERAGE at $result.profile: the result states 2 pieces, the proposal gives 1
    orders sent: 0

**Zero orders sent. This is correct behaviour, not a fault.**

Note the trap: the class reads `PROFILE_COVERAGE`, which sounds like a broken payoff
profile. It is not. With the family allowlisted the same bytes are accepted; the only
variable is the review state. If you see `PROFILE_COVERAGE` on a bundle you believe is
good, check the registry review state before you go looking at the profile.

**The owner's registry review is what unblocks a live approval.** Until an entry is
`reviewed` with a review digest matching its `semantics_version`, every real check is
`needs_review` and the gate refuses to place. `needs_review` is not a softer pass.

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

Set it for the single command, so it is never written to your shell history file or
left in the environment afterwards:

    read -rs HEDGECHECK_AGENT_KEY && export HEDGECHECK_AGENT_KEY

`read -rs` does not echo and does not enter history. Unset it the moment the run is
done:

    unset HEDGECHECK_AGENT_KEY

**For the length of one run.** Not a session, not a day, not a `.env` file.

## 4. The single command

    node --experimental-strip-types consumer/src/run.ts \
      --bundle <BUNDLE_DIR> --network testnet

Add `--dry-run` to do everything, including the gate, and stop before sending. **Run
it once with `--dry-run` first.**

`--captured-at <ms>` states when the book was captured, in milliseconds since the
epoch. It defaults to now. It is your statement: the bundle records a skew, never an
instant, so nothing can re-derive it. A capture 15 minutes old or older is stale and
the gate refuses.

## 5. What to expect

**Refusal** (exit 1). The common case today.

    REFUSED <REASON>: <detail>
    orders sent: 0

`orders sent: 0` is printed on every refusal. If you ever see a refusal with a nonzero
count, stop and treat it as a defect in the gate.

Reasons: `CHECKER_REFUSED`, `NOT_PASSES`, `NO_ENVELOPE`, `DIGEST_MISMATCH`,
`CAPTURE_STALE`, `CHECKER_THREW`, `UNREADABLE`.

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
      > research/testnet-run-$(date -u +%Y%m%dT%H%M%SZ).log 2>&1

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
