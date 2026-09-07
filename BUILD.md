# Certify the Camera

**Origin registry for photographers — prove an image came out of a specific camera body.**

ETHOnline 2026 · 4–16 September · 13 days

> Supersedes `provenance-agent-brief.md` and `certify-the-camera-BUILD.md`.
> Where any of them disagree, this document wins.

---

## 1. Thesis

The photo world is trying to verify a negative — proving an image *wasn't*
generated. It can't be done. Generated images carry no metadata to detect them
by, platforms strip provenance on upload, and classifiers lose to every new
generator.

We verify the positive instead. Every image sensor carries a permanent,
per-body physical fingerprint (PRNU) that imprints multiplicatively on every
exposure and cannot exist in an image that never passed through it. We register
it and certify **origin, not truth**.

The property that makes this a product rather than a paper: **it works
retroactively**, on images already published, already scraped, already stripped
of metadata, from cameras whose manufacturers will never cooperate.

---

## 2. Prior art

Read this section before writing the submission. Two of these will come up.

### The Birthmark Standard — the closest thing to us

arXiv 2602.04933 (Feb 2026), `github.com/Birthmark-Standard/Birthmark`,
Apache 2.0 + AGPL-3.0.

Authenticates camera origin using NUC maps on professional cameras and PRNU on
phones, stores records on a Substrate consortium chain, verifies on pixel data
alone, and explicitly scopes out the staged-photograph problem — the same
discipline we arrived at independently.

**Its constraint is our opportunity.** Cameras reference manufacturer key
tables; a manufacturer validates the NUC hash. Its own roadmap concedes that
adoption needs manufacturer firmware integration and platform partnership.

**Its actual maturity:** 420 commits, **3 contributors, 2 stars, 0 forks**. A
501(c)(3) *in formation*. Phase 1 is a Raspberry Pi prototype. No manufacturer
has signed on. Phase 2 is an Android app and a 50–100 person pilot.

So it is serious, well-designed, unadopted work. **Do not call it "the
standard" in the pitch** — say "the Birthmark record model," which is accurate
and still gives us the interoperability story.

### ERC-7053 — the standard we implement

A real EIP for on-chain media provenance indexing. `commit()` emits a `Commit`
event carrying the recorder address, an asset CID and commit data; storage is
`mapping(string => uint[]) commitLogs`.

Critically, **the EIP explicitly declines to validate the content behind the
CIDs**, leaving that to implementing applications.

That is our positioning in one line: *ERC-7053 defines the index and disclaims
the validation. PRNU is the validation.*

### Numbers Protocol / Capture — the incumbent

Co-authored ERC-7053. Ships Capture and ProofSnap: embed C2PA credentials, log
an on-chain receipt, "Capture → Certify → Check." Owns the plumbing and the
standard. **Their documentation mentions no sensor fingerprinting, no PRNU, and
no RAW handling.** The pixel-level evidence layer is open.

### Starling Lab + Reuters — the institutional precedent

"78 Days," a verified photo archive proof of concept (2023). Capture, store,
verify with decentralised storage. Journalism-facing, not a tool an individual
photographer uses.

### The graveyard

KodakOne — described by Techdirt as a rebranded copyright-trolling scheme with
a blockchain attached; crashed. Binded (ex-Blockai) — dead.

The lesson is not "blockchain photography fails." It is that all of them sold
*registration* and **had nothing to verify**. We have something to verify.

### The two papers that will be used against us

**PRNU-Bench (arXiv 2509.17581, Sept 2025).** 12,960 images, 126 sensors from
114 devices including cameras through 2024, natural scenes only, realistic
train/test separation. Best method: **73.65% top-1 accuracy, AUC 0.967, EER
0.097.** Prior baselines 58.97%.

Far worse than the 2006 literature implies. **Never quote 2006-era numbers.**
Cite this and explain why our conditions differ: flat-field enrolment frames,
40+ references rather than 5, RAW rather than JPEG, and *verification against
one known body* rather than closed-set identification among 126 — a materially
easier problem.

**Camera Fingerprinting Authentication Revisited (USENIX RAID 2020).**
Concludes PRNU-based authentication adds "complexity without substantial
security benefit." Have the distinction ready: it attacks a *live smartphone
challenge-response protocol involving QR codes*, not forensic attribution of
stored images. Different use case — but know it cold.

**Good news:** privacy-preserving PRNU already exists (PP-PRNU, ACM Computing
2024; encrypted-domain PRNU matching). We don't have to invent confidential
scoring, and its existence validates the Chainlink CRE angle.

### What is genuinely unoccupied

1. PRNU combined with **programmable** smart contracts. Birthmark deliberately
   avoids contracts; Numbers has contracts but no pixel verification.
2. **RAW-native** enrolment from CFA planes. Everyone else works on delivered JPEGs.
3. **Retroactive** archive enrolment with no manufacturer or platform cooperation.
4. **Individual photographers** as the user, rather than a newsroom consortium.

---

## 3. Positioning

> We are the layer that works before the manufacturers arrive, and on the images
> that already left.

Birthmark needs Canon to ship firmware. We need the photographer's own files.

---

## 4. Architecture

Three flows. Build backwards from the demo (§6).

### Flow A — Enrol (once, from an existing archive)

```
40+ RAWs  →  CFA plane split  →  wavelet Wiener residual
          →  ML estimator ΣWI/ΣI²  →  K
          →  private reference store (never published)
          →  commitment hash  →  body record on chain + ENS name
```

### Flow B — Register (per image)

```
CR3  ─┬─→  SHA-256 of pixel data  +  perceptual hash
      └─→  residual → PCE against K
           ↓
     Birthmark-shaped record  +  PRNU attestation
           ↓
     ERC-7053 commit()
```

### Flow C — Verify (anyone, any image, anywhere)

```
image  →  SHA-256 of pixel data  →  exact hit?
                                     ├─ yes → record          (untouched file)
                                     └─ no  → pHash lookup → candidate records
                                              → PRNU re-score against that body
                                              → verdict + confidence
```

**Flow C's lower branch is the differentiator.** An exact pixel hash dies the
moment a platform re-encodes or resizes. Everything that has actually been out
in the world needs the perceptual branch.

---

## 5. Data model

We adopt the Birthmark record field-for-field and substitute one field.

| Field | Source | Our implementation |
| --- | --- | --- |
| `image_hash` | SHA-256 of pixel data | unchanged |
| `modification_level` | 0 raw · 1 exposure/WB/denoise/crop · 2 clone, object removal, generative fill | unchanged — and note these map onto the editing rules photo competitions already publish |
| `parent_image_hash` | links a derivative to its ancestor | unchanged — this is the edit graph, for free |
| metadata hashes | HMAC-SHA256 of timestamp, geolocation, owner | unchanged — **commits without revealing, which solves geotag privacy outright** |
| manufacturer certificate | AES-encrypted NUC hash validated by the camera maker | **replaced** by a PCE score against a privately held fingerprint |
| camera signature | ECDSA secp256k1, signed in-camera | **replaced** by ingest-time signing on the photographer's machine — genuinely weaker, say so |
| storage | Substrate consortium chain, no smart contracts | **replaced** by ERC-7053 on EVM |

Sketch:

```solidity
struct BodyRecord {
    bytes32 fingerprintCommitment;  // hash of K — never K itself
    address owner;
    bytes32 ensNode;
    bool    revoked;
}

struct ImageRecord {
    bytes32 imageHash;        // SHA-256 of pixel data
    bytes32 perceptualHash;   // survives re-encode
    bytes32 bodyId;
    uint8   modificationLevel;   // 0 | 1 | 2
    bytes32 parentImageHash;     // 0x0 for originals
    bytes32 metadataHmac;         // timestamp · geo · owner
    uint32  pceScore;
    uint64  registeredAt;
}
```

**The fingerprint never goes on chain.** A published reference is a published
forgery kit. Only a commitment.

**Batch by session.** One Merkle root per import with inclusion proofs per
frame. Never one write per photograph — a shoot is 2,000 frames.

---

## 6. The demo — target 90 seconds

Everything is scaffolding for this.

1. Enrol the R10 from a folder of existing photographs.
2. Register a photograph → ERC-7053 commit, ENS name resolves to the body.
3. Test a photograph from a different camera → near zero, no match.
4. **The money shot:** take the registered photograph, strip every byte of
   metadata, resize it, re-encode as a web JPEG — and it *still resolves*, via
   the pHash-plus-PRNU branch. Birthmark's exact-hash scheme cannot do this.
5. Verify page: exposed on `r10-4471.cam.osoro.eth`, registered 14:02 UTC.

If step 4 works, the pitch writes itself. If it doesn't, see Gate B.

---

## 7. Repo layout

```
certify-the-camera/
├── fingerprint/          # Python — the imaging core  (BUILT)
│   ├── prnu.py           # CFA split, wavelet Wiener, ML estimator, PCE
│   ├── fingerprint.py    # CLI: enroll · test · pair · demo
│   ├── validate_synthetic.py
│   └── stress.py
├── ingest/               # Python — record construction
│   ├── hashing.py        # pixel SHA-256, perceptual hash
│   ├── record.py         # Birthmark-shaped record + PRNU attestation
│   └── merkle.py         # session batching
├── contracts/            # Solidity + Foundry
│   ├── src/Registry.sol      # ERC-7053 commit() + body registry
│   └── test/
├── identity/             # ENSv2 on Sepolia — body subname registration
├── subgraph/             # The Graph — index registrations, resolve image → record
├── scoring/              # FastAPI — HTTP wrapper around the scorer
├── verify/               # web page — upload, score, look up, verdict
├── mcp/                  # Subgraph MCP server (second Graph track)
└── BUILD.md
```

**Language split is not stylistic.** Python for imaging — `rawloader` in Rust
cannot read CR3 at all, and the raw plus wavelet ecosystem only exists in
Python. Solidity for contracts. Rust anywhere else you like.

---

## 8. Toolchain

Every dependency, and why it is there. Anything not on this list needs a reason.

### Imaging — Python 3.11+

| Tool | Why |
| --- | --- |
| `rawpy` >= 0.27 | LibRaw bindings; **the only realistic CR3 path**. Verified here against LibRaw 0.22.1. Gives `raw_image_visible`, `raw_colors_visible`, `black_level_per_channel`, `white_level`. |
| `numpy` 2.x | everything. Note `ndarray.ptp()` was removed in numpy 2 — use `np.ptp()`. |
| `scipy` | `ndimage.uniform_filter` for the local-variance Wiener; `ndimage.zoom` for the crop-and-scale search Gate B needs. |
| `PyWavelets` >= 1.8 | `db8`, 4-level decomposition, for noise extraction. |
| `Pillow` | JPEG export and re-ingest for Gate B; feeds the perceptual hash. |
| perceptual hash | DCT-based pHash. `imagehash` works; consider writing it directly (~40 lines) rather than taking the dependency. |
| `exiftool` (CLI, optional) | maker notes and body serial, to cross-check a file against what the camera reports. |

Reference implementations to **adapt, not import**: `polimi-ispl/prnu-python`
(built for RGB — needs a CFA front end) and the Binghamton MATLAB original
(canonical behaviour when something looks wrong).

**Do not reach for Rust here.** `rawloader` handles CR2 and CRW but not CR3, and
the wavelet ecosystem does not exist. This is the one place Python is not a
preference.

### Contracts

| Tool | Why |
| --- | --- |
| **Foundry** (`forge`, `cast`, `anvil`) | build, test, local chain. Solidity-native tests, much faster than Hardhat. |
| Solidity 0.8.2x | |
| OpenZeppelin Contracts | access control, ownership. Nothing exotic. |
| ERC-7053 reference | check Numbers Protocol's repos for an interface to conform to rather than reimplementing the event shape and getting it subtly wrong. |

### Chain and network

| Tool | Why |
| --- | --- |
| **Ethereum Sepolia** | Chosen because ENSv2's testnet deployment is there and the ENS prize requires it. **This is a prize constraint, not a technical one** — CRE supports Ethereum Sepolia, Base Sepolia and Arbitrum Sepolia, and The Graph indexes all three. If ENS is cut (§10), the chain choice reopens and Base Sepolia is cheaper and faster. |
| `anvil` | local dev, forked from Sepolia where useful. |
| Alchemy or Infura free tier | RPC. |

### Identity

| Tool | Why |
| --- | --- |
| ENSv2 contracts on Sepolia | Permissioned Registry, Permissioned Resolver, ETH Registrar, Universal Resolver V2. **Pin the addresses on day 4.** |
| `ensdomains/ens-cli` | scripting registration. Their README flags it as not production-ready — fine for scripts, keep it off the demo path. |
| `viem` | JS-side chain interaction. Lighter than ethers, better typed. |

### Indexing

| Tool | Why |
| --- | --- |
| `graph-cli` + Subgraph Studio | the subgraph; AssemblyScript mappings. |
| Subgraph MCP server | open source; the second Graph track for near-zero marginal work. |

### Scoring service

The verify page cannot run PRNU in the browser — the scorer is Python and there
is no practical WASM path in 13 days.

| Tool | Why |
| --- | --- |
| `FastAPI` + `uvicorn` | thin HTTP wrapper around `fingerprint.py`. Upload an image, get back a PCE score and a registry lookup. |

The confidential-compute path (§11) eventually replaces this service — which is
the honest reason CRE is in the design at all, rather than a sponsor tick.

### Verify page

Plain HTML plus TypeScript, or a small Vite app. **No framework.** `viem` for
chain reads, `fetch` to the scoring service. It is one page: an upload control
and a result.

### Confidential compute — stretch

| Tool | Why |
| --- | --- |
| `@chainlink/cre-sdk` | Go or TypeScript only, compiles to WASM. The correlation kernel gets rewritten in TS — trivial at 512², but it must agree bit-for-bit with the Python preprocessing. |
| CRE CLI | deployment and Vault DON secrets. |

### Dev

`uv` or plain `venv` + `pip`. `pytest` for imaging, `forge test` for contracts.
The synthetic-sensor harness already written **is** the imaging test suite —
treat `validate_synthetic.py` as a regression test, not a demo.

### First commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install rawpy numpy scipy PyWavelets Pillow fastapi uvicorn

python3 fingerprint/fingerprint.py demo      # must PASS before anything else

curl -L https://foundry.paradigm.xyz | bash && foundryup
forge init contracts --no-git
```

---

## 9. The two gates — day one and day two

Everything above is worthless if the fingerprint doesn't survive the R10's raw
pipeline. Both experiments are cheap and both are decisive.

### Gate A — does K exist on this body?

Shoot 40–50 frames of a defocused white wall. **CR3 not C-RAW.** **Long
Exposure NR off** (it is dark-frame subtraction applied to the raw itself).
High ISO NR off. Base ISO. Evenly exposed, nothing clipping.

```
python3 fingerprint.py demo                                 # sanity check
python3 fingerprint.py pair --crop 1024 ~/flats/*.CR3        # 2-frame quick look
python3 fingerprint.py enroll --out r10.npz ~/flats/*.CR3
python3 fingerprint.py test --fingerprint r10.npz ~/shoot/*.CR3
```

- **Pass:** own held-out frames well above PCE 50, other cameras near zero, at
  least an order of magnitude apart.
- **Fail:** the pipeline is eroding the fingerprint. Stop. Report honestly. One
  afternoon spent.

### Gate B — does it survive the web?

Export one enrolled frame at Flickr dimensions (≈1800px, JPEG q80). Test it
against the fingerprint **with crop-and-scale search**.

- **Pass:** the retroactive claim is live and demo step 4 works. This is the
  strong product.
- **Fail:** the tool works only on files the photographer still holds. Still a
  real product — an archive claim tool — but the pitch changes and step 4 comes
  out. **Decide by day 2, not day 10.**

---

## 10. Schedule

| Day | Date | Work |
| --- | --- | --- |
| 1 | Fri 4 Sep | **Gate A.** Shoot flats, enrol, measure separation. |
| 2 | Sat 5 Sep | **Gate B.** Web-JPEG survival, crop/scale search. The pitch is decided today. |
| 3 | Sun 6 Sep | Registry contract implementing ERC-7053 + body registry. Local mock, end to end offline. |
| 4 | Mon 7 Sep | Deploy to testnet. ENSv2 on Sepolia — **pin contract addresses today, do not chase changes.** |
| 5 | Tue 8 Sep | Enrolment CLI hardening: archive-scan mode, progress, resumability. |
| 6 | Wed 9 Sep | Record construction: pixel hash, pHash, HMAC metadata, Merkle batching. |
| 7 | Thu 10 Sep | Subgraph. Resolve an image to its record. |
| 8 | Fri 11 Sep | Verify page, both branches of Flow C. |
| 9 | Sat 12 Sep | Subgraph MCP server, then CRE confidential scoring. **First to be cut.** |
| 10 | Sun 13 Sep | Demo path end to end on a clean machine, from the README. |
| 11 | Mon 14 Sep | Record the demo. Write the submission. |
| 12 | Tue 15 Sep | Buffer. Assume you need it. |
| 13 | Wed 16 Sep | **Freeze.** Submit. |

**Cut order under pressure:** CRE → subgraph (direct RPC demos nearly as well)
→ ENS (a plain address works — and cutting it reopens the chain choice, since
Sepolia was only ever an ENS requirement) → Merkle batching. **Never cut** the fingerprint
or the verify page. Those are the product.

---

## 11. Sponsor mapping

Each must be load-bearing. Judges can tell when it isn't.

**The Graph — $15,000, largest pool.** Two tracks from one body of work: a
subgraph indexing registrations, and a **Subgraph MCP server** so an agent can
verify an image conversationally. The second is nearly free once the first
exists.

**ENS — $5,000, ENSv2 on Sepolia.** The hierarchical registry *is* the identity
model: `osoro.eth` is the photographer, `r10-4471.cam.osoro.eth` is one enrolled
body, resolver records hold the fingerprint commitment, key and revocation
status. Per-record permissions let one body be delegated without handing over
the namespace.

Their bar is explicit and high: ENSv2 features must be **central to the product,
not a cosmetic add-on**, and the demo **cannot rely on hardcoded values** — you
must register a subname and resolve records live. Our body registry clears that
honestly; a decorative name lookup would not.

Two cautions. Their docs warn the contracts aren't final, so pin addresses on
day 4 and leave them. And ENS Labs recently scrapped the Namechain L2 and moved
ENSv2 to Ethereum mainnet, so the architecture is still moving — treat any ENS
work older than a few months as suspect.

**Chainlink CRE — $2,500, Confidential Workflow.** The reference must stay
private. Confidential workflows are public-code/private-data, which is exactly
the shape: published algorithm, secret reference, signed score to a third party.
Extract the residual client-side, send a 512² crop, correlate in the enclave.
Their service-quotas page 404s — spike the limits early, fall back to
Confidential HTTP if a ~1 MB reference won't ride as a Vault secret.

**Skip:** 1inch, Uniswap, Privy, Arc, Hedera, World.

---

## 12. Claims discipline

A product decision, not a copywriting one. Overclaiming here gets you publicly
dismantled by anyone who understands the analog hole.

**We certify:** exposed on body X · body registered to identity Y · first
registered at time T · these derivatives descend from that original.

**We never say:** "authentic" · "AI-free" · "verified real" · that the absence
of a record means anything.

A camera pointed at a high-quality screen produces a genuine exposure of a
fabricated scene, and defeats every provenance system on the market including
in-camera cryptographic signing. Say so before someone else does.

---

## 13. Out of scope

Rephotography and analog-hole detection. Edit-chain capture from Lightroom.
The contest policy engine. CCAPI, tethering, camera control. Purpose-built
hardware. Any AI-detection classifier.

Several are good ideas. None fit in 13 days, and each one weakens the demo by
splitting it.

---

## 14. Risks

| Risk | Trigger | Response |
| --- | --- | --- |
| K doesn't survive the R10 pipeline | Gate A fails | Stop. Report honestly. |
| Web JPEG doesn't match | Gate B fails | Narrow to archive-claim tool, drop demo step 4, adjust the pitch by day 2 |
| Judge cites PRNU-Bench's 73.65% | during Q&A | Have §2 ready — different task, different conditions |
| Judge cites the USENIX critique | during Q&A | Different use case: live auth protocol, not stored-image attribution |
| ENSv2 interfaces change mid-build | Sepolia calls revert | Pinned addresses; no upgrades during the window |
| CRE quotas won't hold a 1 MB reference | day 9 spike | Confidential HTTP fetch instead of a Vault secret |
| Scope creep | you are reading a Lightroom catalog | Re-read §12 |

---

## 15. What already exists

`prnu-toolkit`, working and validated against a simulated sensor:

- `prnu.py` — CFA plane split, Mihcak wavelet Wiener extraction, ML estimator,
  zero-mean + DFT Wiener postprocessing, PCE scoring
- `fingerprint.py` — `enroll`, `test`, `pair`, `demo`
- `validate_synthetic.py`, `stress.py` — the evidence

Fingerprint recovered at **0.985** correlation with ground truth; same-body PCE
~126,700 against other-body ~21, threshold 50. Degrades roughly an order of
magnitude per insult with several orders of headroom.

**These are synthetic upper bounds.** The simulation has a perfectly stable
fingerprint, no lens vignetting, no dark current, no demosaic. Real figures will
be far lower. The moment you have real ones they replace these everywhere —
here, in the toolkit README, and in the pitch.

The CR3 read path is the one thing never exercised against a real Canon file.
If something breaks on day 1, look there first.

---

## 16. References

1. The Birthmark Standard — https://arxiv.org/pdf/2602.04933 · https://birthmarkstandard.org/ · https://github.com/Birthmark-Standard/Birthmark
2. ERC-7053, Interoperable Digital Media Indexing — https://eips.ethereum.org/EIPS/eip-7053
3. Numbers Protocol whitepaper — https://whitepaper.numbersprotocol.io/
4. PRNU-Bench — https://arxiv.org/html/2509.17581v1
5. Camera Fingerprinting Authentication Revisited, USENIX RAID 2020 — https://www.usenix.org/system/files/raid20-maier.pdf
6. PP-PRNU, privacy-preserving source camera attribution — https://dl.acm.org/doi/10.1007/s00607-024-01330-w
7. Binghamton DDE Lab camera fingerprint reference implementation — https://dde.binghamton.edu/download/camera_fingerprint/
8. polimi-ispl/prnu-python — https://github.com/polimi-ispl/prnu-python
9. 78 Days, Starling Lab and Reuters — https://www.starlinglab.org/78days/
10. rawpy / LibRaw (CR3 decoding) — https://letmaik.github.io/rawpy/api/rawpy.RawPy.html
