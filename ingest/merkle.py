"""Session batching: one Merkle root per import, inclusion proofs per frame.

A shoot is ~2,000 frames, so never one on-chain write per photograph.
"""

from __future__ import annotations

from eth_hash.auto import keccak

# --- the rules, pinned -----------------------------------------------------
#
# Must match OpenZeppelin's MerkleProof exactly; a mismatch fails silently.
# 1. keccak256 (cheap on chain), not the SHA-256 used elsewhere.
# 2. Pairs hashed in sorted order, so proofs carry no left/right flags.
# 3. An odd node is promoted unchanged, NOT duplicated: duplicating (the
#    Bitcoin rule) lets trees of n and n+1 leaves share a root.


def _hash_pair(a: bytes, b: bytes) -> bytes:
    return keccak(a + b) if a <= b else keccak(b + a)


def _level(nodes):
    """One level up the tree, promoting a trailing odd node."""
    parents = [_hash_pair(nodes[i], nodes[i + 1]) for i in range(0, len(nodes) - 1, 2)]
    if len(nodes) % 2:
        parents.append(nodes[-1])
    return parents


def merkle_root(leaves) -> bytes:
    """Root over sorted leaves, so it depends on the set of frames, not import order."""
    nodes = sorted(bytes(leaf) for leaf in leaves)
    if not nodes:
        raise ValueError("a session needs at least one frame")
    while len(nodes) > 1:
        nodes = _level(nodes)
    return nodes[0]


def inclusion_proof(leaves, index: int):
    """Sibling path proving ``leaves[index]`` (caller's order; need not be sorted) is under the root."""
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
