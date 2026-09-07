# contracts

Foundry. `forge init` was not run here -- the tree is already laid out, so:

```bash
cd contracts
forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts
forge build && forge test
```

`Registry.sol` implements ERC-7053 `commit()` over a camera-body registry.
Chain is Ethereum Sepolia **because ENSv2's testnet deployment is there** --
a prize constraint, not a technical one. If ENS is cut, Base Sepolia is
cheaper and faster and The Graph indexes it too.
