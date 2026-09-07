"""Session batching -- one Merkle root per import.

Never one on-chain write per photograph: a shoot is 2,000 frames
(BUILD.md sec.5). Register the root, keep inclusion proofs per frame, and
let verification present a proof against the root.

First to be cut after CRE, subgraph and ENS -- but the demo reads better
with it, because a photographer importing a shoot is the real workflow.
"""

from __future__ import annotations


def merkle_root(leaves) -> bytes:
    """Root over sorted leaf hashes. Pin the duplicate-odd-node rule here."""
    raise NotImplementedError


def inclusion_proof(leaves, index: int):
    """Sibling path proving ``leaves[index]`` is under the root."""
    raise NotImplementedError


def verify_proof(leaf: bytes, proof, root: bytes) -> bool:
    """Check an inclusion proof. Must agree with the Solidity verifier exactly."""
    raise NotImplementedError
