"""The arithmetic that runs where K is, in both backends.

This is `prnu.score` with the residual extraction lifted out -- the client
did that before anything left the machine -- and with K arriving quantised.
It is written once here and mirrored in `cre/workflow/genesis/workflow.ts`,
and `cre/validate_cre.py` asserts the two agree on the same inputs.

Nothing in this file is secret. That is the point, and it is also the CRE
beta's actual boundary: the workflow binary the DON hands the enclave is
*not* confidential, so the algorithm is published either way. What the
enclave keeps is the data -- K, released by the Vault DON into an attested
enclave and never to a node operator.
"""

from __future__ import annotations

import numpy as np

from cre import payload as payload_mod
from fingerprint import prnu


def correlate(payload: dict, secret: dict) -> float:
    """PCE of the summed correlation surfaces, from a payload and a cropped K.

    Every step mirrors ``prnu.score`` and the comments there explain why each
    exists; the one difference is that the residual arrives rather than being
    extracted, and both sides arrive on an int8 scale.
    """
    size = int(payload["planeSize"])
    total = None

    for c in payload_mod.PLANES:
        key = str(c)
        if key not in secret:
            continue
        entry = payload["planes"][key]
        residual = payload_mod.Quantised.from_json(entry["residual"]).restore(size)
        plane = payload_mod.Quantised.from_json(entry["plane"]).restore(size)
        k = payload_mod.Quantised.from_json(secret[key]).restore(size)

        # A clipped photosite is clamped rather than modulated: it carries no
        # fingerprint but still feeds the energy the peak is measured against.
        keep = (plane < prnu.SATURATION_LEVEL).astype(np.float64)
        cc = prnu.cross_correlation(residual * keep, (plane * k) * keep)

        rms = np.sqrt((cc**2).mean())
        if rms <= 0:
            continue
        # Normalise before summing so one plane cannot dominate on scale alone.
        total = cc / rms if total is None else total + cc / rms

    return float(prnu._pce_of(total)) if total is not None else 0.0
