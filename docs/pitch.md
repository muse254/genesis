# Genesis: the pitch

For Colosseum, Crypto World's Fair, 12 October 2026. `docs/claims.md`
governs every sentence. The Nikon, paywall and free-quota claims were
confirmed by the founder on 12 October.

## The insight

The photo world is trying to prove a negative: that an image was not
generated. Genesis records a positive instead. A photographer registers a
photograph on a public record, under the key that owns their camera body. Later, anyone can check whether a copy that has been stripped,
resized and re-posted traces back to that registration.

It works on the camera the photographer already owns, and on the archive they
already have.

## How it works

Every image sensor carries a fixed, per-body noise pattern (PRNU) that is
imprinted on every exposure. Genesis estimates it from about 40 RAW files
<!-- README.md --> on the photographer's own machine. The fingerprint never
leaves that machine. Only a commitment to it goes on chain.

Genesis claims two things and nothing else. First, the body's owner
registered this image at time T. Second, these pixels correlate with that
body's fingerprint at a measured score. The score is evidence of a link, not
proof of origin. It is never reported alone. A missing record means nothing
about an image.

On a real Canon R10, every held-out frame matched: 672 at worst and 56,255 at
best, against a threshold of 100 and a null of 29 to 43 <!-- docs/submission.md -->.
A second R10 scored 39.1 <!-- docs/submission.md -->. That is one negative
body, not a false-positive rate, and we say so.

## We attacked our own system

Results are published in `docs/adversarial.md`.

The fingerprint alone can be forged. Anyone with one RAW file off the camera
can plant its fingerprint in an image that camera never took. Corrected
figure: score 280.5 at 58.4 dB PSNR, which no eye sees, against a threshold of
100 <!-- docs/adversarial.md -->. A synthetic test pattern that never passed
through any lens scored 291,608 <!-- docs/adversarial.md -->. A photo from a
different camera model, resized and planted, scored 393,382, against 56,255
for our best genuine frame <!-- docs/adversarial.md -->.

Three of our numbers did not reproduce when re-measured on 8 September. We
corrected them in place <!-- docs/adversarial.md -->. In both attacks they
affected, the attack was cheaper than first written. We also implemented a published defence, [B18]'s
pooled statistic, and it did not separate forgeries from genuine frames in
our tests: forgery ranked higher in 5 of 8 runs at every ratio
<!-- docs/adversarial.md -->. We report that as "not reproduced", not as
"the paper is wrong".

What survived every attack is the contract: only the key that owns a body can
register an image to it. So the owner's registration carries the claim, and
the fingerprint is supporting evidence. The attacks are also why we never
publish RAW files or fingerprints, ours included.

## Why camera signing does not close the gap

The industry's answer is signing inside the camera (C2PA). It is right for
new captures, and it has limits.

Nikon shipped free C2PA on the Z6 III in August 2025. It suspended the
service that September after Multiple Exposure mode produced validly signed
composites, and revoked every certificate it had issued
<!-- COLOSSEUM.md; docs/adversarial.md records the suspension -->. Signing by
the manufacturer can be broken, and it can be revoked by someone who is not
the photographer. No manufacturer can revoke a sensor fingerprint. It can be planted, though
(docs/adversarial.md), which is why the owner's registration carries the
claim and the fingerprint never stands alone.

Who gets signing today: Sony charges to sign and again to verify. Canon ships
it on two flagships. No body under about $2,000 has it <!-- COLOSSEUM.md -->.
And none of it covers anything already shot.

So: PRNU for the archive that already exists, C2PA for what is shot from now
on. Genesis is not a replacement. Neither system defeats a camera pointed at
a good screen, and we say that first.

Prior art we name before a judge does: the Birthmark Standard and OpenOrigins
<!-- docs/colosseum-checklist.md -->.

## Who else is working on this

Named here before a judge has to ask.

- **The Birthmark record model** (arXiv 2602.04933) is the closest design.
  It authenticates camera origin from sensor data and verifies on pixels
  alone, and it scopes out staged photographs, as we do. It depends on
  camera makers shipping firmware and on a consortium chain, and no maker
  has signed on yet <!-- BUILD.md, "The Birthmark Standard" -->. Genesis
  adopts its record format field for field, and needs only the
  photographer's own files.
- **OpenOrigins**, which raised a $4.5M seed led by Galaxy Interactive,
  installs capture software on cameras and iPhones and validates media
  archives for media companies such as ITN, on its own blockchain
  <!-- fortune.com, 31 Oct 2024; pulse2.com -->. It serves newsrooms. Genesis
  serves individual photographers, on cameras they already own.
- **Certana** checks online images with machine learning and
  zero-knowledge proofs on Solana, including resized and recompressed
  copies <!-- Chrome Web Store listing -->. It asks whether an image matches
  a known asset. Genesis also ties the asset to one camera sensor and to
  the owner who registered it.
- **Earlier Colosseum projects** in the same space include decentracam and
  here.

What none of them does is all four: PRNU combined with programmable
contracts, enrolment from RAW files, retroactive registration of an
existing archive without any manufacturer, and individual photographers as
the customer <!-- BUILD.md, "What is genuinely unoccupied" -->.

## Market

Photographers lose money when work is used without a licence or credited to
someone else. What they need most is a dated record that predates the
dispute. Photographers pay for a dispute, not for insurance. Businesses pay
to not have disputes.

Who buys, in order <!-- docs/go-to-market.md -->:

1. **Photo competitions**, which already disqualify undisclosed composites.
2. **Licensing libraries, stock and print marketplaces**, where an earlier
   registration becomes recovered fees.
3. **Agencies that buy from freelancers**, for attribution of contributed work.

AI agents reach it through the MCP server, which lets an agent check an
image's registration directly.

## The platform (planned)

A photographer signs in with Google, adds their camera, and registers
photographs. They pay through Stripe, or with crypto if they choose, and
never see a key, a wallet or a gas fee: each account gets its own signer
behind the sign-in, and Genesis pays the gas <!-- docs/desktop-parity.md -->.
Because every photographer signs for themselves, the record still says
"this body's owner registered this image", not "Genesis did".

For organisations: a public verify page with shareable results, an
organisation console for contests and archives, and an intake API their
submission flows call <!-- docs/platform-plan.md -->. Only the verify page
exists today.

## What is free, what is paid (planned)

Open core, paid cloud <!-- docs/cloud-plan.md -->. Everything that runs on
the photographer's machine is open source and free: enrolment, registration,
the verify page, the desktop app. Verifying an image needs no account, no
wallet and no crypto.

Genesis Cloud is the planned paid tier. Nothing in it is built yet
<!-- docs/cloud-plan.md -->:

- encrypted backup of the fingerprint and the RAW archive, encrypted on the
  device so Genesis cannot read them;
- registration without gas, within a quota;
- certificate pages, one per registered photograph;
- dispute packs: the record and a report an adjudicator can follow.

Planned: 20 free registrations per body <!-- founder's plan, confirmed 12 Oct 2026 -->,
then Pro and Studio tiers with larger quotas <!-- docs/cloud-plan.md -->.
Prices come from what onboarded photographers tell us they would pay.

## Traction

Stated as it stands.

- **Shipped:** the verify page, one verification core shared by the web page
  and desktop app, LibRaw in WASM for enrolment in the browser, and the
  published adversarial work.
- **Live on Base mainnet since 12 October:** registry 1.0.0 at
  `0xBa5Ea549c9e1414C14038dB050e0caCB4f9E48cB`, verified on Basescan, with
  no admin and no reset <!-- README.md, Deployments -->. The founder's
  Canon R10 is registered with its camera commitment, and 20 of their
  photographs are registered, each scored against the camera's fingerprint
  first (PCE 12,117 to 140,753, against a threshold of 100).
- **Measured:** all 20 resolve from their files, and all 20 still resolve
  after being resized, re-encoded and stripped of metadata. A registration
  costs about 0.0000013 ETH in gas, a fraction of a cent
  <!-- docs/colosseum-checklist.md -->.
- **Next:** onboarding other photographers, Nairobi contacts first, with one
  written note per onboarding on what confused them and what they would pay
  for. None is enrolled yet.
- **osoroprints:** every print is planned to carry a Genesis certificate
  linking to its record. None has shipped yet.
- **Not yet:** a paying customer, or a conversation with a competition
  organiser <!-- docs/go-to-market.md -->.

## Why this founder

Osoro runs osoroprints, a print business that needs a certificate on every
print linking to a record a buyer can check. They
shoot on the camera Genesis was measured against. And they attacked their own
system, published the numbers, corrected the ones that failed, and reported
the defence that did not work.
