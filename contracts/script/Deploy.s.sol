// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Registry} from "../src/Registry.sol";

/// @notice Rehearse on Base Sepolia, then deploy once to Base mainnet and PIN
///         THE ADDRESS. The mainnet registry is permanent: its registration
///         dates are the claim, so it is never redeployed to fix a typo.
/// @dev `REGISTRY_TEST_MODE=true` deploys a registry that `resetAll` can wipe,
///      so the demo can be rehearsed without a fresh deployment each time. It
///      defaults to **false** and the constructor refuses it off a testnet, so
///      a mainnet deploy is the safe one to get wrong.
contract Deploy is Script {
    function run() external returns (Registry registry) {
        bool testMode = vm.envOr("REGISTRY_TEST_MODE", false);
        vm.startBroadcast();
        registry = new Registry(testMode);
        vm.stopBroadcast();
    }
}
