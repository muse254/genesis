# The demo console server

A localhost orchestration API behind the five steps in `docs/demo-script.md`.
The frontend brief is separate; this is what it calls.

Two services already exist and neither changes shape. `scoring/app.py` does
the imaging and decides nothing about the chain. The verify page does chain
reads with viem. This server is the third thing: it drives *state changes* —
enrolment and registration — which today only `contracts/script/local-e2e.sh`
and the CLI can do, and which a presenter cannot run from a browser.

## What forced a new service

`/lookup` returns pixel evidence: `imageHash`, `perceptualHash`, `threshold`,
`verdict`, and per-body PCE. After `acf3f87` the verify page has three
outcomes, and the strong one — *Registered by the body's owner* — needs
`owner`, `registeredAt` and the transaction that carries it. None of those are
pixel facts and the scorer must not learn to fetch them; that would make the
scorer the thing that decides what is on chain, which the whole design
avoids.

## Endpoints

Base `http://127.0.0.1:8100`. Demo-only, localhost-bound.

### `POST /enrol` — step 1

```
{ "folder": "...", "name": "r10" }  ->  { "jobId": "..." }
```

Long-running. Progress over `GET /enrol/{jobId}/events` (SSE): frames read,
frames accepted after the clipping cut, then `commitment`, `bodyId`, and the
plane shapes. The `.npz` is written under `GENESIS_REFERENCES` and **its path
is never returned to the browser**. Nothing that could carry K leaves the
process. See `docs/security.md`.

### `POST /register-body` — step 2a

```
{ "name": "r10", "ensLabel": "r10-4471" }
->  { "bodyId", "txHash", "blockNumber", "ensName" }
```

Calls `registerBody(bodyId, commitment, ensNode)` with `DEPLOYER_PRIVATE_KEY`,
then `identity/scripts/register-body.ts` for the subname and its records.
Registering a body is a race that a leaked K wins, so this is deliberately the
first chain call and not a later one.

### `POST /register-image` — step 2b

```
multipart: file, body=<bodyId>
->  { "imageHash", "perceptualHash", "pce", "txHash", "blockNumber",
      "registeredAt", "owner" }
```

Scores first through `scoring/app.py`, refuses below `PCE_THRESHOLD`, builds
the record with `ingest/record.py`, calls `registerImage` and then `commit()`
for the ERC-7053 log. `msg.sender` is the owner, and that owner check is the
system's only real boundary — so this endpoint signs, and no other one does.

### `POST /degrade` — step 4

```
multipart: file; { "longestEdge": 1800, "quality": 95, "stripMetadata": true }
->  the degraded image
```

The money shot, done live rather than pre-baked. Quality is a required
parameter with no default, because `docs/gates.md` measured 1800px q95 at 408
and q80 at 37 — the same size and the same pixels, and the claim dies between
them. A default here would hide the one number the demo depends on.

### `POST /verify` — steps 3 and 5

```
multipart: file  ->  {
  "verdict": "registered" | "fingerprint-only" | "no-record",
  "pce", "threshold", "method", "orientation",
  "body": { "bodyId", "ensName", "owner", "commitment" } | null,
  "registration": { "txHash", "blockNumber", "registeredAt",
                    "modificationLevel", "explorerUrl" } | null,
  "consistency": { "bodyConsistency": float, "resamplingPeak": float } | null
}
```

The one endpoint the frontend needs for a verdict, and the shape carries the
distinction the whole system now rests on:

- `registered` **requires** a chain read that returned a record, and
  `registration` is non-null. Only this verdict may be presented as a claim.
- `fingerprint-only` means the pixels matched and nothing is registered. Not a
  pass. `registration` is null and the frontend must render it differently.
- `no-record` is neutral. Absence means nothing.

`consistency` is advisory and **must not** be thresholded — neither check
catches a delivered-JPEG forgery (`docs/security.md`). It is shown as evidence
beside the score, never as a verdict, and the API returning it does not make
it one.

### `GET /health`, `GET /state`

`state` returns what the presenter needs to see before recording: chain id and
block, registry address, whether the ENS parent resolves, how many bodies the
scorer holds, and whether the deployer has gas. Every one of these can fail on
camera; the console shows them before step 1 rather than during step 2.

## Constraints

**It signs, so it is the sensitive component.** `DEPLOYER_PRIVATE_KEY` lives
here and nowhere else. Bind to `127.0.0.1` only. No `--host 0.0.0.0`, no
tunnel, no deployment. It is a demo driver and it is not a product surface.

**K never leaves the process.** No endpoint returns a reference path, a plane,
or anything K can be reconstructed from. The commitment is the only derived
value that goes out.

**No endpoint stamps a fingerprint into an image.** `POST /degrade` resizes
and re-encodes; it does not inject. An endpoint that accepted a K and an image
and returned a stamped image would be forgery-as-a-service regardless of
intent — see `docs/security.md`.

**Chain reads stay honest.** The server may read the chain to answer
`/verify`, but it reports what it read and never synthesises a registration
from a score. If the RPC is down, `/verify` returns an error rather than
degrading to `fingerprint-only`, because silently downgrading a verdict is how
a demo tells a comfortable lie.

## Chain target

Sepolia, against the live deployment: `Registry` at
`0xDf71e9350B4cA587eb3Bd01F2e7D710F3Fc25CF3`, block 11659977, verified on
Blockscout and Etherscan. `docs/e2e-checklist.md` §6 is the state of it.

ENSv2 names on Sepolia reset on redeployment, so `/state` resolves the parent
live and the console shows it before recording. `identity/addresses.md` has
the sequence and the `--dry-run` rehearsal.

## Build order

1. `/health`, `/state` — nothing else is debuggable without them.
2. `/verify` — the three-verdict shape, and the only thing the public page
   also needs.
3. `/register-image`, `/register-body` — the signing paths, together.
4. `/degrade` — cheap once `/verify` works.
5. `/enrol` — last. It is the slowest, the least likely to be run live, and
   the CLI already does it.
