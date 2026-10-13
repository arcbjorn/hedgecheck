// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

import {ApprovedOrderGate, ICoreWriter} from "../src/ApprovedOrderGate.sol";

/// NO TEST FRAMEWORK. ARCHITECTURE allows exactly one third-party dependency — `@noble/curves`
/// in `consumer/`, for signing — so `forge-std` is not available and its cheatcodes are not
/// used. Everything below is plain Solidity: a helper contract to be a different `msg.sender`,
/// `try`/`catch` for expected reverts, and an injected recorder to observe the call.
///
/// That injection is why the gate takes its writer as a constructor argument. Hardcoding the
/// address would mean planting code at it to see the call, which needs the framework — and an
/// untested external call is the one part of a gate that most needs testing.

/// Records what was sent, standing in for the system contract.
contract RecordingCoreWriter is ICoreWriter {
    bytes public lastAction;
    uint256 public calls;

    function sendRawAction(bytes calldata data) external {
        lastAction = data;
        calls += 1;
    }
}

/// A `msg.sender` that is not the owner, without a cheatcode.
contract Caller {
    function send(ApprovedOrderGate gate, bytes32 digest, uint64 limitPx, uint64 size) external {
        gate.send(digest, limitPx, size);
    }

    function approve(ApprovedOrderGate gate, bytes32 digest, uint32 asset, uint64 limitPx, uint64 size, uint128 maxCost)
        external
    {
        gate.approve(digest, asset, limitPx, size, maxCost);
    }

    function withdraw(ApprovedOrderGate gate, bytes32 digest) external {
        gate.withdraw(digest);
    }
}

contract ApprovedOrderGateTest {
    ApprovedOrderGate internal gate;
    RecordingCoreWriter internal writer;
    Caller internal stranger;

    // The 18 September retained envelope, in the venue's own 10^8 fixed point: 0.17399 is
    // 17,399,000 and 924 contracts is 92,400,000,000. Their product is the envelope's own
    // max_cost of 160.76676, scaled to 10^16 — which is where the product of two 10^8 values
    // lives, so no division and no rounding.
    bytes32 internal constant DIGEST = keccak256("input-digest-of-the-18-september-bundle");
    uint32 internal constant ASSET = 100_039_710;
    uint64 internal constant LIMIT_PX = 17_399_000;
    uint64 internal constant SIZE = 92_400_000_000;
    uint128 internal constant MAX_COST = uint128(LIMIT_PX) * uint128(SIZE);

    error Failed(string what);

    function _check(bool condition, string memory what) internal pure {
        if (!condition) revert Failed(what);
    }

    /// Asserts a call reverts WITH A NAMED REASON, not merely that it reverts.
    ///
    /// The reason is the point. An absent approval is the zero struct, so `limitPx` and `size`
    /// are both 0 and any positive order trips `PriceTooHigh` or `SizeTooLarge` -- which means
    /// a test asking only "did it revert" cannot tell the approval check from the ceilings, and
    /// each masks the other. Run as mutations: removing the approval check, the price ceiling
    /// and the size ceiling ALL went undetected, the three most important refusals here.
    ///
    /// Two earlier spellings were worse. `try ... { revert Failed(...) } catch {}` puts the
    /// failure signal inside the block that catches it, so it passed either way; asserting only
    /// that the call failed hit the masking above. This asserts the selector.
    function _revertsWith(bytes memory call, bytes4 expected, string memory what) internal {
        (bool ok, bytes memory returned) = address(gate).call(call);
        _check(!ok, what);
        _check(returned.length >= 4, "a revert with no reason");
        bytes4 actual =
            bytes4(returned[0]) | (bytes4(returned[1]) >> 8) | (bytes4(returned[2]) >> 16) | (bytes4(returned[3]) >> 24);
        _check(actual == expected, what);
    }

    /// External so a refused construction is observable as a failed call.
    function deploy(address gateOwner, address gateWriter) external returns (address) {
        return address(new ApprovedOrderGate(gateOwner, gateWriter));
    }

    function setUp() public {
        writer = new RecordingCoreWriter();
        gate = new ApprovedOrderGate(address(this), address(writer));
        stranger = new Caller();
    }

    function _approve() internal {
        gate.approve(DIGEST, ASSET, LIMIT_PX, SIZE, MAX_COST);
    }

    // NOTHING IS SENT WITHOUT AN APPROVAL. The default is refusal, so a digest nobody approved
    // cannot produce an order however it is asked for.
    function test_RefusesAnUnapprovedDigest() public {
        _revertsWith(
            abi.encodeCall(gate.send, (DIGEST, LIMIT_PX, SIZE)),
            ApprovedOrderGate.NotApproved.selector,
            "an unapproved digest was sent"
        );
        _check(writer.calls() == 0, "an unapproved digest reached the writer");
    }

    // ONLY THE OWNER APPROVES. A gate anyone can approve against is not a gate.
    function test_OnlyOwnerApproves() public {
        (bool approved,) =
            address(stranger).call(abi.encodeCall(stranger.approve, (gate, DIGEST, ASSET, LIMIT_PX, SIZE, MAX_COST)));
        _check(!approved, "a stranger approved");
        (bool withdrew,) = address(stranger).call(abi.encodeCall(stranger.withdraw, (gate, DIGEST)));
        _check(!withdrew, "a stranger withdrew");
    }

    // THE APPROVED ORDER GOES THROUGH, and the bytes are the venue's layout: byte 0 the
    // encoding version, bytes 1-3 the action id big-endian, then seven static ABI words.
    function test_SendsTheApprovedOrder() public {
        _approve();
        gate.send(DIGEST, LIMIT_PX, SIZE);
        _check(writer.calls() == 1, "the approved order was not sent");

        bytes memory action = writer.lastAction();
        _check(action.length == 4 + 32 * 7, "wrong action length");
        _check(uint8(action[0]) == 1, "encoding version");
        _check(uint8(action[1]) == 0 && uint8(action[2]) == 0, "action id high bytes");
        _check(uint8(action[3]) == 1, "action id is the limit order");

        // DECODED, not compared byte for byte, so the test says what the fields MEAN.
        bytes memory tail = new bytes(action.length - 4);
        for (uint256 index = 0; index < tail.length; index += 1) {
            tail[index] = action[4 + index];
        }
        (uint32 asset, bool isBuy, uint64 limitPx, uint64 size, bool reduceOnly, uint8 tif, uint128 cloid) =
            abi.decode(tail, (uint32, bool, uint64, uint64, bool, uint8, uint128));
        _check(asset == ASSET, "asset");
        _check(isBuy, "an envelope bounds a buy");
        _check(limitPx == LIMIT_PX, "limitPx");
        _check(size == SIZE, "size");
        _check(!reduceOnly, "acquiring protection is not reduceOnly");
        _check(tif == 3, "Ioc, because a resting order outlives the book that priced it");
        _check(cloid == 0, "no client order id");
    }

    // A BETTER PRICE AND A SMALLER SIZE ARE INSIDE THE APPROVAL.
    //
    // The envelope is a CEILING, not an equality: paying less, or buying less, is still within
    // what the verdict permitted. Refusing them would make the gate stricter than the claim.
    function test_AllowsABetterPriceAndASmallerSize() public {
        _approve();
        gate.send(DIGEST, LIMIT_PX - 1, SIZE - 1);
        _check(writer.calls() == 1, "a strictly better order was refused");
    }

    // A WORSE PRICE OR A LARGER SIZE IS OUTSIDE IT.
    function test_RefusesAWorsePriceOrALargerSize() public {
        _approve();
        _revertsWith(
            abi.encodeCall(gate.send, (DIGEST, LIMIT_PX + 1, SIZE)),
            ApprovedOrderGate.PriceTooHigh.selector,
            "a worse price was sent"
        );
        _revertsWith(
            abi.encodeCall(gate.send, (DIGEST, LIMIT_PX, SIZE + 1)),
            ApprovedOrderGate.SizeTooLarge.selector,
            "a larger size was sent"
        );
        _check(writer.calls() == 0, "an order outside the approval was sent");
    }

    // THE COST CEILING BINDS ON ITS OWN.
    //
    // Without it a caller could stay under both the price and size ceilings and still spend
    // more than approved. Here the approval permits 924 contracts but a max_cost for only half,
    // so the price and size checks both pass and only the cost check refuses.
    function test_TheCostCeilingBindsOnItsOwn() public {
        gate.approve(DIGEST, ASSET, LIMIT_PX, SIZE, MAX_COST / 2);
        _revertsWith(
            abi.encodeCall(gate.send, (DIGEST, LIMIT_PX, SIZE)),
            ApprovedOrderGate.CostTooHigh.selector,
            "an order over the cost ceiling was sent"
        );
        _check(writer.calls() == 0, "the writer was reached");

        // And an order inside it still goes through, so the rule refuses the wrong order rather
        // than every order.
        gate.send(DIGEST, LIMIT_PX, SIZE / 2);
        _check(writer.calls() == 1, "an order inside the cost ceiling was refused");
    }

    // A ZERO SIZE IS NOT AN ORDER, in either direction.
    function test_RefusesAZeroSize() public {
        _revertsWith(
            abi.encodeCall(gate.approve, (DIGEST, ASSET, LIMIT_PX, 0, MAX_COST)),
            ApprovedOrderGate.ZeroSize.selector,
            "a zero size was approved"
        );
        _approve();
        _revertsWith(
            abi.encodeCall(gate.send, (DIGEST, LIMIT_PX, 0)),
            ApprovedOrderGate.ZeroSize.selector,
            "a zero size was sent"
        );
    }

    // WITHDRAWAL WORKS: a certificate is about a book that keeps moving, so an owner must be
    // able to stop standing behind one.
    function test_WithdrawalStopsFurtherSends() public {
        _approve();
        gate.send(DIGEST, LIMIT_PX, SIZE);
        gate.withdraw(DIGEST);
        _revertsWith(
            abi.encodeCall(gate.send, (DIGEST, LIMIT_PX, SIZE)),
            ApprovedOrderGate.NotApproved.selector,
            "a withdrawn approval still sent"
        );
        _check(writer.calls() == 1, "a withdrawn approval sent again");
    }

    // ANYONE MAY SEND what the owner approved. Deliberate: the guarantee is the approval, not
    // who calls at the moment of sending.
    function test_AnyoneMaySendAnApprovedOrder() public {
        _approve();
        stranger.send(gate, DIGEST, LIMIT_PX, SIZE);
        _check(writer.calls() == 1, "a stranger could not send an approved order");
    }

    // ONE DIGEST'S APPROVAL DOES NOT AUTHORISE ANOTHER'S ORDER.
    function test_ApprovalsDoNotLeakBetweenDigests() public {
        _approve();
        _revertsWith(
            abi.encodeCall(gate.send, (keccak256("a different certificate"), LIMIT_PX, SIZE)),
            ApprovedOrderGate.NotApproved.selector,
            "an approval leaked to another digest"
        );
        _check(writer.calls() == 0, "the writer was reached");
    }

    // NEITHER THE OWNER NOR THE WRITER MAY BE ZERO. A zero owner is a gate nobody can approve
    // against; a zero writer would report success having sent into nothing, which is worse than
    // refusing because a caller would believe an order was placed.
    function test_RefusesAZeroOwnerOrWriter() public {
        (bool zeroOwner,) = address(this).call(abi.encodeCall(this.deploy, (address(0), address(writer))));
        _check(!zeroOwner, "a zero owner was accepted");
        (bool zeroWriter,) = address(this).call(abi.encodeCall(this.deploy, (address(this), address(0))));
        _check(!zeroWriter, "a zero writer was accepted");
    }

    // THE PURE ENCODING IS WHAT GETS SENT, so the bytes can be checked without sending -- and
    // compared against the TypeScript encoder in `consumer/src/corewriter.ts`, which must agree.
    function test_ThePureEncodingIsWhatGetsSent() public {
        _approve();
        bytes memory encoded = gate.encodeLimitOrder(ASSET, LIMIT_PX, SIZE);
        gate.send(DIGEST, LIMIT_PX, SIZE);
        _check(keccak256(encoded) == keccak256(writer.lastAction()), "the pure encoding differs from what was sent");
    }
}
