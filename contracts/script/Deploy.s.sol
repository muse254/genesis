// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Registry} from "../src/Registry.sol";

/// @notice Day 4: deploy to Sepolia, then PIN THE ADDRESS. ENSv2's contracts
///         are not final; chasing changes mid-window is how the demo breaks.
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
