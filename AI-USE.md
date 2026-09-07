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

## Not done

The imaging core is unwritten. `fingerprint/`, `ingest/`, the contracts and
the subgraph are stubs. No K estimated, no PCE scored, neither gate in
`docs/gates.md` run, nothing shown to work on a real body.

## Checks

- Every mermaid block rendered through `@mermaid-js/mermaid-cli` before commit.
- Contract names and fields read from `contracts/src/Registry.sol`.
- PRNU, Birthmark and ERC-7053 facts quoted from `BUILD.md`, not recalled.
