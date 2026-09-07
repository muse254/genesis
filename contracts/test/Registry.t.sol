// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Registry} from "../src/Registry.sol";

contract RegistryTest is Test {
    Registry internal registry;

    function setUp() public {
        registry = new Registry();
    }

    function test_registerBody() public {}
    function test_registerBody_revertsOnDuplicate() public {}
    function test_revokeBody_onlyOwner() public {}
    function test_registerImage_emitsCommit() public {}
    function test_registerImage_revertsForRevokedBody() public {}
    function test_parentImageHash_buildsEditGraph() public {}
    /// @dev Must agree bit-for-bit with ingest/merkle.py.
    function test_verifyInclusion() public {}
}
