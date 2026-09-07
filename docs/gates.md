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

**The null is mostly not a second body.** The 41 R10 frames come from one
camera, so the standing negative control is K rotated 180 degrees: alignment
destroyed, statistics preserved.

One real other-body probe now exists. A Canon EOS 5D Mark III linear DNG,
centre-cropped to a common size and scored against the R10 fingerprint,
returned **26.6** — inside the null band, against 1,895 to 56,255 for true
matches. That is a different *model*, though, and models differ in sensor,
readout and raw pipeline. **The case that decides the threshold is two bodies
of the same model**, which share every model-level artefact and differ only in
the fingerprint. Until that runs, 50 stays provisional.

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

### Verification pass rate, and what raised it

The table above scores one CFA plane at a time. Scoring every non-enrolment
frame -- all 25, clipped ones included, not just the 10 clean held-out --
gives the rate that matters:

| Statistic | Weakest of 25 | Pass at PCE 50 |
| --- | --- | --- |
| Best single plane | 143 | 25/25 |
| Summed correlation surfaces, 4 planes | 257 | 25/25 |
| Summed surfaces + saturated pixels excluded | **672** | 25/25 |

Nothing fails on this body. What changed is the margin: the weakest frame
went from 2.9x the threshold to 13x, and `prnu.score()` now does both by
default.

**Summing the four CFA planes.** Each plane is an independent measurement of
the same body, and a true match peaks at the same shift in all four, so the
surfaces add coherently while their noise does not. Worth roughly 2x on the
weakest frame.

**Excluding saturated pixels.** A clipped photosite is clamped, not
modulated: it carries no fingerprint but still contributes to the energy the
peak is measured against. Dropping those pixels from both sides is worth
another 3-9x on frames with 10-18% clipping -- IMG_0236 goes from 2,659 to
24,186.

The clipping cut of the enrolment set is a separate thing and still applies:
a saturated pixel is useless for *building* K. It is not a filter on what can
be verified. Frames up to 17.7% clipped score in the tens of thousands.

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

### Partial result — full resolution, no resize

A camera JPEG of 7 September 2026: `game.jpg`, Canon EOS R10, 6000x4000,
processed through ACDSee Photo Studio, same body as the enrolled fingerprint.
Sampling each output pixel from the channel its photosite actually measured
puts a delivered image back on the enrolment lattice.

| | |
| --- | --- |
| Probe | delivered JPEG, native sensor resolution, no resize |
| PCE against its own body | **1,147.8** |
| Same image against K rotated 180 degrees | -27.2 |
| Same image against a shuffled K | -27.5 |
| Verdict | the fingerprint survives demosaic, tone curve and JPEG encoding |

So the pipeline that destroys metadata does not destroy the fingerprint. What
this does **not** yet show is Gate B: a web JPEG has also been *resized*, and
a resized image no longer has a pixel-to-photosite correspondence at all.
That is what `crop_and_scale_search` is for, and it is not written.

Linearising the JPEG through an inverse sRGB curve made it worse (309 against
1,148 gamma-encoded), which is worth knowing before anyone assumes the tone
curve must be undone. The camera's curve is not sRGB, so inverting the wrong
curve costs more than leaving it alone.

### Result — the web round trip

| | |
| --- | --- |
| Date run | |
| Export settings | |
| PCE after web round trip | |
| Best scale | |
| Verdict | |
