// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Registry -- ERC-7053 commit log plus a camera-body registry.
/// @notice ERC-7053 defines the index and explicitly declines to validate
///         the content behind the CIDs. PRNU is that validation; this
///         contract records the verdict, it does not compute it.
/// @dev Conform to Numbers Protocol's ERC-7053 interface rather than
///      reimplementing the event shape and getting it subtly wrong.
contract Registry {
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

    event Commit(address indexed recorder, string assetCid, string commitData);
    event BodyRegistered(bytes32 indexed bodyId, address indexed owner, bytes32 ensNode);
    event BodyRevoked(bytes32 indexed bodyId);
    event ImageRegistered(bytes32 indexed imageHash, bytes32 indexed bodyId, uint32 pceScore);
    event SessionCommitted(bytes32 indexed sessionId, bytes32 merkleRoot, uint32 frameCount);

    // --- ERC-7053 ---------------------------------------------------------

    function commit(string calldata assetCid, string calldata commitData) external {
        revert("not implemented");
    }

    // --- body registry ----------------------------------------------------

    function registerBody(bytes32 bodyId, bytes32 fingerprintCommitment, bytes32 ensNode) external {
        revert("not implemented");
    }

    /// @notice Revocation matters: a sold or stolen body must stop
    ///         certifying for its former owner.
    function revokeBody(bytes32 bodyId) external {
        revert("not implemented");
    }

    // --- image registry ---------------------------------------------------

    function registerImage(ImageRecord calldata record) external {
        revert("not implemented");
    }

    function commitSession(bytes32 sessionId, bytes32 merkleRoot, uint32 frameCount) external {
        revert("not implemented");
    }

    function verifyInclusion(bytes32 sessionId, bytes32 leaf, bytes32[] calldata proof)
        external
        view
        returns (bool)
    {
        revert("not implemented");
    }
}
