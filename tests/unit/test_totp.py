"""RFC 6238 test vectors for the e2e TOTP helper (``tests/e2e/utils/totp.py``)."""

import pytest

import tests.e2e.utils.totp as totp_module
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


def test_generate_totp_accepts_unpadded_cognito_secret() -> None:
    # Cognito issues TOTP secrets without base32 padding (#336); a bare
    # b32decode of the 26-char form raises binascii.Error('Incorrect padding').
    unpadded = "GEZDGNBVGY3TQOJQGEZDGNBVGY"
    assert len(unpadded) % 8 != 0
    padded = unpadded + "=" * (-len(unpadded) % 8)
    assert generate_totp(unpadded, timestamp=1234567890) == generate_totp(padded, timestamp=1234567890)


class _FakeClock:
    """Fake clock: ``time`` reads ``now``; ``sleep`` advances it."""

    def __init__(self, now: float) -> None:
        self.now = now

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)


@pytest.fixture(autouse=True)
def _clear_totp_window_tracking() -> None:
    totp_module._last_window_by_secret.clear()
    yield


def test_generate_totp_waits_for_next_window_on_reuse(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cognito rejects reuse of a code within a 30-second window (#336), so a
    # second live generation in the same window must wait for the next one.
    clock = _FakeClock(now=1_000_000.0)
    monkeypatch.setattr(totp_module, "time", clock)
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY"
    first = generate_totp(secret)  # consumes the current window
    assert len(first) == 6
    next_window = int(1_000_000.0 // 30) + 1
    second = generate_totp(secret)  # must sleep past the window boundary
    assert clock.now >= next_window * 30
    assert second == generate_totp(secret, timestamp=next_window * 30)
