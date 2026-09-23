# Deploying and using the approved-order gate

For the owner, by hand. No agent runs any step on this page, and nothing in this repository
can: `onchain/` holds a contract and its tests, and `make check` compiles and runs them
offline. Deploying, approving and sending are yours.

**No mainnet key is ever used here.** Every step is testnet.

## STOP — read what this gate does and does not prove

It proves: **the order sent is the one a digest you approved authorised** — the asset that
digest named, as an `Ioc` buy, at no worse a price, no larger a size, and costing no more than
the approved ceiling. All integer comparisons, all on chain.

It does **not** prove the certificate is valid. Nothing on a chain can:

- Verifying a certificate means rebuilding the payoff profile from the proposal and
  re-deriving the verdict — canonical JSON, exact rationals, piecewise functions, infima over
  a domain. Three implementations do that off chain; a fourth here would cost enormous gas and
  add a fourth thing to keep in step.
- **The evidence cannot be established on chain at all.** A cost bound is walked from an order
  book. Retained evidence — `research/2026-09-18-decisions/interacting-with-hypercore.md` at
  commit `085ccfb`, read with `git show`, not in the working tree — lists the read
  precompiles as "perps positions, spot balances, vault equity, staking
  delegations, oracle prices, and the L1 block number" — there is no order book among them. A
  contract cannot see the depth the bound came from, and nothing on chain can attest that some
  bytes are the venue's own response.

So **you** check the certificate off chain, with the checker, and the gate holds the order to
what you approved. That replaces "trust whoever calls the sender" with "trust the digest the
owner approved". A real reduction. Not a proof.

## What no gate can undo

- **An `Ioc` order may fill partly, or not at all.** The remainder is cancelled, so you can
  end up with less protection than the verdict assumed — and the fill is decided after the
  gate has returned. A partial fill is a **new proposal**, re-checked against the books as they
  then are. It is not a smaller version of the one you approved.
- **The action is delayed.** Retained evidence: order actions sent from CoreWriter "are delayed
  onchain for a few seconds" so HyperEVM gives no latency advantage over the L1 mempool. The
  book that priced your bound is never the book that fills your order.
- **The explorer shows it twice.** Retained evidence: these onchain-delayed actions "appear
  twice in the L1 explorer: first as an enqueuing and second as a HyperCore execution". The
  first entry is not a fill. Do not read it as one.

## 0. There is nothing to send today, and the reason is liquidity

The same blocker as [`consumer/RUNBOOK.md`](../consumer/RUNBOOK.md), and worth repeating here
because this page is where someone will start.

**Do not approve a digest from `fixtures/bundles/`.** Every bundle in the repository is built
from MAINNET books and carries coin `#39710` — asset id `100,039,710`. Testnet's outcomes are a
different range. Approving one of those digests and sending it on testnet either bounces or
buys an unrelated instrument that answers to that id.

**Measured 23 Sep: depth exists, but this still blocks — on DISCOVERY, not liquidity.** The
sweep is read-only and is the check:

    $ python3 tools/sweep_testnet.py

114 of 1,236 books carry a quote, so the earlier "0 bids and 0 asks" on this page was a probe
bug (the wrong coin encoding answering `null`) and not an empty venue. But the live path still
refuses: `engine/discover/discover.go` needs a binary **and** a bucket at one expiry, and
testnet has no price bucket. And of the 10 markets that both lower and are quoted, every one is
Pyth-referenced, so it yields `needs_review` — which **this gate refuses by design.** See
[`consumer/RUNBOOK.md`](../consumer/RUNBOOK.md) for the full cross and the numbers.

So there is still nothing to approve today. Steps 1 onward are correct and tested; they wait on
a decision about discovery or a declared basis bound, both of which are the owner's. **Re-sweep
before you approve anything** regardless: these are dated instruments and the digest you
approve is bound to a capture.

## 1. Build and check the gate

Offline, with no dependencies. `forge-std` is not used — ARCHITECTURE allows exactly one
third-party dependency and it is `@noble/curves` in `consumer/` — so the tests are plain
Solidity.

    $ cd onchain && forge test --offline
    Ran 1 test suite in 25.43ms: 12 tests passed, 0 failed, 0 skipped (12 total tests)

`make check` runs this too, and skips it with a notice where `forge` is absent.

## 2. Check the certificate off chain, and get its digest

This is the step the gate cannot do for you, and the only one that establishes anything about
the hedge. Run the checker over the bundle and read the verdict:

    $ node --experimental-strip-types consumer/src/run.ts --bundle <dir> --network testnet

Approve **only** on `accept` with `model_result: passes` and an `order_envelope`. Anything
else — `needs_review` included — is not an approval. `needs_review` is not a softer pass.

The digest to approve is the envelope's own `input_digest`. It binds everything that
determines the result except the engine: the proposal, the lowered form, the semantics versions
and every cited snapshot. Change the size, the cap, or a snapshot, and it moves — verified.

    $ python3 -c "import json;print(json.load(open('<dir>/result.json'))['order_envelope']['input_digest'])"

## 3. Deploy

Two arguments: who may approve, and where actions go. Pass the CoreWriter address the venue
documents; the constructor refuses the zero address for either.

    $ forge create onchain/src/ApprovedOrderGate.sol:ApprovedOrderGate \
        --rpc-url https://rpc.hyperliquid-testnet.xyz/evm \
        --constructor-args <your-address> 0x3333333333333333333333333333333333333333

**There is no owner transfer.** A new owner is a new gate — a gate whose owner can change is a
gate whose approvals can be re-pointed by whoever holds the key today.

The writer address is a constructor argument rather than a hardcoded constant so a test can
observe the call it makes. That is the same shape as the consumer's `place` parameter: the thing
that can act is supplied, not constructed. **Check it after deploying** — reading `coreWriter()`
is one call, and a gate pointed at the wrong address would report success having done nothing.

    $ cast call <gate> "coreWriter()(address)" --rpc-url <rpc>

## 4. Approve what the envelope authorises

Every number is the envelope's, scaled to the venue's own 10^8 fixed point: retained evidence
says `limitPx` and `sz` are sent as "10^8 * the human readable value".

Worked from the retained mainnet envelope — **as an illustration of the arithmetic, not
something to send**:

| Envelope field | Value | Scaled |
|---|---|---|
| `coin` `#39710` | asset `100,000,000 + 39,710` | `100039710` |
| `limit_price` | `0.17399` | `17399000` |
| `size` | `924` | `92400000000` |
| `max_cost` | `160.76676` | `1607667600000000000` (at 10^16) |

`max_cost` is scaled to **10^16**, not 10^8: it is compared against `limitPx * sz`, and the
product of two 10^8 values lives at 10^16. No division, so no rounding.

    $ cast send <gate> "approve(bytes32,uint32,uint64,uint64,uint128)" \
        <input_digest> 100039710 17399000 92400000000 1607667600000000000 \
        --rpc-url <rpc> --interactive

**A value that does not survive 10^8 exactly is refused, not rounded**, by the encoder in
`consumer/src/corewriter.ts`. Rounding would send an order about a number nobody established.
It does not bite on real data: the envelope carries a displayed price and a sum of products,
never an average. The retained books need 10^5 at most, five orders inside the scale.

## 5. Send

The price and size are the caller's; the asset is not — it comes from the approval, so there is
nothing to get wrong. Both are **ceilings**: a better price or a smaller size is inside what you
approved, and the gate lets those through, because refusing them would make it stricter than
the claim rather than faithful to it.

    $ cast send <gate> "send(bytes32,uint64,uint64)" \
        <input_digest> 17399000 92400000000 --rpc-url <rpc> --interactive

**Anyone may call `send`.** Deliberate: what it can send is bounded by what you approved, so the
guarantee does not rest on who holds a key at the moment of sending.

If it reverts, the reason names which ceiling bound:

| Revert | Meaning |
|---|---|
| `NotApproved` | no approval for that digest, or it was withdrawn |
| `PriceTooHigh` | a worse price than approved |
| `SizeTooLarge` | a larger size than approved |
| `CostTooHigh` | inside both ceilings but over the approved cost — approve a small size at a high price and this is what stops the full size going through |
| `ZeroSize` | not an order |

## 6. Read the result, and do not trust the first explorer entry

Expect **two** entries: the enqueuing, then the HyperCore execution a few seconds later. Only
the second is the order reaching the book.

Then read the fill from HyperCore, not from the chain. The gate's `OrderSent` event says what
was **sent**, and says nothing about what filled — an `Ioc` remainder is cancelled silently.

## 7. Withdraw the approval afterwards

A certificate is about a book that keeps moving. An approval you no longer stand behind should
not be sitting there.

    $ cast send <gate> "withdraw(bytes32)" <input_digest> --rpc-url <rpc> --interactive

Use is not one-shot by design — a partial fill may warrant a second send within the same
ceilings — so the approval outlives one send and withdrawing is the deliberate end of it.

## What is not established here

- **Deployment has not been done.** No gate address exists; nothing on this page has been run
  against a chain. It is written from the contract's own ABI, its tests, and retained evidence.
- **No chain id or mainnet RPC is stated**, because the retained page gives neither. It names
  `rpc.hyperliquid-testnet.xyz` only. Look them up before going near mainnet; do not infer.
- **Gas is not measured.** Retained evidence says CoreWriter burns ~25,000 gas and "in practice
  the gas usage for a basic call will be ~47000", which is the venue's figure for its own
  example and not a measurement of this gate.
