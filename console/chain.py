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

#: Every chain the registry is deployed to, keyed by `GENESIS_CHAIN`. One
#: place, so the chain id, the RPC and both explorers cannot disagree.
#: Base mainnet is production (COLOSSEUM.md D1); Sepolia is the ETHOnline
#: deployment, kept readable because its records are real.
CHAINS = {
    "base": {
        "name": "Base",
        "chainId": 8453,
        "rpc": "https://mainnet.base.org",
        "etherscan": "https://basescan.org",
        "blockscout": "https://base.blockscout.com",
    },
    "base-sepolia": {
        "name": "Base Sepolia",
        "chainId": 84532,
        "rpc": "https://sepolia.base.org",
        "etherscan": "https://sepolia.basescan.org",
        "blockscout": "https://base-sepolia.blockscout.com",
    },
    "sepolia": {
        "name": "Sepolia",
        "chainId": 11155111,
        "rpc": "https://ethereum-sepolia-rpc.publicnode.com",
        "etherscan": "https://sepolia.etherscan.io",
        "blockscout": "https://eth-sepolia.blockscout.com",
    },
}

CHAIN_KEY = (os.environ.get("GENESIS_CHAIN") or "sepolia").strip().lower()
if CHAIN_KEY not in CHAINS:
    raise RuntimeError(f"GENESIS_CHAIN={CHAIN_KEY!r}; expected one of {sorted(CHAINS)}")
CHAIN = CHAINS[CHAIN_KEY]

#: `RPC_URL` is the name now; `SEPOLIA_RPC_URL` is honoured only on Sepolia,
#: so an old `.env` cannot quietly point a Base console at the wrong chain.
RPC_URL = (
    os.environ.get("RPC_URL")
    or (os.environ.get("SEPOLIA_RPC_URL") if CHAIN_KEY == "sepolia" else None)
    or CHAIN["rpc"]
)
REGISTRY = (os.environ.get("REGISTRY_ADDRESS") or "").strip()

#: A demo that silently talked to the wrong chain would look like it worked,
#: so `/state` reports this and the console shows it before recording.
EXPECTED_CHAIN_ID = CHAIN["chainId"]
CHAIN_NAME = CHAIN["name"]

EXPLORER = CHAIN["blockscout"]


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


def _call(signature: str, argument: str = "") -> bytes:
    """One `eth_call`. `argument` is a single bytes32-shaped word, or nothing
    for a no-argument getter like `testMode()`."""
    if not REGISTRY:
        raise ChainError("REGISTRY_ADDRESS is not set")
    encoded = argument.removeprefix("0x").rjust(64, "0") if argument else ""
    data = "0x" + _selector(signature) + encoded
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
    #: `ingest/hashing.py:body_commitment`; all zeros when none was committed.
    body_commitment: str
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
        body_commitment="0x" + _word(raw, 2).hex(),
        revoked=bool(_uint(raw, 3)),
    )


#: `testMode` is `immutable` in the contract, so for a given registry the
#: answer can never change. Asking once per process rather than once per
#: `/state` poll matters: the public RPC is the slowest thing the console
#: touches, and `/state` is polled.
_TEST_MODE: dict[str, bool] = {}


def test_mode() -> bool:
    """`testMode()`. True on a registry whose records can be wiped.

    Read from the contract rather than from configuration, because it is the
    contract's answer that matters: a console that believed a `.env` flag
    could offer a reset button on a registry that has no reset, or hide one
    that does.

    Memoised per registry address. The value is immutable on chain, so a
    cached answer cannot go stale -- only a redeployment changes it, and that
    changes the address too.
    """
    if REGISTRY in _TEST_MODE:
        return _TEST_MODE[REGISTRY]
    try:
        raw = _call("testMode()")
        answer = bool(_uint(raw, 0)) if len(raw) >= 32 else False
    except Exception:
        return False  # a registry predating the flag cannot be reset
    _TEST_MODE[REGISTRY] = answer
    return answer


def registry_epoch() -> int:
    """`epoch()`. Bumped by every reset; 0 on a registry never wiped."""
    try:
        raw = _call("epoch()")
    except Exception:
        return 0
    return _uint(raw, 0) if len(raw) >= 32 else 0


def status() -> dict:
    """What the presenter has to see before recording, not during."""
    chain_id = int(_rpc("eth_chainId", []), 16)
    return {
        "rpc": RPC_URL.split("//")[-1].split("/")[0],  # host only, never a key
        "chainId": chain_id,
        "expectedChainId": EXPECTED_CHAIN_ID,
        "onExpectedChain": chain_id == EXPECTED_CHAIN_ID,
        "chainName": CHAIN_NAME,
        "etherscan": ETHERSCAN,
        "blockscout": EXPLORER,
        "blockNumber": int(_rpc("eth_blockNumber", []), 16),
        "registry": REGISTRY or None,
    }


def balance(address: str) -> int:
    return int(_rpc("eth_getBalance", [address, "latest"]), 16)


def explorer_url(tx_or_address: str, kind: str = "tx") -> str:
    return f"{EXPLORER}/{kind}/{tx_or_address}"


#: The second explorer, on purpose. The registry is verified on both, so a
#: reader who distrusts one has another that serves the same ABI.
ETHERSCAN = CHAIN["etherscan"]

#: Where the subgraph can actually be looked at. The query endpoint in `.env`
#: answers POSTs and is no use in a browser; the Studio page is the one a
#: person can open.
GRAPH_STUDIO = "https://thegraph.com/studio/subgraph/genesis"


def reference_links(tx_hash: str = "") -> list[dict]:
    """Every place a claim made here can be checked by someone else.

    Returned by the server rather than assembled in the frontend, for the same
    reason verdicts are: the console knows the addresses and the frontend
    should not be a second place that has to be kept in step with them.

    The point is not decoration. `docs/claims.md` says a registration is
    "verifiable by anyone against the registry without taking our word for
    it", and a claim nobody is shown how to check is a claim taken on trust.
    """
    links: list[dict] = []
    if tx_hash:
        links.append({"label": "Transaction · Etherscan", "url": f"{ETHERSCAN}/tx/{tx_hash}"})
        links.append({"label": "Transaction · Blockscout", "url": f"{EXPLORER}/tx/{tx_hash}"})
    if REGISTRY:
        # Verified source, so the Read Contract tab needs no wallet -- this is
        # the link that lets someone check the record themselves.
        links.append({
            "label": "Registry · Etherscan (read contract)",
            "url": f"{ETHERSCAN}/address/{REGISTRY}#readContract",
        })
        links.append({
            "label": "Registry · Blockscout",
            "url": f"{EXPLORER}/address/{REGISTRY}?tab=read_contract",
        })
    links.append({"label": "Index · The Graph", "url": GRAPH_STUDIO})
    return links


#: ENSv2 Sepolia. Pinned in `identity/addresses.md`; blank env means unset,
#: not empty -- `.env` declared these keys with no value and `??` semantics
#: cost an afternoon once already.
ETH_REGISTRY = (os.environ.get("ENS_ETH_REGISTRY") or
                "0xbdc85dd5b15d7ecb354cd7cb6f2c50b4f2c4f0e2")


def _encode_string(value: str) -> str:
    """ABI-encode one dynamic string argument: offset, length, padded data."""
    raw = value.encode("utf-8")
    padded = raw + b"\x00" * ((32 - len(raw) % 32) % 32)
    return (
        (32).to_bytes(32, "big").hex()
        + len(raw).to_bytes(32, "big").hex()
        + padded.hex()
    )


def block_age_seconds() -> int:
    """How stale the head is. A chain that stopped advancing looks identical
    to one that is fine, until a transaction never confirms on camera."""
    import time

    block = _rpc("eth_getBlockByNumber", ["latest", False])
    return max(0, int(time.time()) - int(block["timestamp"], 16))


def ens_parent_ready(name: str) -> tuple[bool, str]:
    """Can body subnames actually be created under `name` yet?

    Walks `ETHRegistry` for a subregistry, the same walk
    `identity/scripts/register-body.ts` does. Owning a name does not give it
    one -- checked live, `raffy.eth` and `hello.eth` are both owned and both
    return zero -- so this is the check that says the ENS step is finished,
    where "is the name registered" would say yes too early.
    """
    labels = name.removesuffix(".eth").split(".")
    registry = ETH_REGISTRY
    walked: list[str] = []

    for label in reversed(labels):
        data = "0x" + _selector("getSubregistry(string)") + _encode_string(label)
        try:
            result = _rpc("eth_call", [{"to": registry, "data": data}, "latest"])
        except ChainError as error:
            return False, str(error)
        address = "0x" + result[-40:]
        if int(address, 16) == 0:
            under = ".".join(reversed(walked)) + ".eth" if walked else "eth"
            return False, f"`{label}` has no subregistry under {under}"
        walked.append(label)
        registry = address

    return True, registry
