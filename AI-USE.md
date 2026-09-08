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

Six of the eight were found by measuring or by the tooling failing loudly.
The other two — the constant taken from memory, and the roadmap misread —
were found only by going back to the source and reading it.

## Not done

The CRE workflow is still a stub. The subgraph, the scoring service, the
verify page and the MCP server are written and tested, and the subgraph is
not deployed — that waits on a Graph Studio key.

`Registry` is live on Sepolia, verified on both Blockscout and Etherscan,
with a body, an image and a session registered and reading back. ENS is
implemented but not registered: the parent name is deliberately left until
close to the recording, because ENSv2 Sepolia resets names on redeployment.

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
