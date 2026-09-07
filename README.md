<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="logos/genesis-lockup-horizontal-white.png">
    <img src="logos/genesis-lockup-horizontal-ink.png" alt="Genesis" width="440">
  </picture>
</p>

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

One body has been tested: a Canon EOS R10, 41 CR3 frames, 16 enrolled. Every
one of the 25 frames that did not build the fingerprint scores as a match —
672 at worst, 56,255 at best, against a null of 29 to 43. That includes
frames up to 17.7% blown out.

It worked on frames that break four of the five enrolment conditions: ordinary
photographs rather than defocused flats, **C-RAW rather than lossless CR3**,
High ISO NR on, and mostly not base ISO. Surviving Canon's lossy raw
compression matters more than the rest, because C-RAW is what a great many
photographers actually shoot.

**A second R10 does not match.** The case that matters is two bodies of the
same model, sharing every model-level artefact and differing only in the
fingerprint. A different R10 (serial `022031004996` against our
`473034005088`, from `raw.pixls.us`) scores **39.1** against our fingerprint,
and −44.0 through the orientation search — the null band, where our own body
scores 629 to 56,255.

That is one negative sample, not a false-positive rate. It rules out the
approach being broken; it does not say how often a wrong body matches, which
needs dozens of bodies. The threshold sits at 100 — about twice the worst null
observed, well under the weakest true match — and is a floor with a margin
rather than a calibrated operating point.

Method, numbers and the rest of the findings are in `docs/gates.md`.

## Validate the mathematics yourself

**The test frames are not in this repository.** Publishing 16 enrolment
frames publishes everything needed to reconstruct K for that body, and the
[fingerprint-copy attack](https://dlnext.acm.org/doi/10.1109/TIFS.2010.2099220)
needs nothing more than that to forge images this project would attribute to
that camera. So the numbers in `docs/gates.md` are reported rather than
handed over, and here is what you can check for yourself instead.

**No files needed.** The synthetic sensor has a known ground-truth
fingerprint, so this proves the estimator recovers what it is given:

```bash
python3 fingerprint/fingerprint.py demo
pytest fingerprint ingest        # 26 tests
```

**With your own camera.** 40+ RAW frames from an archive you already have:

```bash
python3 fingerprint/fingerprint.py enroll --out data/references/mine.npz ~/photos/*.CR3
python3 fingerprint/fingerprint.py test --fingerprint data/references/mine.npz ~/other/*.CR3
```

**The different-body test, from public data.** [raw.pixls.us](https://raw.pixls.us/)
is a public archive of camera raw samples. Take any body of the same model as
your own and score it against your fingerprint; it should land in the null
band, in the tens, against thousands for your own frames. That is the
experiment that decides whether any of this means anything, and it needs no
files from us.

Check `exiftool -SerialNumber` before trusting a file as a different body.
Two candidates for that role here turned out to be the same camera.

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

## The offline run

Everything below the imaging core, without a testnet:

```bash
anvil &
contracts/script/local-e2e.sh data/references/r10.npz frame.CR3
```

Scores the frame, deploys the registry, registers the body and the
photograph, commits a session root, reads it back and proves inclusion. A
frame from another body is refused before it reaches the chain.

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

| | Component | State |
| --- | --- | --- |
| ██████████ | `fingerprint/` — enrolment, scoring, commitment | done, 7 tests |
| ██████████ | Gate A — does K exist on this body | **passed**, one body |
| ███████░░░ | Gate B — does K survive the web | **conditional pass** |
| ██████████ | `fingerprint/stress.py` — degradation ladder | done |
| ██████████ | `ingest/` — hashing, record, Merkle | done, 17 tests |
| ██████████ | `contracts/` — ERC-7053 registry | done, 12 tests |
| ░░░░░░░░░░ | `identity/` — ENSv2 subnames | not started |
| █████████░ | `subgraph/` — image → record | indexes a local chain; needs the testnet deploy |
| ██████████ | `scoring/` — FastAPI wrapper | done, 5 tests |
| █████████░ | `verify/` — the page | both branches verified against anvil |
| █████████░ | `mcp/` — Subgraph MCP server | answers from a real index |

Nine of eleven done. The imaging core works on real files: `enroll`, `test`
and `pair` run against RAW and delivered JPEGs, `demo` runs without a camera.
Everything downstream of it is scaffolding.

`docs/e2e-checklist.md` is the ordered list of what unblocks what.

## Further Work?

We never say "authentic", "AI-free", "verified real", or that the absence of a
record means anything. A camera pointed at a high-quality screen produces a
genuine exposure of a fabricated scene and defeats every provenance system on
the market, including in-camera cryptographic signing. See `docs/claims.md`.
