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

/**
 * Generate a 6-digit TOTP code for the given base32 secret.
 *
 * @param secret - Base32-encoded TOTP secret (as issued by Cognito)
 * @param timestampMs - Reference time in milliseconds (defaults to now)
 * @returns Zero-padded 6-digit TOTP code
 */
export function generateTotp(secret: string, timestampMs: number = Date.now()): string {
  const counter = Math.floor(timestampMs / 1000 / TOTP_PERIOD_SECONDS);
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
