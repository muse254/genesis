# ETHOnline submission copy

Rewritten 13 September 2026. Every claim here is either built and running or
says plainly that it is not. Measurements live in `docs/gates.md`,
`docs/adversarial.md` and `docs/cre.md`; the closed list of what this system
will and will not say is `docs/claims.md`.

---

## What it does

Every image sensor carries a permanent, per-body physical fingerprint (PRNU)
that imprints on every exposure and cannot exist in an image that never passed
through it. Genesis enrols that fingerprint from the photographer's own
archive, registers a commitment to it on chain, and lets anyone check whether
a photograph carries it — **and whether the body's owner signed for that
photograph.**

Two claims, and nothing else:

1. these pixels correlate with body X's fingerprint at PCE *p*, and
2. body X's **owner** registered this image on chain at time T.

Never the first alone. A fingerprint can be planted by anyone holding one RAW
file off the body, invisibly — measured. So the score is evidence of a link
and the owner's signature is the claim.

## How it's made

**Imaging core — Python.** `rawpy` (LibRaw) reads Canon CR3 and returns the
raw mosaic, split into its four Bayer sublattices, each corrected against its
own black level. Nothing demosaics. Per plane: a wavelet Wiener denoiser
(`PyWavelets`, `scipy`) yields the noise residual, a maximum likelihood
estimator builds K across 40+ frames, post-processing strips artefacts shared
by every body of the model, and matching is Peak to Correlation Energy over an
FFT cross-correlation.

The maths is Fridrich, *Digital Image Forensics Using Sensor Noise*, IEEE SPM
26(2), 2009, cited by equation number in `fingerprint/prnu.py`.

K is stored locally as `.npz` and never leaves the machine. Only a SHA-256
commitment over a pinned serialisation goes on chain.

**Contracts — Solidity, Foundry.** `Registry` implements ERC-7053 `commit()`
over a camera-body registry. `BodyRecord` carries the fingerprint commitment,
owner, ENS node and revocation flag; `ImageRecord` carries pixel hash,
perceptual hash, body id, modification level, parent hash and PCE score.
Sessions batch as one Merkle root per shoot, with `verifyInclusion` proving
membership. 21 Foundry tests.

Live on Sepolia at `0xd1bbDB8A6BfD25563d2e6444fA41E4C5230Ed3C9`,
source-verified on Etherscan **and** Blockscout, carrying one body and five
registered photographs.

**ENS — ENSv2 on Sepolia.** The hierarchy *is* the identity model:
`osoro.eth` is the photographer, `cam.osoro.eth` the fleet,
`r10-4471.cam.osoro.eth` one enrolled body, with the fingerprint commitment,
signing key and revocation status in its resolver records. Per-record
permissions let one body be delegated without handing over the namespace.

All three write paths are rehearsed on chain — register a subname, write the
records, revoke — and resolution goes through the **UniversalResolver**, which
is the path a third party takes rather than a direct read of the resolver we
wrote to.

A photographer needs no ENS name of their own: `registerBody`'s `ensNode` may
be zero, and bodies are subnames under the operator's parent.

**The Graph.** A subgraph indexes registrations so a perceptual hash resolves
to a body record — the registry has no index on `perceptualHash`, so the
subgraph *is* that index, and the demo's hardest step depends on it. Live as
`genesis` v0.0.4 against real Sepolia events, 9 matchstick tests.

A Subgraph MCP server exposes the same lookups to an agent, with the claims
discipline enforced in the wording it repeats — a test fails if it ever says
"exposed on" rather than "registered by the owner of".

The index is never an authority: a candidate from the subgraph is read back
off the chain before anything is claimed, so a stale or hostile index cannot
manufacture a registration.

**Chainlink CRE.** The scoring service is the trust hole by design — it holds
K and you take its word for a score. A Confidential Workflow removes it:
the algorithm is public, K arrives from the Vault DON inside an attested
enclave, and only a score crosses back.

Built and running as a real `cre workflow simulate` per call, driven from
console screen 07. The residual is extracted client-side, a **256² int8 crop**
per CFA plane is sent, the workflow compiles to WASM and executes, the score
returns. About seventeen seconds, deterministic.

Three things measured rather than assumed, because the original plan had them
wrong:

- The reference is **89 MB**, not the ~1 MB assumed, against a
  `WASMSecretsSizeLimit` of 1mb — so K is cropped and quantised.
- **Confidential HTTP is not the fallback**: 125 kb request, 500 kb response.
- A 512² crop does not fit either. 256² does, and at that size the weakest
  frame in the corpus falls into the null. That cost is documented rather
  than buried.

**`attested` is false on every path available today.** The simulator is not a
real enclave — the CLI says so itself — and the report is built rather than
DON-signed. A deployed workflow would produce the real thing and needs
private-beta enrolment. Chainlink's criteria accept **either** a CLI
simulation **or** a deployment, so this is the first, honestly labelled.
`cre/capture-evidence.sh` writes the transcript.

Confidential compute does nothing about forgery. An enclave would score a
planted fingerprint faithfully and sign it; it protects the reference from the
verifier, and the attack happens before the pixels arrive.

**Scoring, verify page and console.** FastAPI wraps the imaging core. The
verify page is a single page with no framework, `viem` for chain reads, and
four verdicts. An eight-screen presenter console drives the demo on localhost
and holds the signing key — it is never deployed.

## Measured — Canon EOS R10

41 CR3 frames. Every held-out frame scores as a match: **672 at worst, 56,255
at best**, against a null of 29 to 43, including frames up to 17.7% blown out.
It worked on frames breaking four of the five enrolment conditions, C-RAW
included.

**A second R10 does not match** — the case that decides the threshold, since
two bodies of the same model share every model-level artefact. A different R10
from `raw.pixls.us` scores **39.1**, and −44.0 through the orientation search:
the null band. Cross-model, a 5D Mark III scores 26.6.

That is one negative body, **not a false-positive rate**. It rules out a
broken approach; it does not say how often a wrong body matches, which needs
dozens. The threshold sits at 100 — about twice the worst null, well under the
weakest true match.

**In-camera JPEGs carry no readable fingerprint.** Four straight off the card
score 24.7, 18.5, −29.2 and 29.6. The same sensor developed from RAW on a
desktop scores 1,148. The camera's own noise reduction removes the very signal
PRNU lives in.

## What we do not claim

No forgery-detection rate, and none should be quoted: measured separations are
AUC 0.725 to 0.900 with every range overlapping. We never say "authentic",
"AI-free", "verified real", or that the absence of a record means anything. A
camera pointed at a high-quality screen defeats every provenance system on the
market, including in-camera cryptographic signing — we say so before anyone
else does.

**177 tests**: 133 pytest, 21 Foundry, 9 matchstick, 6 MCP, 8 identity.

## Known gaps, named

Not built, and each one stated rather than left to be discovered:

- **A false-positive rate.** One negative body is not one. It needs dozens of
  bodies and a designed study — the PCAST bar, which this does not meet.
- **Forgery detection on the delivered path.** Nothing built catches it, and
  that is the path the product serves. Four candidates queued in
  `docs/security.md`, none a control until measured.
- **A deployed confidential workflow.** Simulation today; deployment needs
  private-beta enrolment and is what would make `attested` true.
- **A second enrolled body**, so the match test runs both ways.
- **A Merkle commitment over the body fields**, so a serial can be revealed
  without also revealing geolocation.

Deliberately not planned: receipt parsing and issuer checks — a harder
forensics problem that would add a weak link. Out of scope: phone
photographs (`docs/phones.md`).
