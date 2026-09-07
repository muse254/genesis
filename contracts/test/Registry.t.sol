// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Registry} from "../src/Registry.sol";

contract RegistryTest is Test {
    Registry internal registry;

    address internal photographer = address(0xA11CE);
    address internal stranger = address(0xB0B);

    bytes32 internal constant COMMITMENT = keccak256("K for body one");
    bytes32 internal constant ENS_NODE = keccak256("r10-4471.cam.osoro.eth");

    bytes32 internal bodyId;

    event Commit(address indexed recorder, string assetCid, string commitData);
    event BodyRegistered(bytes32 indexed bodyId, address indexed owner, bytes32 ensNode);
    event BodyRevoked(bytes32 indexed bodyId);
    event ImageRegistered(bytes32 indexed imageHash, bytes32 indexed bodyId, uint32 pceScore);

    function setUp() public {
        registry = new Registry();
        bodyId = registry.deriveBodyId(COMMITMENT);
    }

    function _register() internal {
        vm.prank(photographer);
        registry.registerBody(bodyId, COMMITMENT, ENS_NODE);
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
        emit BodyRegistered(bodyId, photographer, ENS_NODE);
        _register();

        (bytes32 commitment, address owner, bytes32 ensNode, bool revoked) = registry.bodies(bodyId);
        assertEq(commitment, COMMITMENT);
        assertEq(owner, photographer);
        assertEq(ensNode, ENS_NODE);
        assertFalse(revoked);
    }

    function test_registerBody_revertsOnDuplicate() public {
        _register();
        vm.prank(stranger);
        vm.expectRevert("body already registered");
        registry.registerBody(bodyId, COMMITMENT, ENS_NODE);
    }

    /// @dev The id is not a free choice: it follows from the commitment, so
    ///      nobody can register a camera under an id of their own picking.
    function test_registerBody_revertsWhenIdDoesNotDerive() public {
        vm.prank(photographer);
        vm.expectRevert("bodyId must derive from commitment");
        registry.registerBody(keccak256("an id I liked"), COMMITMENT, ENS_NODE);
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
