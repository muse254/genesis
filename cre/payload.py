"""What leaves the photographer's machine, and what the enclave signs.

Two constraints shape every number here, both measured against CRE v1.32.0
(`cre workflow limits export`) rather than assumed:

**The reference does not fit.** `WASMSecretsSizeLimit` is 1mb and
`data/references/r10.npz` is 89 MB -- four CFA planes of 2000x3000 float32.
Confidential HTTP is no escape either, capped at 125kb request and 500kb
response, so BUILD.md sec.11's fallback does not rescue an 89 MB reference.
Embedding K in the binary would fit under `WASMBinarySizeLimit` (100mb) and
is ruled out for a better reason: the workflow binary is explicitly *not*
confidential, so that would publish K.

So K is cropped and quantised, and `docs/cre.md` carries what that costs.

**The residual is not enough.** BUILD.md sec.11 says to send a 512x512 crop
of the noise residual. That is one array short: `prnu.score` correlates the
residual against ``plane * k``, so the enclave needs the image plane too --
for the multiplicative model and for the saturation mask. Both cross.

Nothing here ever packs K into a payload. `cre/validate_cre.py` has a test
that fails if it does.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

import numpy as np

from fingerprint import prnu

#: Canonical encoding tag for the signed score. Signatures are computed over
#: this, so changing it invalidates every attestation already issued -- the
#: same one-way door as ``record.RECORD_VERSION`` and ``prnu.COMMITMENT_VERSION``.
ATTESTATION_VERSION = b"genesis-cre-score-v1"

#: CFA plane edge, in photosites. 256 is not a taste: at 4 planes and one
#: byte per photosite it is 256 kB of K, which fits a 1mb Vault secret with
#: room for base64. 512 would be 1 MB before encoding and does not fit.
#: What the choice costs is measured in `docs/cre.md` -- and it costs the
#: weakest frame in the corpus, which is why the number is documented rather
#: than buried.
PLANE_SIZE = 256

#: Which CFA planes travel. All four, because they are independent
#: measurements of the same body and summing their correlation surfaces adds
#: the peaks coherently -- worth more than spending the same bytes on area
#: (measured: 4 planes at 256 scores 390 where 1 plane at 512 scores 285).
PLANES = (0, 1, 2, 3)


@dataclass(frozen=True)
class Quantised:
    """One int8 array plus the scale that puts it back on its own axis.

    int8 is free here, and that is measured rather than hoped: quantising
    both K and the probe moved IMG_0217 from 1,647.5 to 1,647.0, under 0.5%.
    It buys a factor of four on the secret and on the wire, which is the
    difference between fitting a Vault secret and not.
    """

    scale: float
    data: bytes

    def to_json(self) -> dict:
        return {"scale": self.scale, "data": base64.b64encode(self.data).decode()}

    @classmethod
    def from_json(cls, blob: dict) -> "Quantised":
        return cls(scale=float(blob["scale"]), data=base64.b64decode(blob["data"]))

    def restore(self, size: int) -> np.ndarray:
        flat = np.frombuffer(self.data, dtype=np.int8).astype(np.float64) * self.scale
        return flat.reshape(size, size)


def quantise(array: np.ndarray) -> Quantised:
    """Scale to int8 by the array's own maximum.

    Per-array rather than global: the planes differ in magnitude and a shared
    scale would spend the range on whichever plane is loudest.
    """
    peak = float(np.abs(array).max())
    if peak == 0:
        return Quantised(scale=1.0, data=np.zeros(array.size, dtype=np.int8).tobytes())
    scale = peak / 127.0
    packed = np.round(array / scale).clip(-127, 127).astype(np.int8)
    return Quantised(scale=scale, data=packed.tobytes())


def build_payload(planes: dict, body_id: str, size: int = PLANE_SIZE) -> dict:
    """Crop, extract the residual, quantise -- on the photographer's machine.

    The residual extraction stays here rather than in the enclave, which is
    the one place BUILD.md sec.8's "must agree bit-for-bit with the Python
    preprocessing" is satisfied by construction: there is only one
    implementation of it, and both backends call this same function.

    Parameters
    ----------
    planes : dict[int, np.ndarray]
        The probe's CFA planes, as ``prnu.load_raw_planes`` returns.
    body_id : str
        Which enrolled body to score against. Selects the secret, not the key.
    """
    missing = [c for c in PLANES if c not in planes]
    if missing:
        raise ValueError(f"probe is missing CFA plane(s) {missing}")

    out = {"version": ATTESTATION_VERSION.decode(), "bodyId": body_id, "planeSize": size,
           "planes": {}}
    for c in PLANES:
        cropped = prnu._centre_crop(planes[c], size)
        if cropped.shape != (size, size):
            raise ValueError(f"plane {c} is {cropped.shape}, too small to crop to {size}")
        out["planes"][str(c)] = {
            "residual": quantise(prnu.noise_residual(cropped)).to_json(),
            "plane": quantise(cropped).to_json(),
        }
    return out


def build_secret(reference: dict, size: int = PLANE_SIZE) -> dict:
    """K, cropped and quantised, as the enclave will hold it.

    One entry per CFA plane so it can be split across several Vault secrets:
    the CLI passes secret values to the compiler as process arguments, and
    macOS ``ARG_MAX`` is 1,048,576 -- measured, three 400 kB secrets fail to
    simulate with "argument list too long" where three 200 kB ones do not.
    """
    return {
        str(c): quantise(prnu._centre_crop(reference[c], size)).to_json()
        for c in PLANES
        if c in reference
    }


def payload_digest(payload: dict) -> bytes:
    """SHA-256 over the payload's arrays, in a fixed order.

    Covers what was actually scored, so an attestation cannot be lifted onto
    a different probe. Hashed field by field rather than over serialised JSON,
    because a digest over a pretty-printed dictionary is a digest over
    whitespace -- the same reasoning as ``record.canonical_bytes``.
    """
    digest = hashlib.sha256()
    digest.update(ATTESTATION_VERSION)
    digest.update(payload["bodyId"].encode())
    digest.update(int(payload["planeSize"]).to_bytes(2, "big"))
    for c in PLANES:
        entry = payload["planes"][str(c)]
        for field in ("residual", "plane"):
            part = Quantised.from_json(entry[field])
            digest.update(np.float64(part.scale).tobytes())
            digest.update(part.data)
    return digest.digest()


def attestation_bytes(payload: dict, pce: float) -> bytes:
    """The exact bytes a signature covers.

    PCE crosses as a signed integer of thousandths, never as a float: a
    signature over a float is a signature over one runtime's rounding, and
    the enclave and the verifier are not the same runtime.
    """
    return b"".join([
        ATTESTATION_VERSION,
        payload_digest(payload),
        pce_millis(pce).to_bytes(8, "big", signed=True),
        int(prnu.PCE_THRESHOLD * 1000).to_bytes(4, "big"),
    ])


def pce_millis(pce: float) -> int:
    """PCE as thousandths. Signed, because a strong negative peak is not a
    match and rounding it away would hide that."""
    return int(round(float(pce) * 1000))
