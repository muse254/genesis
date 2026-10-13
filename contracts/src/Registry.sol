// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {MerkleProof} from "openzeppelin-contracts/contracts/utils/cryptography/MerkleProof.sol";

/// @title Registry -- ERC-7053 commit log plus a camera-body registry.
/// @notice Records the PRNU verdict; it does not compute it.
/// @dev Follows Numbers Protocol's ERC-7053 event shape exactly.
contract Registry {
    /// @notice This contract's version, semver.
    /// @dev Never upgraded in place: its dates are the claim, and a proxy
    ///      owner could rewrite them. An upgrade is a new deployment; old ones
    ///      stay readable and the earliest registration across them wins.
    string public constant VERSION = "1.0.0";

    /// @notice Domain tag for body ids. Must equal RECORD_VERSION in
    ///         ingest/record.py, or the two sides derive different ids.
    /// @dev Bumped only when id derivation changes, so body ids stay stable
    ///      across registry versions.
    bytes public constant RECORD_VERSION = "genesis-record-v1";

    /// @notice One enrolled camera body.
    /// @dev fingerprintCommitment is a hash of K. K never goes on chain:
    ///      a published reference is a published forgery kit.
    ///      bodyCommitment is an HMAC over make, model, serial and owner
    ///      (`ingest/hashing.py:body_commitment`), zero if none
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
    /// @dev Immutable and refused off a testnet. Verifiers should check it:
    ///      on a resettable registry, registration dates prove nothing.
    bool public immutable testMode;

    /// @notice Who may call `resetAll`. Zero when `testMode` is false.
    address public immutable admin;

    /// @notice Bumped by `resetAll`. Records are scoped by epoch, so a reset
    ///         is one storage write, not an unbounded loop.
    uint64 public epoch;

    /// @notice ERC-7053 commit log: asset CID -> commit indices.
    mapping(uint64 => mapping(string => uint256[])) private _commitLogs;

    mapping(uint64 => mapping(bytes32 => BodyRecord)) private _bodies;
    mapping(uint64 => mapping(bytes32 => ImageRecord)) private _images;
    /// @notice One Merkle root per import rather than one write per frame.
    mapping(uint64 => mapping(bytes32 => bytes32)) private _sessionRoots;

    /// @notice Running count of commits, which is what commitLogs indexes.
    /// @dev Deliberately NOT reset: reusing an index across epochs would
    ///      make the event log ambiguous.
    uint256 public commitCount;

    /// @notice Getter-shaped reads over the current epoch; records from a
    ///         previous epoch read as absent.
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
    event BodyTransferred(bytes32 indexed bodyId, address indexed from, address indexed to);
    /// @notice Anyone's statement about a body or image. See `attest`.
    event Attested(bytes32 indexed subject, address indexed attester, bytes32 indexed kind, bytes32 dataHash);
    /// @notice Anyone's dispute of a body or image. See `challenge`.
    event Challenged(bytes32 indexed subject, address indexed challenger, bytes32 evidenceHash);
    /// @notice Every record written before `newEpoch` is now unreachable.
    event RegistryReset(uint64 indexed previousEpoch, uint64 indexed newEpoch, address indexed by);

    /// @param enableTestMode Allow `resetAll`. **Pass false for mainnet.**
    /// @dev Explicit testnet allowlist, so it fails closed on unknown chains.
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
    /// @dev Testnet only, for rehearsals: body ids are deterministic, so
    ///      `registerBody` would otherwise refuse the same camera forever.
    ///      This rewrites history, which is why it can never exist on mainnet
    ///      (`docs/security.md`: first-registration time is a trust boundary).
    ///      Records become unreachable, not deleted, and the reset is an event.
    function resetAll() external {
        require(testMode, "not a test registry");
        require(msg.sender == admin, "not the admin");

        uint64 previous = epoch;
        epoch = previous + 1;
        emit RegistryReset(previous, epoch, msg.sender);
    }

    // --- ERC-7053 ---------------------------------------------------------

    /// @notice Log a commit against an asset CID.
    /// @dev Unchecked, per the EIP: anyone may call it. Ownership-checked
    ///      writes go through registerImage.
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
    /// @dev Derived, not chosen, so nobody can squat someone else's id.
    function deriveBodyId(bytes32 fingerprintCommitment) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(RECORD_VERSION, "body", fingerprintCommitment));
    }

    /// @param bodyCommitment Optional; zero for none. No setter on purpose:
    ///        it is only worth something if it predates any dispute.
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
    /// @dev Existing records stay: rewriting history would make every past
    ///      record unfalsifiable.
    function revokeBody(bytes32 bodyId) external {
        BodyRecord storage body = _bodies[epoch][bodyId];
        require(body.fingerprintCommitment != bytes32(0), "unknown body");
        require(body.owner == msg.sender, "not the body owner");
        require(!body.revoked, "already revoked");

        body.revoked = true;
        emit BodyRevoked(bodyId);
    }

    /// @notice Hand a body to a new owner; its history stays.
    /// @dev Current owner only, not while revoked. Earlier images stay
    ///      attributed to the owner of the time.
    function transferBody(bytes32 bodyId, address newOwner) external {
        BodyRecord storage body = _bodies[epoch][bodyId];
        require(body.fingerprintCommitment != bytes32(0), "unknown body");
        require(body.owner == msg.sender, "not the body owner");
        require(!body.revoked, "body revoked");
        require(newOwner != address(0), "zero owner");

        body.owner = newOwner;
        emit BodyTransferred(bodyId, msg.sender, newOwner);
    }

    // --- attestations and challenges --------------------------------------
    //
    // Event-only and unchecked: verifiers choose whose statements to trust.

    /// @param subject A body id, an image hash or any other 32-byte subject.
    /// @param kind    A tag the attester defines, e.g. keccak256("witnessed-enrolment-v1").
    /// @param dataHash Hash of the statement or evidence held off chain.
    function attest(bytes32 subject, bytes32 kind, bytes32 dataHash) external {
        require(subject != bytes32(0), "empty subject");
        emit Attested(subject, msg.sender, kind, dataHash);
    }

    /// @param subject A body id or an image hash.
    /// @param evidenceHash Hash of the evidence held off chain.
    function challenge(bytes32 subject, bytes32 evidenceHash) external {
        require(subject != bytes32(0), "empty subject");
        emit Challenged(subject, msg.sender, evidenceHash);
    }

    // --- image registry ---------------------------------------------------

    /// @notice Register one photograph against its body.
    /// @dev Only the body's owner may attribute an image to it.
    ///      `registeredAt` comes from `block.timestamp`, never the caller,
    ///      so a registration cannot be backdated.
    function registerImage(ImageRecord calldata input) external {
        ImageRecord memory record = input;
        record.registeredAt = uint64(block.timestamp);
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

        // Also an ERC-7053 entry, for standard indexers.
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
    /// @dev OpenZeppelin rules (keccak256, sorted pairs); ingest/merkle.py
    ///      must match, including promoting odd nodes.
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
