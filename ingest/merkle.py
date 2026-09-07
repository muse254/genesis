"""Session batching -- one Merkle root per import.

Never one on-chain write per photograph: a shoot is 2,000 frames
(BUILD.md sec.5). Register the root, keep inclusion proofs per frame, and
let verification present a proof against the root.

First to be cut after CRE, subgraph and ENS -- but the demo reads better
with it, because a photographer importing a shoot is the real workflow.
"""

from __future__ import annotations

from eth_hash.auto import keccak

# --- the rules, pinned -----------------------------------------------------
#
# These three choices have to agree with the Solidity verifier exactly, and
# a mismatch shows up as a proof that fails for no visible reason. They are
# OpenZeppelin's MerkleProof conventions, because that is what the contract
# will use rather than a hand-rolled verifier:
#
# 1. keccak256, not SHA-256. The rest of this package hashes with SHA-256;
#    the tree does not, because it has to be cheap on chain.
# 2. Pairs are hashed in sorted order, so a proof carries no left/right
#    flags and the verifier stays small.
# 3. An odd node at any level is promoted to the next level unchanged --
#    NOT duplicated. Duplicating is the Bitcoin rule and it admits a
#    second-preimage attack where a tree of n leaves and one of n+1 can
#    share a root.


def _hash_pair(a: bytes, b: bytes) -> bytes:
    return keccak(a + b) if a <= b else keccak(b + a)


def _level(nodes):
    """One level up the tree, promoting a trailing odd node."""
    parents = [_hash_pair(nodes[i], nodes[i + 1]) for i in range(0, len(nodes) - 1, 2)]
    if len(nodes) % 2:
        parents.append(nodes[-1])
    return parents


def merkle_root(leaves) -> bytes:
    """Root over sorted leaf hashes. Pin the duplicate-odd-node rule here.

    Leaves are sorted so that the root depends on the set of frames in a
    session and not on the order they happened to be imported in.
    """
    nodes = sorted(bytes(leaf) for leaf in leaves)
    if not nodes:
        raise ValueError("a session needs at least one frame")
    while len(nodes) > 1:
        nodes = _level(nodes)
    return nodes[0]


def inclusion_proof(leaves, index: int):
    """Sibling path proving ``leaves[index]`` is under the root.

    ``index`` is into the caller's own ordering; the leaf is located in the
    sorted tree by value, so callers do not have to sort first.
    """
    leaves = [bytes(leaf) for leaf in leaves]
    target = leaves[index]

    nodes = sorted(leaves)
    position = nodes.index(target)

    proof = []
    while len(nodes) > 1:
        sibling = position ^ 1
        if sibling < len(nodes):
            proof.append(nodes[sibling])
        # a promoted odd node has no sibling at this level and adds nothing
        nodes = _level(nodes)
        position //= 2
    return proof


def verify_proof(leaf: bytes, proof, root: bytes) -> bool:
    """Check an inclusion proof. Must agree with the Solidity verifier exactly."""
    node = bytes(leaf)
    for sibling in proof:
        node = _hash_pair(node, bytes(sibling))
    return node == bytes(root)
