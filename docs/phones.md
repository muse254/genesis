# Phones

The pipeline cannot ingest phone photographs, and will not be made to. The
reason is not a missing codec. Every stage of this design assumes a property
that phone output does not have, and the assumptions are load-bearing rather
than incidental — the same choices that make the R10 result strong are the
ones that make phones impossible here.

This is worth stating precisely, because "PRNU works on phones" is true in the
literature and would be a fair objection to a flat refusal. It works there with
a different estimator, on the demosaiced output grid, at materially worse
separation. That is a second system, not an extension of this one.

## HEIC does not decode

Measured 8 September 2026, in the project venv:

| Check | Result |
| --- | --- |
| Pillow | 12.3.0 |
| `features.check("heif")` | `False` |
| `pillow-heif` installed | no |
| Registered extensions | `.avif` only — no `.heic`, no `.heif` |

`load_delivered_planes` says "any image PIL can open". HEIC is not one of them.
Adding `pillow-heif` and calling `register_heif_opener()` would fix the decode
in two lines, and is not worth doing, because the four blocks below all sit
downstream of it. A decoded HEIC reaches a pipeline that has nothing to do
with it.

## The blocks, in the order they bite

**1. There is no enrolment path.** `load_raw_planes` refuses anything whose
`raw_type` is not `Flat` — it needs a CFA mosaic to split into photosite
planes. Apple ProRAW is a linear DNG, already demosaiced, so it lands on the
error written for Adobe's lossy conversion: "already demosaiced, so there are
no photosite planes to split". An iPhone cannot be enrolled from its own RAW
format. Some Android bodies (Pixel, Samsung Expert RAW) do emit true Bayer
DNGs and would clear this first block, though not the ones after it.

**2. The delivered path depends on the RAW path anyway.** Scoring a delivered
image needs a CFA pattern, and `cfa_pattern` needs rawpy and a mosaic file. No
RAW enrolment means no pattern, which means no delivered scoring either. HEIC
support on its own buys exactly nothing.

**3. There is no native resolution to sample onto.** `load_delivered_planes`
takes `rgb[i::2, j::2, channel]`: one output pixel over one photosite. Its
docstring is explicit that this is "only valid at native sensor resolution".

Surveyed by EXIF over 116 HEIC files from the owner's library on this machine,
8 September 2026:

| Camera | Output sizes seen |
| --- | --- |
| iPhone 17 Pro back 6.765mm | 5712x4284 and 4032x3024 |
| iPhone 17 Pro back 16.891mm | 5712x4284 and 4032x3024 |
| iPhone 16 back 5.96mm | 5712x4284 and 4032x3024 |
| iPhone 12 back 4.2mm | 4032x3024 |

One physical sensor, two output resolutions, chosen per shot. At most one of
them can be one-to-one with photosites and in practice neither is: the sensor
bins several photosites into each output pixel. The lattice `[i::2, j::2]`
walks is not a photosite lattice. This is not an approximation that costs some
PCE — the correspondence the whole delivered path rests on is absent.

**4. Computational photography.** Deep Fusion, HDR and night modes align and
fuse several exposures into one output frame. PRNU is a fixed multiplicative
per-photosite gain; sub-pixel alignment smears it across neighbours and fusion
averages it down. The advantage this project's enrolment has — flat fields,
40+ frames, RAW, linear data — is precisely what phone output destroys before
the file is written. Nothing downstream recovers it.

## A phone is not one sensor

Even granting all of the above, the unit of enrolment would not be "a phone".
The 116 files above come from four iPhone bodies and an iPad, and the 17 Pro
alone appears with four distinct lenses — 2.22mm, 6.765mm and 16.891mm on the
back, 2.715mm on the front — each a separate sensor with its own fingerprint,
with digital zoom crossfading between them mid-range. Enrolment would be per
`(body, lens, output resolution)`, and the demo's one-name-per-body identity
model in `identity/` does not describe that.

## What "supporting phones" would actually mean

A second estimator that works on the delivered RGB grid, keyed to a fixed
output resolution, with its own threshold measured from its own negatives.
That is how the phone PRNU literature operates, and it shares no code with the
CFA-plane path beyond the denoiser. `PCE_THRESHOLD = 100` was measured on R10
CFA planes against one other R10 body; carrying it to phone output would be
the exact overclaiming `claims.md` exists to prevent.

The material to test it is available — four phone bodies is better evidence
than the single negative the R10 threshold currently rests on. The honest
first experiment is to enrol one lens at one output resolution from ~30 frames
and score held-out frames against a second phone, which answers whether any
signal survives Apple's pipeline before anything gets built. Until someone
runs it, this document asserts only that the current code cannot, not that the
signal is gone.

## What we say

Scope phones out, in those words, rather than describing them as unfinished:

> Genesis enrols from RAW files with an intact CFA mosaic. Phone photographs
> are outside its scope: they arrive binned and multi-frame-fused, with no
> photosite lattice to sample onto, and the RAW formats phones emit are
> already demosaiced.

Two things not to say. Not "phones aren't supported yet", which promises a
roadmap that does not exist. And not "PRNU does not work on phones", which is
false and hands an easy correction to anyone who knows the field.
