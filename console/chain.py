"""The chain reads the console needs, over raw JSON-RPC.

No web3 dependency. The registry's getters return fixed-size static structs,
so encoding a call is a selector plus one word and decoding is slicing --
which is less code than a dependency and leaves nothing to guess about what
went over the wire.

This module reads. It never signs. Signing lives in the endpoints that
register, because `registerImage`'s owner check is the system's only real
boundary (`docs/security.md`) and it should be obvious where it is exercised.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
from eth_utils import keccak

RPC_URL = os.environ.get("SEPOLIA_RPC_URL") or "https://ethereum-sepolia-rpc.publicnode.com"
REGISTRY = (os.environ.get("REGISTRY_ADDRESS") or "").strip()

#: Sepolia. A demo that silently talked to the wrong chain would look like it
#: worked, so `/state` reports this and the console shows it before recording.
EXPECTED_CHAIN_ID = 11155111

EXPLORER = "https://eth-sepolia.blockscout.com"


class ChainError(RuntimeError):
    """The RPC could not answer. Never swallowed: a verdict that degrades
    because the network blinked is a comfortable lie (`docs/console-server.md`)."""


def _selector(signature: str) -> str:
    return keccak(text=signature)[:4].hex()


def _rpc(method: str, params: list, timeout: float = 15.0):
    try:
        response = httpx.post(
            RPC_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as error:  # network, DNS, timeout, non-2xx
        raise ChainError(f"{method}: {error}") from error

    if "error" in payload:
        raise ChainError(f"{method}: {payload['error'].get('message', payload['error'])}")
    return payload["result"]


def _call(signature: str, argument: str) -> bytes:
    if not REGISTRY:
        raise ChainError("REGISTRY_ADDRESS is not set")
    data = "0x" + _selector(signature) + argument.removeprefix("0x").rjust(64, "0")
    return bytes.fromhex(_rpc("eth_call", [{"to": REGISTRY, "data": data}, "latest"])[2:])


def _word(raw: bytes, index: int) -> bytes:
    return raw[index * 32 : (index + 1) * 32]


def _uint(raw: bytes, index: int) -> int:
    return int.from_bytes(_word(raw, index), "big")


@dataclass(frozen=True)
class ImageRecord:
    image_hash: str
    perceptual_hash: str
    body_id: str
    modification_level: int
    parent_image_hash: str
    metadata_hmac: str
    pce_score: int
    registered_at: int


@dataclass(frozen=True)
class BodyRecord:
    fingerprint_commitment: str
    owner: str
    ens_node: str
    revoked: bool


def image(image_hash: str) -> ImageRecord | None:
    """`images(bytes32)`. ``None`` for a hash nobody registered.

    An unregistered hash reads back as a zeroed struct rather than an error,
    so the zero check is the registration check -- and it is the *only* thing
    that may produce a `registered` verdict.
    """
    raw = _call("images(bytes32)", image_hash)
    if len(raw) < 256 or not any(_word(raw, 0)):
        return None
    return ImageRecord(
        image_hash="0x" + _word(raw, 0).hex(),
        perceptual_hash="0x" + _word(raw, 1).hex(),
        body_id="0x" + _word(raw, 2).hex(),
        modification_level=_uint(raw, 3),
        parent_image_hash="0x" + _word(raw, 4).hex(),
        metadata_hmac="0x" + _word(raw, 5).hex(),
        pce_score=_uint(raw, 6),
        registered_at=_uint(raw, 7),
    )


def body(body_id: str) -> BodyRecord | None:
    """`bodies(bytes32)`. ``None`` for a body nobody registered."""
    raw = _call("bodies(bytes32)", body_id)
    if len(raw) < 128 or not any(_word(raw, 0)):
        return None
    return BodyRecord(
        fingerprint_commitment="0x" + _word(raw, 0).hex(),
        owner="0x" + _word(raw, 1)[12:].hex(),
        ens_node="0x" + _word(raw, 2).hex(),
        revoked=bool(_uint(raw, 3)),
    )


def status() -> dict:
    """What the presenter has to see before recording, not during."""
    chain_id = int(_rpc("eth_chainId", []), 16)
    return {
        "rpc": RPC_URL.split("//")[-1].split("/")[0],  # host only, never a key
        "chainId": chain_id,
        "expectedChainId": EXPECTED_CHAIN_ID,
        "onExpectedChain": chain_id == EXPECTED_CHAIN_ID,
        "blockNumber": int(_rpc("eth_blockNumber", []), 16),
        "registry": REGISTRY or None,
    }


def balance(address: str) -> int:
    return int(_rpc("eth_getBalance", [address, "latest"]), 16)


def explorer_url(tx_or_address: str, kind: str = "tx") -> str:
    return f"{EXPLORER}/{kind}/{tx_or_address}"
