// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Deploy} from "../script/Deploy.s.sol";
import {Registry} from "../src/Registry.sol";

/// The deploy script is the path the mainnet registry actually takes, so its
/// guard is tested through `run()` rather than only through the constructor.
///
/// Every case lives in one function on purpose: `vm.setEnv` mutates the
/// process environment, and forge runs test functions in parallel, so
/// splitting these would let them race on REGISTRY_TEST_MODE.
contract DeployTest is Test {
    function test_deploy_script_guards_test_mode_by_chain() public {
        Deploy deploy = new Deploy();

        // Base mainnet with test mode requested: refused by the script itself.
        vm.chainId(8453);
        vm.setEnv("REGISTRY_TEST_MODE", "true");
        vm.expectRevert("Deploy: unset REGISTRY_TEST_MODE for a mainnet deploy");
        deploy.run();

        // Ethereum mainnet likewise.
        vm.chainId(1);
        vm.expectRevert("Deploy: unset REGISTRY_TEST_MODE for a mainnet deploy");
        deploy.run();

        // Base Sepolia, the rehearsal chain: test mode is allowed.
        vm.chainId(84532);
        Registry rehearsal = deploy.run();
        assertEq(rehearsal.testMode(), true);

        // Base mainnet with test mode explicitly off: a production registry.
        vm.chainId(8453);
        vm.setEnv("REGISTRY_TEST_MODE", "false");
        Registry production = deploy.run();
        assertEq(production.testMode(), false);
        assertEq(production.admin(), address(0));
        assertEq(production.epoch(), 0);

        // An unlisted chain falls through to the constructor, which fails
        // closed. Last, because a revert inside the broadcast leaves the
        // cheatcode's broadcast state open for anything after it.
        vm.chainId(42161);
        vm.setEnv("REGISTRY_TEST_MODE", "true");
        vm.expectRevert("test mode is testnet-only");
        deploy.run();
    }
}
