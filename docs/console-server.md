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

## Demo step 4 works, and it is `derived` rather than `registered`

Superseded by the subgraph deployment on 8 September 2026. `/verify` now has
four verdicts, and the separation matters more than the count:

| Probe | verdict | PCE | link |
| --- | --- | --- | --- |
| IMG_0230, the registered original | `registered` | 1,895 | exact pixel hash |
| The same, stripped to 1800px q95 | **`derived`** | **37.3** | perceptual hash, Hamming 0, chain-confirmed |
| A forgery that was never a photograph | `fingerprint-only` | **82,190** | none |
| Canon 5D Mark III | `no-record` | 38.4 | none |

Read rows two and three together. **A real degraded photograph scoring 37
gets a stronger verdict than a forgery scoring 82,190**, because one descends
from a registration and the other does not. That is the whole argument, and it
is now a table rather than a paragraph.

`derived` is deliberately not `registered`. The link is a perceptual hash,
which is collidable and cheap to forge, so it says the image *descends from* a
registered photograph rather than *is* one — and note the PCE on that row is
below threshold, which is the honest state of a copy that has been through
Flickr. The pixels do not support it; the pHash and the chain do, and the
response says which.

Two rules the tests enforce. A perceptual hit the chain cannot confirm grants
nothing — the index is not the authority. And a dead subgraph degrades to the
pixel answer rather than inventing a link.

## Superseded: why step 4 was limited to `fingerprint-only`

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

## Answering the design handoff

`design_handoff_genesis_console/` is high-fidelity and mostly implementable as
drawn. These are the places where the backend had to decide something
different, and why.

**Pre-flight thresholds are ours.** The handoff asks for deployer balance
>= 0.05 ETH and >= 2 enrolled bodies. Both would read NO-GO today for no real
reason: the demo sends four transactions, which on Sepolia costs far under
0.01 ETH, and the deployer holds 0.0484; and a second body needs a second
physical camera (`docs/e2e-checklist.md` §1). A gate that fails on a condition
that is actually fine teaches a presenter to override it, which is worse than
having no gate. `MIN_BALANCE_WEI` is 0.01 ETH and `MIN_BODIES` is 1.

**`/state` now returns rows, not raw values.** Each check carries
`check / measured / expected / go` — matching the handoff's columns exactly —
plus a `remedy` string when it fails. The frontend renders; it never
evaluates. A gate that says no without saying what to do gets ignored.

**The ENS row is a real check, not a string.** It walks `ETHRegistry` for a
subregistry rather than asking whether the name resolves, because owning a
name does not give it one — `raffy.eth` and `hello.eth` are both owned and
both return zero. Asking "does it resolve" would go green too early. This is
currently the only NO-GO row, correctly.

**The AUCs in 2d are wrong and `calibrated` is not a signal.** The board
lists 0.900 / 0.842 / 0.810 / 0.777 / 0.725 across five rows including
`calibrated`, which is a boolean saying whether a band exists. The measured
values, per path, are:

| Signal | RAW | Delivered |
| --- | --- | --- |
| `bodyConsistency` | 0.900 | 0.725 |
| `effectiveStrength` | 0.800 | 0.767 |
| `resamplingPeak` | — | 0.517 |
| `pooledTriangle` | not reproduced | not reproduced |

Two consequences for the drawing. The axis needs a **path** label, because the
same signal reads differently on RAW and delivered. And `resamplingPeak` at
0.517 is chance — its band spans nearly the whole axis, which is the honest
picture and worth drawing rather than tidying.

**The log rail needs a rule for non-positive PCE.** `log10(pce)/5` is
undefined at or below zero, and scores of -30.9 and -44.0 are ordinary here —
a different camera frequently lands negative. Rule: clamp the marker to the
left edge and label it `< 1`. The rail starts at 1 because that is where the
log scale can start, not because scores do.

**Explorer host.** `chain.explorer_url` uses Blockscout; the handoff says
Etherscan. The registry is verified on both, so either is honest. The backend
returns a full `explorerUrl` and the frontend should render whatever comes
back rather than building the link itself.

**Not yet available: sub-step progress for screen 04's working state.**
`/verify` and `/degrade` are synchronous and return once. The determinate
ledger the handoff draws — `scale search · window 4/9` — needs the scorer to
emit progress, which `/enrol` already does over SSE and these do not. Until
then the working state has elapsed time and a typical figure, and no window
count.

## Running it

Three processes, in this order. The console API signs, so it binds to
localhost and nothing else.

```bash
uvicorn scoring.app:app --port 8000                        # the scorer
uvicorn console.app:app --host 127.0.0.1 --port 8100       # the console API
cd console-ui && cp .env.example .env && npm install && npm run dev
```

Then <http://127.0.0.1:5173> and press **P** for pre-flight. Screens are
reachable by number key; **P** re-runs the gate.

`console-ui/` is Vite and TypeScript with no framework, matching `verify/` so
the repo has one idiom rather than two. It is drawn at 1280x720 -- the
recording resolution -- and scaled to fit the window, so the measurements in
`design_handoff_genesis_console/` stay literal instead of approximate.

The dev server pins `host: 127.0.0.1`. Vite's default binds `localhost`,
which resolves to `::1` only on this machine, so `http://127.0.0.1:5173`
refused the connection while `localhost` worked. Both spellings are in the
API's CORS allowlist and in the handoff's chrome, and a presenter typing the
wrong one loses a minute on camera to a blank page.

## Chrome does not depend on the internet

The handoff lists the brand marks as public `raw.githubusercontent.com` URLs.
That is right for a design board and wrong for the console: while this was
being wired, that host returned **503**, which would have put a broken-image
icon in the header of a recording.

The marks are served from `console-ui/public/` instead. `width` and `height`
are set explicitly — the art is 1540x416, so 20px tall is 74px wide, and
`width:auto` would reflow the step tabs as the PNG decodes.

The ink lockup is 93% dark pixels on a transparent background, so it is
correct on paper `#fbfbf9` and would vanish on a dark one. A dark-mode
console has to swap in `-white`, not invert the ink file.

## Three bugs the first live registration found

Screen 02 registered nothing. It called `/verify` like every other screen, so
a genuine frame came back `fingerprint-only` — correctly, since nothing was on
chain — and read as a failure. Verifying asks what the chain already says;
registering is what puts it there, and only one screen may write.

Then `/register-image` returned 500 twice:

- **`METADATA_HMAC_KEY` is a `str` and `hmac.new` wants `bytes`.** It raised
  inside the request rather than at startup, so the endpoint looked like the
  chain refusing a photograph. Hex is decoded as hex, anything else as UTF-8.
- **The perceptual hash is eight bytes and the ABI field is `bytes32`.**
  `cast` rejected it with a bare `parser error` naming no field. Every hash is
  left-padded to a full word now, and a test fails if one is not.

And `cast --interactive` does not work without a terminal — piping to it fails
with "Device not configured", which is how the ENS registries got deployed
with `--private-key` instead. The console does the same, so the key is on the
argv for the length of one transaction and visible in `ps`. Acceptable for a
localhost demo driver on the operator's own machine; not acceptable for
anything hosted, which this is not and must not become. `cast`'s stderr is
redacted before it reaches an error response so a failed transaction cannot
spill the key into a log or a recording.

Verified end to end after the fixes: IMG_0217 registers in block 11666892,
verifies as `registered` at PCE 49,310, and its 1800px q95 copy comes back
`derived` at **407.9** — which is `docs/gates.md`'s 408 for that frame.

## The console fills the window; the artboard does not

First cut locked `#stage` to 1280x720 and scaled it, on the reasoning that
the handoff's measurements should stay literal. Wrong trade: anything that is
not 16:9 letterboxes, and on an ordinary browser window most of the page's
height went unused. The stage now fills the viewport, the two-column screens
flex into it, and the photo slot is `aspect-ratio: 3 / 2` capped at `46vh`
rather than a hard 430x287. Size the window to 16:9 when recording and it is
the board again, exactly.

`main.screen` carries `min-height: 0` with it. Without that a flex child
refuses to shrink below its content, so a long verdict pushed the footer off
screen instead of scrolling.

## Choosing an enrolment folder

`GET /browse` lists folders on the machine running the console, each with a
count of the RAW frames inside, rooted at `$HOME` and overridable with
`GENESIS_BROWSE_ROOT` for an archive on an external drive.

It browses the *server's* filesystem rather than the browser's, because a
browser cannot hand a server a path: `webkitdirectory` gives file contents,
so a folder chooser in the page would mean uploading forty 24-megapixel RAWs
— well over a gigabyte — to a service reading the same disk. The console runs
on the photographer's machine and can simply look.

The frame count is the reason the listing exists rather than a plain path
field. Gate A wants 40–50 frames, and a picker that does not say which folders
have them makes the operator guess at the one number that decides whether K is
any good.

Rooted rather than open: the console is localhost-only and already holds a
signing key, but a filesystem listing is still a disclosure surface, and a
test fails if it can be walked above its root.

## RAW does not render in a browser

`/preview` develops any accepted file to a small JPEG. It exists because the
register screen showed no image at all: an `<img>` pointing at a CR3 renders
nothing and reports nothing, so the slot just stayed empty. A browser cannot
decode RAW, and the only decoder on the machine is the scorer's.

Display only, and the docstring says so: `/verify` and `/register-image` read
the uploaded file and never this. A preview that could influence a verdict
would be a second decode path to disagree with the first.

## Build order

1. `/health`, `/state` — nothing else is debuggable without them.
2. `/verify` — the three-verdict shape, and the only thing the public page
   also needs.
3. `/register-image`, `/register-body` — the signing paths, together.
4. `/degrade` — cheap once `/verify` works.
5. `/enrol` — last. It is the slowest, the least likely to be run live, and
   the CLI already does it.
