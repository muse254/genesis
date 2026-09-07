# ETHOnline submission copy

Drafted 7 September 2026 — day 4 of 13. **Everything here is true as of that
date.** Lines marked `[UNBUILT]` describe work that is scaffolded but not
written; delete or rewrite them before submitting rather than letting them
stand as claims. `docs/gates.md` holds the measurements.

---

## How it's made

The core is a PRNU imaging pipeline in Python, and it is deliberately
CFA-plane-native — it never demosaics. `rawpy` (LibRaw bindings) is the only
realistic path into Canon CR3, and we take `raw_image_visible` straight off
the sensor, split it into its four Bayer sublattices, and correct each plane
against its own black level. Every existing open PRNU implementation we
found, including `polimi-ispl/prnu-python`, assumes a delivered RGB image;
working on the raw mosaic means each plane is one photosite type rather than
an interpolation of four, so the fingerprint is not smeared by a demosaic we
did not control.

From there the maths follows Fridrich's 2009 tutorial exactly, with equation
numbers in the source: a Mihcak wavelet Wiener denoiser (`PyWavelets`, db8,
4-level, local variance estimated as the minimum over 3/5/7/9 windows via
`scipy.ndimage.uniform_filter`) gives the noise residual W; the maximum
likelihood estimator `K̂ = Σ(W·I)/Σ(I²)` builds the fingerprint across 40+
frames; zero-meaning rows and columns plus a DFT Wiener filter strips the
model-level artefacts that would otherwise make two different bodies of the
same camera correlate. Matching is Peak to Correlation Energy over an FFT
cross-correlation. `numpy` throughout.

The chain layer is Solidity on Foundry: a `Registry` implementing ERC-7053's
`commit()` over a camera-body registry, with a `BodyRecord` holding only a
*hash* of the fingerprint — K itself never goes on chain, because a published
reference is a published forgery kit. Session batching commits one Merkle
root per shoot rather than one write per frame, since a working shoot is two
thousand exposures. `[UNBUILT]`

Partner technologies each carry weight rather than decorate. **ENS**: the
hierarchical registry *is* our identity model — `osoro.eth` is the
photographer, `r10-4471.cam.osoro.eth` is one enrolled body, and resolver
records hold the fingerprint commitment and revocation status, so a sold or
stolen body can be made to stop certifying without touching the namespace.
**The Graph** turns a stripped image into a record: the subgraph indexes
registrations so a perceptual-hash lookup resolves to a body, and a Subgraph
MCP server lets an agent do the same conversationally. **Chainlink CRE**'s
confidential workflows are public-code/private-data, which is the exact shape
of the problem — published algorithm, secret reference, signed score. `[UNBUILT]`

The nitty-gritty, and the parts that surprised us:

**We had no second camera, so the negative control is a rotated fingerprint.**
All 41 test frames came from one Canon R10. Correlating a held-out frame
against K rotated 180° destroys alignment while preserving K's statistics,
which bounds the false-positive rate the way a second body would — but it is
not the same evidence, and we say so rather than claiming a clean pass.

**The null is not zero, and that nearly fooled us.** PCE takes its peak over
every shift, so uncorrelated inputs still score near `2·ln(N)` — about 22 on
a 256² plane and 31 on a full-frame one. Our measured null landed at 24–38,
matching the theory almost exactly. A threshold set naively just above zero
would have called everything a match.

**A constant taken from memory cost an order of magnitude.** The denoiser's
assumed noise sigma was written as 5/255 with a comment calling it "the
literature value". It isn't — the source specifies 2/255. At the wrong value
our weakest held-out frame scored 91 against a null of 38; at the sourced
value, 1,212. The pipeline ran and the tests passed either way. It surfaced
only because we went back to cite the paper.

**Enrolment worked on ordinary photographs.** The procedure asks for 40–50
defocused flat-field frames. We only had normal pictures — landscapes,
interiors, mixed exposure — and 16 of them still produced a fingerprint that
identified all 10 held-out frames at 32× margin over the null. That matters
for the product, because it means an archive that already exists is enough.

**Resolution is not a performance knob.** Cropping to 2048px for speed drops
PCE roughly 6× and pushes the weakest frame under the decision threshold.
PCE grows with the number of correlated samples, so cropping trades away
precisely the evidence the verdict rests on.

Verification runs as a FastAPI service rather than in the browser, for the
unglamorous reason that the scorer is Python and a wavelet decomposition of a
24-megapixel raw is not something to ship to a phone. `[UNBUILT]`
