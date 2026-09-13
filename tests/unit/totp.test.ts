import { describe, expect, it } from 'vitest';

import { generateTotp } from '../integration/setup/totp';

/**
 * RFC 6238 Appendix B SHA-1 test vectors (8-digit) reduced to the 6-digit
 * codes Cognito accepts. Secret is the base32 encoding of ASCII
 * "12345678901234567890".
 */
const SECRET_B32 = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ';

const RFC6238_SHA1_VECTORS: Array<[number, string]> = [
  [59, '287082'],
  [1111111109, '081804'],
  [1111111111, '050471'],
  [1234567890, '005924'],
  [2000000000, '279037'],
  [20000000000, '353130'],
];

describe('generateTotp', () => {
  it.each(RFC6238_SHA1_VECTORS.map(([t, expected]) => [t, expected] as const))(
    'matches the RFC 6238 SHA-1 vector at T=%i',
    (timestampSeconds, expected) => {
      expect(generateTotp(SECRET_B32, timestampSeconds * 1000)).toBe(expected);
    },
  );

  it('always returns a zero-padded 6-digit code', () => {
    // Timestamps chosen so the raw HOTP value has fewer than 6 digits.
    expect(generateTotp(SECRET_B32, 59_000)).toMatch(/^\d{6}$/);
  });
});
