# Genesis

**Origin registry for photographers — prove an image came out of a specific camera body.**

ETHOnline 2026 · 4–16 September

---

> *Let there be light* — and a record of the sensor it fell on.

The photo world is trying to verify a negative — proving an image *wasn't*
AI-generated. It can't be done. We verify the positive instead: every image
sensor carries a permanent, per-body physical fingerprint (PRNU) that imprints
on every exposure and cannot exist in an image that never passed through it.
We register it and certify **origin, not truth**.

The record model follows the Birthmark Standard (arXiv 2602.04933,
`github.com/Birthmark-Standard/Birthmark`), which authenticates camera origin
from pixel data alone — NUC maps on professional bodies, PRNU on phones — and
explicitly scopes out the staged-photograph problem.

Its verification path references manufacturer key tables — a manufacturer
validates the NUC hash — and its own roadmap concedes that adoption needs
manufacturer firmware integration. We enrol from the photographer's own files
instead: 40+ RAW frames from an archive that already exists, with no
manufacturer and no platform involved. The camera's own data is the whole
input — K is estimated by maximum likelihood from the frames the body itself
produced, so nothing outside them is needed to enrol a body or to score an
image against it.

We certify: exposed on camera body X · camera body registered to identity Y · first
registered at time T · these derivatives descend from that original.

`BUILD.md` is the source of truth. Where it and this README disagree,
`BUILD.md` wins.

## The maths behind K

A sensor's photosites differ slightly in how much charge each returns for the
same light. That gain error is fixed at manufacture, unique to the die, and
it multiplies the signal rather than adding to it:

```
I = I⁰ + I⁰·K + Θ
```

`I` is what the sensor read, `I⁰` the light that fell on it, `K` the
per-pixel gain field — the fingerprint — and `Θ` everything else, shot noise
and dark current. Because K multiplies I⁰, a bright pixel carries more
evidence of K than a dark one, and a saturated pixel carries none.

Enrolment recovers K from frames alone. Each frame is denoised and the
denoised copy subtracted from the original, leaving a residual
`W = I − denoise(I)` that holds the fingerprint plus noise. Maximum likelihood over `d` frames then gives:

```
K̂ = Σ(Wₖ · Iₖ) / Σ(Iₖ²)
```

Each frame is weighted by its own intensity, which is exactly the weighting
the multiplicative model calls for. The model is linear, so this estimator is
minimum-variance unbiased and its variance falls as 1/d — more frames, a
sharper K, with no ceiling other than patience.

Verification asks whether a candidate image's residual contains that body's
fingerprint, scaled by the candidate's own intensity. The statistic is Peak
to Correlation Energy: correlate `W` against `I·K̂`, take the peak over all
shifts, divide its square by the energy in every other shift. PCE is used
rather than plain correlation because it is alignment-independent and its
null distribution is stable enough to set one threshold across bodies.

Two properties are what make this work retroactively. K is a property of the
silicon, not of the file, so stripping metadata removes nothing. And K is
never published — only a hash of it goes on chain, because a published
fingerprint is a forgery kit.

The full derivation is Fridrich, *Digital Image Forensics Using Sensor Noise*,
IEEE Signal Processing Magazine 26(2), 2009: sensor model eq. (3), estimator
eq. (6), variance bound eq. (7), PCE eq. (14), denoiser in Appendix A.

## Where this stands on real cameras

One body has been tested: a Canon EOS R10, 41 CR3 frames, 16 enrolled and 10
held out. Every held-out frame scored between 1,212 and 18,929 against a null
of 24 to 38 — a margin of 32x at worst. It worked on ordinary photographs
rather than the defocused flats the enrolment procedure asks for.

What that does not yet establish: **the false-positive rate.** With one body
available the negative control is K rotated 180°, which destroys alignment
while preserving the statistics. That bounds the error the way a second
camera would, but it is not the same evidence. The case that matters most is
two bodies *of the same model*, which share every model-level artefact and
differ only in the fingerprint itself. Until that runs, the PCE threshold of
50 is provisional and no claim about how often a wrong body matches can be
made from this repo.

Method, numbers and the rest of the findings are in `docs/gates.md`.

## Layout

```
fingerprint/   Python — PRNU extraction, PCE scoring
ingest/        Python — record construction, hashing, Merkle session batching
contracts/     Solidity + Foundry — ERC-7053 commit() and the body registry
identity/      ENSv2 on Sepolia — body subname registration
subgraph/      The Graph — index registrations, resolve image → record
scoring/       FastAPI — HTTP wrapper around the scorer
verify/        web page — upload, score, look up, verdict
mcp/           Subgraph MCP server
docs/          claims discipline, gate results, demo script
data/          local scratch: enrolment frames, references (gitignored)
```

Python does the imaging because the CR3 decoders and the wavelet denoising
the PRNU pipeline depends on live there. FastAPI puts the scorer behind HTTP
so the verify page and the contracts side never import the imaging code.
Solidity and Foundry hold the registry, The Graph makes an image lookup
resolve to a record, and the chain is Ethereum Sepolia because that is where
ENSv2 is deployed.

## How it works

```mermaid
flowchart TB
  subgraph Enrol["Flow A · Enrol — once per camera body"]
    direction TB
    subgraph EnrolLocal["CLI on the photographer's machine · fingerprint/"]
      A1["40+ RAW frames from the archive"] --> A2["CFA plane split"]
      A2 --> A3["wavelet Wiener residual"]
      A3 --> A4["ML estimator ΣWI/ΣI² → K"]
    end
    A4 --> A5[("local disk · data/<br/>K itself is never published")]
    A4 --> A6["CLI · ingest/<br/>commitment hash of K"]
    subgraph EnrolChain["on chain · Sepolia"]
      A7["contract · Registry.registerBody<br/>bodyId · fingerprintCommitment · ensNode"]
      A8["contract · ENSv2<br/>subname r10-4471.cam.osoro.eth"]
    end
    A6 --> A7
    A7 <--> A8
  end

  subgraph Register["Flow B · Register — per image"]
    direction TB
    subgraph RegLocal["CLI on the photographer's machine · ingest/ + fingerprint/"]
      B1["RAW"] --> B2["SHA-256 of pixel data<br/>+ perceptual hash"]
      B1 --> B3["residual → PCE against K"]
      B2 --> B4["Birthmark-shaped ImageRecord<br/>+ PRNU attestation"]
      B3 --> B4
    end
    subgraph RegChain["on chain · Sepolia"]
      B5["contract · Registry.registerImage"]
      B6["contract · Registry.commitSession<br/>one Merkle root per shoot, not one write per frame"]
      B7["contract · ERC-7053 commit()"]
    end
    B4 --> B5
    B4 --> B6
    B5 --> B7
  end

  subgraph Verify["Flow C · Verify — anyone, any image, anywhere"]
    direction TB
    C1["web page · verify/ (browser)<br/>image upload"] --> C2{"exact pixel hash hit?"}
    C2 -->|yes| C3["record — untouched file"]
    C2 -->|no| C4["index · subgraph/ on The Graph<br/>pHash lookup → candidate records"]
    C4 --> C5["HTTP service · scoring/ (FastAPI)<br/>PRNU re-score — the browser cannot do this"]
    C5 --> C6["web page · verify/<br/>verdict + confidence"]
  end

  A5 -.->|K stays local| B3
  A7 -.->|events indexed| C4
  B5 -.->|events indexed| C2
```

The lower branch of Verify is the one that matters. An exact pixel hash dies
the moment a platform re-encodes or resizes, and everything that has been out
in the world has been re-encoded.

## Getting started

Python 3.11+ (`numpy` 2.x removed `ndarray.ptp()` — use `np.ptp()`).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 fingerprint/fingerprint.py demo      # must PASS before anything else

uvicorn scoring.app:app --reload
```

Contracts (`forge init` was not run here — the tree is already laid out):

```bash
curl -L https://foundry.paradigm.xyz | bash && foundryup
cd contracts
forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts
forge build && forge test
```

## The gates

Nothing downstream matters until both have run. See `docs/gates.md`.

- **Gate A** — does K exist on this body? 40–50 defocused flats, CR3 not
  C-RAW, Long Exposure NR off.
- **Gate B** — does K survive a web JPEG round trip?

## Status

The enrolment math is written and passes on a synthetic sensor: CFA split,
wavelet Wiener residual, ML estimator, zero-mean plus DFT Wiener
post-processing, PCE, and the pinned commitment hash. `enroll`, `test` and
`pair` run against RAW files; `demo` runs without a camera.

Everything else in this tree is still a stub — ingest, contracts, subgraph,
scoring, verify. The Gate B crop-and-scale search is not written.

Gate A has run on a real body and passed; Gate B has not run. See **Where
this stands on real cameras** above and `docs/gates.md`.

## Further Work?

We never say "authentic", "AI-free", "verified real", or that the absence of a
record means anything. A camera pointed at a high-quality screen produces a
genuine exposure of a fabricated scene and defeats every provenance system on
the market, including in-camera cryptographic signing. See `docs/claims.md`.
