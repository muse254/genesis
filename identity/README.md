# identity -- ENSv2 on Sepolia

The hierarchical registry *is* the identity model:

```
osoro.eth                    the photographer
r10-4471.cam.osoro.eth       one enrolled body
```

Resolver records hold the fingerprint commitment, the signing key and
revocation status. Per-record permissions let one body be delegated without
handing over the namespace.

ENS's bar is explicit: ENSv2 features must be **central to the product, not
cosmetic**, and the demo **cannot rely on hardcoded values** -- a subname is
registered and records resolved live.

Two cautions:

1. The contracts are not final. **Pin the addresses on day 4 and leave them.**
2. ENS Labs scrapped Namechain L2 and moved ENSv2 to mainnet, so treat any
   ENS material older than a few months as suspect.

`ens-cli` is fine for scripts; its README flags it as not production-ready,
so keep it off the demo path.

## Pinned addresses -- fill in on day 4, then freeze

| Contract | Sepolia address | Pinned |
| --- | --- | --- |
| Permissioned Registry | `0x…` | |
| Permissioned Resolver | `0x…` | |
| ETH Registrar | `0x…` | |
| Universal Resolver V2 | `0x…` | |
