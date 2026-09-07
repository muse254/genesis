// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {Registry} from "../src/Registry.sol";

/// @notice Day 4: deploy to Sepolia, then PIN THE ADDRESS. ENSv2's contracts
///         are not final; chasing changes mid-window is how the demo breaks.
contract Deploy is Script {
    function run() external returns (Registry registry) {
        vm.startBroadcast();
        registry = new Registry();
        vm.stopBroadcast();
    }
}
