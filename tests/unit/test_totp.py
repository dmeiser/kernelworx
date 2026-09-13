"""RFC 6238 test vectors for the e2e TOTP helper (``tests/e2e/utils/totp.py``)."""

import pytest

from tests.e2e.utils.totp import generate_totp

#: Base32 encoding of ASCII "12345678901234567890" (RFC 6238 Appendix B secret).
SECRET_B32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

#: RFC 6238 Appendix B SHA-1 vectors (8-digit) reduced to 6-digit codes.
RFC6238_SHA1_VECTORS = [
    (59, "287082"),
    (1111111109, "081804"),
    (1111111111, "050471"),
    (1234567890, "005924"),
    (2000000000, "279037"),
    (20000000000, "353130"),
]


@pytest.mark.parametrize(("timestamp", "expected"), RFC6238_SHA1_VECTORS)
def test_generate_totp_matches_rfc6238_sha1_vectors(timestamp: int, expected: str) -> None:
    assert generate_totp(SECRET_B32, timestamp=timestamp) == expected


def test_generate_totp_always_returns_zero_padded_six_digits() -> None:
    assert generate_totp(SECRET_B32, timestamp=59) == "287082"
    code = generate_totp(SECRET_B32, timestamp=1234567890)
    assert len(code) == 6
    assert code.isdigit()
