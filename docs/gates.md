# The two gates

Everything else is worthless if the fingerprint doesn't survive the R10's raw
pipeline. Both experiments are cheap. Both are decisive. **Decide by day 2,
not day 10.**

## Gate A — does K exist on this body?

Shoot 40–50 frames of a defocused white wall.

- **CR3, not C-RAW**
- **Long Exposure NR off** — it is dark-frame subtraction applied to the raw itself
- High ISO NR off
- Base ISO
- Evenly exposed, nothing clipping

```bash
python3 fingerprint/fingerprint.py demo
python3 fingerprint/fingerprint.py pair --crop 1024 ~/flats/*.CR3
python3 fingerprint/fingerprint.py enroll --out r10.npz ~/flats/*.CR3
python3 fingerprint/fingerprint.py test --fingerprint r10.npz ~/shoot/*.CR3
```

**Pass:** held-out own frames well above PCE 50, other cameras near zero, at
least an order of magnitude apart.

**Fail:** the pipeline is eroding the fingerprint. Stop. Report honestly. One
afternoon spent.

### Result

| | |
| --- | --- |
| Date run | 7 September 2026 |
| Body | Canon EOS R10, 6000x4000, RGGB, 14-bit |
| Frames | 41 available. 26 passed a clipping cut (99.5th percentile below 12000 of 16383); 16 enrolled, 10 held out |
| Frame type | **ordinary photographs, not defocused flats** |
| Enrolment | full resolution, no crop; 2000x3000 per CFA plane |
| Own-body PCE (held out) | 1,212 to 18,929 on the strongest plane. Every CFA plane of every held-out frame scored above 221 |
| Null | 24 to 38, absolute, across all 40 measurements |
| Separation | 32x at worst (IMG_0230), 600x at best (IMG_0217) |
| Verdict | **PASS**, with the caveats below |

**The null is not a second body.** All 41 frames come from one R10, so the
negative control is K rotated 180 degrees: alignment destroyed, statistics
preserved. It bounds the false-positive rate the way a different body would,
but it is not the same evidence. **Gate A is not discharged until a second
body has been tested**, and the threshold cannot be set honestly until then.

Four findings.

**The denoiser's sigma decided the margin.** Running with an unsourced
sigma0 = 5/255 put the weakest held-out frame at 91 against a null of 38 --
passing, but barely. The value the source actually specifies is 2/255
([F09] Appendix A: "we used sigma0 = 2 (for dynamic range 0...255) to be
conservative"). At that value the same frame scores 1,212. A constant taken
from memory rather than from the paper cost an order of magnitude of margin.

**Resolution costs verdicts.** The same 16 frames enrolled at `--crop 2048`
score roughly 6x lower, and IMG_0230 drops to 41 -- under the threshold and
inside the null band. Nine of ten still pass. Cropping for speed is not free:
PCE grows with the number of correlated samples, so it trades away exactly
the evidence the decision rests on.

**Exposure decides which frames are worth enrolling.** The strongest results
come from the bright frames and the weakest from the dim ones, as the CRLB
predicts -- estimator variance falls with luminance and rises with scene
texture ([F09] eq. 7). The clipping cut is the same fact from the other side:
a saturated photosite is clamped, not modulated, so it carries no PRNU.
`estimate_fingerprint` now warns when a frame is more than 1% saturated.

**Green planes carry the result.** Plane 3 scored highest on all ten frames
and red lowest, typically by 4-5x. Twice the photosites, and more signal on
these frames.

Untested: defocused flats as the enrolment set (the procedure above asks for
them; ordinary photographs worked anyway), a second body, and a second body
of the same model -- the case that matters most, since two R10s share every
model-level artefact and differ only in the fingerprint itself.

## Gate B — does it survive the web?

Export one enrolled frame at Flickr dimensions (~1800px, JPEG q80). Test it
against the fingerprint **with crop-and-scale search**.

**Pass:** the retroactive claim is live and demo step 4 works. This is the
strong product.

**Fail:** the tool works only on files the photographer still holds. Still a
real product — an archive claim tool — but step 4 comes out and the pitch
changes.

### Result

| | |
| --- | --- |
| Date run | |
| Export settings | |
| PCE after web round trip | |
| Best scale | |
| Verdict | |
