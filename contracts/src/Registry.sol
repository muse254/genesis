// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MerkleProof} from "openzeppelin-contracts/contracts/utils/cryptography/MerkleProof.sol";

/// @title Registry -- ERC-7053 commit log plus a camera-body registry.
/// @notice ERC-7053 defines the index and explicitly declines to validate
///         the content behind the CIDs. PRNU is that validation; this
///         contract records the verdict, it does not compute it.
/// @dev Conform to Numbers Protocol's ERC-7053 interface rather than
///      reimplementing the event shape and getting it subtly wrong.
contract Registry {
    /// @notice Domain tag for body ids. Must equal RECORD_VERSION in
    ///         ingest/record.py -- the id is derived the same way on both
    ///         sides so that neither can register something the other
    ///         cannot reproduce.
    bytes private constant RECORD_VERSION = "genesis-record-v1";

    /// @notice One enrolled camera body.
    /// @dev fingerprintCommitment is a hash of K. K itself never goes on
    ///      chain -- a published reference is a published forgery kit.
    ///
    ///      bodyCommitment binds the body to a camera someone can physically
    ///      produce: an HMAC over make, model, serial and owner from
    ///      `ingest/hashing.py:body_commitment`, never the serial in clear.
    ///      Zero when the photographer chose not to commit one. It takes the
    ///      slot the ENS node used to occupy, so the ABI types are unchanged
    ///      (`docs/security.md`, "Binding a body to a physical camera").
    struct BodyRecord {
        bytes32 fingerprintCommitment;
        address owner;
        bytes32 bodyCommitment;
        bool revoked;
    }

    /// @notice One registered photograph.
    struct ImageRecord {
        bytes32 imageHash;         // SHA-256 of pixel data
        bytes32 perceptualHash;    // survives re-encode
        bytes32 bodyId;
        uint8 modificationLevel;   // 0 raw | 1 adjust | 2 generative
        bytes32 parentImageHash;   // 0x0 for originals
        bytes32 metadataHmac;      // timestamp . geo . owner
        uint32 pceScore;
        uint64 registeredAt;
    }

    /// @notice True only on a registry that can be wiped. See `resetAll`.
    /// @dev Immutable and refused outright off a testnet, so no upgrade, no
    ///      admin action and no mistake can turn it on for a mainnet
    ///      deployment. A verifier should read this before believing a
    ///      registration date: on a resettable registry, "first registered
    ///      at T" is not a claim anyone can rely on.
    bool public immutable testMode;

    /// @notice Who may call `resetAll`. Zero when `testMode` is false.
    address public immutable admin;

    /// @notice Bumped by `resetAll`. Every record is scoped to the epoch it
    ///         was written in, so a reset is one storage write rather than an
    ///         unbounded loop over records nothing on chain can enumerate.
    uint64 public epoch;

    /// @notice ERC-7053 commit log: asset CID -> commit indices.
    mapping(uint64 => mapping(string => uint256[])) private _commitLogs;

    mapping(uint64 => mapping(bytes32 => BodyRecord)) private _bodies;
    mapping(uint64 => mapping(bytes32 => ImageRecord)) private _images;
    /// @notice Session batching: one Merkle root per import, not one write
    ///         per photograph. A shoot is 2,000 frames.
    mapping(uint64 => mapping(bytes32 => bytes32)) private _sessionRoots;

    /// @notice Running count of commits, which is what commitLogs indexes.
    /// @dev Deliberately NOT reset: a commit that happened, happened, and
    ///      reusing an index across epochs would make the event log ambiguous.
    uint256 public commitCount;

    /// @notice The same reads the auto-generated getters used to provide, so
    ///         the ABI is unchanged for the verify page, the console and the
    ///         subgraph. Records from a previous epoch read as absent, which
    ///         is exactly how an unregistered hash has always read.
    function bodies(bytes32 bodyId) external view returns (
        bytes32 fingerprintCommitment, address owner, bytes32 bodyCommitment, bool revoked
    ) {
        BodyRecord storage body = _bodies[epoch][bodyId];
        return (body.fingerprintCommitment, body.owner, body.bodyCommitment, body.revoked);
    }

    function images(bytes32 imageHash) external view returns (
        bytes32 imageHash_,
        bytes32 perceptualHash,
        bytes32 bodyId,
        uint8 modificationLevel,
        bytes32 parentImageHash,
        bytes32 metadataHmac,
        uint32 pceScore,
        uint64 registeredAt
    ) {
        ImageRecord storage r = _images[epoch][imageHash];
        return (
            r.imageHash, r.perceptualHash, r.bodyId, r.modificationLevel,
            r.parentImageHash, r.metadataHmac, r.pceScore, r.registeredAt
        );
    }

    function sessionRoots(bytes32 sessionId) external view returns (bytes32) {
        return _sessionRoots[epoch][sessionId];
    }

    function commitLogs(string calldata assetCid, uint256 index) external view returns (uint256) {
        return _commitLogs[epoch][assetCid][index];
    }

    event Commit(address indexed recorder, string assetCid, string commitData);
    event BodyRegistered(bytes32 indexed bodyId, address indexed owner, bytes32 bodyCommitment);
    event BodyRevoked(bytes32 indexed bodyId);
    event ImageRegistered(bytes32 indexed imageHash, bytes32 indexed bodyId, uint32 pceScore);
    event SessionCommitted(bytes32 indexed sessionId, bytes32 merkleRoot, uint32 frameCount);
    /// @notice Every record written before `newEpoch` is now unreachable.
    event RegistryReset(uint64 indexed previousEpoch, uint64 indexed newEpoch, address indexed by);

    /// @param enableTestMode Allow `resetAll`. **Pass false for mainnet.**
    /// @dev Refused outright off a known testnet, so this cannot be switched
    ///      on by accident where it would matter. The list is explicit rather
    ///      than "anything but mainnet", so it fails closed on a chain nobody
    ///      thought about.
    constructor(bool enableTestMode) {
        if (enableTestMode) {
            require(
                block.chainid == 11155111 // Sepolia
                    || block.chainid == 84532 // Base Sepolia
                    || block.chainid == 17000 // Holesky
                    || block.chainid == 31337 // anvil
                    || block.chainid == 1337, // ganache
                "test mode is testnet-only"
            );
            admin = msg.sender;
        }
        testMode = enableTestMode;
    }

    /// @notice Wipe every body, image, session and commit log in one call.
    /// @dev Exists so the demo can be rehearsed end to end without a fresh
    ///      deployment each time: `bodyId` derives from SHA-256(K), so the
    ///      same camera always reaches the same id and `registerBody` would
    ///      otherwise refuse forever after the first run.
    ///
    ///      **This is not revocation, and it is not a feature.** `revokeBody`
    ///      says "no more from here" and leaves written records standing,
    ///      because rewriting history would make every past record
    ///      unfalsifiable. This does precisely that rewriting, which is why it
    ///      cannot exist on mainnet: `docs/security.md` counts
    ///      first-registration time as one of only two boundaries the system
    ///      has, and a registry whose dates can be withdrawn has one.
    ///
    ///      Records are made unreachable rather than deleted, and the reset is
    ///      an event, so the wipe is itself part of the permanent history.
    function resetAll() external {
        require(testMode, "not a test registry");
        require(msg.sender == admin, "not the admin");

        uint64 previous = epoch;
        epoch = previous + 1;
        emit RegistryReset(previous, epoch, msg.sender);
    }

    // --- ERC-7053 ---------------------------------------------------------

    /// @notice Log a commit against an asset CID.
    /// @dev The EIP deliberately says nothing about what the CID points at
    ///      or whether the data is true. Anyone may call this; a caller
    ///      asserting a body they do not own should use registerImage,
    ///      which checks.
    function commit(string calldata assetCid, string calldata commitData) external {
        _commit(assetCid, commitData);
    }

    function _commit(string memory assetCid, string memory commitData) internal {
        _commitLogs[epoch][assetCid].push(commitCount);
        commitCount += 1;
        emit Commit(msg.sender, assetCid, commitData);
    }

    /// @notice How many commits an asset CID carries.
    function commitCountFor(string calldata assetCid) external view returns (uint256) {
        return _commitLogs[epoch][assetCid].length;
    }

    // --- body registry ----------------------------------------------------

    /// @notice The id a fingerprint commitment must be registered under.
    /// @dev Derived rather than chosen, so the same camera reaches the same
    ///      id for everyone and nobody can squat an id that does not follow
    ///      from their own commitment.
    function deriveBodyId(bytes32 fingerprintCommitment) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(RECORD_VERSION, "body", fingerprintCommitment));
    }

    /// @param bodyCommitment Optional; zero for none. There is no setter, on
    ///        purpose: the commitment is worth something only because it
    ///        predates any dispute, and one added later would not.
    function registerBody(bytes32 bodyId, bytes32 fingerprintCommitment, bytes32 bodyCommitment) external {
        require(fingerprintCommitment != bytes32(0), "empty commitment");
        require(bodyId == deriveBodyId(fingerprintCommitment), "bodyId must derive from commitment");
        require(_bodies[epoch][bodyId].fingerprintCommitment == bytes32(0), "body already registered");

        _bodies[epoch][bodyId] = BodyRecord({
            fingerprintCommitment: fingerprintCommitment,
            owner: msg.sender,
            bodyCommitment: bodyCommitment,
            revoked: false
        });

        emit BodyRegistered(bodyId, msg.sender, bodyCommitment);
    }

    /// @notice Revocation matters: a sold or stolen body must stop
    ///         certifying for its former owner.
    /// @dev Records already written stay written. Revocation says "no more
    ///      from here", not "none of that happened" -- rewriting history
    ///      would make every past record unfalsifiable.
    function revokeBody(bytes32 bodyId) external {
        BodyRecord storage body = _bodies[epoch][bodyId];
        require(body.fingerprintCommitment != bytes32(0), "unknown body");
        require(body.owner == msg.sender, "not the body owner");
        require(!body.revoked, "already revoked");

        body.revoked = true;
        emit BodyRevoked(bodyId);
    }

    // --- image registry ---------------------------------------------------

    /// @notice Register one photograph against its body.
    /// @dev Only the body's owner may attribute an image to it. Without
    ///      that check anyone could point a record at someone else's
    ///      camera, which is the claim the whole system exists to make.
    function registerImage(ImageRecord calldata record) external {
        BodyRecord storage body = _bodies[epoch][record.bodyId];
        require(body.fingerprintCommitment != bytes32(0), "unknown body");
        require(!body.revoked, "body revoked");
        require(body.owner == msg.sender, "not the body owner");
        require(record.imageHash != bytes32(0), "empty image hash");
        require(_images[epoch][record.imageHash].imageHash == bytes32(0), "image already registered");
        require(record.modificationLevel <= 2, "modification level out of range");
        require(
            record.parentImageHash == bytes32(0)
                || _images[epoch][record.parentImageHash].imageHash != bytes32(0),
            "unknown parent image"
        );

        _images[epoch][record.imageHash] = record;
        emit ImageRegistered(record.imageHash, record.bodyId, record.pceScore);

        // An ERC-7053 entry as well, so an indexer following the standard
        // sees this without knowing anything about this contract.
        _commit(_assetCid(record.imageHash), "");
    }

    /// @dev The local URI ingest/record.py uses when nothing has been pinned.
    function _assetCid(bytes32 imageHash) internal pure returns (string memory) {
        bytes16 hexAlphabet = "0123456789abcdef";
        bytes memory out = new bytes(8 + 64);
        out[0] = "g"; out[1] = "e"; out[2] = "n"; out[3] = "e";
        out[4] = "s"; out[5] = "i"; out[6] = "s"; out[7] = ":";
        for (uint256 i = 0; i < 32; i++) {
            out[8 + i * 2] = hexAlphabet[uint8(imageHash[i]) >> 4];
            out[9 + i * 2] = hexAlphabet[uint8(imageHash[i]) & 0x0f];
        }
        return string(out);
    }

    function commitSession(bytes32 sessionId, bytes32 merkleRoot, uint32 frameCount) external {
        require(merkleRoot != bytes32(0), "empty root");
        require(frameCount > 0, "empty session");
        require(_sessionRoots[epoch][sessionId] == bytes32(0), "session already committed");

        _sessionRoots[epoch][sessionId] = merkleRoot;
        emit SessionCommitted(sessionId, merkleRoot, frameCount);
    }

    /// @notice Prove a frame was in a committed session.
    /// @dev OpenZeppelin's verifier: keccak256, pairs hashed in sorted
    ///      order. ingest/merkle.py builds trees to the same rules and
    ///      promotes an odd node rather than duplicating it, so proofs
    ///      generated there verify here.
    function verifyInclusion(bytes32 sessionId, bytes32 leaf, bytes32[] calldata proof)
        external
        view
        returns (bool)
    {
        bytes32 root = _sessionRoots[epoch][sessionId];
        if (root == bytes32(0)) return false;
        return MerkleProof.verify(proof, root, leaf);
    }
}
