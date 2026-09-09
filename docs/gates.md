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
| Enrolment conditions | **four of the five above were violated** — see the audit |
| Enrolment | full resolution, no crop; 2000x3000 per CFA plane |
| Own-body PCE (held out) | 1,212 to 18,929 on the strongest plane. Every CFA plane of every held-out frame scored above 221 |
| Null | 24 to 38, absolute, across all 40 measurements |
| Separation | 32x at worst (IMG_0230), 600x at best (IMG_0217) |
| Verdict | **PASS** — and the same-model negative below now supports it |

### The same-model negative, measured

The case that decides the threshold: **two bodies of the same model**, which
share every model-level artefact and differ only in the fingerprint itself.

A second Canon EOS R10 from `raw.pixls.us`, serial `022031004996` against our
`473034005088`, lossless RAW, ISO 1600, scored against our fingerprint:

| Probe | Body | Path | PCE |
| --- | --- | --- | --- |
| `Canon - EOS R10 - 3_2.CR3` | **different R10** | plane-wise | **39.1** |
| `Canon - EOS R10 - 3_2.CR3` | **different R10** | orientation search | **-44.0** |
| IMG_0217.CR3 | ours | orientation search | 8,694.6 |
| `a-piece-of-quiet.jpg` | ours | orientation search | 629.2 |
| Canon 5D Mark III DNG | different model | cropped, plane-wise | 26.6 |

A different body of the same model lands in the null band. That is the result
the whole approach depends on, and it now exists rather than being assumed.

**The threshold moved from 50 to 100 because of this.** 50 was set against a
null of 24 to 43 from rotated fingerprints; a real negative reaching 44 left
1.1x of headroom, which is not a margin. 100 is about twice the worst null and
well below the weakest true match, 629.

**Searching orientations raises the null.** The different-body probe reached
44 through the eight-orientation search against 39 fixed — the null is the
largest of eight tries, so it grows with the search space. Any future search
over more transforms has to re-measure it rather than inherit this number.

**One body is not a false-positive rate.** This is a single negative sample.
It rules out the approach being broken; it does not tell anyone how often a
wrong body matches. That needs dozens of bodies, and until then the number
above is a floor with a margin rather than a calibrated operating point.

**Serials, not filenames.** Two files offered as other-body samples turned out
to carry serial `473034005088` — our own camera. `exiftool -SerialNumber` is
the first check on any negative, before it is scored.

### The enrolment conditions were not met

Audited with `exiftool` across all 41 frames on 7 September 2026:

| Condition asked for | What the frames actually are |
| --- | --- |
| 40-50 defocused flats | ordinary photographs, 16 used |
| **CR3, not C-RAW** | **all 41 are `Quality: CRAW`** — Canon's lossy compressed raw |
| Long Exposure NR off | Off on all 41 — the one condition met |
| High ISO NR off | `Standard` on all 41 |
| Base ISO | ISO 100 on 3, 250 on 23, 2000-3200 on 15 |
| Evenly exposed, nothing clipping | exposures from 1/320s to 30s, 15 frames clipping |

It passed anyway, at 32x margin over the null. Two readings, and both matter.

For the product this is the better news in this document: **the fingerprint
survives Canon's lossy raw compression**, at high ISO, on handheld pictures of
real scenes. C-RAW is what a great many photographers actually shoot, and an
enrolment procedure that demanded a wall and a tripod would exclude most
archives that already exist.

For the evidence, it means the procedure as written has still never been
tested. Flats at base ISO in lossless CR3 should do better than this, not
worse, so the numbers here are a floor rather than a ceiling — but that is an
inference, not a measurement.

One caveat on High ISO NR: on Canon bodies this setting governs in-camera
JPEG rendering rather than the raw, so `Standard` does not necessarily mean
these raws were denoised. Long Exposure NR is the one that does write into
the raw, and it was off throughout.

Four further findings.

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

### A border defeats the search, not the fingerprint

Found 9 September 2026 on a real pair of files, and worth its own note because
the failure looks like the fingerprint being gone when it is entirely intact.

| File | Size | PCE | Path |
| --- | --- | --- | --- |
| `ancestral-call.jpg` | 6000x4000 | **90,845.8** | aligned |
| `ancestral-call_border.jpg` | 6400x4400 | **37.9** | scale search, "mirrored, 90 deg" |
| the same, border cropped off | 6000x4000 | **86,096.7** | aligned |

A 200px white margin, nothing else. The plain file is at native sensor
resolution so it takes the aligned path, one output pixel per photosite. The
bordered one is 6400x4400, which moves the aspect ratio from 1.5000 to 1.4545
— and `crop_and_scale_search` searches a *uniform* scale, so no single factor
maps that canvas back onto the lattice. It reported `mirrored, 90 deg`, which
is the largest of eight orientations on noise: the signature of finding
nothing rather than of a weak match.

`stress.strip_uniform_border` now runs before the search, and the same file
scores **31,676** — `fingerprint-only` rather than `no-record`. It is
deliberately conservative: a side counts as border only if it is almost
perfectly flat, at most a quarter of each side is removed, and **all four
sides must agree**, so a blown sky or a studio backdrop cannot be cropped into
to make a score look better. The scorer reports `borderStripped` when it
fires, because a score that exists only after cropping is a different claim
from one measured on the file as supplied.

Bordered exports are ordinary — print margins, gallery frames, social
templates — and every one of them read `no-record` before this.

## Gate B — does it survive the web?

Export one enrolled frame at Flickr dimensions (~1800px, JPEG q80). Test it
against the fingerprint **with crop-and-scale search**.

**Pass:** the retroactive claim is live and demo step 4 works. This is the
strong product.

**Fail:** the tool works only on files the photographer still holds. Still a
real product — an archive claim tool — but step 4 comes out and the pitch
changes.

### A delivered JPEG at native resolution

Before the ladder, the simplest case. `game.jpg` of 7 September 2026 — Canon
EOS R10, 6000x4000, out of ACDSee Photo Studio, same body as the fingerprint,
never resized. Sampling each output pixel from the channel its photosite
actually measured puts it back on the enrolment lattice, no scale search
needed.

| | |
| --- | --- |
| PCE against its own body | **1,147.8** |
| Against K rotated 180 degrees | -27.2 |
| Against a shuffled K | -27.5 |

Linearising it through an inverse sRGB curve made it worse — 309 against 1,148
gamma-encoded. The camera's curve is not sRGB, so inverting the wrong one
costs more than leaving it alone.

### Result

Run 7 September 2026 against the 16-frame R10 fingerprint. Each rung develops
the RAW, resizes with Lanczos, encodes JPEG at the stated quality, then scores
the green channel with `crop_and_scale_search`.

| Longest edge | Quality | File | IMG_0217 | IMG_0216 | IMG_0230 |
| --- | --- | --- | --- | --- | --- |
| 6000 (native) | 95 | 3.8 MB | 6,149 | 4,849 | 282 |
| 6000 (native) | 80 | 898 KB | 3,517 | 2,924 | 112 |
| 4000 | 80 | 279 KB | 900 | 629 | -36 |
| 3000 | 80 | 125 KB | 198 | 187 | -35 |
| 2400 | 80 | 71 KB | 53 | -40 | 33 |
| **1800** | **95** | 188 KB | **408** | **316** | 37 |
| **1800** | **80** | 38 KB | 37 | 35 | -33 |
| 1200 | 80 | 17 KB | -35 | -38 | 33 |

**Verdict: conditional pass.** A published photograph still resolves to its
body at Flickr dimensions — 1800px — provided the JPEG is encoded at quality
95. At the same size and quality 80 every frame drops to the null. So demo
step 4 works, and the sentence it supports has to name the condition.

**Quality costs more than size.** 1800px q95 scores 408; 1800px q80 scores 37.
Same pixels, same resize, and the fingerprint is gone. Downscaling removes the
fingerprint in proportion to the pixels it removes; quantisation can take all
of it at once, because at q80 the high-frequency coefficients the fingerprint
lives in are exactly what gets rounded away. Anyone reporting a number from
this ladder has to state the quality or the number means nothing.

**Frames differ by two orders of magnitude.** IMG_0217 survives to 1800px;
IMG_0230 does not survive its own development. It was already the weakest
frame on the raw path — 1,895 where IMG_0217 scored 49,309 — and development
costs roughly another factor of ten, so it starts below where the others end.
A per-image verdict is not a per-camera verdict.

**Orientation is part of the search, and that changed the null.** IMG_0230 is
a portrait frame: `Orientation: Rotate 270 CW`. A fingerprint lives in sensor
space, which is always landscape, so the developed image is turned ninety
degrees against it and PCE is not rotation-invariant. Before the search tried
orientations, IMG_0230 scored at the null on every rung including the
undegraded one. It now matches at 282 and reports the turn.

The search covers all eight orientations, four rotations by two reflections,
because the metadata that would say which is exactly what a published image
has lost. **This retires the rotated-K null for this path**: once the search
tries every orientation it simply undoes the rotation and matches. The
negative control for anything orientation-aware has to be a different body.

**One anomaly, unexplained.** IMG_0216 scores 187 at 3000px, -40 at 2400px,
and 316 at 1800px q95. Non-monotonic, so something about the 2400px resampling
ratio is defeating the scale band rather than the fingerprint being absent.
The band is +/-6% around nominal; widening it is the first thing to try.

### Result — the web round trip

| | |
| --- | --- |
| Date run | |
| Export settings | |
| PCE after web round trip | |
| Best scale | |
| Verdict | |
