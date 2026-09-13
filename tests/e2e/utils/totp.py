"""RFC 6238 TOTP (Time-Based One-Time Password) generation for e2e tests.

Used to answer the Cognito TOTP challenge shown to the admin owner test user
during browser logins (#336). The owner user's TOTP device is provisioned by
``scripts/create-test-users.sh`` (dev) or
``scripts/create-ephemeral-test-users.sh`` (ephemeral CI) and provided as
``TEST_OWNER_TOTP_SECRET``.

Implemented with the Python standard library only (HMAC-SHA1, 30-second
step, 6 digits), matching the Cognito software-token MFA profile.
"""

import base64
import hashlib
import hmac
import struct
import time

_TOTP_PERIOD_SECONDS = 30
_TOTP_DIGITS = 6


def generate_totp(secret: str, timestamp: float | None = None) -> str:
    """Generate a zero-padded 6-digit TOTP code for the given base32 secret.

    Args:
        secret: Base32-encoded TOTP secret (as issued by Cognito).
        timestamp: Reference time as seconds since the epoch (defaults to now).

    Returns:
        The 6-digit TOTP code for the current (or given) 30-second step.
    """
    # Cognito issues the secret unpadded; b32decode requires RFC 4648 padding.
    padded = secret.upper() + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded)
    counter = int((time.time() if timestamp is None else timestamp) // _TOTP_PERIOD_SECONDS)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 10**_TOTP_DIGITS:0{_TOTP_DIGITS}d}"
