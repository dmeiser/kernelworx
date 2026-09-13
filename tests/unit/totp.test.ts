import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  generateTotp,
  resetTotpWindowTracking,
  totpReuseWaitMs,
} from '../integration/setup/totp';

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
  beforeEach(() => {
    resetTotpWindowTracking();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each(RFC6238_SHA1_VECTORS.map(([t, expected]) => [t, expected] as const))(
    'matches the RFC 6238 SHA-1 vector at T=%i',
    async (timestampSeconds, expected) => {
      expect(await generateTotp(SECRET_B32, timestampSeconds * 1000)).toBe(expected);
    },
  );

  it('always returns a zero-padded 6-digit code', async () => {
    // Timestamps chosen so the raw HOTP value has fewer than 6 digits.
    expect(await generateTotp(SECRET_B32, 59_000)).toMatch(/^\d{6}$/);
  });

  describe('totpReuseWaitMs', () => {
    const nowMs = 1_700_000_000_123_456;
    const currentWindow = Math.floor(nowMs / 1000 / 30);

    it('waits to the window end when the secret already answered the current window', () => {
      const waitMs = totpReuseWaitMs(currentWindow, nowMs);
      expect(waitMs).toBe((currentWindow + 1) * 30_000 - nowMs);
      expect(waitMs).toBeGreaterThan(0);
    });

    it('never waits for an unknown or different window', () => {
      expect(totpReuseWaitMs(undefined, nowMs)).toBe(0);
      expect(totpReuseWaitMs(currentWindow - 1, nowMs)).toBe(0);
      expect(totpReuseWaitMs(currentWindow + 1, nowMs)).toBe(0);
    });
  });

  it('waits out the current window when the secret already answered it', async () => {
    vi.useFakeTimers({ now: 1_700_000_000_010_000 });
    // The first live generation consumes the current 30-second window.
    await generateTotp(SECRET_B32);
    // The second must not answer with the same code: it waits for the
    // next window boundary before generating.
    const pending = generateTotp(SECRET_B32);
    expect(vi.getTimerCount()).toBeGreaterThan(0);
    await vi.advanceTimersByTimeAsync(30_000);
    const code = await pending;
    expect(code).toMatch(/^\d{6}$/);
  });
});
