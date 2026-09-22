# Colosseum checklist

Tracks `COLOSSEUM.md`. The plan says why; this says what is done. Deadline
**Sunday 12 October 2026**. Tick items in the commit that finishes them.

Work happens on `colosseum` only. `main`, `ethonline` and the tag
`ethonline-submission` stay at `1e2f392`, the prior-work boundary.

## Setup — 17 Sept

- [x] Freeze ETHOnline: branch `ethonline` + annotated tag `ethonline-submission` at `1e2f392`, pushed
- [x] Branch `colosseum` created and pushed; `COLOSSEUM.md` its first commit
- [x] D1 Base mainnet · D2 drop ENS, commitment on chain · D3 ~3h/day
- [x] Registry: `bodyCommitment` replaces `ensNode`; Base Sepolia allowed test mode
- [x] Console, ingest, subgraph, MCP, verify page follow `GENESIS_CHAIN` and the rename
- [x] `python -m ingest commit-body`
- [x] Colosseum project created — name Genesis, chain Base, category Identity & Privacy, brief description
- [x] **D4 — K lives only on the photographer's machine**; the hosted service runs `GENESIS_PUBLIC=1` and holds none. TEE and ZK scoring are future work (`docs/security.md`, "Where K lives")
- [x] **D5 — desktop app with Tauri, built before the mainnet tests**; gasless onboarding through an app key and our relayer (ERC-2771), invite codes; every platform via CI

## Week 1 — 17–23 Sept · Go live

- [ ] Deployer key chosen and backed up — it owns the R10 body forever; there is no transfer
- [x] Rehearsal key funded: `0x63723f1C…2137` holds Base Sepolia ETH, bridged from the ETHOnline deployer (faucets want a mainnet balance)
- [ ] Mainnet key decided and funded with ~0.005 ETH on Base
- [x] Rehearse on Base Sepolia — 17 Sept
  - test registry [`0x0C0F3Ec87339F985c509c01dEE8474BB8f5b0EB2`](https://sepolia.basescan.org/address/0x0c0f3ec87339f985c509c01dee8474bb8f5b0eb2), `testMode` true, verified on Basescan
  - R10 body registered ([tx](https://sepolia.basescan.org/tx/0xec7bf4dee6428634bc7ecf2a1a75f2a70554a47f2ad75c59ec870323301833aa)); IMG_0191 registered at PCE 220,907 ([tx](https://sepolia.basescan.org/tx/0xa7cba6cae1f5677ce756e23bd5faa533747d60ef805c7526de24e05f8b8b4e83))
  - public scorer (`GENESIS_PUBLIC=1`, no references) refuses `/score` and returns the pixel hash, which resolves on chain to the R10 body
- [ ] Verify page driven in a browser against the Base Sepolia registry
- [ ] Deploy to Base mainnet, `REGISTRY_TEST_MODE` unset (false)
- [ ] Verified on Basescan; address and deploy tx pinned in README and `.env.example`
- [x] Subgraph on Base Sepolia for the rehearsal — `genesis` v0.1.0-base-sepolia
      (22 Sept), indexing the rehearsal registry from its actual deploy block
      (46937327). Found by the dashboard's first real query: every
      `VITE_SUBGRAPH_URL` in the repo, and `SUBGRAPH_URL`/`REGISTRY_ADDRESS`
      in `.env`, had been left pointed at the ETHOnline subgraph/registry on
      Ethereum Sepolia the whole time -- a different chain, a different
      contract, silently answering with someone else's data instead of
      erroring. All repointed at the Base Sepolia deployment.
- [ ] Subgraph on Base: `subgraph.yaml` network `base`, new address, `startBlock`; deployed and **published** —
      the Studio development URL is capped at 3,000 queries/day and is for testing only; a published
      subgraph queried with an API key has 100,000 free queries/month, then $2 per 100,000
- [x] Scoring service has a public mode: no K, hashes only, refuses to start beside a reference
- [ ] Scoring service hosted with `GENESIS_PUBLIC=1`: HTTPS on a real domain, health check green, survives reboot
- [x] Verify page takes body identity from the chain record, and labels the stored PCE as owner-reported
- [ ] Verify page public, pointed at Base; both Flow C branches live (exact hash; pHash via the subgraph, no re-score)
- [ ] R10 body registered on mainnet with a camera commitment
- [ ] 20+ photographs registered, each resolvable from the public verify page
- [ ] README for a stranger: verify an image in 60 seconds without `BUILD.md`; `adversarial.md` linked prominently
- [ ] README and `docs/claims.md` point at the Base address, not Sepolia; the "test registry" caveat updated for a production registry
- [x] Say what happened to CRE: code removed; `docs/cre.md` and `docs/security.md` say so
- [x] README rewritten for Colosseum: intro, how it works, maths references (474 → 124 lines)
- [ ] Push

## Week 2 — 24–30 Sept

- [ ] Hot-pixel and defect map — `adversarial.md` §"Proposals, ranked", tier 1 item 2 (items 1 and 3 shipped 8 Sept)
- [ ] MCP server real, not sketched: runs against the Base subgraph, `verify_image` / `lookup_body` / `image_lineage` answer from live data
- [ ] MCP: an agent can check an image it holds, not only a hash it already knows (through the public service's hashes)
- [ ] MCP: install instructions a stranger can follow; one recorded agent session
- [ ] Push

## Week 3 — 1–7 Oct · Traction

- [ ] osoroprints: every print sold carries a Genesis certificate linking to its record
- [ ] osoroprints: first customer through the live integration
- [ ] Onboarding path a stranger can finish: enrol, commit, register — with their own key and their own gas
- [ ] 10 enrolled bodies that are not the founder's
- [ ] One note per onboarding: what confused them, what they would pay for
- [ ] Push

## Week 4 — 8–12 Oct · The pitch

- [ ] Demo video: register, strip, resize, re-encode, still resolves; then a forgery caught
- [ ] Pitch covers: the insight sentence, the adversarial work, the Nikon paragraph, the paywall map, PRNU for the archive and C2PA for new captures, the market
- [ ] Name the prior art before a judge does: Birthmark Standard (arXiv 2602.04933), OpenOrigins (Galaxy-backed); nearest Colosseum projects `decentracam`, `certana`, `here.`
- [x] Go-to-market written: `docs/go-to-market.md` (competitions → licensing/print → agencies buying from freelancers; not a fake-news pitch)
- [ ] Update its demand-validation section with what week 3 actually produced
- [ ] Every sentence checked against `docs/claims.md`
- [ ] **LICENSE** chosen and committed — open-source status is scored
- [x] CI green on every push: pytest ≥75% coverage, Foundry with 10k fuzz runs and Registry at 100% coverage, Slither, subgraph, MCP, web, desktop clippy (17 Sept)
- [ ] Prior-work disclosure: `git log ethonline-submission..colosseum`, with the tag as the boundary
- [ ] Confirm the event: Crypto World's Fair 14 Sept – 12 Oct vs the blog's Fall hackathon 28 Sept – 2 Nov
- [ ] Submission form complete; links resolve from a logged-out browser
- [ ] Tell Osoro it is ready — **the merge to `main` is theirs to make**

## Scoring without Chainlink

CRE is a binding non-goal. What it did and did not do, from `docs/cre.md`:

- **K was never computed there.** Enrolment runs locally in Python and always has.
- **CRE only scored**, on a 256² crop, and only ever in the simulator:
  `attested` was false on every path that ran. Removing it removes no guarantee
  the ETHOnline build actually delivered.

So the Colosseum build scores the way ETHOnline's `/score` always did: the
scoring service holds the reference and runs `prnu.score` on the full frame,
which is also stronger than the crop (IMG_0230: 1,895.4 full, −25.5 at 256²).

What the public verify page needs K for, and what it does not:

| Verdict | Needs K? |
| --- | --- |
| `registered` — exact pixel hash on chain | No |
| `derived` — pHash finds the original via the subgraph | No, for the match; yes, for the PCE shown beside it |
| `fingerprint-only` / `no-record` for an unregistered image | Yes |

**D4, decided 17 Sept:** no server holds K. The public verify page shows the
first two verdicts; fingerprint scoring happens on the photographer's machine.
A verifiable score — confidential VM or zero-knowledge proof — is future work,
costed in `docs/security.md`, and neither would defend against a planted
fingerprint.

## Desktop app

Decided 17 Sept: the photographer-side tooling ships as a Tauri app. The
presenter console (`console/` + `console-ui/`) is already that app in a
browser tab on localhost, so this packages it rather than rewrites it.

Why it fits: enrolment and scoring need the RAW archive and K, both of which
are on the photographer's machine. A desktop app keeps them there, which is
what `docs/security.md` wants.

Open before building:

- [x] Python sidecar frozen with PyInstaller: 49 MB; verifies a CR3 against Base Sepolia (`desktop/`)
- [x] App shell: free port injected into the page, backend exits with the app, Genesis icons
- [x] CI for macOS, Windows, Linux into a draft release (`.github/workflows/desktop.yml`) — not yet run
- [x] Sidebar UI (18 Sept): five destinations (Home, Photos, Verify, Cameras, Settings) replace the
      eight-screen presenter console. Negative/Survival/Verdict merged into one Verify, using the
      same four-verdict card verbatim. `main.ts`/`screens.ts` superseded, kept for reference.
- [x] Fixed the real "Load failed" bug: the frozen backend cold-starts in 13–35s but the page fired
      its first fetches immediately with no retry. `app.ts` now waits on `/health` before rendering.
      Found by rebuilding and reading the actual `.app`, not by curling the backend directly — that
      looked fine the whole time. Two more CORS/plist issues fixed along the way (real, not the
      cause): WKWebView needs `allow_private_network=True` on both FastAPI services, and the bundle
      needs `NSLocalNetworkUsageDescription` in Info.plist.
- [x] Cold start fixed properly (18 Sept): the sidecar process is gone, replaced by an embedded
      Python interpreter (PyO3) in the app's own process — 2s cold start, down from 13–35s.
      Proven on macOS only; Windows and Linux follow the same pattern, unverified — see
      `desktop/PACKAGING.md`
- [ ] Onboarding screens for photographers; hide the presenter-only screens (pre-flight, reset) —
      largely done by the sidebar rebuild; recheck against `console/app.py`'s `/reset` (not exposed
      in the new UI, confirm nothing else presenter-only leaked through)
- [ ] App key in the OS keychain with a recovery phrase; signs ERC-2771 requests instead of calling `cast`
- [ ] Registry: ERC-2771 forwarder support (before the mainnet deploy)
- [ ] Relayer service: invite codes, per-body quotas, pays gas; hosted
- [ ] Code signing: deferred; unsigned installers with instructions on the landing page
- [x] Landing page on GitHub Pages: download links pulled live from the
      Releases API (`site/`), plus a no-login dashboard (`dashboard/`) that
      reads any address's bodies/images straight off the subgraph -- there's
      no account to log into since nothing behind it is private. Both
      deploy alongside `verify/` via `.github/workflows/pages.yml`.
      Screenshots and a real user-journey pass still open.
- [ ] Which week: it is the week-3 onboarding path, so it has to exist before 1 Oct
- [ ] Strip the presenter-only screens (pre-flight, reset, 07 confidential) from the shipped app
