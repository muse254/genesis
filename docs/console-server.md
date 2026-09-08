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

`consistency` carries the advisory signals from
`fingerprint/consistency.py`, in the order they run:

| Field | Check | What it is worth |
| --- | --- | --- |
| `bodyConsistency` | Does the frame carry the body's structure beyond K? | Catches a synthetic carrier 23x clear; fails on a delivered-JPEG forgery at 1.6x |
| `effectiveStrength` | How hard was the fingerprint planted? | Separates every forgery we built — until an attacker sweeps alpha and lands in the band. Path-dependent: calibrate RAW and delivered separately |
| `resamplingPeak` | Was this interpolated to reach the lattice? | Catches an attacker who resized; blind to one who generates at native size |
| `pooledTriangle` | `[B18]`, when reference frames are available | **Not reproduced.** Returned for research, and no consumer should read it yet |

All four are advisory and **must not** be thresholded. None catches a
delivered-JPEG forgery, which is the path the product serves
(`docs/security.md`). They are shown as evidence beside the score, never as a
verdict, and the API returning them does not make them one. A frontend that
turns any of these into a pass/fail has misread the contract — which is why
`verdict` is a separate field decided only by the chain read.

`effectiveStrength` and `pooledTriangle` need a calibration the server does
not have at first run: the genuine band per processing path, and reference
vectors from the enrolment set. Until `/enrol` stores them, both are returned
as `null` rather than as a number nobody can interpret.

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

## Built so far

`console/chain.py` and `console/app.py`, with `console/validate_console.py`.
`/health`, `/state` and `/verify` are live. Chain reads go over raw JSON-RPC —
the registry's getters return fixed-size static structs, so a selector plus one
word and some slicing beats a `web3` dependency and leaves nothing to guess
about what went over the wire.

Verified against the live Sepolia deployment, 8 September 2026:

| Probe | verdict | PCE | registration |
| --- | --- | --- | --- |
| A forgery that was never a photograph | `fingerprint-only` | 82,190 | null |
| IMG_0230, the registered original | `registered` | 1,895 | block time 1788857551, owner `0x91c968d9…` |
| Canon 5D Mark III | `no-record` | 38.4 | null |

The first row is the point. Eighty-two thousand and no record still does not
read as a pass.

## Demo step 4 is limited to `fingerprint-only`, and that is not a bug

Measured through the running server: `game.jpg` degraded to 1800px comes back
at **PCE 126.5 at q95** and **33.3 at q80**, reproducing the Gate B result on
the live path. The q95 copy matches — and its verdict is `fingerprint-only`,
not `registered`.

That is correct and it is a real limit. A degraded copy has a different pixel
hash, so `images(imageHash)` misses, and the only thing that could link it to
the original's registration is a **perceptual-hash index** — which is the
subgraph, still blocked on a Graph Studio key (`docs/e2e-checklist.md` §7).

So today the money shot proves the fingerprint survives re-encoding, and
cannot yet show the registration it descends from. Two ways forward, and the
second is honest:

1. Deploy the subgraph. The designed path.
2. Have the console keep a local index of the registrations *it* made, look up
   a near pHash, then **do a real chain read of that image hash** before
   reporting `registered`, with a field saying the link was perceptual rather
   than exact. The registration stays chain-verified; only the lookup is
   local. That is what the subgraph would serve anyway.

What must not happen is reporting `registered` from a pHash match alone. The
verdict has to keep meaning a chain read succeeded.

## Build order

1. `/health`, `/state` — nothing else is debuggable without them.
2. `/verify` — the three-verdict shape, and the only thing the public page
   also needs.
3. `/register-image`, `/register-body` — the signing paths, together.
4. `/degrade` — cheap once `/verify` works.
5. `/enrol` — last. It is the slowest, the least likely to be run live, and
   the CLI already does it.
