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

## A model error worth recording

The model wrote `SIGMA = 5.0 / 255.0` with a comment calling it "the
literature value". It was not. The source specifies 2/255, and the wrong
value cost an order of magnitude of Gate A margin — the weakest held-out
frame scored 91 against a null of 38, where the sourced value gives 1,212.

It surfaced only because the human asked for the constants to be backed by a
reference. Nothing in the code, the tests or the passing gate would have
caught it: the pipeline ran, the demo passed, and the number was wrong.

## Not done

`ingest/`, the contracts, the subgraph, the scoring service and the verify
page are stubs. Gate B has not run and the crop-and-scale search it needs is
not written. Gate A passed against one body, so the negative control is a
rotated fingerprint rather than a second camera and the false-positive rate
is unmeasured.

## Checks

- Every mermaid block rendered through `@mermaid-js/mermaid-cli` before commit.
- Contract names and fields read from `contracts/src/Registry.sol`.
- PRNU, Birthmark and ERC-7053 facts quoted from `BUILD.md`, not recalled.
- Gate A run on 41 real CR3 files, not simulated. Both the crop and the
  full-resolution runs are reported, including the frame that fails when
  cropped.
- The denoiser constants were read out of the cited paper rather than
  recalled, which is how the error above was found.
