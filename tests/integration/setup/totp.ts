/**
 * RFC 6238 TOTP (Time-Based One-Time Password) generation.
 *
 * Used to answer Cognito SOFTWARE_TOKEN_MFA challenges for the admin owner
 * test user, whose TOTP device is provisioned by
 * `scripts/create-ephemeral-test-users.sh` (ephemeral CI) or
 * `scripts/create-test-users.sh` (dev) and provided as
 * TEST_OWNER_TOTP_SECRET.
 *
 * Implemented with node:crypto only (HMAC-SHA1, 30-second step, 6 digits),
 * matching the Cognito software-token MFA profile.
 */

import { createHmac } from 'node:crypto';

const TOTP_PERIOD_SECONDS = 30;
const TOTP_DIGITS = 6;

const BASE32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

/**
 * Cognito rejects reuse of a TOTP code within the same 30-second window
 * (ExpiredCodeException: "software token has already been used once"). The
 * integration suite signs the admin owner in from many test files, so the
 * helper tracks the window each secret last answered a challenge in and
 * waits out the rest of a reused window before generating (#336).
 */
const lastWindowBySecret = new Map<string, number>();

/**
 * Clear the per-secret window tracking (test isolation helper).
 */
export function resetTotpWindowTracking(): void {
  lastWindowBySecret.clear();
}

/**
 * Decode a base32 (RFC 4648) encoded string, ignoring padding.
 */
function base32Decode(secret: string): Buffer {
  let bits = 0;
  let value = 0;
  const bytes: number[] = [];
  for (const char of secret.toUpperCase().replace(/=+$/, '')) {
    const index = BASE32_ALPHABET.indexOf(char);
    if (index === -1) {
      continue;
    }
    value = (value << 5) | index;
    bits += 5;
    if (bits >= 8) {
      bytes.push((value >>> (bits - 8)) & 0xff);
      bits -= 8;
    }
  }
  return Buffer.from(bytes);
}

function counterForMs(ms: number): number {
  return Math.floor(ms / 1000 / TOTP_PERIOD_SECONDS);
}

/**
 * Milliseconds to wait before a code may be generated: the time remaining in
 * the window when `lastWindow` (the window this secret last answered a
 * challenge in) is the window containing `nowMs`; zero otherwise.
 */
export function totpReuseWaitMs(lastWindow: number | undefined, nowMs: number): number {
  if (lastWindow === undefined) {
    return 0;
  }
  const currentWindow = counterForMs(nowMs);
  if (lastWindow !== currentWindow) {
    return 0;
  }
  return (currentWindow + 1) * TOTP_PERIOD_SECONDS * 1000 - nowMs;
}

/**
 * Generate a 6-digit TOTP code for the given base32 secret.
 *
 * Live generations (no timestamp) wait out a reused 30-second window so the
 * returned code has not already been consumed by Cognito (#336).
 *
 * @param secret - Base32-encoded TOTP secret (as issued by Cognito)
 * @param timestampMs - Reference time in milliseconds (defaults to now)
 * @returns Zero-padded 6-digit TOTP code
 */
export async function generateTotp(secret: string, timestampMs?: number): Promise<string> {
  if (timestampMs === undefined) {
    while (totpReuseWaitMs(lastWindowBySecret.get(secret), Date.now()) > 0) {
      const waitMs = totpReuseWaitMs(lastWindowBySecret.get(secret), Date.now());
      await new Promise((resolve) => setTimeout(resolve, waitMs));
    }
    timestampMs = Date.now();
    lastWindowBySecret.set(secret, counterForMs(timestampMs));
  }
  const counter = counterForMs(timestampMs);
  const message = Buffer.alloc(8);
  message.writeBigUInt64BE(BigInt(counter));
  const hmac = createHmac('sha1', base32Decode(secret)).update(message).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const binary =
    ((hmac[offset] & 0x7f) << 24) |
    (hmac[offset + 1] << 16) |
    (hmac[offset + 2] << 8) |
    hmac[offset + 3];
  return String(binary % 10 ** TOTP_DIGITS).padStart(TOTP_DIGITS, '0');
}
