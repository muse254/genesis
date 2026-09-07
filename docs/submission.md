# ETHOnline submission copy

Drafted 7 September 2026 — day 4 of 13. **True as of that date.** Lines marked
`[UNBUILT]` are scaffolded, not written; delete or rewrite them before
submitting. Measurements are in `docs/gates.md`.

---

## How it's made

**Imaging core — Python.** `rawpy` (LibRaw bindings) reads Canon CR3 and
returns the raw mosaic, which is split into its four Bayer sublattices, each
plane corrected against its own black level. Nothing in the pipeline
demosaics.

Per plane: a wavelet Wiener denoiser (`PyWavelets`, `scipy`) yields a noise
residual, a maximum likelihood estimator builds the fingerprint K across 40+
frames, post-processing strips the artefacts shared by every body of the
model, and matching is Peak to Correlation Energy over an FFT
cross-correlation. `numpy` throughout.

The maths — sensor model, estimator, PCE and the denoiser — is Fridrich,
*Digital Image Forensics Using Sensor Noise*, IEEE Signal Processing Magazine
26(2), 2009, cited by equation number in `fingerprint/prnu.py`:
http://ws2.binghamton.edu/fridrich/Research/full_paper_02.pdf

**CLI:** `enroll`, `test`, `pair`, `demo`. K is stored locally as `.npz`.
Only a SHA-256 commitment over a pinned serialisation leaves the machine.

**Contracts — Solidity, Foundry.** `Registry` implements ERC-7053 `commit()`
over a camera-body registry. `BodyRecord` carries the fingerprint commitment,
owner, ENS node and revocation flag; `ImageRecord` carries pixel hash,
perceptual hash, body id, modification level, parent hash and PCE score.
Sessions batch as one Merkle root per shoot. `[UNBUILT]`

**ENS — ENSv2 on Sepolia.** `osoro.eth` is the photographer,
`r10-4471.cam.osoro.eth` one enrolled body; resolver records hold the
fingerprint commitment and revocation status. `[UNBUILT]`

**The Graph.** A subgraph indexes registrations so a perceptual hash resolves
to a body record; a Subgraph MCP server exposes the same lookup to agents.
`[UNBUILT]`

**Chainlink CRE.** A confidential workflow scores a 512² residual crop
against the reference, which stays private. `[UNBUILT]`

**Scoring and verify.** FastAPI wraps the imaging core; the verify page is a
single page, no framework, `viem` for chain reads. `[UNBUILT]`

**Measured — Canon EOS R10.** 41 CR3 frames, 16 enrolled, 10 held out, full
resolution, 2000×3000 per plane. Held-out PCE 1,212 to 18,929 against a null
of 24 to 38 taken from K rotated 180°, there being one body available. At
`--crop 2048` the same frames score roughly 6× lower and one drops below the
threshold. The enrolment set was ordinary photographs, not defocused flats.
