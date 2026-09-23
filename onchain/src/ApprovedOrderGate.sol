// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title ApprovedOrderGate
///
/// @notice Sends a CoreWriter limit order only when it is the order an approved certificate
/// authorised, and refuses everything else.
///
/// WHAT THIS PROVES, AND WHAT IT DOES NOT.
///
/// It proves: the order emitted is the one a named `inputDigest` approved, at no worse a price
/// and no larger a size, as an `Ioc` buy of the asset that digest named, costing at most the
/// `maxCost` it named. All of that is integer arithmetic on numbers the caller supplies and the
/// gate compares against what the owner approved.
///
/// It does NOT prove the certificate is valid. A certificate is verified by rebuilding the
/// payoff profile from the proposal and re-deriving the verdict — canonical JSON, exact
/// rationals, piecewise functions, infima over a domain. That is three implementations'
/// worth of work off chain and would be a fourth here, at enormous gas, with the drift risk
/// that implies.
///
/// And it could not be made sound even then, because the EVIDENCE cannot be established on
/// chain. A cost bound is walked from an order book, and retained evidence
/// (085ccfb, `interacting-with-hypercore.md`) lists the read precompiles as "perps positions,
/// spot balances, vault equity, staking delegations, oracle prices, and the L1 block number" —
/// there is no order book among them. A contract cannot see the depth the bound came from, and
/// nothing on chain can attest that some bytes are the venue's own response.
///
/// So the trust boundary is stated rather than hidden: the OWNER approves a digest, having
/// checked the certificate off chain with `checker/`, and the gate holds the order to it. The
/// gate replaces "trust whoever called the sender" with "trust the digest the owner approved",
/// which is a real reduction and not a proof.
///
/// WHAT NO GATE CAN UNDO. An `Ioc` order may fill PARTLY or not at all: the remainder is
/// cancelled, so the holder can end up with less protection than the verdict assumed, and the
/// fill is decided after this function has returned. A partial fill is a NEW proposal, re-checked
/// against the books as they then are — not a smaller version of the one approved. And retained
/// evidence says actions from CoreWriter "are delayed onchain for a few seconds", so the book
/// that priced the bound is never the book that fills the order.
contract ApprovedOrderGate {
    /// @notice The system contract the venue documents. Retained evidence,
    /// `interacting-with-hypercore.md`.
    address public constant CORE_WRITER = 0x3333333333333333333333333333333333333333;

    /// @notice Where actions are sent. `CORE_WRITER` in production, and INJECTABLE so a test
    /// can observe what was sent without a cheatcode.
    ///
    /// The same shape as the consumer's `place` parameter: the thing that can ACT is supplied
    /// rather than constructed, so a test sees the real call and the production wiring is one
    /// visible argument. A gate that hardcoded the address would have to be tested by planting
    /// code at it, which needs a test framework this project does not depend on -- and an
    /// untested external call is the one part of a gate that most needs testing.
    address public immutable coreWriter;

    /// @notice Encoding version 1, the only one that exists.
    uint8 private constant ENCODING_VERSION = 1;

    /// @notice Action 1 is a limit order. The header below writes the three bytes literally,
    /// so this is the documented value rather than the source of them -- a shift of a wider
    /// constant would be a truncation to trust, and the bytes are the thing that matters.
    uint24 public constant ACTION_LIMIT_ORDER = 1;

    /// @notice `Ioc`. Retained evidence: "1 for Alo, 2 for Gtc, 3 for Ioc".
    uint8 private constant TIF_IOC = 3;

    /// @notice What one approved certificate authorises.
    ///
    /// Every field is what the envelope said, in the venue's own 10^8 fixed point. `limitPx` and
    /// `size` are ceilings, not equalities: an order at a better price or a smaller size is
    /// still inside what was approved, and refusing it would make the gate stricter than the
    /// claim rather than faithful to it.
    struct Approval {
        uint32 asset;
        uint64 limitPx;
        uint64 size;
        /// @dev limitPx * size at the approved values, in the 10^16 domain their product lives
        /// in. Stored rather than recomputed so the gate compares against what was approved and
        /// not against what the caller's numbers happen to multiply to.
        uint128 maxCost;
        bool approved;
    }

    /// @notice The owner, set once at construction. There is no transfer: an owner change is a
    /// new gate, because a gate whose owner can change is a gate whose approvals can be
    /// re-pointed by whoever holds the owner key today.
    address public immutable owner;

    /// @notice inputDigest => what it authorises.
    mapping(bytes32 => Approval) public approvals;

    /// @notice Emitted when the owner approves a certificate's order.
    event Approved(bytes32 indexed inputDigest, uint32 asset, uint64 limitPx, uint64 size, uint128 maxCost);

    /// @notice Emitted when an approval is withdrawn. Withdrawal is possible and use is not
    /// one-shot: an approval the owner no longer stands behind must be removable, and a
    /// certificate is about a book that keeps moving.
    event Withdrawn(bytes32 indexed inputDigest);

    /// @notice Emitted when an order is sent, naming the digest that authorised it.
    event OrderSent(bytes32 indexed inputDigest, uint32 asset, uint64 limitPx, uint64 size);

    error NotOwner();
    error NotApproved(bytes32 inputDigest);
    // There is no WrongAsset: the ASSET IS NOT A PARAMETER. It comes from the approval, so a
    // caller cannot name one -- which is stronger than checking it, because there is nothing
    // to get wrong. Only the price and the size are the caller's, and both are ceilinged.
    error PriceTooHigh(uint64 approved, uint64 asked);
    error SizeTooLarge(uint64 approved, uint64 asked);
    error CostTooHigh(uint128 approved, uint128 asked);
    error ZeroSize();
    error NoWriter();

    /// @param gateOwner who may approve. There is no transfer; a new owner is a new gate.
    /// @param writer where to send actions. Pass `CORE_WRITER` in production. Zero is refused:
    /// a gate that sends into nothing would report success having done nothing, which is worse
    /// than refusing, because a caller would believe an order was placed.
    constructor(address gateOwner, address writer) {
        if (gateOwner == address(0)) revert NotOwner();
        if (writer == address(0)) revert NoWriter();
        owner = gateOwner;
        coreWriter = writer;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    /// @notice Approve the order a certificate authorises.
    ///
    /// The owner has checked the certificate off chain; this records what it permits. `maxCost`
    /// is taken from the envelope rather than computed here, so the ceiling is the one the
    /// verdict rested on.
    function approve(bytes32 inputDigest, uint32 asset, uint64 limitPx, uint64 size, uint128 maxCost)
        external
        onlyOwner
    {
        if (size == 0) revert ZeroSize();
        approvals[inputDigest] =
            Approval({asset: asset, limitPx: limitPx, size: size, maxCost: maxCost, approved: true});
        emit Approved(inputDigest, asset, limitPx, size, maxCost);
    }

    /// @notice Withdraw an approval.
    function withdraw(bytes32 inputDigest) external onlyOwner {
        delete approvals[inputDigest];
        emit Withdrawn(inputDigest);
    }

    /// @notice Send the order a digest approved, or revert.
    ///
    /// ANYONE MAY CALL THIS. What it can send is bounded by what the owner approved, so a
    /// caller who is not the owner can only send an order the owner already authorised — and
    /// that is deliberate: the gate's guarantee should not rest on who holds a key at the
    /// moment of sending.
    ///
    /// The cost check is `limitPx * size <= maxCost`, in the scaled domain. No division, so no
    /// rounding: the product of two 10^8 values lives at 10^16, and the approved `maxCost` was
    /// scaled the same way. `uint64 * uint64` cannot overflow `uint128`, so the multiplication
    /// is exact.
    function send(bytes32 inputDigest, uint64 limitPx, uint64 size) external {
        Approval memory permitted = approvals[inputDigest];
        if (!permitted.approved) revert NotApproved(inputDigest);
        if (size == 0) revert ZeroSize();
        if (limitPx > permitted.limitPx) revert PriceTooHigh(permitted.limitPx, limitPx);
        if (size > permitted.size) revert SizeTooLarge(permitted.size, size);

        uint128 cost = uint128(limitPx) * uint128(size);
        if (cost > permitted.maxCost) revert CostTooHigh(permitted.maxCost, cost);

        // THE EVENT IS EMITTED BEFORE THE CALL. CoreWriter is a system contract and not
        // expected to re-enter, but ordering state and logs before an external call is the rule
        // that does not depend on that expectation -- and a log that lands only if the callee
        // behaves is a log a reader cannot rely on.
        emit OrderSent(inputDigest, permitted.asset, limitPx, size);
        ICoreWriter(coreWriter).sendRawAction(_encode(permitted.asset, limitPx, size));
    }

    /// @notice The raw action bytes, exposed so the encoding can be checked without sending.
    ///
    /// The layout is the retained page's own: byte 0 the encoding version, bytes 1-3 the action
    /// id big-endian, then `abi.encode` of the seven fields. Every field is a static type, so
    /// the tail is seven 32-byte words with no head/tail split.
    function encodeLimitOrder(uint32 asset, uint64 limitPx, uint64 size) external pure returns (bytes memory) {
        return _encode(asset, limitPx, size);
    }

    /// @dev BUY AND `Ioc` ONLY, and not parameters. An envelope bounds the cost of one order: a
    /// buy of its size, priced no worse than the highest level the walk touched, and cancelled
    /// rather than rested. A resting order outlives the book that priced it, so `Gtc` or `Alo`
    /// would make the bound a claim about evidence that has moved on. `reduceOnly` is false and
    /// `cloid` is zero for the same reason: the envelope describes acquiring protection.
    function _encode(uint32 asset, uint64 limitPx, uint64 size) private pure returns (bytes memory) {
        bytes memory action = abi.encode(asset, true, limitPx, size, false, TIF_IOC, uint128(0));
        bytes memory out = new bytes(4 + action.length);
        // The header, spelled out. The truncations are deliberate: the action id is three bytes
        // by the venue's definition, and these are the three. Written as constants rather than
        // shifts of a wider value so nothing has to be trusted not to truncate -- 1 is
        // 0x00 0x00 0x01, and if the action id ever changes the change is visible here.
        out[0] = bytes1(ENCODING_VERSION);
        out[1] = 0x00;
        out[2] = 0x00;
        out[3] = 0x01;
        for (uint256 index = 0; index < action.length; index += 1) {
            out[4 + index] = action[index];
        }
        return out;
    }
}

interface ICoreWriter {
    function sendRawAction(bytes calldata data) external;
}
