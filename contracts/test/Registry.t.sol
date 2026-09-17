// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Registry} from "../src/Registry.sol";

contract RegistryTest is Test {
    Registry internal registry;

    address internal photographer = address(0xA11CE);
    address internal stranger = address(0xB0B);

    bytes32 internal constant COMMITMENT = keccak256("K for body one");
    bytes32 internal constant BODY_COMMITMENT = keccak256("HMAC(Canon, EOS R10, serial, owner)");

    bytes32 internal bodyId;

    event Commit(address indexed recorder, string assetCid, string commitData);
    event BodyRegistered(bytes32 indexed bodyId, address indexed owner, bytes32 bodyCommitment);
    event BodyRevoked(bytes32 indexed bodyId);
    event ImageRegistered(bytes32 indexed imageHash, bytes32 indexed bodyId, uint32 pceScore);

    function setUp() public {
        // chainid 31337 is anvil, which the constructor accepts for test mode.
        registry = new Registry(true);
        bodyId = registry.deriveBodyId(COMMITMENT);
    }

    function _register() internal {
        vm.prank(photographer);
        registry.registerBody(bodyId, COMMITMENT, BODY_COMMITMENT);
    }

    function _image(bytes32 imageHash, bytes32 parent)
        internal
        view
        returns (Registry.ImageRecord memory)
    {
        return Registry.ImageRecord({
            imageHash: imageHash,
            perceptualHash: bytes32(uint256(0xe829e9b0556d25cb)),
            bodyId: bodyId,
            modificationLevel: 0,
            parentImageHash: parent,
            metadataHmac: keccak256("when and where"),
            pceScore: 1895,
            registeredAt: uint64(block.timestamp)
        });
    }

    function test_registerBody() public {
        vm.expectEmit(true, true, false, true);
        emit BodyRegistered(bodyId, photographer, BODY_COMMITMENT);
        _register();

        (bytes32 commitment, address owner, bytes32 camera, bool revoked) = registry.bodies(bodyId);
        assertEq(commitment, COMMITMENT);
        assertEq(owner, photographer);
        assertEq(camera, BODY_COMMITMENT);
        assertFalse(revoked);
    }

    /// @dev The camera commitment is optional: a body without one is still a
    ///      body, it just cannot later be tied to a camera anyone can produce.
    function test_registerBody_withoutBodyCommitment() public {
        vm.prank(photographer);
        registry.registerBody(bodyId, COMMITMENT, bytes32(0));

        (bytes32 commitment, address owner, bytes32 camera,) = registry.bodies(bodyId);
        assertEq(commitment, COMMITMENT);
        assertEq(owner, photographer);
        assertEq(camera, bytes32(0));
    }

    function test_registerBody_revertsOnDuplicate() public {
        _register();
        vm.prank(stranger);
        vm.expectRevert("body already registered");
        registry.registerBody(bodyId, COMMITMENT, BODY_COMMITMENT);
    }

    /// @dev The id is not a free choice: it follows from the commitment, so
    ///      nobody can register a camera under an id of their own picking.
    function test_registerBody_revertsWhenIdDoesNotDerive() public {
        vm.prank(photographer);
        vm.expectRevert("bodyId must derive from commitment");
        registry.registerBody(keccak256("an id I liked"), COMMITMENT, BODY_COMMITMENT);
    }

    function test_revokeBody_onlyOwner() public {
        _register();

        vm.prank(stranger);
        vm.expectRevert("not the body owner");
        registry.revokeBody(bodyId);

        vm.expectEmit(true, false, false, false);
        emit BodyRevoked(bodyId);
        vm.prank(photographer);
        registry.revokeBody(bodyId);

        (,,, bool revoked) = registry.bodies(bodyId);
        assertTrue(revoked);
    }

    /// @dev Revocation stops future claims; it does not unwrite past ones.
    ///      Erasing history would make every earlier record unfalsifiable.
    function test_revokeBody_leavesEarlierRecordsStanding() public {
        _register();
        vm.startPrank(photographer);
        registry.registerImage(_image(keccak256("before"), bytes32(0)));
        registry.revokeBody(bodyId);
        vm.stopPrank();

        (bytes32 imageHash,,,,,,,) = registry.images(keccak256("before"));
        assertEq(imageHash, keccak256("before"));
    }

    function test_registerImage_emitsCommit() public {
        _register();
        bytes32 imageHash = keccak256("a photograph");

        vm.expectEmit(true, true, false, true);
        emit ImageRegistered(imageHash, bodyId, 1895);
        vm.prank(photographer);
        registry.registerImage(_image(imageHash, bytes32(0)));

        // An ERC-7053 entry too, under the local URI ingest/record.py uses,
        // so an indexer that knows only the standard still sees this.
        string memory cid = string(abi.encodePacked("genesis:", _hex(imageHash)));
        assertEq(registry.commitCountFor(cid), 1);
        assertEq(registry.commitCount(), 1);
    }

    function test_registerImage_revertsForRevokedBody() public {
        _register();
        vm.startPrank(photographer);
        registry.revokeBody(bodyId);
        vm.expectRevert("body revoked");
        registry.registerImage(_image(keccak256("after revocation"), bytes32(0)));
        vm.stopPrank();
    }

    /// @dev Anyone being able to attribute an image to someone else's camera
    ///      would defeat the only claim this contract makes.
    function test_registerImage_revertsForNonOwner() public {
        _register();
        vm.prank(stranger);
        vm.expectRevert("not the body owner");
        registry.registerImage(_image(keccak256("not mine to claim"), bytes32(0)));
    }

    function test_parentImageHash_buildsEditGraph() public {
        _register();
        bytes32 original = keccak256("the original");
        bytes32 edited = keccak256("the crop");

        vm.startPrank(photographer);
        registry.registerImage(_image(original, bytes32(0)));

        Registry.ImageRecord memory child = _image(edited, original);
        child.modificationLevel = 1;
        registry.registerImage(child);

        // A derivative of something never registered has no graph to join.
        vm.expectRevert("unknown parent image");
        registry.registerImage(_image(keccak256("orphan"), keccak256("never seen")));
        vm.stopPrank();

        (,,,, bytes32 parent,,,) = registry.images(edited);
        assertEq(parent, original);
    }

    /// @dev Must agree bit-for-bit with ingest/merkle.py.
    ///      Root and proofs below were generated by that module over leaves
    ///      0x01..0x05 repeated to 32 bytes. If either side changes its
    ///      hashing, its pair ordering, or what it does with an odd node,
    ///      this test fails rather than the failure surfacing as proofs
    ///      that mysteriously do not verify on chain.
    function test_verifyInclusion() public {
        bytes32 sessionId = keccak256("shoot of 7 September");
        bytes32 root = hex"55d458ff264cc10cb4ef71d27a18db86f587999b2355cfa5eb5fccf8c973bced";
        registry.commitSession(sessionId, root, 5);

        bytes32[] memory proof = new bytes32[](3);
        proof[0] = hex"0202020202020202020202020202020202020202020202020202020202020202";
        proof[1] = hex"15812c763262dabc33411aff2c78af2cfcf55d57327737349ab4a7321a3dca59";
        proof[2] = hex"0505050505050505050505050505050505050505050505050505050505050505";
        bytes32 leaf = hex"0101010101010101010101010101010101010101010101010101010101010101";
        assertTrue(registry.verifyInclusion(sessionId, leaf, proof));

        // The promoted odd leaf, which is where the two implementations
        // would diverge first if either changed the rule.
        bytes32[] memory oddProof = new bytes32[](1);
        oddProof[0] = hex"0b242b9a6559f2d9f8563485a0697b746ec58ce879e0e5ac94d4c8a250723121";
        bytes32 oddLeaf = hex"0505050505050505050505050505050505050505050505050505050505050505";
        assertTrue(registry.verifyInclusion(sessionId, oddLeaf, oddProof));

        // A frame that was not in the session must not prove.
        assertFalse(registry.verifyInclusion(sessionId, keccak256("another shoot"), proof));

        // Nor may a proof against a session nobody committed.
        assertFalse(registry.verifyInclusion(keccak256("no such session"), leaf, proof));
    }

    function test_commitSession_revertsOnDuplicate() public {
        bytes32 sessionId = keccak256("one import");
        registry.commitSession(sessionId, keccak256("root"), 2000);
        vm.expectRevert("session already committed");
        registry.commitSession(sessionId, keccak256("another root"), 2000);
    }

    function test_commit_isOpenAndIndexed() public {
        vm.expectEmit(true, false, false, true);
        emit Commit(address(this), "ipfs://bafy", "{}");
        registry.commit("ipfs://bafy", "{}");

        registry.commit("ipfs://bafy", "{}");
        assertEq(registry.commitCountFor("ipfs://bafy"), 2);
    }

    function _hex(bytes32 value) internal pure returns (bytes memory) {
        bytes16 alphabet = "0123456789abcdef";
        bytes memory out = new bytes(64);
        for (uint256 i = 0; i < 32; i++) {
            out[i * 2] = alphabet[uint8(value[i]) >> 4];
            out[i * 2 + 1] = alphabet[uint8(value[i]) & 0x0f];
        }
        return out;
    }
}

/// @notice The testnet-only reset, and the promises it must not break.
contract RegistryResetTest is Test {
    address internal photographer = address(0xA11CE);
    address internal stranger = address(0xB0B);

    bytes32 internal constant COMMITMENT = keccak256("K for body one");
    bytes32 internal constant BODY_COMMITMENT = keccak256("HMAC(Canon, EOS R10, serial, owner)");

    event RegistryReset(uint64 indexed previousEpoch, uint64 indexed newEpoch, address indexed by);

    function _registered() internal returns (Registry registry, bytes32 bodyId) {
        registry = new Registry(true);
        bodyId = registry.deriveBodyId(COMMITMENT);
        vm.prank(photographer);
        registry.registerBody(bodyId, COMMITMENT, BODY_COMMITMENT);
    }

    /// The reason it exists: `bodyId` derives from SHA-256(K), so the same
    /// camera always reaches the same id and a second rehearsal would be
    /// refused forever.
    function test_resetAll_frees_a_body_id_for_re_registration() public {
        (Registry registry, bytes32 bodyId) = _registered();

        vm.prank(photographer);
        vm.expectRevert("body already registered");
        registry.registerBody(bodyId, COMMITMENT, BODY_COMMITMENT);

        registry.resetAll();

        vm.prank(photographer);
        registry.registerBody(bodyId, COMMITMENT, BODY_COMMITMENT);
        (, address owner,,) = registry.bodies(bodyId);
        assertEq(owner, photographer);
    }

    /// A wiped record must read exactly like one that was never written --
    /// the zeroed struct every consumer already treats as "no record".
    function test_a_reset_record_reads_as_absent() public {
        (Registry registry, bytes32 bodyId) = _registered();

        registry.resetAll();

        (bytes32 commitment, address owner, bytes32 camera, bool revoked) = registry.bodies(bodyId);
        assertEq(commitment, bytes32(0));
        assertEq(owner, address(0));
        assertEq(camera, bytes32(0));
        assertEq(revoked, false);
    }

    function test_resetAll_clears_images_and_sessions() public {
        (Registry registry, bytes32 bodyId) = _registered();

        Registry.ImageRecord memory record = Registry.ImageRecord({
            imageHash: keccak256("pixels"),
            perceptualHash: bytes32(uint256(0x1234)),
            bodyId: bodyId,
            modificationLevel: 0,
            parentImageHash: bytes32(0),
            metadataHmac: keccak256("meta"),
            pceScore: 1895,
            registeredAt: uint64(block.timestamp)
        });
        vm.prank(photographer);
        registry.registerImage(record);
        registry.commitSession(keccak256("session"), keccak256("root"), 2);

        registry.resetAll();

        (bytes32 imageHash,,,,,,,) = registry.images(keccak256("pixels"));
        assertEq(imageHash, bytes32(0));
        assertEq(registry.sessionRoots(keccak256("session")), bytes32(0));
        assertEq(registry.commitCountFor("genesis:whatever"), 0);
    }

    /// The commits happened. Reusing an index across epochs would make the
    /// event log ambiguous, so the counter is deliberately not rewound.
    function test_commitCount_is_not_rewound() public {
        (Registry registry,) = _registered();
        registry.commit("genesis:one", "");
        uint256 before = registry.commitCount();

        registry.resetAll();
        registry.commit("genesis:two", "");

        assertEq(registry.commitCount(), before + 1);
    }

    function test_only_the_admin_may_reset() public {
        (Registry registry,) = _registered();
        vm.prank(stranger);
        vm.expectRevert("not the admin");
        registry.resetAll();
    }

    function test_a_production_registry_cannot_be_reset() public {
        Registry registry = new Registry(false);
        assertEq(registry.testMode(), false);
        assertEq(registry.admin(), address(0));
        vm.expectRevert("not a test registry");
        registry.resetAll();
    }

    /// The guard that matters. If this ever passes on a mainnet chainid, the
    /// registry can withdraw its own registration dates and `docs/claims.md`
    /// claim 1 stops being true.
    function test_test_mode_is_refused_off_a_testnet() public {
        vm.chainId(1); // Ethereum mainnet
        vm.expectRevert("test mode is testnet-only");
        new Registry(true);

        vm.chainId(8453); // Base mainnet, the production target
        vm.expectRevert("test mode is testnet-only");
        new Registry(true);

        vm.chainId(42161); // and any other chain nobody listed
        vm.expectRevert("test mode is testnet-only");
        new Registry(true);
    }

    /// A production registry deploys anywhere, including mainnet.
    function test_production_mode_deploys_on_mainnet() public {
        vm.chainId(1);
        Registry registry = new Registry(false);
        assertEq(registry.testMode(), false);

        vm.chainId(8453);
        registry = new Registry(false);
        assertEq(registry.testMode(), false);
    }

    /// Base Sepolia is where the Base mainnet deploy is rehearsed.
    function test_test_mode_is_allowed_on_base_sepolia() public {
        vm.chainId(84532);
        Registry registry = new Registry(true);
        assertEq(registry.testMode(), true);
    }

    function test_reset_is_announced() public {
        (Registry registry,) = _registered();
        vm.expectEmit(true, true, true, true);
        emit RegistryReset(0, 1, address(this));
        registry.resetAll();
        assertEq(registry.epoch(), 1);
    }
}
