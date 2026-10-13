# Genesis — read API

One image's record, as JSON, for a partner's server. It reads the registry
contract through `core/` (`core/src/record.ts`), the same code and the same
wording as the verify page's `?hash=` mode, so the two cannot disagree.

**Base URL:** `https://genesis-api.<subdomain>.workers.dev` (set on first deploy; replace this line with it).

## `GET /v1/images/{imageHash}`

`imageHash` must match `^0x[0-9a-f]{64}$`; anything else is a `400`.

```json
{
  "registered": true,
  "imageHash": "0x6e8e0c11580e265fa7a2757fdfa083030bac668a5d156868f2b7dab900a76d54",
  "perceptualHash": "0x…909b017ca32f5d9b",
  "bodyId": "0x653c40ddc28de2ee0067810f57c9aab6c58239b00ae7e93c40d266c6fcba3b37",
  "bodyRevoked": false,
  "owner": "0xc0b60ce1d7efac453cd0d5bc1783b9b28972625a",
  "registeredAt": 1791890447,
  "pceScore": 123821,
  "threshold": 100,
  "pceScoreNote": "Strength of evidence, not a verdict and not a probability. The owner computed this score …",
  "modificationLevel": 0,
  "parentImageHash": null,
  "registry": "0xBa5Ea549c9e1414C14038dB050e0caCB4f9E48cB",
  "chainId": 8453,
  "testMode": false,
  "txHash": "0xaa1c85968b908f20a046b7022e4854a43f26a0de99f900a7b78104f9c8f18efd",
  "txUrl": "https://basescan.org/tx/0xaa1c85968b908f20a046b7022e4854a43f26a0de99f900a7b78104f9c8f18efd",
  "verifyUrl": "https://muse254.github.io/genesis/verify/?hash=0x6e8e0c11580e265fa7a2757fdfa083030bac668a5d156868f2b7dab900a76d54",
  "source": "confirmed on chain: Registry.images(imageHash) read from the contract"
}
```

An unknown hash is `200` with `"registered": false` and a `note` saying there
is no record, which is not a finding about the image.

- **Every field but `txHash` comes from the contract** (`images`, `bodies`,
  `testMode`). The subgraph only locates the transaction, and its receipt on
  chain confirms it; if either fails, `txHash` is null and the record stands.
- `owner` is the address that registered the image (`msg.sender`, which the
  contract required to own the body).
- `verifyUrl` is the verify page at this hash: link "Check this copy" to it
  rather than building the URL. It is null for any registry but Base
  mainnet's, because that is the only one the page reads. It is set for an
  unknown hash too, where the page says "No record".
- `txUrl` is the registration on Basescan; null when `txHash` is.
- `registeredAt` is the block's time, in Unix seconds. The contract sets it.
- **`pceScore` is not recomputed.** The owner computed it on their own machine
  against their own K when they registered, and the contract does not check
  it. Show `pceScoreNote` and `threshold` wherever you show the score, and
  never call it a verdict, a probability, "authentic", "verified" or proof of
  origin ([`docs/claims.md`](../docs/claims.md)).

## Changing the response

The path is the contract: `/v1/images/{hash}` keeps answering. Fields may be
added under `/v1`; removing or renaming one needs `/v2`. Either way, bump
`SHAPE` in `src/index.ts`, or the edge keeps serving the old answer for a year.

## Limits and caching

- No key. CORS is open for `GET`.
- **60 requests a minute per client IP** (`429` with `Retry-After: 60` past it).
  Cached answers are served before the limit is counted.
- A registered mainnet record with its tx is cached for a year
  (`immutable`): it cannot change. No record, a test registry, or a record
  without its tx is cached for 60 seconds.
- `502` means the chain could not be read; the record is withheld, never
  reported as missing.

## Develop and deploy

```sh
npm ci
npx wrangler types   # worker-configuration.d.ts, for tsc
npx wrangler dev     # http://localhost:8787/v1/images/0x…
npx wrangler deploy  # needs `wrangler login`
```

`wrangler.jsonc` points at Base mainnet; its `vars` switch the registry. It
imports from `../core/src`, so `npm ci` in `core/` first.
