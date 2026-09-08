# AI use

Built with Claude Code (Claude Opus 5). Checkable against `git log`.

**Input — human.** Every decision: scope, what the project may claim, the
name, what to cut, what was too speculative, when a label was wrong. All
domain knowledge — PRNU, the bodies, the prior art in `BUILD.md` §2.

**Output — model.** Prose, diagrams, edits, deletions, commits, and checking
its own work. Editorial calls were surfaced, not taken silently.

## Log — 7 September 2026

| Asked | Produced |
| --- | --- |
| (predates this session) | `8d0374d` — initial scaffold, every module a stub |
| Cut the speculative opening | Positioning copy replaced with sourced fact |
| One README, small | Four sub-READMEs deleted; pinned-address table kept as `identity/addresses.md` |
| Say AI-generated | One word, paragraph rewrapped |
| Elaborate Birthmark and ERC-7053 | Two paragraphs, traced to `BUILD.md` §2 |
| Note the camera's data is all we need | One sentence, checked against Flow A |
| Less technicality | `commit()` internals and CID mechanics dropped |
| Make it the closing section | Moved to the end |
| No Rust; explain the stack; emit a diagram | Stack paragraph, three-flow mermaid |
| Show contract vs subsystem | Redrawn with the on-chain boundary |
| Label things as contract, etc. | Nodes prefixed by kind |
| Desktop or web app? | Neither — labels corrected to CLI |
| Rename to Genesis | Six files |
| "Let there be light" | The epigraph |
| Update `BUILD.md` from the README | Diagram ported to §4, both copies identical |
| Remote and push | Committed first, `_to_delete/` excluded |
| Start with the enrolment maths | Flow A written: CFA split, wavelet residual, ML estimator, post-processing, PCE, commitment. `demo` passes on a synthetic sensor |
| Here are 41 real CR3 frames | Gate A run on the R10. All 10 held-out frames pass. Numbers and caveats in `docs/gates.md` |
| Back the constants with a reference | Every constant cited to Fridrich 2009. One of them was wrong — see below |
| Keep AI-USE current; make the repo public | This file, then the visibility change |
| Explain the maths behind K | README section: sensor model, estimator, PCE, all cited by equation |
| The fail rate looks high | It was not — 25/25 non-enrolment frames passed. Measured rather than assumed, then plane summing and saturation masking took the weakest from 143 to 672 |
| Redo the test; write an e2e checklist | CLI enrol → test verified, 13/13; `docs/e2e-checklist.md` ordered by what blocks what |
| A 5D Mark III DNG, a camera JPEG | Linear DNGs refused with a reason; delivered JPEGs scored by re-mosaicking onto the photosite lattice |
| Validate Gate B | Conditional pass: survives 1800px at quality 95, dies at quality 80. Ladder in `docs/gates.md` |
| Look at mirroring too | Search widened to all eight orientations, four rotations by two reflections |
| Continue the checklist | `ingest/` — hashing, records, Merkle — then `Registry.sol`, 12 tests |
| Another R10, from raw.pixls.us | **A different body scores 39.1.** Threshold raised 50 → 100 on that evidence |
| Do the local anvil run | `contracts/script/local-e2e.sh` — enrol, register, look up, prove inclusion, offline |
| Commit the corpus; document a sample run | 662 MB of frames published, with the forgery-kit consequence stated |
| Then: scrub it and keep the files private | History rewritten and force-pushed. The rewrite also deleted the local copies — see below |

## Log — 8 September 2026

| Asked | Produced |
| --- | --- |
| Pick up what the checklist can unblock | Etherscan verification of the live `Registry`, and the verify page's chain read re-checked against Sepolia itself rather than anvil |
| (key provided mid-task) | `forge verify-contract` run; confirmed independently through the Etherscan V2 API rather than trusting the command's own output |
| The last four ENS stubs | `identity/scripts/register-body.ts` implemented against ENSv2 ABIs read from the verified sources on Blockscout, plus `ens.ts` and 8 tests |
| Adversarial research: K has leaked | Subagent briefed to attack the system as built and measure it, with the attack code and `docs/adversarial.md` as deliverables. In flight at time of writing |
| Can the library process HEIC, from two phones? | No, and `docs/phones.md` — the reasons are architectural, not a missing codec |
| Explain the birthmark each photo carries | `docs/camera-sensors.md` — sensor physics, the estimator, the enrolment set |
| Link the references for each claim | Four papers added and verified by lookup rather than recalled; paper claims and repo measurements marked as different kinds of source |
| Make it shorter | 228 lines to 170, tables in place of prose |

Continued, same day — the adversarial turn.

| Asked | Produced |
| --- | --- |
| Attack it: K has leaked and they have the raw files | A leaked K forges invisibly, and the leak is not needed — one RAW file off the body reaches PCE 280 at 58 dB. A synthetic pattern that was never a photograph scores 82,190 through the shipped CLI |
| Can a forgery be a RAW file? | A Bayer DNG the pipeline reads as `Flat`, matching at 88.9 dB. `UniqueCameraModel` says what I typed |
| Can Fourier maths salt K? | No. Measured: a secret phase mask leaves the weakest genuine frame at 26 and a forgery at 375. The forgery *is* the signal the detector looks for, scaled |
| Explore detection | Two partial checks built, one published defence not reproduced, and the honest numbers: AUC 0.725–0.900, every range overlapping |
| What is the success rate? | None quotable, and the doc says so with the reason |
| Prior art, other industries | Biometrics settled this: the trait is an identifier, not a secret. C2PA keys at capture instead |
| Deploy key provided | Subgraph live on Studio, MCP and the verify page both answering from it |
| Bind the camera serial | Keyed commitment in an ENS resolver record, plus an optional evidence digest and the dispute workflow |

## Model errors worth recording

**A constant taken from memory.** The model wrote `SIGMA = 5.0 / 255.0` with
a comment calling it "the literature value". It was not. The source specifies
2/255, and the wrong value cost an order of magnitude of Gate A margin — the
weakest held-out frame scored 91 against a null of 38, where the sourced
value gives 1,212. It surfaced only because the human asked for the constants
to be backed by a reference. Nothing in the code, the tests or the passing
gate would have caught it: the pipeline ran, the demo passed, and the number
was wrong.

**The wrong resampling for Gate B.** The first scale search interpolated the
fingerprint. A resize *averages* neighbouring pixels, so what survives is the
area average — interpolating keeps detail the resized image no longer has,
and the two decorrelate. It scored at the null, which read as "Gate B fails"
until the method was questioned rather than the result.

**A test fixture that indicted the wrong thing.** The perceptual hash was
declared broken by a test using a 64×48 noise field, where it moved 16 bits
under a resize. On a real photograph it moves zero bits from 1800px q95 down
to 400px q60. The hash was fine; the fixture had no low-frequency structure
for it to hold on to.

**A null that stopped being a null.** Once the search tried all eight
orientations, the rotated-K negative control was no longer a control — the
search simply undoes the rotation and matches. The model's own test caught it
by scoring 1,084 where it expected 40.

**A history rewrite that deleted the originals.** `git filter-branch` removed
the test corpus from history and the checkout removed it from the working
tree too, leaving GitHub as the only copy of 662 MB of the human's own
photographs. Caught before the force-push that would have destroyed both.
Restoring from `origin` first, then scrubbing, was the order that should have
been planned rather than recovered into.

**An empty string is a perfectly good string.** `.env` declared the `ENS_*`
keys blank, and the model used `??` for the fallback, which only catches
`undefined`. The address became `""`, and the RPC rejected it as "Invalid
params" — an error four frames away from the mistake and naming none of it.
The offline tests all passed. It surfaced only when the code was pointed at
live Sepolia, which is the argument for running the read paths against the
real chain rather than trusting a green suite.

**A roadmap that belonged to someone else.** The model reported that
`BUILD.md` put an Android app in this project's phase 2. It does not — that
passage describes the *Birthmark Standard's* roadmap, as does the README's
"PRNU on phones". Left uncorrected it would have written a commitment into
`docs/phones.md` that nobody had made. Caught by re-reading the surrounding
lines before citing them, which is the only reason it was caught at all.

**A subagent's numbers that did not reproduce.** The adversarial research was
delegated, came back with measured tables, and read as authoritative. Three
figures did not survive an independent re-run: a different-model carrier
scored 393,382 rather than the 2,895 reported, because the agent cropped K to
the carrier where an attacker would resize the carrier instead; the minimum
injection strength from one stolen RAW was 0.10, not 0.250; and the reported
trend of needing *more* strength as the attacker steals *more* frames was
backwards. The conclusion held and was understated in every case, which is
exactly what makes it worth recording — plausible numbers in the right
direction are the ones that get quoted without checking.

The first re-run also failed, and that was the checker's error rather than the
agent's: `postprocess` was applied to the attacker's estimate, which is a
defender-side step that destroys the attack. It read as "the finding is wrong"
until the control — planting the leaked K, which had to work — was run and did.
A negative result against your own tooling needs a positive control before it
means anything.

**Bands quoted from a sample of two.** The docstrings in
`fingerprint/consistency.py` carried a genuine `effective_strength` band of
0.0109–0.0218 on the delivered path, measured on **two** images, and 0.97–3.64
on raw from eight. Re-run on ten per path they are 0.0011–0.6674 and
0.0326–3.6250 — the first three hundred times wider — and forgeries land
inside both without aiming. The `resampling_peak` figures were worse: two
genuine files read 16.0 and 25.8 against forgeries at 32–33 and looked like a
detector; ten reach 96.8 and it is chance, AUC 0.517. Each was a description
of a sample presented as a property of a method, and each was corrected only
because the human asked for a success rate.

**A verdict that outran its evidence.** Wiring the perceptual branch, the
first version returned `registered` for a degraded copy whose PCE was 37.3,
below the threshold — the same word an exact pixel-hash match at 1,895 gets.
Caught by reading the number in the response rather than the verdict beside
it. It is now `derived`, and it prints the sub-threshold PCE with the words
"the pixels do not carry this claim".

**A quote that was never said.** "C2PA makes only two security claims" is
widely repeated and does not appear in their Security Considerations at all;
it is a critique paper's characterisation. Caught by fetching the source
before quoting it, which is the rule the sigma error above bought.

Ten of the twelve were found by measuring or by the tooling failing loudly.
The other two — the constant taken from memory, and the roadmap misread —
were found only by going back to the source and reading it. The pattern is
consistent enough to be a rule: **every error that survived a passing test
suite was a number quoted from too small a sample, or a sentence quoted from
memory.**

## Not done

Chainlink CRE has no code at all — not a stub, three comments and an empty
env var. It is the one sponsor track with nothing behind it, and
`docs/e2e-checklist.md` §10 now tracks that rather than leaving it implied.
Deploying needs enrolment through a Chainlink account team, so it is an
approval with unknown turnaround rather than a key anyone can fetch.

Everything else is built. `Registry` is live on Sepolia and verified on both
Blockscout and Etherscan. The subgraph is deployed to Studio and indexing real
events, and the MCP server and the verify page's perceptual branch both answer
from it. The demo console has all five steps wired, though its signing paths
have only been tested against stubs.

ENS is implemented and tested but not registered: the parent name is
deliberately left until close to the recording, because ENSv2 Sepolia resets
names on redeployment.

**There is no forgery-detection rate, and none should be quoted.** Measured
separations are AUC 0.725 to 0.900 with every range overlapping, so no
operating point buys useful detection at a tolerable false-positive cost —
and a false positive means calling a real photograph a fake.

The false-positive rate is still unmeasured. One same-model negative exists
and it lands in the null band, which rules out a broken approach but does not
give a rate — that needs dozens of bodies. No second body has been enrolled,
so the test has never run both ways.

## Checks

- Every mermaid block rendered through `@mermaid-js/mermaid-cli` before commit.
- Contract names and fields read from `contracts/src/Registry.sol`.
- PRNU, Birthmark and ERC-7053 facts quoted from `BUILD.md`, not recalled.
- Gate A run on 41 real CR3 files, not simulated. Both the crop and the
  full-resolution runs are reported, including the frame that fails when
  cropped.
- The denoiser constants were read out of the cited paper rather than
  recalled, which is how the first error above was found.
- Gate B is a ladder of eight rungs across three frames, and the rungs that
  fail are reported next to the ones that pass.
- Merkle proofs generated in Python are pinned as vectors in the Solidity
  test, so the two implementations cannot drift apart silently.
- Every file offered as a different camera was checked with
  `exiftool -SerialNumber` first. Two turned out to be the same body, and
  scoring them as negatives would have produced a fake result.
- The whole chain path was run offline against `anvil` before any claim that
  it works.
- ENSv2 ABIs were read from the verified sources on Blockscout rather than
  recalled, and both failure paths of the registry walk were exercised
  against live Sepolia state — including `raffy.eth`, which is owned but has
  no subregistry, the case that would otherwise have been found on camera.
- The Etherscan verification was confirmed through the API rather than
  trusting the exit status of the command that submitted it.
- The papers cited in `docs/camera-sensors.md` were verified by lookup
  before being added, after the sigma error above.
