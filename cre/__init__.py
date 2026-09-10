"""Confidential scoring: the same verdict, computed where nobody holds K.

`scoring/app.py` is the trust hole by design -- it holds the reference and
you take its word for a PCE. This package closes that, and offers two
backends behind one flag because the CRE path is private beta and the demo
cannot rest on an approval with unknown turnaround:

    GENESIS_CONFIDENTIAL_BACKEND=cre     a real Chainlink confidential workflow
    GENESIS_CONFIDENTIAL_BACKEND=local   the same arithmetic, in this process

They are NOT equivalent guarantees and the code refuses to blur that. See
`cre/backend.py`. What neither does is help against forgery: an enclave
would score a planted fingerprint faithfully and sign it (`docs/security.md`).
"""
