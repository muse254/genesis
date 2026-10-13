// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {Registry} from "../src/Registry.sol";

/// @notice Rehearse on Base Sepolia, then deploy once to Base mainnet and pin
///         the address. The mainnet registry is permanent: never redeploy it.
/// @dev `REGISTRY_TEST_MODE=true` deploys a wipeable registry (default false).
///      Refused here on mainnet before broadcast, so the error names the
///      variable instead of surfacing as a constructor revert.
contract Deploy is Script {
    uint256 internal constant ETHEREUM_MAINNET = 1;
    uint256 internal constant BASE_MAINNET = 8453;

    function run() external returns (Registry registry) {
        bool testMode = vm.envOr("REGISTRY_TEST_MODE", false);
        if (testMode) {
            require(
                block.chainid != BASE_MAINNET && block.chainid != ETHEREUM_MAINNET,
                "Deploy: unset REGISTRY_TEST_MODE for a mainnet deploy"
            );
        }

        vm.startBroadcast();
        registry = new Registry(testMode);
        vm.stopBroadcast();

        console.log("Registry deployed at", address(registry));
        console.log("chain id", block.chainid);
        console.log("testMode", registry.testMode());
    }
}
