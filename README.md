# Certify the Camera

**Origin registry for photographers — prove an image came out of a specific camera body.**

ETHOnline 2026 · 4–16 September

---

The photo world is trying to verify a negative — proving an image *wasn't*
generated. It can't be done. We verify the positive instead.

Every image sensor carries a permanent, per-body physical fingerprint (PRNU)
that imprints on every exposure and cannot exist in an image that never
passed through it. We register it and certify **origin, not truth**.

The property that makes this a product rather than a paper: **it works
retroactively**, on images already published, already scraped, already
stripped of metadata, from cameras whose manufacturers will never cooperate.

> We are the layer that works before the manufacturers arrive, and on the
> images that already left.

`BUILD.md` is the source of truth for this project. Where this README and
`BUILD.md` disagree, `BUILD.md` wins.

## What this certifies — and what it does not

We certify: exposed on body X · body registered to identity Y · first
registered at time T · these derivatives descend from that original.

We never say "authentic", "AI-free", "verified real", or that the absence of
a record means anything. A camera pointed at a high-quality screen produces a
genuine exposure of a fabricated scene and defeats every provenance system on
the market, including in-camera cryptographic signing. See `docs/claims.md`.

## Layout

```
fingerprint/   Python — the imaging core (PRNU extraction, PCE scoring)
ingest/        Python — record construction, hashing, Merkle session batching
contracts/     Solidity + Foundry — ERC-7053 commit() and the body registry
identity/      ENSv2 on Sepolia — body subname registration
subgraph/      The Graph — index registrations, resolve image → record
scoring/       FastAPI — HTTP wrapper around the scorer
verify/        web page — upload, score, look up, verdict
mcp/           Subgraph MCP server
docs/          claims discipline, gate results, demo script
data/          local scratch: enrolment frames, references (gitignored)
```

The language split is not stylistic. `rawloader` in Rust cannot read CR3 at
all, and the raw-plus-wavelet ecosystem only exists in Python. Solidity for
contracts. Rust anywhere else you like.

## Getting started

Python 3.11+ (`numpy` 2.x wants it; note `ndarray.ptp()` was removed in
numpy 2 — use `np.ptp()`).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 fingerprint/fingerprint.py demo      # must PASS before anything else
```

Contracts:

```bash
curl -L https://foundry.paradigm.xyz | bash && foundryup
cd contracts
forge install foundry-rs/forge-std OpenZeppelin/openzeppelin-contracts
forge build && forge test
```

Scoring service:

```bash
uvicorn scoring.app:app --reload
```

## The gates

Nothing downstream matters until both have run. See `docs/gates.md`.

- **Gate A** — does K exist on this body? 40–50 defocused flats, CR3 not
  C-RAW, Long Exposure NR off.
- **Gate B** — does it survive a web JPEG round trip? Decides whether the
  retroactive claim is live.

## Status

Nothing is implemented. Every module in this tree is a stub with the
signatures and the reasoning in place. Fill them in from `BUILD.md`.
