# Claims discipline

A product decision, not a copywriting one. Overclaiming gets you publicly
dismantled by anyone who understands the analog hole.

## We certify

- this image contains the sensor fingerprint of body X, **and body X's owner
  registered it on chain**
- body X is registered to identity Y
- it was first registered at time T
- these derivatives descend from that original

## What the fingerprint alone proves

Nothing, on its own. Anyone holding K — or **one RAW file off the body** —
can plant the fingerprint in an image that was never exposed on it, at 50 to
90 dB PSNR, which no eye sees. Measured against our own reference in
`docs/adversarial.md`: a Canon 5D Mark III photograph with our K stamped on it
scores 393,382 through the shipped CLI, where the best genuine frame scores
56,255.

So a PCE score is evidence only together with an on-chain registration by the
body's owner, and only for images registered before the dispute. **A match on
an unregistered image says the pixels carry the fingerprint. It does not say
the light did.**

## We never say

- "authentic"
- "AI-free"
- "verified real"
- that the absence of a record means anything

## Scope

Phone photographs are out of scope, and `docs/phones.md` is why: binned
output, multi-frame fusion, and no photosite lattice to sample onto. Say
"outside its scope", not "not supported yet" and not "PRNU does not work on
phones" — the first promises a roadmap that does not exist, the second is
false.

## Why the test files are not published

The enrolment frames, the references and the raw corpus are not in this
repository and will not be. They were published once, for one commit, and the
history was rewritten to remove them.

The rule people expect is "do not publish K", and that much is obvious: K
identifies the body, so a published fingerprint is a forgery kit. The measured
finding is worse. **The attacker does not need K.** The estimator is public and
in this repository, and it runs on whatever frames anyone has: from a single
RAW file off the body, an attacker reaches PCE 280 against our shipped
fingerprint at 58 dB PSNR — invisible, and above a threshold of 100.

So the RAW files *are* the kit. Publishing 41 frames from this body would let
anyone manufacture images that score against a fingerprint registered live on
Sepolia, and no take-down recovers it: clones, forks and caches are immediate
and permanent.

The same reasoning is why this repository contains no forged image and no
`.npz`. Everything in `docs/adversarial.md` regenerates from a seed or from
files already on the machine that ran it.

It cuts against reproducibility and we accept the cost. What is published is
the method, the code, every measured number, and the conditions each was taken
under — enough to reproduce the work on your own camera, which is the only
camera whose fingerprint you should be handling anyway.

The consequence does not stop at this repository. It applies to every RAW a
photographer has ever delivered to a client, and those cannot be recalled. The
system therefore does not assume RAW files stay private; it assumes they do
not, and rests on the owner's registration instead.

## Say it before someone else does

A camera pointed at a high-quality screen produces a genuine exposure of a
fabricated scene, and defeats every provenance system on the market —
including in-camera cryptographic signing.

## Numbers

Never quote 2006-era PRNU accuracy. The current public benchmark is
PRNU-Bench (arXiv 2509.17581): **73.65% top-1, AUC 0.967, EER 0.097** on
closed-set identification across 126 sensors.

Our conditions differ and the difference is defensible: flat-field enrolment
frames, 40+ references rather than 5, RAW rather than JPEG, and verification
against *one known body* rather than identification among 126.

The figures in the toolkit README are synthetic upper bounds. The moment
real ones exist they replace them everywhere — here, in the README, and in
the pitch.
