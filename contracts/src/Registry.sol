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
    struct BodyRecord {
        bytes32 fingerprintCommitment;
        address owner;
        bytes32 ensNode;
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

    /// @notice ERC-7053 commit log: asset CID -> commit indices.
    mapping(string => uint256[]) public commitLogs;

    mapping(bytes32 => BodyRecord) public bodies;
    mapping(bytes32 => ImageRecord) public images;
    /// @notice Session batching: one Merkle root per import, not one write
    ///         per photograph. A shoot is 2,000 frames.
    mapping(bytes32 => bytes32) public sessionRoots;

    /// @notice Running count of commits, which is what commitLogs indexes.
    uint256 public commitCount;

    event Commit(address indexed recorder, string assetCid, string commitData);
    event BodyRegistered(bytes32 indexed bodyId, address indexed owner, bytes32 ensNode);
    event BodyRevoked(bytes32 indexed bodyId);
    event ImageRegistered(bytes32 indexed imageHash, bytes32 indexed bodyId, uint32 pceScore);
    event SessionCommitted(bytes32 indexed sessionId, bytes32 merkleRoot, uint32 frameCount);

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
        commitLogs[assetCid].push(commitCount);
        commitCount += 1;
        emit Commit(msg.sender, assetCid, commitData);
    }

    /// @notice How many commits an asset CID carries.
    function commitCountFor(string calldata assetCid) external view returns (uint256) {
        return commitLogs[assetCid].length;
    }

    // --- body registry ----------------------------------------------------

    /// @notice The id a fingerprint commitment must be registered under.
    /// @dev Derived rather than chosen, so the same camera reaches the same
    ///      id for everyone and nobody can squat an id that does not follow
    ///      from their own commitment.
    function deriveBodyId(bytes32 fingerprintCommitment) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(RECORD_VERSION, "body", fingerprintCommitment));
    }

    function registerBody(bytes32 bodyId, bytes32 fingerprintCommitment, bytes32 ensNode) external {
        require(fingerprintCommitment != bytes32(0), "empty commitment");
        require(bodyId == deriveBodyId(fingerprintCommitment), "bodyId must derive from commitment");
        require(bodies[bodyId].fingerprintCommitment == bytes32(0), "body already registered");

        bodies[bodyId] = BodyRecord({
            fingerprintCommitment: fingerprintCommitment,
            owner: msg.sender,
            ensNode: ensNode,
            revoked: false
        });

        emit BodyRegistered(bodyId, msg.sender, ensNode);
    }

    /// @notice Revocation matters: a sold or stolen body must stop
    ///         certifying for its former owner.
    /// @dev Records already written stay written. Revocation says "no more
    ///      from here", not "none of that happened" -- rewriting history
    ///      would make every past record unfalsifiable.
    function revokeBody(bytes32 bodyId) external {
        BodyRecord storage body = bodies[bodyId];
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
        BodyRecord storage body = bodies[record.bodyId];
        require(body.fingerprintCommitment != bytes32(0), "unknown body");
        require(!body.revoked, "body revoked");
        require(body.owner == msg.sender, "not the body owner");
        require(record.imageHash != bytes32(0), "empty image hash");
        require(images[record.imageHash].imageHash == bytes32(0), "image already registered");
        require(record.modificationLevel <= 2, "modification level out of range");
        require(
            record.parentImageHash == bytes32(0)
                || images[record.parentImageHash].imageHash != bytes32(0),
            "unknown parent image"
        );

        images[record.imageHash] = record;
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
        require(sessionRoots[sessionId] == bytes32(0), "session already committed");

        sessionRoots[sessionId] = merkleRoot;
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
        bytes32 root = sessionRoots[sessionId];
        if (root == bytes32(0)) return false;
        return MerkleProof.verify(proof, root, leaf);
    }
}
