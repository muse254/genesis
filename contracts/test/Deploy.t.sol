// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Deploy} from "../script/Deploy.s.sol";
import {Registry} from "../src/Registry.sol";

/// One function on purpose: `vm.setEnv` is process-wide and forge runs tests
/// in parallel, so split cases would race on REGISTRY_TEST_MODE.
contract DeployTest is Test {
    function test_deploy_script_guards_test_mode_by_chain() public {
        Deploy deploy = new Deploy();

        // Base mainnet with test mode: refused by the script.
        vm.chainId(8453);
        vm.setEnv("REGISTRY_TEST_MODE", "true");
        vm.expectRevert("Deploy: unset REGISTRY_TEST_MODE for a mainnet deploy");
        deploy.run();

        // Ethereum mainnet likewise.
        vm.chainId(1);
        vm.expectRevert("Deploy: unset REGISTRY_TEST_MODE for a mainnet deploy");
        deploy.run();

        // Base Sepolia: test mode allowed.
        vm.chainId(84532);
        Registry rehearsal = deploy.run();
        assertEq(rehearsal.testMode(), true);

        vm.chainId(8453);
        vm.setEnv("REGISTRY_TEST_MODE", "false");
        Registry production = deploy.run();
        assertEq(production.testMode(), false);
        assertEq(production.admin(), address(0));
        assertEq(production.epoch(), 0);

        // Unlisted chain: the constructor fails closed. Last, because a revert
        // inside the broadcast leaves broadcast state open afterwards.
        vm.chainId(42161);
        vm.setEnv("REGISTRY_TEST_MODE", "true");
        vm.expectRevert("test mode is testnet-only");
        deploy.run();
    }
}
