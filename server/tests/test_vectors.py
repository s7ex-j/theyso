"""Cross-language vectors. app/test/crypto_test.dart asserts the SAME values.
Change one side only if you change the other."""

import hashlib

from theyso.security.handshake import transcript
from theyso.security.keys import b64u, fingerprint
from theyso.security.pairing import compute_proof, compute_sas

SECRET = bytes(range(32))
DEV = bytes(range(32, 64))
SRV = bytes(range(64, 96))


def test_proof_vector():
    assert b64u(compute_proof(SECRET, "pid123", DEV)) == "9tTALmf9ku5zANZwf12VktIF2i8MfSdiW7ykGZlELHc"


def test_sas_vector():
    assert compute_sas(SECRET, DEV, SRV) == "516447"


def test_fingerprint_vector():
    assert fingerprint(SRV) == "ZIVE-7ZZH-7KXM-6FXM"


def test_transcript_vector():
    t = transcript("dev_abc", bytes([1] * 32), bytes([2] * 32), SRV)
    assert hashlib.sha256(t).hexdigest() == "d5fc65ebc41d15d7451d1ee92b791f11e4728a158337a2bbad503bc714bc16fa"
